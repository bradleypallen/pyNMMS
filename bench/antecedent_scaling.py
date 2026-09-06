"""Query cost versus antecedent size |Γ|.

Γ is n irrelevant ground atoms plus ``Man(a)``; the base has
``subClassOf(Man, Mortal)``.

    hit       Γ => Man(a)      succeeds by Containment before any rule is tried
    miss      Γ => Mortal(a)   the EXACT schema needs an exact match, so the
                               irrelevant atoms defeat it
    guarded   Γ => Flies(a)    a GUARDED subClassOf(Bird, Flies) unless Penguin
                               survives the irrelevant atoms (Γ also has Bird(a))
    defeated  Γ, Penguin(a) => Flies(a)   the guard fires

The miss column is the one that exposed the Θ(|Γ|²) left-rule loop (issue 1)
and the per-node re-parse of Γ (issue 3); guarded/defeated exercise the
Phase 2 robust-entry path, which must stay flat in |Γ|.
"""

from __future__ import annotations

from pynmms.onto.base import OntoMaterialBase
from pynmms.reasoner import NMMSReasoner
from pynmms.robustness import guarded

from ._util import Section, timeit

SIZES_FULL = (501, 1001, 2001, 4001, 8001)
SIZES_QUICK = (101, 201, 401)


def run(quick: bool = False) -> Section:
    sizes = SIZES_QUICK if quick else SIZES_FULL
    reps = 5 if quick else 3
    base = OntoMaterialBase()
    base.register_subclass("Man", "Mortal")
    base.register_subclass("Bird", "Flies", robustness=guarded(["Penguin"]))
    reasoner = NMMSReasoner(base)
    section = Section(
        "antecedent_scaling",
        ["gamma", "hit_ms", "miss_ms", "guarded_ms", "defeated_ms", "miss_growth"],
        notes="growth = miss_ms ratio to previous row; ~2x is linear, ~4x quadratic",
    )
    prev = None
    for n in sizes:
        gamma = frozenset({f"P{i}(x{i})" for i in range(n - 2)} | {"Man(a)", "Bird(a)"})
        gamma_defeated = gamma | {"Penguin(a)"}
        hit = timeit(lambda: reasoner.derives(gamma, frozenset({"Man(a)"})), reps)
        miss = timeit(lambda: reasoner.derives(gamma, frozenset({"Mortal(a)"})), reps)
        ok = timeit(lambda: reasoner.derives(gamma, frozenset({"Flies(a)"})), reps)
        defeated = timeit(
            lambda: reasoner.derives(gamma_defeated, frozenset({"Flies(a)"})), reps
        )
        assert reasoner.derives(gamma, frozenset({"Flies(a)"})).derivable
        assert not reasoner.derives(gamma_defeated, frozenset({"Flies(a)"})).derivable
        growth = (miss / prev) if prev else float("nan")
        section.add(n, hit, miss, ok, defeated, growth)
        prev = miss
    return section
