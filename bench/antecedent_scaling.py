"""Query cost versus antecedent size |Γ|.

Γ is n irrelevant ground atoms plus ``Man(a)``; the base has
``subClassOf(Man, Mortal)``.

    hit   Γ => Man(a)      succeeds by Containment before any rule is tried
    miss  Γ => Mortal(a)   the schema needs an exact match, so the irrelevant
                           atoms defeat it and every left rule is tried

The miss column is the one that exposes the Θ(|Γ|²) left-rule loop (issue 1)
and the per-node re-parse of Γ (issue 3). After Phase 2 a GUARDED schema
turns this case into a hit; keep both columns so the change is visible.
"""

from __future__ import annotations

from pynmms.onto.base import OntoMaterialBase
from pynmms.reasoner import NMMSReasoner

from ._util import Section, timeit

SIZES_FULL = (501, 1001, 2001, 4001, 8001)
SIZES_QUICK = (101, 201, 401)


def run(quick: bool = False) -> Section:
    sizes = SIZES_QUICK if quick else SIZES_FULL
    reps = 5 if quick else 3
    base = OntoMaterialBase()
    base.register_subclass("Man", "Mortal")
    reasoner = NMMSReasoner(base)
    section = Section(
        "antecedent_scaling",
        ["gamma", "hit_ms", "miss_ms", "miss_growth"],
        notes="growth = miss_ms ratio to previous row; ~2x is linear, ~4x quadratic",
    )
    prev = None
    for n in sizes:
        gamma = frozenset({f"P{i}(x{i})" for i in range(n - 1)} | {"Man(a)"})
        hit = timeit(lambda: reasoner.derives(gamma, frozenset({"Man(a)"})), reps)
        miss = timeit(lambda: reasoner.derives(gamma, frozenset({"Mortal(a)"})), reps)
        growth = (miss / prev) if prev else float("nan")
        section.add(n, hit, miss, growth)
        prev = miss
    return section
