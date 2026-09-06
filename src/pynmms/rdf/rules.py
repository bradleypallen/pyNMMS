"""Entailment regimes as Horn rules over generalized RDF triples.

Definition 9 of the paper: a regime is a set of rules ``<A, c>`` with a finite
premise set *A* of triples and a conclusion *c* that is a triple or ⊥,
range-restricted and uniform under substitution. Here a rule is a schema over
variables; its instances are the regime's rules.

Shipped regimes:

* ``SIMPLE`` -- the empty regime (simple entailment, Corollary 36).
* ``RDFS``   -- the RDF and RDFS entailment patterns of RDF 1.1 Semantics
  §9.2.1 (rdf1, rdfs2-13 except the literal-typing rules rdfs1 and rdfD1,
  which need a side condition) with the finite axiomatic triples of §9.2.2
  (the container-membership family ``rdf:_i`` excluded). See Corollary 37.

Custom regimes are built from :func:`parse_rule` lines such as::

    ?x ex:parentOf ?y -> ?y ex:childOf ?x
    ?x a ex:Alive, ?x a ex:Dead -> false
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import URIRef
from rdflib.namespace import RDF
from rdflib.namespace import RDFS as RDFSNS
from rdflib.term import Node

from pynmms.rdf.atoms import Resolver, _tokens, content_to_term
from pynmms.syntax import split_top_level

if TYPE_CHECKING:
    from pynmms.rdf.atoms import Triple


@dataclass(frozen=True, slots=True)
class Var:
    """A rule variable."""

    name: str

    def __str__(self) -> str:
        return f"?{self.name}"


Term = Node | Var
Pattern = tuple[Term, Term, Term]


@dataclass(frozen=True)
class Rule:
    """A Horn rule schema. ``conclusion is None`` means ⊥ (false-concluding)."""

    name: str
    premises: tuple[Pattern, ...]
    conclusion: Pattern | None

    def __post_init__(self) -> None:
        premise_vars = {t for p in self.premises for t in p if isinstance(t, Var)}
        if self.conclusion is not None:
            for t in self.conclusion:
                if isinstance(t, Var) and t not in premise_vars:
                    raise ValueError(
                        f"Rule {self.name!r} is not range-restricted: {t} not in premises"
                    )

    @property
    def is_false_concluding(self) -> bool:
        return self.conclusion is None

    def __str__(self) -> str:
        prem = ", ".join(" ".join(str(t) for t in p) for p in self.premises)
        concl = "false" if self.conclusion is None else " ".join(str(t) for t in self.conclusion)
        return f"{prem} -> {concl}"


@dataclass(frozen=True)
class Regime:
    """A named rule set plus axiomatic triples."""

    name: str
    rules: tuple[Rule, ...] = ()
    axioms: tuple[Triple, ...] = ()

    def __str__(self) -> str:
        return self.name


# --- Rule text parsing ---


def _parse_pattern(text: str, resolver: Resolver | None) -> Pattern:
    toks = list(_tokens(text.strip()))
    if len(toks) != 3:
        raise ValueError(f"A rule pattern needs three terms: {text!r}")

    def term(tok: str, predicate: bool = False) -> Term:
        if tok.startswith("?"):
            return Var(tok[1:])
        return content_to_term(tok, resolver, predicate=predicate)

    return (term(toks[0]), term(toks[1], True), term(toks[2]))


def parse_rule(text: str, resolver: Resolver | None = None, name: str | None = None) -> Rule:
    """Parse ``p1, p2, ... -> conclusion`` where conclusion is a pattern or ``false``."""
    if "->" not in text:
        raise ValueError(f"Rule must contain '->': {text!r}")
    left, right = text.split("->", 1)
    premises = tuple(_parse_pattern(p, resolver) for p in split_top_level(left, ","))
    if not premises:
        raise ValueError(f"Rule has no premises: {text!r}")
    right = right.strip()
    conclusion = None if right.lower() in ("false", "⊥", "bottom") else _parse_pattern(
        right, resolver
    )
    return Rule(name or text.strip(), premises, conclusion)


# --- RDFS ---

X, Y, Z, P, Q, C, D = (Var(v) for v in "xyzpqcd")
_R = RDFSNS.Resource

RDFS_RULES: tuple[Rule, ...] = (
    Rule("rdf1", ((X, P, Y),), (P, RDF.type, RDF.Property)),
    Rule("rdfs2", ((P, RDFSNS.domain, C), (X, P, Y)), (X, RDF.type, C)),
    Rule("rdfs3", ((P, RDFSNS.range, C), (X, P, Y)), (Y, RDF.type, C)),
    Rule("rdfs4a", ((X, P, Y),), (X, RDF.type, _R)),
    Rule("rdfs4b", ((X, P, Y),), (Y, RDF.type, _R)),
    Rule("rdfs5", ((P, RDFSNS.subPropertyOf, Q), (Q, RDFSNS.subPropertyOf, Z)),
         (P, RDFSNS.subPropertyOf, Z)),
    Rule("rdfs6", ((P, RDF.type, RDF.Property),), (P, RDFSNS.subPropertyOf, P)),
    Rule("rdfs7", ((P, RDFSNS.subPropertyOf, Q), (X, P, Y)), (X, Q, Y)),
    Rule("rdfs8", ((C, RDF.type, RDFSNS.Class),), (C, RDFSNS.subClassOf, _R)),
    Rule("rdfs9", ((C, RDFSNS.subClassOf, D), (X, RDF.type, C)), (X, RDF.type, D)),
    Rule("rdfs10", ((C, RDF.type, RDFSNS.Class),), (C, RDFSNS.subClassOf, C)),
    Rule("rdfs11", ((C, RDFSNS.subClassOf, D), (D, RDFSNS.subClassOf, Z)),
         (C, RDFSNS.subClassOf, Z)),
    Rule("rdfs12", ((P, RDF.type, RDFSNS.ContainerMembershipProperty),),
         (P, RDFSNS.subPropertyOf, RDFSNS.member)),
    Rule("rdfs13", ((C, RDF.type, RDFSNS.Datatype),), (C, RDFSNS.subClassOf, RDFSNS.Literal)),
)

_T, _SC, _SP = RDF.type, RDFSNS.subClassOf, RDFSNS.subPropertyOf
_DOM, _RNG = RDFSNS.domain, RDFSNS.range
_PROP, _CLS = RDF.Property, RDFSNS.Class

RDFS_AXIOMS: tuple[Triple, ...] = (
    # RDF axiomatic triples (§9.2.2, finite part)
    (RDF.type, _T, _PROP), (RDF.subject, _T, _PROP), (RDF.predicate, _T, _PROP),
    (RDF.object, _T, _PROP), (RDF.first, _T, _PROP), (RDF.rest, _T, _PROP),
    (RDF.value, _T, _PROP), (RDF.nil, _T, RDF.List),
    # RDFS axiomatic triples: domains
    (RDF.type, _DOM, _R), (RDFSNS.domain, _DOM, _PROP), (RDFSNS.range, _DOM, _PROP),
    (RDFSNS.subPropertyOf, _DOM, _PROP), (RDFSNS.subClassOf, _DOM, _CLS),
    (RDF.subject, _DOM, RDF.Statement), (RDF.predicate, _DOM, RDF.Statement),
    (RDF.object, _DOM, RDF.Statement), (RDFSNS.member, _DOM, _R),
    (RDF.first, _DOM, RDF.List), (RDF.rest, _DOM, RDF.List),
    (RDFSNS.seeAlso, _DOM, _R), (RDFSNS.isDefinedBy, _DOM, _R),
    (RDFSNS.comment, _DOM, _R), (RDFSNS.label, _DOM, _R), (RDF.value, _DOM, _R),
    # ranges
    (RDF.type, _RNG, _CLS), (RDFSNS.domain, _RNG, _CLS), (RDFSNS.range, _RNG, _CLS),
    (RDFSNS.subPropertyOf, _RNG, _PROP), (RDFSNS.subClassOf, _RNG, _CLS),
    (RDF.subject, _RNG, _R), (RDF.predicate, _RNG, _R), (RDF.object, _RNG, _R),
    (RDFSNS.member, _RNG, _R), (RDF.first, _RNG, _R), (RDF.rest, _RNG, RDF.List),
    (RDFSNS.seeAlso, _RNG, _R), (RDFSNS.isDefinedBy, _RNG, _R),
    (RDFSNS.comment, _RNG, RDFSNS.Literal), (RDFSNS.label, _RNG, RDFSNS.Literal),
    (RDF.value, _RNG, _R),
    # subclass / subproperty
    (RDF.Alt, _SC, RDFSNS.Container), (RDF.Bag, _SC, RDFSNS.Container),
    (RDF.Seq, _SC, RDFSNS.Container),
    (RDFSNS.ContainerMembershipProperty, _SC, _PROP),
    (RDFSNS.isDefinedBy, _SP, RDFSNS.seeAlso),
    # datatypes
    (RDF.XMLLiteral, _T, RDFSNS.Datatype), (RDF.XMLLiteral, _SC, RDFSNS.Literal),
    (RDF.HTML, _T, RDFSNS.Datatype), (RDF.HTML, _SC, RDFSNS.Literal),
    (RDFSNS.Datatype, _SC, _CLS),
)

SIMPLE = Regime("simple")
RDFS = Regime("rdfs", RDFS_RULES, RDFS_AXIOMS)

REGIMES: dict[str, Regime] = {"simple": SIMPLE, "rdfs": RDFS}


def custom(name: str, rules: tuple[Rule, ...] | list[Rule], axioms: tuple[Triple, ...] = (),
           *, extends: Regime | None = None) -> Regime:
    """A user regime, optionally extending a shipped one."""
    base_rules = extends.rules if extends else ()
    base_axioms = extends.axioms if extends else ()
    return Regime(name, base_rules + tuple(rules), base_axioms + tuple(axioms))


__all__ = [
    "Var", "Rule", "Regime", "Pattern", "Term", "parse_rule", "custom",
    "RDFS_RULES", "RDFS_AXIOMS", "SIMPLE", "RDFS", "REGIMES", "URIRef",
]
