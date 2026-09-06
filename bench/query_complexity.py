"""Proof cost versus the number of connectives k in the query.

Two curves, neither of which any base-side indexing can change:

    tautology     Γ = ∅ => ((p0 | ~p0) & (p1 | ~p1) & ...) on an empty base.
                  Derivable, so [R&] and [R|] verify every premise and the
                  whole tree is explored. Worst case.
    underivable   (C0(a) & C1(a) & ... & Ck(a)) => C999999(a) against a
                  10k-schema chain. Not derivable, so every branch fails.

Axiom checks are the distinct proof nodes examined (``ProofResult.nodes``);
cost should grow roughly as 2.17^k (memoization shares subgoals below the
naive 3^k).
"""

from __future__ import annotations

from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner

from ._util import Section, timeit
from .schema_scaling import make_chain_base

KS_FULL = (1, 2, 3, 4, 5, 6, 7, 8)
KS_QUICK = (1, 2, 3, 4, 5)


def tautology(k: int) -> str:
    s = "(p0 | ~p0)"
    for i in range(1, k):
        s = f"({s} & (p{i} | ~p{i}))"
    return s


def conjunction_chain(k: int) -> str:
    s = "C0(a)"
    for i in range(k):
        s = f"({s} & C{i + 1}(a))"
    return s


def run(quick: bool = False) -> list[Section]:
    ks = KS_QUICK if quick else KS_FULL
    reps = 3

    taut = Section("query_complexity_tautology", ["k", "axiom_checks", "ms"])
    for k in ks:
        q = frozenset({tautology(k)})
        nodes = NMMSReasoner(MaterialBase()).derives(frozenset(), q).nodes
        ms = timeit(lambda: NMMSReasoner(MaterialBase()).derives(frozenset(), q), reps)
        taut.add(k, nodes, ms)

    chain = make_chain_base(1_000 if quick else 10_000)
    under = Section("query_complexity_underivable", ["k", "ms"],
                    notes="10k-schema chain (1k in quick mode)")
    for k in ks:
        q = frozenset({conjunction_chain(k)})
        d = frozenset({"C999999(a)"})
        under.add(k, timeit(lambda: NMMSReasoner(chain).derives(q, d), reps))

    return [taut, under]
