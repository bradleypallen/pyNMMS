"""Material entries as patterns (PLAN.md workstream D).

A :class:`DefeasibleRule` is an entry of the regime-relative material base
with variables, ``⟨A(x̄), D(x̄); E⟩``::

    ?x am:maker ?m, ?m rdf:value ?p |~ ?x am:madeBy ?p unless ?m am:creatorQualifier "naar"
    ?g go:involved_in ?c, ?c rdfs:subClassOf ?d |~ ?g go:involved_in ?d
        unless ?g go:not_involved_in ?d
    ?x ex:maker ?p, ?p ex:died ?d, ?x ex:made ?s, [year(?s) > year(?d)] |~ false
        unless ?x ex:posthumous "yes"

It fires for a substitution σ at a leaf ⟨Γ, Δ⟩ when ``Aσ ⊆ cl_R(Γ)`` (the
premises join against the closure, value guards included), no defeater
has a solution in the closure (a defeater is a conjunction of patterns
that may bind its own variables and carry a guard), and ``Dσ``, elaborated
by the regime, meets Δ. A ⊥ conclusion is an incompatibility, counted
against a position only when its own triples take part in the match
(attribution). ``monotone`` means no defeaters; ``guarded`` is the default
with defeaters given. Entries do not chain: one entry per leaf, its
premises read through the regime, never through another entry.

Matching is by unification. For a Δ atom, the rules whose conclusion
unifies with it are tried with the bindings that gives; for elaboration
and for incompatibilities, rules are anchored on the position's own
triples, so the cost is bounded by the position, not the store.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from rdflib import BNode
from rdflib.term import Node

from pynmms.rdf.atoms import PatternAtom, Resolver, TripleAtom
from pynmms.rdf.rules import Var, _parse_pattern
from pynmms.syntax import split_top_level

logger = logging.getLogger(__name__)

Triple = tuple[Node, Node, Node]
Pattern = tuple[Any, Any, Any]
Bindings = dict[Var, Node]
Lookup = Callable[[tuple[Node | None, Node | None, Node | None]], Iterable[Triple]]


@dataclass(frozen=True)
class Defeater:
    """A conjunction of patterns, with an optional value guard, whose solution defeats."""

    patterns: tuple[Pattern, ...]
    guard_expr: Any = None

    def __str__(self) -> str:
        s = ", ".join(" ".join(str(t) for t in p) for p in self.patterns)
        return f"{s}, [{self.guard_expr}]" if self.guard_expr is not None else s


@dataclass(frozen=True)
class DefeasibleRule:
    """``A |~ D unless E1 ; E2`` with variables; ``D`` ``false`` for an incompatibility."""

    name: str
    premises: tuple[Pattern, ...]
    conclusion: Pattern | None
    defeaters: tuple[Defeater, ...] = ()
    robustness: str = "guarded"
    guard_expr: Any = None

    def __post_init__(self) -> None:
        pvars = {t for p in self.premises for t in p if isinstance(t, Var)}
        if self.conclusion is not None:
            for t in self.conclusion:
                if isinstance(t, Var) and t not in pvars:
                    raise ValueError(f"{self.name!r}: conclusion variable {t} not in premises")
        if self.guard_expr is not None:
            for v in self.guard_expr.variables:
                if v not in pvars:
                    raise ValueError(f"{self.name!r}: guard variable {v} not in premises")
        if self.robustness == "monotone" and self.defeaters:
            raise ValueError(f"{self.name!r}: a monotone entry has no defeaters")
        if self.robustness not in ("monotone", "guarded"):
            raise ValueError(f"{self.name!r}: pattern entries are monotone or guarded")

    @property
    def is_incompatibility(self) -> bool:
        return self.conclusion is None

    def __str__(self) -> str:
        prem = ", ".join(" ".join(str(t) for t in p) for p in self.premises)
        if self.guard_expr is not None:
            prem += f", [{self.guard_expr}]"
        concl = "false" if self.conclusion is None else " ".join(str(t) for t in self.conclusion)
        s = f"{prem} |~ {concl}"
        if self.defeaters:
            s += " unless " + " ; ".join(str(d) for d in self.defeaters)
        elif self.robustness == "monotone":
            s += " monotone"
        return s


# --- Parsing ------------------------------------------------------------------


def _patterns_and_guard(text: str, resolver: Resolver | None) -> tuple[tuple[Pattern, ...], Any]:
    parts = [p.strip() for p in split_top_level(text, ",") if p.strip()]
    guards = [p[1:-1].strip() for p in parts if p.startswith("[") and p.endswith("]")]
    patterns = tuple(_parse_pattern(p, resolver) for p in parts
                     if not (p.startswith("[") and p.endswith("]")))
    guard = None
    if guards:
        from pynmms.rdf.values import parse_guard

        text = " && ".join(f"({g})" for g in guards) if len(guards) > 1 else guards[0]
        guard = parse_guard(text)
    return patterns, guard


def parse_defeasible_rule(text: str, resolver: Resolver | None = None,
                          name: str | None = None) -> DefeasibleRule:
    """Parse ``A |~ D [unless E1 ; E2 | monotone]`` with variables."""
    if "|~" not in text:
        raise ValueError(f"pattern entry needs |~: {text!r}")
    left, right = text.split("|~", 1)
    premises, guard = _patterns_and_guard(left, resolver)
    if not premises:
        raise ValueError(f"pattern entry has no premises: {text!r}")
    right = right.strip()
    robustness = "guarded"
    defeaters: list[Defeater] = []
    if right.endswith(" monotone") or right == "monotone":
        right = right[: -len("monotone")].strip()
        robustness = "monotone"
    else:
        pieces = split_top_level(right, " unless ")
        if len(pieces) > 1:
            right = pieces[0].strip()
            for alt in split_top_level(" unless ".join(pieces[1:]), ";"):
                pats, dguard = _patterns_and_guard(alt, resolver)
                if not pats:
                    raise ValueError(f"empty defeater in {text!r}")
                defeaters.append(Defeater(pats, dguard))
    if right.lower() in ("", "false", "⊥", "bottom"):
        conclusion = None
    else:
        concl_patterns, cguard = _patterns_and_guard(right, resolver)
        if len(concl_patterns) != 1 or cguard is not None:
            raise ValueError(f"a pattern entry concludes one pattern: {text!r}")
        conclusion = concl_patterns[0]
    return DefeasibleRule(name or text.strip(), premises, conclusion, tuple(defeaters),
                          robustness, guard)


def is_pattern_entry(text: str) -> bool:
    """Does a tell-syntax line have variables (a pattern entry, not a ground one)?"""
    return "|~" in text and "?" in text.split("|~", 1)[0]


# --- Matching -----------------------------------------------------------------


def unify(pattern: Pattern, t: Triple, bindings: Bindings | None = None) -> Bindings | None:
    b: Bindings = dict(bindings or {})
    for p, x in zip(pattern, t):
        if isinstance(p, Var):
            if p in b:
                if b[p] != x:
                    return None
            else:
                b[p] = x
        elif p != x:
            return None
    return b


def apply(pattern: Pattern, b: Bindings) -> Pattern:
    return tuple(b.get(x, x) if isinstance(x, Var) else x for x in pattern)  # type: ignore[return-value]


def is_ground(pattern: Pattern) -> bool:
    return not any(isinstance(x, Var) for x in pattern)


def as_atom(pattern: Pattern) -> str:
    """A ground pattern as a triple atom, an open one as a pattern atom with blank nodes."""
    if is_ground(pattern):
        return str(TripleAtom(*pattern))
    return str(PatternAtom([tuple(BNode(x.name) if isinstance(x, Var) else x for x in pattern)]))  # type: ignore[misc, list-item]


class Matcher:
    """Match pattern entries against a closure given as a lookup."""

    def __init__(self, rules: Iterable[DefeasibleRule], lookup: Lookup) -> None:
        self.rules = list(rules)
        self.lookup = lookup

    def solutions(self, patterns: Iterable[Pattern], b: Bindings, guard: Any = None
                  ) -> Iterator[Bindings]:
        from pynmms.rdf.closure import join_patterns

        for sol in join_patterns(list(patterns), b, self.lookup):
            if guard is None or guard.evaluate(sol):
                yield sol

    def complete(self, rule: DefeasibleRule, b: Bindings) -> Iterator[Bindings]:
        """Full substitutions extending *b* under which the premises hold."""
        yield from self.solutions(rule.premises, b, rule.guard_expr)

    def defeated(self, rule: DefeasibleRule, b: Bindings) -> Defeater | None:
        for d in rule.defeaters:
            if next(self.solutions(d.patterns, b, d.guard_expr), None) is not None:
                return d
        return None

    def for_conclusion(self, t: Triple) -> Iterator[tuple[DefeasibleRule, Bindings]]:
        """Rules whose conclusion unifies with *t*, with the bindings that gives."""
        for rule in self.rules:
            if rule.conclusion is None:
                continue
            b = unify(rule.conclusion, t)
            if b is not None:
                yield rule, b

    def anchored(self, rule: DefeasibleRule, anchors: Iterable[Triple]
                 ) -> Iterator[Bindings]:
        """Partial substitutions from unifying one premise with an anchor triple."""
        seen: set[tuple[tuple[Var, Node], ...]] = set()
        for premise in rule.premises:
            for t in anchors:
                b = unify(premise, t)
                if b is None:
                    continue
                key = tuple(sorted(b.items(), key=lambda kv: kv[0].name))
                if key in seen:
                    continue
                seen.add(key)
                yield b

    def missing(self, rule: DefeasibleRule, b: Bindings) -> list[str]:
        """Premises with no solution under *b*, as atoms the holder could be asked for."""
        out: list[str] = []
        for premise in rule.premises:
            p = apply(premise, b)
            if next(self.solutions([p], b), None) is None:
                out.append(as_atom(p))
        return out

    def rescue(self, rule: DefeasibleRule, b: Bindings) -> tuple[str, ...]:
        """The defeaters under *b*, as atoms or patterns."""
        out: list[str] = []
        for d in rule.defeaters:
            out.extend(as_atom(apply(p, b)) for p in d.patterns)
        return tuple(out)
