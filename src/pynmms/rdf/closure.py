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

from rdflib import Literal
from rdflib.namespace import RDF

from pynmms.rdf.rules import AnyRule, Pattern, ProceduralRule, Regime, Rule, Var

if TYPE_CHECKING:
    from rdflib.term import Node

    from pynmms.rdf.atoms import Triple

logger = logging.getLogger(__name__)

Lookup = Callable[[tuple["Node | None", "Node | None", "Node | None"]], Iterable["Triple"]]
Bindings = dict[Var, "Node"]
Join = Callable[[list[Pattern], Bindings], Iterable[Bindings]]
"""Answer several patterns at once against the store: all extensions of the
given bindings that make every pattern a store triple. One round trip on a
remote backend."""


class _TripleIndex:
    """In-memory triple set with single and composite indexes for joins.

    Lookups pick the most selective index available: ``(s, p)``, ``(p, o)``,
    ``s``, ``o``, then ``p``. The composite ones matter: a premise such as
    ``?x owl:hasValue C`` with only the object bound must not scan every
    triple whose object is ``C`` (all the type assertions of a class), or
    the class-restriction rules become quadratic in the graph.
    """

    __slots__ = ("triples", "_by_s", "_by_p", "_by_o", "_by_sp", "_by_po")

    def __init__(self) -> None:
        self.triples: set[Triple] = set()
        self._by_s: dict[Node, list[Triple]] = {}
        self._by_p: dict[Node, list[Triple]] = {}
        self._by_o: dict[Node, list[Triple]] = {}
        self._by_sp: dict[tuple[Node, Node], list[Triple]] = {}
        self._by_po: dict[tuple[Node, Node], list[Triple]] = {}

    def add(self, t: Triple) -> bool:
        if t in self.triples:
            return False
        self.triples.add(t)
        self._by_s.setdefault(t[0], []).append(t)
        self._by_p.setdefault(t[1], []).append(t)
        self._by_o.setdefault(t[2], []).append(t)
        self._by_sp.setdefault((t[0], t[1]), []).append(t)
        self._by_po.setdefault((t[1], t[2]), []).append(t)
        return True

    def __contains__(self, t: object) -> bool:
        return t in self.triples

    def __len__(self) -> int:
        return len(self.triples)

    def match(self, pattern: tuple[Node | None, Node | None, Node | None]) -> Iterator[Triple]:
        s, p, o = pattern
        if s is not None and p is not None and o is not None:
            if (s, p, o) in self.triples:
                yield (s, p, o)
            return
        cands: Iterable[Triple]
        if s is not None and p is not None:
            cands = self._by_sp.get((s, p), ())
        elif p is not None and o is not None:
            cands = self._by_po.get((p, o), ())
        elif s is not None:
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
        self._by_pred: dict[Node | None, list[tuple[AnyRule, int]]] = {}
        for rule in regime.rules:
            if isinstance(rule, ProceduralRule):
                for trig in rule.triggers:
                    self._by_pred.setdefault(trig, []).append((rule, -1))
                continue
            for i, prem in enumerate(rule.premises):
                key = None if isinstance(prem[1], Var) else prem[1]
                self._by_pred.setdefault(key, []).append((rule, i))

    def _candidates(self, t: Triple) -> Iterable[tuple[AnyRule, int]]:
        yield from self._by_pred.get(t[1], ())
        yield from self._by_pred.get(None, ())

    def _fire(self, rule: AnyRule, i: int, t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
        """All conclusions of *rule* with premise *i* matched to *t*."""
        if isinstance(rule, ProceduralRule):
            yield from rule.fire(t, lookup)
            return
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

        yield from self._conclude(rule, join(0, b0))

    def _fire_batched(
        self, rule: Rule, i: int, t: Triple, new: _TripleIndex, store_join: Join
    ) -> Iterator[Triple | None]:
        """Like ``_fire`` but with the store-resident premises answered in one query.

        The remaining premises are split into those matched against the
        in-process ``new`` set and those handed to the store. Every subset is
        tried; the ``new`` positions are bound first (they are few) and the
        store is then asked for all extensions over the other positions at
        once. ``new`` and the store are disjoint, so the subsets partition the
        space and nothing is derived twice.
        """
        b0 = _unify(rule.premises[i], t, {})
        if b0 is None:
            return
        rest = [p for j, p in enumerate(rule.premises) if j != i]
        n = len(rest)

        def bindings() -> Iterator[Bindings]:
            for mask in range(1 << n):
                from_new = [j for j in range(n) if mask >> j & 1]
                from_store = [rest[j] for j in range(n) if not mask >> j & 1]

                def go(idx: int, b: Bindings) -> Iterator[Bindings]:
                    if idx == len(from_new):
                        if from_store:
                            yield from store_join(from_store, b)
                        else:
                            yield b
                        return
                    pat = rest[from_new[idx]]
                    for cand in new.match(_instantiate(pat, b)):
                        b2 = _unify(pat, cand, b)
                        if b2 is not None:
                            yield from go(idx + 1, b2)

                yield from go(0, b0)

        yield from self._conclude(rule, bindings())

    @staticmethod
    def _conclude(rule: Rule, bindings: Iterable[Bindings]) -> Iterator[Triple | None]:
        for b in bindings:
            if rule.guard is not None and not rule.guard(b):
                continue
            yield None if rule.conclusion is None else _ground(rule.conclusion, b)

    def extend(
        self,
        extras: Iterable[Triple],
        store_lookup: Lookup | None,
        store_contains: Callable[[Triple], bool] | None,
        store_join: Join | None = None,
    ) -> tuple[_TripleIndex, bool]:
        """Close ``store ∪ extras`` incrementally.

        Returns the set of triples in the closure that are *not* in the store
        (the extras themselves included) and whether ⊥ was derived. With
        *store_join* the pattern rules batch their store-side premises into
        one query per firing (procedural rules still use *store_lookup*).
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
                    if store_join is not None and isinstance(rule, Rule):
                        conclusions = self._fire_batched(rule, i, t, new, store_join)
                    else:
                        conclusions = self._fire(rule, i, t, lookup)
                    for concl in conclusions:
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


def _selectivity(pattern: Pattern, bound: set[Var]) -> tuple[int, int, int, int]:
    """Higher sorts first, without any cardinality statistics.

    In order: more bound terms; a bound literal object (a literal value is
    usually unique); not an ``rdf:type`` pattern (a class has many members);
    a bound subject over a bound object.
    """
    fixed = sum(1 for t in pattern if not isinstance(t, Var) or t in bound)
    subj, pred, obj = pattern
    obj_bound = not isinstance(obj, Var) or obj in bound
    literal_obj = 1 if isinstance(obj, Literal) else 0
    not_type = 0 if pred == RDF.type else 1
    subj_bound = 1 if (not isinstance(subj, Var) or subj in bound) else 0
    return (fixed, literal_obj, not_type, subj_bound if not obj_bound else 0)


def order_patterns(patterns: list[Pattern], bindings: Bindings) -> list[Pattern]:
    """Greedy join order: at each step the pattern with the most bound terms.

    A pattern query such as ``?b a C . ?b name "x"`` must start from the
    name, which matches once, not from the class, which matches every member.
    """
    remaining = list(patterns)
    bound = set(bindings)
    ordered: list[Pattern] = []
    while remaining:
        best = max(remaining, key=lambda p: _selectivity(p, bound))
        remaining.remove(best)
        ordered.append(best)
        bound |= {t for t in best if isinstance(t, Var)}
    return ordered


def join_patterns(
    patterns: list[Pattern], bindings: Bindings, lookup: Lookup
) -> Iterator[Bindings]:
    """All extensions of *bindings* making every pattern a triple of *lookup*."""
    patterns = order_patterns(patterns, bindings)

    def go(k: int, b: Bindings) -> Iterator[Bindings]:
        if k == len(patterns):
            yield b
            return
        for cand in lookup(_instantiate(patterns[k], b)):
            b2 = _unify(patterns[k], cand, b)
            if b2 is not None:
                yield from go(k + 1, b2)

    return go(0, bindings)


def match_patterns(patterns: Iterable[Pattern], lookup: Lookup) -> Bindings | None:
    """Find one instance mapping making every pattern a triple in *lookup*.

    This is the witness search of Lemma 33: with the blank nodes of a
    succedent graph H as variables, ``H`` is entailed iff some binding puts
    all of ``μ(H)`` in the closure. Returns the binding or ``None``.
    """
    pats = order_patterns(list(patterns), {})

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
