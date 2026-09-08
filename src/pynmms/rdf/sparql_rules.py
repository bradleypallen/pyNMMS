"""Translate regime rules into SPARQL so a store can run the closure itself.

A pattern :class:`~pynmms.rdf.rules.Rule` ``<A, c>`` (``def:entailmentregime``)
with no guard becomes one ``INSERT { c } WHERE { A FILTER NOT EXISTS { c } }``
update; running the whole set to a fixpoint materialises ``cl_R(G)`` inside
the store, with the store's own join engine doing the work. A ⊥ rule becomes
``ASK { A }``: true iff the store's graph is R-inconsistent
(``prop:incoherence``). Rules with a Python guard and
:class:`~pynmms.rdf.rules.ProceduralRule`\\s are not translatable and are
reported by :func:`partition`; a backend runs those in process against the
store.

Terms are written in N3: rdflib nodes through ``Node.n3()``, rule variables
as ``?name``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rdflib import Literal
from rdflib.term import Node

from pynmms.rdf.rules import ProceduralRule, Regime, Rule, Var

logger = logging.getLogger(__name__)

RuleLike = Rule | ProceduralRule

PROLOGUE = "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> "


def term_n3(t: Any) -> str:
    """N3 for a rule term: ``?x`` for a variable, ``Node.n3()`` otherwise."""
    if isinstance(t, Var):
        return f"?{t.name}"
    if isinstance(t, Node):
        return t.n3()  # type: ignore[no-any-return]
    raise TypeError(f"not a rule term: {t!r}")


def pattern_n3(p: tuple[Any, Any, Any]) -> str:
    return " ".join(term_n3(t) for t in p)


def bgp(premises: tuple[tuple[Any, Any, Any], ...]) -> str:
    """The basic graph pattern of a premise set."""
    return " . ".join(pattern_n3(p) for p in premises)


def order_bgp(patterns: list[Any], bindings: dict[Any, Any]) -> list[Any]:
    """Order a basic graph pattern for a store without a statistics planner.

    Oxigraph evaluates a BGP left to right, so ``?x a ex:C2 . ?x ex:p ex:j7``
    scans every instance of the class before touching the selective triple
    (2.8 s against 0.4 ms on a 10⁷ graph). Most bound terms first, an
    ``rdf:type`` pattern with an unbound subject last, and among equals a
    pattern sharing a variable with an earlier one before one that does not.
    """
    from rdflib import RDF

    def bound(t: Any) -> bool:
        return not isinstance(t, Var) or t in bindings

    remaining = list(patterns)
    ordered: list[Any] = []
    seen: set[Any] = set()
    while remaining:
        def key(p: Any) -> tuple[int, int, int]:
            s, pr, o = p
            n_bound = sum(bound(t) for t in p)
            type_scan = int(bound(pr) and pr == RDF.type and not bound(s))
            joins = int(any(isinstance(t, Var) and t in seen for t in p))
            return (-n_bound, type_scan, -joins)

        best = min(remaining, key=key)
        remaining.remove(best)
        ordered.append(best)
        seen.update(t for t in best if isinstance(t, Var))
    return ordered


def translatable(rule: RuleLike) -> bool:
    """Can *rule* run as one SPARQL update or ASK?

    Pattern rules without a guard are translatable. A rule whose conclusion
    has a literal in subject position is not: it is a generalized triple
    (``def:rdftriple``) that a SPARQL store cannot hold.
    """
    if not isinstance(rule, Rule):
        return False
    if rule.guard is not None and (rule.guard_expr is None or rule.guard_expr.to_sparql() is None):
        return False
    if rule.conclusion is not None and isinstance(rule.conclusion[0], Literal):
        return False
    return True


def _filter(rule: Rule) -> str:
    """The ``FILTER`` clause of a guarded rule, empty when there is no guard."""
    if rule.guard_expr is None:
        return ""
    return f" FILTER({rule.guard_expr.to_sparql()})"


def rule_to_update(rule: Rule, *, into: str | None = None) -> str:
    """``INSERT { c } WHERE { A FILTER NOT EXISTS { c } }`` for a pattern rule.

    With *into* an IRI, the conclusions go to that named graph while the
    premises and the ``NOT EXISTS`` check read the default graph.
    """
    if rule.conclusion is None:
        raise ValueError(f"{rule.name} is false-concluding; use rule_to_ask")
    if not translatable(rule):
        raise ValueError(f"{rule.name} is not translatable to SPARQL")
    head = pattern_n3(rule.conclusion)
    target = f"GRAPH <{into}> {{ {head} }}" if into else head
    return (f"{PROLOGUE}INSERT {{ {target} }} WHERE {{ {bgp(rule.premises)}{_filter(rule)} "
            f"FILTER NOT EXISTS {{ {head} }} }}")


def rule_to_ask(rule: Rule) -> str:
    """``ASK { A }`` for a false-concluding pattern rule."""
    if rule.conclusion is not None:
        raise ValueError(f"{rule.name} is not false-concluding")
    if not translatable(rule):
        raise ValueError(f"{rule.name} is not translatable to SPARQL")
    return f"{PROLOGUE}ASK {{ {bgp(rule.premises)}{_filter(rule)} }}"


@dataclass(frozen=True)
class StoreRules:
    """A regime split into what the store runs and what stays in process."""

    updates: tuple[str, ...]
    asks: tuple[str, ...]
    in_process: tuple[RuleLike, ...]
    skipped: tuple[str, ...]

    @property
    def store_side(self) -> int:
        return len(self.updates) + len(self.asks)


def partition(regime: Regime, *, skip: frozenset[str] = frozenset()) -> StoreRules:
    """Split *regime* into SPARQL updates, SPARQL asks, and in-process rules.

    Rule names in *skip* are dropped altogether (with a log line); a backend
    uses this for rules whose conclusions it cannot store.
    """
    updates: list[str] = []
    asks: list[str] = []
    in_process: list[RuleLike] = []
    skipped: list[str] = []
    for rule in regime.rules:
        if rule.name in skip:
            skipped.append(rule.name)
        elif translatable(rule):
            assert isinstance(rule, Rule)
            (asks if rule.conclusion is None else updates).append(
                rule_to_ask(rule) if rule.conclusion is None else rule_to_update(rule)
            )
        else:
            in_process.append(rule)
    if skipped:
        logger.info("Regime %s: %d rule(s) skipped for the store: %s",
                    regime.name, len(skipped), ", ".join(skipped))
    logger.debug("Regime %s: %d store-side rule(s), %d in process",
                 regime.name, len(updates) + len(asks), len(in_process))
    return StoreRules(tuple(updates), tuple(asks), tuple(in_process), tuple(skipped))
