"""Query cost versus stored-graph size for the RDF layer (in-memory backend).

Synthetic graph: n individuals typed under a 3-level class chain
``C0 ⊑ C1 ⊑ C2`` plus a role ``p`` with a range. Queries, all with the
whole graph as antecedent:

    atomic     G => (i0 type C2)             closure hit in the store
    negation   G, (i0 type Alive) => ~(i0 type Dead)   extras closure + II
    k4         G => ((i0 type C0) & (i0 type C1)) -> ((i0 type C2) | (i0 type Zed))

Acceptance: per-query cost independent of |G| for each row; the load and
closure columns are the one-time costs and are expected to grow with |G|.
Requires the ``rdf`` extra.
"""

from __future__ import annotations

from ._util import Section, timeit

SIZES_FULL = (10_000, 50_000, 100_000)
SIZES_QUICK = (1_000, 5_000)


def run(quick: bool = False) -> Section:
    try:
        from rdflib import Graph, Namespace
        from rdflib.namespace import RDF, RDFS
    except ImportError:  # pragma: no cover
        return Section("rdf_scale", ["skipped"], [["rdflib not installed"]])
    import time

    from pynmms.rdf import RDFS as RDFS_REGIME
    from pynmms.rdf import RegimeBase, Resolver, parse_rule
    from pynmms.rdf.backends import MemoryBackend
    from pynmms.rdf.rules import custom
    from pynmms.reasoner import NMMSReasoner

    EX = Namespace("http://ex.org/")
    sizes = SIZES_QUICK if quick else SIZES_FULL
    reps = 5
    section = Section(
        "rdf_scale",
        ["triples", "closure", "load_ms", "atomic_ms", "negation_ms", "k4_ms"],
        notes="in-memory backend, RDFS regime plus an Alive/Dead incompatibility rule",
    )
    for n in sizes:
        g = Graph()
        g.bind("ex", EX)
        g.add((EX.C0, RDFS.subClassOf, EX.C1))
        g.add((EX.C1, RDFS.subClassOf, EX.C2))
        g.add((EX.p, RDFS.range, EX.C1))
        for i in range(n):
            g.add((EX[f"i{i}"], RDF.type, EX.C0))
            g.add((EX[f"i{i}"], EX.p, EX[f"j{i}"]))
        rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(g))
        regime = custom("rdfs+ad", [rule], extends=RDFS_REGIME)
        t0 = time.perf_counter()
        backend = MemoryBackend(g, regime=regime, skolemize=False)
        load_ms = (time.perf_counter() - t0) * 1000
        base = RegimeBase(backend)
        r = NMMSReasoner(base, persistent_cache=False)

        atomic = timeit(lambda: r.derives_sequent(base.sequent([], ["<ex:i0 a ex:C2>"])), reps)
        negation = timeit(lambda: r.derives_sequent(base.sequent(
            ["<ex:i0 a ex:Alive>"], ["~<ex:i0 a ex:Dead>"])), reps)
        k4 = timeit(lambda: r.derives_sequent(base.sequent(
            [], ["(<ex:i0 a ex:C0> & <ex:i0 a ex:C1>) -> (<ex:i0 a ex:C2> | <ex:i0 a ex:Zed>)"]
        )), reps)
        assert r.derives_sequent(base.sequent([], ["<ex:i0 a ex:C2>"])).derivable
        section.add(len(g), backend.closure_size(), load_ms, atomic, negation, k4)
    return section
