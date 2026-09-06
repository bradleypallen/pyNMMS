"""Axiom-check cost versus number of registered ontology schemas.

The base holds a chain ``subClassOf(C0, C1), ..., subClassOf(C{S-1}, CS)``.

    hit   C_mid(a) => C_mid+1(a)    matched by one schema
    miss  Zed(a)   => Nope(a)       matched by nothing

With the linear scan of issue 6 both columns grow with S; after the Phase 2
index both should be flat (issue 7 requires misses to be indexed too).
"""

from __future__ import annotations

from pynmms.onto.base import OntoMaterialBase
from pynmms.reasoner import NMMSReasoner

from ._util import Section, timeit

SIZES_FULL = (1_000, 10_000, 100_000)
SIZES_QUICK = (100, 1_000)


def make_chain_base(n_schemas: int) -> OntoMaterialBase:
    base = OntoMaterialBase()
    for i in range(n_schemas):
        base.register_subclass(f"C{i}", f"C{i + 1}")
    return base


def run(quick: bool = False) -> Section:
    sizes = SIZES_QUICK if quick else SIZES_FULL
    reps = 15
    section = Section("schema_scaling", ["schemas", "hit_ms", "miss_ms"])
    for n in sizes:
        reasoner = NMMSReasoner(make_chain_base(n))
        mid = n // 2
        hit = timeit(
            lambda: reasoner.derives(frozenset({f"C{mid}(a)"}), frozenset({f"C{mid + 1}(a)"})),
            reps,
        )
        miss = timeit(
            lambda: reasoner.derives(frozenset({"Zed(a)"}), frozenset({"Nope(a)"})), reps
        )
        section.add(n, hit, miss)
    return section
