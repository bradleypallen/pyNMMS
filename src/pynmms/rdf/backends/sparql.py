"""SPARQL endpoint backend.

Membership and pattern queries are answered by the endpoint. Closure is
whatever the endpoint's configured entailment regime materialises: declare
it with ``regime=`` so that a :class:`~pynmms.rdf.base.RegimeBase` knows
which rules to apply to the per-node extras. An optional probe query at
construction checks that the store really does entail a known consequence,
so a mismatch between the declared and the actual regime fails loudly rather
than silently under-reporting.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from rdflib import Graph
from rdflib.plugins.stores.sparqlstore import SPARQLStore
from rdflib.term import Node

from pynmms.rdf.atoms import Resolver

if TYPE_CHECKING:
    from pynmms.rdf.rules import Regime

logger = logging.getLogger(__name__)

Triple = tuple[Node, Node, Node]
Pattern = tuple[Node | None, Node | None, Node | None]


class SPARQLBackend:
    """A remote (or local server) graph reached over SPARQL.

    Parameters:
        endpoint: Query endpoint URL.
        regime: The regime the endpoint materialises (declared, not enforced).
        probe: Optional ``(premises, conclusion)`` triples: the conclusion
            must be entailed by the endpoint for the declared regime; raises
            ``ValueError`` otherwise.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        regime: Regime | None = None,
        probe: tuple[Triple, ...] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self._regime = regime
        self._store = SPARQLStore(endpoint)
        self._graph = Graph(store=self._store)
        self._resolver = Resolver(self._graph)
        self._generation = 1
        self._calls = 0
        self._latency = 0.0
        if probe is not None:
            for t in probe:
                if not self.closure_contains(t):
                    raise ValueError(
                        f"Endpoint {endpoint} does not entail probe triple {t}; "
                        f"declared regime {regime} is not materialised"
                    )

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
    def stats(self) -> dict[str, float]:
        """Round trips and cumulative latency, for post-run analysis."""
        return {"calls": self._calls, "latency_ms": self._latency * 1000}

    def bump(self) -> None:
        """Signal that the remote graph changed (invalidates views and caches)."""
        self._generation += 1

    def _timed(self, what: str):  # type: ignore[no-untyped-def]
        backend = self

        class _T:
            def __enter__(self) -> None:
                self.t0 = time.perf_counter()

            def __exit__(self, *exc: object) -> None:
                dt = time.perf_counter() - self.t0
                backend._calls += 1
                backend._latency += dt
                logger.debug("SPARQL %s: %.1f ms", what, dt * 1000)

        return _T()

    def size(self) -> int:
        with self._timed("count"):
            rows = list(self._graph.query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"))
        return int(str(rows[0][0]))  # type: ignore[index]

    def contains(self, t: Triple) -> bool:
        with self._timed("ask"):
            return t in self._graph

    def triples(self, pattern: Pattern) -> Iterator[Triple]:
        with self._timed("triples"):
            return iter(list(self._graph.triples(pattern)))  # type: ignore[arg-type]

    # The endpoint's materialisation is the closure.
    closure_contains = contains
    closure_triples = triples

    def is_inconsistent(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"SPARQLBackend({self.endpoint!r}, regime={self._regime})"
