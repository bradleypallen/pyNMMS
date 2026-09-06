"""Semi-naive closure of Horn rules over triples.

Two uses:

* :meth:`ClosureEngine.close` -- full closure of a small graph (the in-memory
  backend's regime materialisation, and the test oracle's counterpart).
* :meth:`ClosureEngine.extend` -- the per-node step of a regime base: given
  a store that already holds ``cl_R(G)`` and a small set of *extra* triples
  (the atoms proof rules have moved into Γ), derive ``cl_R(G ∪ extras) \\
  cl_R(G)`` by firing only rules with at least one premise matching a new
  triple. Remaining premises are joined against the store's closure and the
  new set. Cost is proportional to the new triples and their joins, never to
  |G|.

Rules are range-restricted (Definition 9), so every conclusion is ground.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING

from pynmms.rdf.rules import Pattern, Regime, Rule, Var

if TYPE_CHECKING:
    from rdflib.term import Node

    from pynmms.rdf.atoms import Triple

logger = logging.getLogger(__name__)

Lookup = Callable[[tuple["Node | None", "Node | None", "Node | None"]], Iterable["Triple"]]
Bindings = dict[Var, "Node"]


class _TripleIndex:
    """Small in-memory triple set with s/p/o indexes for joins."""

    __slots__ = ("triples", "_by_s", "_by_p", "_by_o")

    def __init__(self) -> None:
        self.triples: set[Triple] = set()
        self._by_s: dict[Node, list[Triple]] = {}
        self._by_p: dict[Node, list[Triple]] = {}
        self._by_o: dict[Node, list[Triple]] = {}

    def add(self, t: Triple) -> bool:
        if t in self.triples:
            return False
        self.triples.add(t)
        self._by_s.setdefault(t[0], []).append(t)
        self._by_p.setdefault(t[1], []).append(t)
        self._by_o.setdefault(t[2], []).append(t)
        return True

    def __contains__(self, t: object) -> bool:
        return t in self.triples

    def __len__(self) -> int:
        return len(self.triples)

    def match(self, pattern: tuple[Node | None, Node | None, Node | None]) -> Iterator[Triple]:
        s, p, o = pattern
        if s is not None:
            cands = self._by_s.get(s, ())
        elif o is not None:
            cands = self._by_o.get(o, ())
        elif p is not None:
            cands = self._by_p.get(p, ())
        else:
            cands = list(self.triples)
        for t in cands:
            if (s is None or t[0] == s) and (p is None or t[1] == p) and (o is None or t[2] == o):
                yield t


def _unify(pattern: Pattern, t: Triple, bindings: Bindings) -> Bindings | None:
    b = dict(bindings)
    for term, value in zip(pattern, t):
        if isinstance(term, Var):
            bound = b.get(term)
            if bound is None:
                b[term] = value
            elif bound != value:
                return None
        elif term != value:
            return None
    return b


def _instantiate(pattern: Pattern, b: Bindings) -> tuple[Node | None, Node | None, Node | None]:
    out: list[Node | None] = []
    for term in pattern:
        out.append(b.get(term) if isinstance(term, Var) else term)  # type: ignore[arg-type]
    return (out[0], out[1], out[2])


def _ground(pattern: Pattern, b: Bindings) -> Triple:
    t = _instantiate(pattern, b)
    assert None not in t, "range restriction guarantees ground conclusions"
    return t  # type: ignore[return-value]


class ClosureEngine:
    """Fires a regime's rules semi-naively."""

    def __init__(self, regime: Regime) -> None:
        self.regime = regime
        # (rule, premise index) pairs keyed by the premise's constant predicate,
        # with wildcard-predicate premises under None.
        self._by_pred: dict[Node | None, list[tuple[Rule, int]]] = {}
        for rule in regime.rules:
            for i, prem in enumerate(rule.premises):
                key = None if isinstance(prem[1], Var) else prem[1]
                self._by_pred.setdefault(key, []).append((rule, i))

    def _candidates(self, t: Triple) -> Iterable[tuple[Rule, int]]:
        yield from self._by_pred.get(t[1], ())
        yield from self._by_pred.get(None, ())

    def _fire(self, rule: Rule, i: int, t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
        """All conclusions of *rule* with premise *i* matched to *t*."""
        b0 = _unify(rule.premises[i], t, {})
        if b0 is None:
            return
        rest = [p for j, p in enumerate(rule.premises) if j != i]

        def join(k: int, b: Bindings) -> Iterator[Bindings]:
            if k == len(rest):
                yield b
                return
            for cand in lookup(_instantiate(rest[k], b)):
                b2 = _unify(rest[k], cand, b)
                if b2 is not None:
                    yield from join(k + 1, b2)

        for b in join(0, b0):
            if rule.guard is not None and not rule.guard(b):
                continue
            yield None if rule.conclusion is None else _ground(rule.conclusion, b)

    def extend(
        self,
        extras: Iterable[Triple],
        store_lookup: Lookup | None,
        store_contains: Callable[[Triple], bool] | None,
    ) -> tuple[_TripleIndex, bool]:
        """Close ``store ∪ extras`` incrementally.

        Returns the set of triples in the closure that are *not* in the store
        (the extras themselves included) and whether ⊥ was derived.
        """
        new = _TripleIndex()
        frontier: list[Triple] = []
        for t in extras:
            if store_contains is not None and store_contains(t):
                continue
            if new.add(t):
                frontier.append(t)

        def lookup(pattern: tuple[Node | None, Node | None, Node | None]) -> Iterator[Triple]:
            if store_lookup is not None:
                yield from store_lookup(pattern)
            yield from new.match(pattern)

        bottom = False
        rounds = 0
        while frontier:
            rounds += 1
            next_frontier: list[Triple] = []
            for t in frontier:
                for rule, i in self._candidates(t):
                    for concl in self._fire(rule, i, t, lookup):
                        if concl is None:
                            if not bottom:
                                logger.debug("closure: rule %s derives false", rule.name)
                            bottom = True
                            continue
                        if concl in new or (store_contains is not None and store_contains(concl)):
                            continue
                        new.add(concl)
                        next_frontier.append(concl)
            frontier = next_frontier
        logger.debug(
            "closure extend: %d new triples in %d rounds (bottom=%s)", len(new), rounds, bottom
        )
        return new, bottom

    def close(self, triples: Iterable[Triple]) -> tuple[set[Triple], bool]:
        """Full closure of *triples* under the regime, axioms included."""
        new, bottom = self.extend(
            (*self.regime.axioms, *triples), store_lookup=None, store_contains=None
        )
        return new.triples, bottom


def match_patterns(patterns: Iterable[Pattern], lookup: Lookup) -> Bindings | None:
    """Find one instance mapping making every pattern a triple in *lookup*.

    This is the witness search of Lemma 33: with the blank nodes of a
    succedent graph H as variables, ``H`` is entailed iff some binding puts
    all of ``μ(H)`` in the closure. Returns the binding or ``None``.
    """
    pats = list(patterns)

    def go(k: int, b: Bindings) -> Bindings | None:
        if k == len(pats):
            return b
        for cand in lookup(_instantiate(pats[k], b)):
            b2 = _unify(pats[k], cand, b)
            if b2 is not None:
                found = go(k + 1, b2)
                if found is not None:
                    return found
        return None

    return go(0, {})
