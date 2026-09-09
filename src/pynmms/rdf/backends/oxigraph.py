"""Oxigraph backend: an embedded store that materialises the regime itself.

`Oxigraph <https://github.com/oxigraph/oxigraph>`_ is a Rust triplestore with
a SPARQL 1.1 engine, usable in process through ``pyoxigraph`` either in
memory or on disk (RocksDB). This backend keeps the asserted graph in the
named graph ``<urn:pynmms:asserted>`` and ``cl_R(G)`` in the default graph,
and computes the closure *inside the store*: every pattern rule of the regime
runs as a SPARQL ``INSERT ... WHERE`` update
(:mod:`pynmms.rdf.sparql_rules`), iterated to a fixpoint, with the rules a
store cannot run (guarded rules, :class:`~pynmms.rdf.rules.ProceduralRule`\\s)
evaluated in process against the store between rounds. Membership, pattern,
and join queries are then microseconds, and a store on disk keeps its
closure across sessions: reopening a path whose recorded regime matches skips
materialisation.

``add()`` extends the closure semi-naively through
:meth:`~pynmms.rdf.closure.ClosureEngine.extend` with the store as the join
partner, so a ``TELL`` of a few triples costs milliseconds at any size.

Rules whose conclusions are generalized triples with a literal subject
(``rdfs1``, ``rdfD1``) cannot be stored and are skipped, so literal typing
is absent from the materialised closure; the in-process extras closure still
derives them for a query's own triples.

Requires ``pip install pyoxigraph`` (the ``oxigraph`` extra).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD
from rdflib.term import Node

from pynmms.rdf.atoms import Resolver, skolemize_triple

if TYPE_CHECKING:
    from pynmms.rdf.rules import Regime

logger = logging.getLogger(__name__)

Triple = tuple[Node, Node, Node]
Pattern = tuple[Node | None, Node | None, Node | None]

ASSERTED = "urn:pynmms:asserted"
META = "urn:pynmms:meta"
_STORE = "urn:pynmms:store"
_REGIME = "urn:pynmms:regime"
_INCONSISTENT = "urn:pynmms:inconsistent"

#: Rules whose conclusions have a literal subject; Oxigraph cannot store those.
UNSTORABLE_RULES = frozenset({"rdfs1", "rdfD1"})

#: Above this many asserted triples an on-disk store materialises directly on
#: disk rather than in a temporary in-memory store (about 600 bytes per
#: closure triple in memory; 2M asserted with a 4x closure is about 5 GB).
IN_MEMORY_LIMIT = 2_000_000

_FORMATS = {".ttl": "text/turtle", ".nt": "application/n-triples", ".n3": "text/n3",
            ".rdf": "application/rdf+xml", ".xml": "application/rdf+xml",
            ".jsonld": "application/ld+json", ".nq": "application/n-quads",
            ".trig": "application/trig"}


def _ox() -> Any:
    try:
        import pyoxigraph
    except ImportError as e:  # pragma: no cover - depends on environment
        raise ImportError("OxigraphBackend needs the pyoxigraph package "
                          "(pip install 'pynmms[oxigraph]')") from e
    return pyoxigraph


def to_ox(n: Node, ox: Any) -> Any:
    """rdflib term -> pyoxigraph term."""
    if isinstance(n, URIRef):
        return ox.NamedNode(str(n))
    if isinstance(n, BNode):
        return ox.BlankNode(str(n))
    if isinstance(n, Literal):
        if n.language:
            return ox.Literal(str(n), language=n.language)
        if n.datatype is not None and n.datatype != XSD.string:
            return ox.Literal(str(n), datatype=ox.NamedNode(str(n.datatype)))
        return ox.Literal(str(n))
    raise TypeError(f"cannot convert {n!r} to an Oxigraph term")


def from_ox(t: Any, ox: Any) -> Node:
    """pyoxigraph term -> rdflib term (plain strings lose their xsd:string)."""
    if isinstance(t, ox.NamedNode):
        return URIRef(t.value)
    if isinstance(t, ox.BlankNode):
        return BNode(t.value)
    if isinstance(t, ox.Literal):
        if t.language:
            return Literal(t.value, lang=t.language)
        dt = t.datatype.value if t.datatype is not None else None
        if dt is None or dt == str(XSD.string):
            return Literal(t.value)
        return Literal(t.value, datatype=URIRef(dt))
    raise TypeError(f"cannot convert {t!r} to an rdflib term")


def _file_prefixes(path: Path) -> dict[str, str]:
    """``@prefix`` / ``PREFIX`` declarations at the head of a Turtle-family file."""
    out: dict[str, str] = {}
    if path.suffix.lower() not in (".ttl", ".n3", ".trig"):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                lowered = stripped.lower()
                if lowered.startswith("@prefix") or lowered.startswith("prefix"):
                    parts = stripped.rstrip(" .").split(None, 2)
                    if len(parts) == 3 and parts[1].endswith(":"):
                        out[parts[1][:-1]] = parts[2].strip("<>")
                    continue
                if lowered.startswith("@base") or lowered.startswith("base"):
                    continue
                break
    except OSError:
        pass
    return out


class OxigraphBackend:
    """A :class:`~pynmms.rdf.backends.GraphBackend` over an embedded Oxigraph store.

    Args:
        path: Directory of an on-disk store (created if absent); ``None`` for
            an in-memory store.
        regime: The entailment regime to materialise. ``None`` means the
            closure is the asserted graph.
        skolemize: Replace blank nodes by Skolem IRIs on load (``lem:skolem``).
        prefixes: Prefix bindings for parsing and display.
        materialize: Materialise on construction when the store's recorded
            regime differs from *regime* (default). Pass ``False`` to load
            several files first and call :meth:`materialize` once.
        in_memory: For an on-disk store, compute the closure in a temporary
            in-memory store and bulk-load the result (fast, but about 600
            bytes of memory per closure triple) rather than by rule updates
            against the disk store (RocksDB-write-bound, no memory cost).
            ``None`` chooses in memory below :data:`IN_MEMORY_LIMIT`
            asserted triples.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        regime: Regime | None = None,
        skolemize: bool = True,
        prefixes: dict[str, str] | None = None,
        materialize: bool = True,
        in_memory: bool | None = None,
    ) -> None:
        self._ox = _ox()
        self.in_memory = in_memory
        ox = self._ox
        self._store = ox.Store(str(path)) if path is not None else ox.Store()
        self._path = Path(path) if path is not None else None
        self._regime = regime
        self._skolemize = skolemize
        self._generation = 0
        self._inconsistent = False
        self._resolver = Resolver(Graph())
        for pfx, ns in (prefixes or {}).items():
            self._resolver.bind(pfx, ns)
        self._default = ox.DefaultGraph()
        self._asserted = ox.NamedNode(ASSERTED) if self._materialising else self._default
        self._meta = ox.NamedNode(META)
        self.round_trips = 0
        if self._materialising:
            if self._recorded_regime() == regime.name:  # type: ignore[union-attr]
                self._inconsistent = self._recorded_inconsistent()
                logger.info("Oxigraph store %s: closure for regime %s already materialised%s",
                            self._path, regime.name,  # type: ignore[union-attr]
                            " (INCONSISTENT)" if self._inconsistent else "")
            elif materialize:
                self.materialize()

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
    def store(self) -> Any:
        """The underlying ``pyoxigraph.Store``."""
        return self._store

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def materialised(self) -> bool:
        """Does the store hold ``cl_R(G)`` for this regime? (Always true without one.)"""
        if not self._materialising:
            return True
        assert self._regime is not None
        return self._recorded_regime() == self._regime.name

    @property
    def _materialising(self) -> bool:
        return self._regime is not None and bool(self._regime.rules or self._regime.axioms)

    def size(self) -> int:
        return self._count(self._asserted)

    def closure_size(self) -> int:
        return self._count(self._default)

    def contains(self, t: Triple) -> bool:
        return self._has(t, self._asserted)

    def triples(self, pattern: Pattern) -> Iterator[Triple]:
        return self._match(pattern, self._asserted)

    def closure_contains(self, t: Triple) -> bool:
        return self._has(t, self._default)

    def closure_triples(self, pattern: Pattern) -> Iterator[Triple]:
        return self._match(pattern, self._default)

    def is_inconsistent(self) -> bool:
        return self._inconsistent

    def join(self, patterns: list[Any], bindings: dict[Any, Node]) -> Iterator[dict[Any, Node]]:
        """One ``SELECT`` over the closure for the whole conjunction (an ``ASK``
        when every term is bound)."""
        from pynmms.rdf.sparql_rules import build_select

        bgp, query, free, names = build_select(patterns, bindings)
        if not free:
            yield from ([dict(bindings)] if bool(self._query(f"ASK {{ {bgp} }}")) else [])
            return
        for row in self._query(query):
            b = dict(bindings)
            for v in free:
                val = row[names[v][1:]]
                if val is None:
                    break
                b[v] = from_ox(val, self._ox)
            else:
                yield b

    # --- Loading and mutation ---
    def load(self, source: str | Path, format: str | None = None, *,
             materialize: bool = True) -> int:
        """Load an RDF file into the store, Skolemize, and (re)materialise.

        Parsing is Oxigraph's own; *format* is a MIME type or guessed from
        the extension. Turtle ``@prefix`` lines are bound in the resolver.
        Returns the number of asserted triples added. With
        ``materialize=False`` the closure is left stale until
        :meth:`materialize` is called.
        """
        ox = self._ox
        path = Path(source)
        mime = format or _FORMATS.get(path.suffix.lower())
        if mime is None:
            raise ValueError(f"Cannot guess the RDF format of {source}")
        before = self.size()
        t0 = time.perf_counter()
        with open(path, "rb") as fh:
            self._store.bulk_load(fh, format=ox.RdfFormat.from_media_type(mime),
                                  to_graph=self._asserted)
        if self._skolemize:
            self._skolemize_graph()
        for pfx, ns in _file_prefixes(path).items():
            self._resolver.bind(pfx, ns)
        added = self.size() - before
        logger.info("Loaded %d triples from %s in %.1f ms", added, source,
                    (time.perf_counter() - t0) * 1000)
        if self._materialising and materialize:
            self.materialize()
        else:
            self._generation += 1
        return added

    def dump(self, destination: str | Path, format: str | None = None) -> None:
        """Write the asserted graph to a file (format from the extension)."""
        ox = self._ox
        path = Path(destination)
        mime = format or _FORMATS.get(path.suffix.lower())
        if mime is None:
            raise ValueError(f"Cannot guess the RDF format of {destination}")
        with open(path, "wb") as fh:
            self._store.dump(fh, format=ox.RdfFormat.from_media_type(mime),
                             from_graph=self._asserted)

    def materialize(self) -> None:
        """Recompute ``cl_R(G)`` in the store from the asserted graph.

        An in-memory store runs the rules in place. An on-disk store does so
        too when ``in_memory=False`` was given, or when it was left to choose
        and holds more than :data:`IN_MEMORY_LIMIT` asserted triples;
        otherwise it computes the closure in a temporary in-memory store and
        bulk-loads the result, since RocksDB writes made the rule updates
        five times slower than in memory, slower than the Python engine at
        two million closure triples.
        """
        if not self._materialising:
            self._generation += 1
            return
        if self._path is None:
            scratch_in_memory = False
        elif self.in_memory is not None:
            scratch_in_memory = self.in_memory
        else:
            scratch_in_memory = self.size() <= IN_MEMORY_LIMIT
        if not scratch_in_memory:
            self._reset_closure()
            self._materialize()
            return
        import tempfile

        ox = self._ox
        disk = self._store
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "graph.nt"
            disk.dump(str(dump), format=ox.RdfFormat.N_TRIPLES, from_graph=self._asserted)
            scratch = ox.Store()
            scratch.bulk_load(path=str(dump), format=ox.RdfFormat.N_TRIPLES)
            self._store = scratch
            try:
                self._asserted, asserted_on_disk = self._default, self._asserted
                self._materialize(asserted=self._count(self._default), record=False)
            finally:
                self._store, self._asserted = disk, asserted_on_disk
            scratch.dump(str(dump), format=ox.RdfFormat.N_TRIPLES, from_graph=self._default)
            del scratch
            self._update("DROP SILENT DEFAULT")
            disk.bulk_load(path=str(dump), format=ox.RdfFormat.N_TRIPLES)
        self._record_meta()
        logger.info("Closure written to %s in %.1f ms total", self._path,
                    (time.perf_counter() - t0) * 1000)

    def load_graph(self, graph: Graph, *, source: URIRef | None = None) -> int:
        """Load an rdflib graph (its namespace bindings included).

        With *source*, the triples are also recorded in that named graph, so
        :meth:`graphs_of` reports them as coming from it (provenance).
        """
        for pfx, ns in graph.namespaces():
            self._resolver.bind(pfx, str(ns))
        triples = [skolemize_triple(t) if self._skolemize else t for t in graph]
        before = self.size()
        self._insert(triples, self._asserted)
        if source is not None:
            self._insert(triples, self._ox.NamedNode(str(source)))
        self.materialize()
        return self.size() - before

    def graphs_of(self, t: Triple) -> list[URIRef]:
        """The named graphs (sources) holding *t*, the backend's own graphs excluded."""
        ox = self._ox
        s, p, o = t
        if isinstance(s, Literal):
            return []
        out: list[URIRef] = []
        for q in self._store.quads_for_pattern(to_ox(s, ox), to_ox(p, ox), to_ox(o, ox), None):
            g = q.graph_name
            if isinstance(g, ox.NamedNode) and g.value not in (ASSERTED, META):
                out.append(URIRef(g.value))
        return sorted(out)

    def add(self, triples: Iterable[Triple], *, source: URIRef | None = None) -> int:
        """Assert triples and extend the closure incrementally in process.

        The new triples are closed by :meth:`ClosureEngine.extend` with the
        store as the join partner, and the result is written to the closure
        graph; the store is never re-materialised. With *source*, they are
        also recorded in that named graph.
        """
        triples = list(triples)
        added = [t for t in triples if not self.contains(t)]
        if source is not None and triples:
            self._insert(triples, self._ox.NamedNode(str(source)))
        if not added:
            return 0
        self._insert(added, self._asserted)
        if self._materialising:
            from pynmms.rdf.closure import ClosureEngine

            assert self._regime is not None
            new, bottom = ClosureEngine(self._regime).extend(
                added, self.closure_triples, self.closure_contains, store_join=self.join
            )
            self._insert(list(new.triples), self._default)
            if bottom and not self._inconsistent:
                self._inconsistent = True
                self._record_meta()
        else:
            self._insert(added, self._default) if self._asserted is not self._default else None
        self._generation += 1
        logger.debug("Added %d triples; generation %d", len(added), self._generation)
        return len(added)

    # --- Materialisation in the store ---
    def _materialize(self, asserted: int | None = None, *, record: bool = True) -> None:
        """Run the regime to a fixpoint inside the store.

        Pattern rules run as SPARQL updates; guarded and procedural rules run
        in process against the store between rounds, until neither adds a
        triple. ⊥ rules are ASKs (``prop:incoherence``). With ``record=False``
        the meta graph is left to the caller (the scratch store of
        :meth:`materialize` is discarded, so recording there is wasted).
        """
        from pynmms.rdf.sparql_rules import partition

        assert self._regime is not None
        rules = partition(self._regime, skip=UNSTORABLE_RULES)
        t0 = time.perf_counter()
        self._insert(list(self._regime.axioms), self._default)
        rounds = 0
        while True:
            rounds += self._sparql_fixpoint(rules.updates)
            if not self._in_process_round(rules.in_process):
                break
        bottom = any(bool(self._query(q)) for q in rules.asks) or self._in_process_bottom(
            rules.in_process
        )
        self._inconsistent = bottom
        self._generation += 1
        if record:
            self._record_meta()
        logger.info(
            "Materialised %s closure in the store: %d asserted -> %d triples%s in %d round(s), "
            "%.1f ms (%d store-side rules, %d in process%s)",
            self._regime.name, self.size() if asserted is None else asserted, self.closure_size(),
            " (INCONSISTENT)" if bottom else "", rounds, (time.perf_counter() - t0) * 1000,
            rules.store_side, len(rules.in_process),
            f", skipped {', '.join(rules.skipped)}" if rules.skipped else "",
        )

    def _sparql_fixpoint(self, updates: tuple[str, ...]) -> int:
        rounds = 0
        while updates:
            before = self.closure_size()
            for u in updates:
                self._update(u)
            rounds += 1
            if self.closure_size() == before:
                break
        return rounds

    def _in_process_round(self, rules: tuple[Any, ...]) -> bool:
        """One pass of the guarded and procedural rules over the closure graph."""
        from pynmms.rdf.rules import ProceduralRule, Rule

        new: list[Triple] = []
        for rule in rules:
            if isinstance(rule, ProceduralRule):
                for concl in self._fire_procedural(rule):
                    if concl is not None and not self.closure_contains(concl):
                        new.append(concl)
            elif isinstance(rule, Rule) and rule.conclusion is not None:
                for b in self.join(list(rule.premises), {}):
                    if rule.guard is None or rule.guard(b):
                        bound: Triple = tuple(b.get(t, t) for t in rule.conclusion)  # type: ignore[assignment]
                        if not isinstance(bound[0], Literal) and not self.closure_contains(bound):
                            new.append(bound)
        if not new:
            return False
        self._insert(new, self._default)
        return True

    def _in_process_bottom(self, rules: tuple[Any, ...]) -> bool:
        from pynmms.rdf.rules import ProceduralRule, Rule

        for rule in rules:
            if isinstance(rule, ProceduralRule):
                if any(c is None for c in self._fire_procedural(rule)):
                    return True
            elif isinstance(rule, Rule) and rule.conclusion is None:
                for b in self.join(list(rule.premises), {}):
                    if rule.guard is None or rule.guard(b):
                        return True
        return False

    def _fire_procedural(self, rule: Any) -> Iterator[Triple | None]:
        triggers = rule.triggers or (None,)
        seen: set[Triple] = set()
        for p in triggers:
            for t in self.closure_triples((None, p, None)):
                if t in seen:
                    continue
                seen.add(t)
                yield from rule.fire(t, self.closure_triples)

    # --- Store plumbing ---
    def _reset_closure(self) -> None:
        """Make the default graph a copy of the asserted graph."""
        if self._asserted is self._default:
            return
        self._update(f"DROP SILENT DEFAULT; ADD SILENT <{ASSERTED}> TO DEFAULT")

    def _skolemize_graph(self) -> None:
        ox = self._ox
        rows = list(self._query(
            f"SELECT ?s ?p ?o WHERE {{ GRAPH <{ASSERTED}> {{ ?s ?p ?o }} "
            f"FILTER(isBlank(?s) || isBlank(?o)) }}"
        )) if self._asserted is not self._default else list(self._query(
            "SELECT ?s ?p ?o WHERE { ?s ?p ?o FILTER(isBlank(?s) || isBlank(?o)) }"
        ))
        if not rows:
            return
        old = [ox.Quad(r["s"], r["p"], r["o"], self._asserted) for r in rows]
        new = [skolemize_triple((from_ox(r["s"], ox), from_ox(r["p"], ox), from_ox(r["o"], ox)))
               for r in rows]
        for q in old:
            self._store.remove(q)
        self._insert(new, self._asserted)
        logger.info("Skolemized %d triple(s) with blank nodes", len(rows))

    def _insert(self, triples: list[Triple], graph: Any) -> None:
        ox = self._ox
        quads = []
        for s, p, o in triples:
            if isinstance(s, Literal):
                continue  # generalized triple; not storable
            quads.append(ox.Quad(to_ox(s, ox), to_ox(p, ox), to_ox(o, ox), graph))
        if quads:
            self._store.extend(quads)

    def _has(self, t: Triple, graph: Any) -> bool:
        ox = self._ox
        s, p, o = t
        if isinstance(s, Literal):
            return False
        self.round_trips += 1
        return ox.Quad(to_ox(s, ox), to_ox(p, ox), to_ox(o, ox), graph) in self._store

    def _match(self, pattern: Pattern, graph: Any) -> Iterator[Triple]:
        ox = self._ox
        s, p, o = pattern
        if isinstance(s, Literal):
            return
        self.round_trips += 1
        for q in self._store.quads_for_pattern(
            None if s is None else to_ox(s, ox), None if p is None else to_ox(p, ox),
            None if o is None else to_ox(o, ox), graph,
        ):
            yield (from_ox(q.subject, ox), from_ox(q.predicate, ox), from_ox(q.object, ox))

    def _count(self, graph: Any) -> int:
        clause = ("{ ?s ?p ?o }" if graph is self._default
                  else f"{{ GRAPH <{ASSERTED}> {{ ?s ?p ?o }} }}")
        row = next(iter(self._query(f"SELECT (COUNT(*) AS ?n) WHERE {clause}")))
        return int(row["n"].value)

    def _query(self, q: str) -> Any:
        self.round_trips += 1
        return self._store.query(q)

    def _update(self, u: str) -> None:
        self.round_trips += 1
        self._store.update(u)

    def _record_meta(self) -> None:
        assert self._regime is not None
        self._update(
            f"DROP SILENT GRAPH <{META}>; INSERT DATA {{ GRAPH <{META}> {{ "
            f"<{_STORE}> <{_REGIME}> {Literal(self._regime.name).n3()} ; "
            f"<{_INCONSISTENT}> {Literal(self._inconsistent).n3()} }} }}"
        )

    def _recorded_regime(self) -> str | None:
        q = f"SELECT ?r WHERE {{ GRAPH <{META}> {{ <{_STORE}> <{_REGIME}> ?r }} }}"
        for row in self._query(q):
            return str(row["r"].value)
        return None

    def _recorded_inconsistent(self) -> bool:
        for row in self._query(
            f"SELECT ?i WHERE {{ GRAPH <{META}> {{ <{_STORE}> <{_INCONSISTENT}> ?i }} }}"
        ):
            return str(row["i"].value) == "true"
        return False

    def close(self) -> None:
        """Release the store (an on-disk store holds a lock while open)."""
        self._store = None

    def __enter__(self) -> OxigraphBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        where = str(self._path) if self._path else "memory"
        return f"OxigraphBackend({where}, {self.size()} triples, regime={self._regime})"
