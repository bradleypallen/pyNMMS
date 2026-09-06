"""In-memory backend: an rdflib Graph plus an in-process regime closure."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rdflib import BNode, Graph
from rdflib.term import Node

from pynmms.rdf.atoms import Resolver

if TYPE_CHECKING:
    from pynmms.rdf.rules import Regime

logger = logging.getLogger(__name__)


def _skolemized(g: Graph) -> Graph:
    """``g.skolemize()`` if it has blank nodes, keeping namespace bindings."""
    if not any(isinstance(n, BNode) for t in g for n in t):
        return g
    out = g.skolemize()
    for prefix, ns in g.namespaces():
        out.namespace_manager.bind(prefix, ns, replace=True)
    return out


Triple = tuple[Node, Node, Node]
Pattern = tuple[Node | None, Node | None, Node | None]


class MemoryBackend:
    """rdflib ``Graph`` as the store, with the regime closure kept in a second graph.

    Parameters:
        graph: Existing graph to wrap (copied by reference, not duplicated).
        regime: Entailment regime to materialise; ``None`` for no closure.
        skolemize: Replace blank nodes by Skolem IRIs on load (sound in the
            antecedent, Lemma 30 of the paper).
    """

    def __init__(
        self,
        graph: Graph | None = None,
        *,
        regime: Regime | None = None,
        skolemize: bool = True,
    ) -> None:
        self._graph = graph if graph is not None else Graph()
        self._regime = regime
        self._skolemize = skolemize
        self._closure: Graph | None = None
        self._inconsistent = False
        self._generation = 0
        self._resolver = Resolver(self._graph)
        if self._skolemize and len(self._graph):
            self._graph = _skolemized(self._graph)
            self._resolver = Resolver(self._graph)
        self._materialize()

    # --- Protocol ---

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def regime(self) -> Regime | None:
        return self._regime

    @property
    def resolver(self) -> Resolver:
        return self._resolver

    @property
    def graph(self) -> Graph:
        return self._graph

    @property
    def closure(self) -> Graph:
        """cl_R(G) (the asserted graph itself when there is no regime)."""
        return self._closure if self._closure is not None else self._graph

    def size(self) -> int:
        return len(self._graph)

    def contains(self, t: Triple) -> bool:
        return t in self._graph

    def triples(self, pattern: Pattern) -> Iterator[Triple]:
        return self._graph.triples(pattern)  # type: ignore[return-value]

    def closure_contains(self, t: Triple) -> bool:
        return t in self.closure

    def closure_triples(self, pattern: Pattern) -> Iterator[Triple]:
        return self.closure.triples(pattern)  # type: ignore[return-value]

    def is_inconsistent(self) -> bool:
        return self._inconsistent

    def join(self, patterns: list[Any], bindings: dict[Any, Node]) -> Iterator[dict[Any, Node]]:
        """Nested-loop join over the closure graph (no batching to be had locally)."""
        from pynmms.rdf.closure import join_patterns

        return join_patterns(patterns, bindings, self.closure_triples)

    def closure_size(self) -> int:
        return len(self.closure)

    # --- Loading and mutation ---

    def load(self, source: str | Path, format: str | None = None) -> int:
        """Parse a file into the graph, Skolemize if configured, re-materialise.

        Returns the number of triples loaded.
        """
        before = len(self._graph)
        t0 = time.perf_counter()
        incoming = Graph()
        incoming.parse(str(source), format=format)
        for prefix, ns in incoming.namespaces():
            self._graph.namespace_manager.bind(prefix, ns, replace=True)
        bnodes = len({n for t in incoming for n in t if isinstance(n, BNode)})
        if self._skolemize and bnodes:
            incoming = _skolemized(incoming)
        for t in incoming:
            self._graph.add(t)
        loaded = len(self._graph) - before
        logger.info(
            "Loaded %d triples from %s (%d blank nodes%s) in %.1f ms",
            loaded, source, bnodes, ", Skolemized" if self._skolemize and bnodes else "",
            (time.perf_counter() - t0) * 1000,
        )
        self._resolver = Resolver(self._graph)
        self._materialize()
        return loaded

    def add(self, triples: Iterable[Triple]) -> int:
        """Assert triples and extend the closure incrementally."""
        added = [t for t in triples if t not in self._graph]
        for t in added:
            self._graph.add(t)
        if added:
            if self._closure is not None and self._regime is not None:
                from pynmms.rdf.closure import ClosureEngine

                engine = ClosureEngine(self._regime)
                new, bottom = engine.extend(
                    added, self.closure.triples, lambda t: t in self.closure
                )
                for t in new.triples:
                    self._closure.add(t)
                self._inconsistent = self._inconsistent or bottom
            self._generation += 1
            logger.debug("Added %d triples; generation %d", len(added), self._generation)
        return len(added)

    def _materialize(self) -> None:
        self._generation += 1
        if self._regime is None or (not self._regime.rules and not self._regime.axioms):
            self._closure = None
            self._inconsistent = False
            return
        from pynmms.rdf.closure import ClosureEngine

        t0 = time.perf_counter()
        closed, bottom = ClosureEngine(self._regime).close(iter(self._graph))
        closure = Graph()
        for t in closed:
            closure.add(t)
        self._closure = closure
        self._inconsistent = bottom
        logger.info(
            "Materialised %s closure: %d asserted -> %d triples%s in %.1f ms",
            self._regime.name, len(self._graph), len(closure),
            " (INCONSISTENT)" if bottom else "", (time.perf_counter() - t0) * 1000,
        )

    def __repr__(self) -> str:
        return f"MemoryBackend({len(self._graph)} triples, regime={self._regime})"
