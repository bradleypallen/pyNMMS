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
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from rdflib import BNode, Graph
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.plugins.stores.sparqlstore import SPARQLStore, SPARQLUpdateStore
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
        probe: Optional triples that the endpoint must entail under the
            declared regime; raises ``ValueError`` otherwise.
        update_endpoint: SPARQL UPDATE endpoint for :meth:`add`.
        prefixes: ``{prefix: namespace}`` for parsing and display; endpoints
            do not expose their prefix declarations to clients.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        regime: Regime | None = None,
        probe: tuple[Triple, ...] | None = None,
        update_endpoint: str | None = None,
        prefixes: dict[str, str] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.update_endpoint = update_endpoint
        self._regime = regime
        self._store: SPARQLStore
        if update_endpoint is not None:
            self._store = SPARQLUpdateStore(endpoint, update_endpoint)
        else:
            self._store = SPARQLStore(endpoint)
        # The default graph: a blank-node identifier would be rejected by
        # SPARQL UPDATE, and the endpoint's prefixes are not visible to the
        # client, so they are declared here.
        self._graph = Graph(store=self._store, identifier=DATASET_DEFAULT_GRAPH_ID)
        self._resolver = Resolver(self._graph)
        for prefix, ns in (prefixes or {}).items():
            self._resolver.bind(prefix, ns)
        self._generation = 1
        self._calls = 0
        self._latency = 0.0
        # Per-generation memo: proof search asks the same memberships and
        # joins many times (every firing checks its conclusions; every query
        # re-derives the same schema-level triples). Cleared on bump().
        self._size: int | None = None
        self._contains_memo: dict[Triple, bool] = {}
        self._join_memo: dict[tuple[tuple[Any, ...], tuple[tuple[Any, Any], ...]], list] = {}
        self.memo_limit = 100_000
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
        self._size = None
        self._contains_memo.clear()
        self._join_memo.clear()

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
        if self._size is None:
            with self._timed("count"):
                rows = list(self._graph.query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"))
            self._size = int(str(rows[0][0]))  # type: ignore[index]
        return self._size

    def contains(self, t: Triple) -> bool:
        hit = self._contains_memo.get(t)
        if hit is not None:
            return hit
        with self._timed("ask"):
            found = t in self._graph
        if len(self._contains_memo) < self.memo_limit:
            self._contains_memo[t] = found
        return found

    def triples(self, pattern: Pattern) -> Iterator[Triple]:
        with self._timed("triples"):
            return iter(list(self._graph.triples(pattern)))  # type: ignore[arg-type]

    # The endpoint's materialisation is the closure.
    closure_contains = contains
    closure_triples = triples

    def is_inconsistent(self) -> bool:
        return False

    def join(self, patterns: list[Any], bindings: dict[Any, Node]) -> Iterator[dict[Any, Node]]:
        """One ``SELECT`` for the whole conjunction, bound terms inlined."""
        from pynmms.rdf.sparql_rules import build_select

        _bgp, query, free, _names = build_select(patterns, bindings)
        key = (tuple(patterns), tuple(sorted(bindings.items(), key=lambda kv: str(kv[0]))))
        rows = self._join_memo.get(key)
        if rows is None:
            with self._timed(f"join {len(patterns)}"):
                rows = list(self._graph.query(query))
            if len(self._join_memo) < self.memo_limit:
                self._join_memo[key] = rows
        out: list[dict[Any, Node]] = []
        for row in rows:
            b = dict(bindings)
            for v, val in zip(free, row):  # type: ignore[arg-type]
                b[v] = val
            out.append(b)
        return iter(out)

    BULK_CHUNK = 500

    def add(self, triples: Iterable[Triple]) -> int:
        """Insert triples through the update endpoint in chunked ``INSERT DATA`` updates.

        The store is expected to maintain its own materialisation; the
        generation is bumped once per call so views and caches invalidate.
        """
        if self.update_endpoint is None:
            raise ValueError("SPARQLBackend.add needs an update_endpoint")
        batch = list(triples)
        if not batch:
            return 0
        for t in batch:
            if any(isinstance(n, BNode) for n in t):
                raise ValueError("SPARQLBackend.add cannot insert blank nodes; Skolemize first")
        for start in range(0, len(batch), self.BULK_CHUNK):
            chunk = batch[start:start + self.BULK_CHUNK]
            data = " ".join(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in chunk)
            with self._timed(f"insert {len(chunk)}"):
                # Call the store directly: Graph.update() would wrap the update
                # in the graph's identifier, which single-graph endpoints reject.
                self._store.update(f"INSERT DATA {{ {data} }}")
        self.bump()
        logger.info("Inserted %d triples into %s in %d update(s); generation %d",
                    len(batch), self.update_endpoint,
                    -(-len(batch) // self.BULK_CHUNK), self._generation)
        return len(batch)

    def __repr__(self) -> str:
        return f"SPARQLBackend({self.endpoint!r}, regime={self._regime})"
