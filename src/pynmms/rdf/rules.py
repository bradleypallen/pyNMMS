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

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF
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


Guard = Callable[[dict["Var", Node]], bool]


@dataclass(frozen=True)
class Rule:
    """A Horn rule schema. ``conclusion is None`` means ⊥ (false-concluding).

    ``guard`` is an optional side condition on the bindings (Definition 9
    admits conditions such as "is a literal" that substitution preserves).
    """

    name: str
    premises: tuple[Pattern, ...]
    conclusion: Pattern | None
    guard: Guard | None = None

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

L = Var("l")


def _is_literal(b: dict[Var, Node]) -> bool:
    return isinstance(b.get(L), Literal)


LITERAL_RULES: tuple[Rule, ...] = (
    # rdfs1: every literal is an rdfs:Literal (generalized RDF lets it be a subject)
    Rule("rdfs1", ((X, P, L),), (L, RDF.type, RDFSNS.Literal), guard=_is_literal),
)

SIMPLE = Regime("simple")
RDFS = Regime("rdfs", RDFS_RULES + LITERAL_RULES, RDFS_AXIOMS)

# --- OWL 2 RL/RDF (W3C OWL 2 Profiles, Section 4.3, Tables 4-9) ---
#
# The fixed-arity rules. Rules whose premises range over an rdf:List of
# arbitrary length (prp-spo2, prp-key, prp-adp, cls-int1, cls-int2, cls-uni,
# cls-oo, cax-adc, eq-diff2, eq-diff3, scm-int, scm-uni) are rule *families*
# indexed by list length and are not expressible as a single pattern; they
# are omitted here and documented in the tutorial. Datatype rules (Table 8
# dt-*) are also omitted: they need the datatype value spaces.

V1, V2, U, W, C1, C2, P1, P2, I1, I2 = (Var(v) for v in
                                        ("v1", "v2", "u", "w", "c1", "c2", "p1", "p2", "i1", "i2"))
_TYPE = RDF.type

OWL2RL_RULES: tuple[Rule, ...] = (
    # Table 4: equality
    Rule("eq-sym", ((X, OWL.sameAs, Y),), (Y, OWL.sameAs, X)),
    Rule("eq-trans", ((X, OWL.sameAs, Y), (Y, OWL.sameAs, Z)), (X, OWL.sameAs, Z)),
    Rule("eq-rep-s", ((X, OWL.sameAs, Y), (X, P, Z)), (Y, P, Z)),
    Rule("eq-rep-p", ((P, OWL.sameAs, Q), (X, P, Z)), (X, Q, Z)),
    Rule("eq-rep-o", ((Z, OWL.sameAs, W), (X, P, Z)), (X, P, W)),
    Rule("eq-diff1", ((X, OWL.sameAs, Y), (X, OWL.differentFrom, Y)), None),
    # Table 5: properties
    Rule("prp-dom", ((P, RDFSNS.domain, C), (X, P, Y)), (X, _TYPE, C)),
    Rule("prp-rng", ((P, RDFSNS.range, C), (X, P, Y)), (Y, _TYPE, C)),
    Rule("prp-fp", ((P, _TYPE, OWL.FunctionalProperty), (X, P, Y), (X, P, Z)), (Y, OWL.sameAs, Z)),
    Rule("prp-ifp", ((P, _TYPE, OWL.InverseFunctionalProperty), (X, P, Y), (Z, P, Y)),
         (X, OWL.sameAs, Z)),
    Rule("prp-irp", ((P, _TYPE, OWL.IrreflexiveProperty), (X, P, X)), None),
    Rule("prp-symp", ((P, _TYPE, OWL.SymmetricProperty), (X, P, Y)), (Y, P, X)),
    Rule("prp-asyp", ((P, _TYPE, OWL.AsymmetricProperty), (X, P, Y), (Y, P, X)), None),
    Rule("prp-trp", ((P, _TYPE, OWL.TransitiveProperty), (X, P, Y), (Y, P, Z)), (X, P, Z)),
    Rule("prp-spo1", ((P1, RDFSNS.subPropertyOf, P2), (X, P1, Y)), (X, P2, Y)),
    Rule("prp-eqp1", ((P1, OWL.equivalentProperty, P2), (X, P1, Y)), (X, P2, Y)),
    Rule("prp-eqp2", ((P1, OWL.equivalentProperty, P2), (X, P2, Y)), (X, P1, Y)),
    Rule("prp-pdw", ((P1, OWL.propertyDisjointWith, P2), (X, P1, Y), (X, P2, Y)), None),
    Rule("prp-inv1", ((P1, OWL.inverseOf, P2), (X, P1, Y)), (Y, P2, X)),
    Rule("prp-inv2", ((P1, OWL.inverseOf, P2), (X, P2, Y)), (Y, P1, X)),
    Rule("prp-npa1", ((X, OWL.sourceIndividual, I1), (X, OWL.assertionProperty, P),
                      (X, OWL.targetIndividual, I2), (I1, P, I2)), None),
    Rule("prp-npa2", ((X, OWL.sourceIndividual, I1), (X, OWL.assertionProperty, P),
                      (X, OWL.targetValue, L), (I1, P, L)), None),
    # Table 6: classes
    Rule("cls-nothing2", ((X, _TYPE, OWL.Nothing),), None),
    Rule("cls-com", ((C1, OWL.complementOf, C2), (X, _TYPE, C1), (X, _TYPE, C2)), None),
    Rule("cls-svf2", ((X, OWL.someValuesFrom, OWL.Thing), (X, OWL.onProperty, P), (U, P, V1)),
         (U, _TYPE, X)),
    Rule("cls-avf", ((X, OWL.allValuesFrom, Y), (X, OWL.onProperty, P), (U, _TYPE, X), (U, P, V1)),
         (V1, _TYPE, Y)),
    Rule("cls-hv1", ((X, OWL.hasValue, Y), (X, OWL.onProperty, P), (U, _TYPE, X)), (U, P, Y)),
    Rule("cls-hv2", ((X, OWL.hasValue, Y), (X, OWL.onProperty, P), (U, P, Y)), (U, _TYPE, X)),
    Rule("cls-maxc2", ((X, OWL.maxCardinality, Literal(1)), (X, OWL.onProperty, P),
                       (U, _TYPE, X), (U, P, Y), (U, P, Z)), (Y, OWL.sameAs, Z)),
    Rule("cls-maxqc3", ((X, OWL.maxQualifiedCardinality, Literal(1)), (X, OWL.onProperty, P),
                        (X, OWL.onClass, C), (U, _TYPE, X), (U, P, Y), (Y, _TYPE, C),
                        (U, P, Z), (Z, _TYPE, C)), (Y, OWL.sameAs, Z)),
    Rule("cls-maxqc4", ((X, OWL.maxQualifiedCardinality, Literal(1)), (X, OWL.onProperty, P),
                        (X, OWL.onClass, OWL.Thing), (U, _TYPE, X), (U, P, Y), (U, P, Z)),
         (Y, OWL.sameAs, Z)),
    Rule("cls-maxc1", ((X, OWL.maxCardinality, Literal(0)), (X, OWL.onProperty, P),
                       (U, _TYPE, X), (U, P, Y)), None),
    Rule("cls-maxqc1", ((X, OWL.maxQualifiedCardinality, Literal(0)), (X, OWL.onProperty, P),
                        (X, OWL.onClass, C), (U, _TYPE, X), (U, P, Y), (Y, _TYPE, C)), None),
    Rule("cls-maxqc2", ((X, OWL.maxQualifiedCardinality, Literal(0)), (X, OWL.onProperty, P),
                        (X, OWL.onClass, OWL.Thing), (U, _TYPE, X), (U, P, Y)), None),
    # Table 7: class axioms
    Rule("cax-sco", ((C1, RDFSNS.subClassOf, C2), (X, _TYPE, C1)), (X, _TYPE, C2)),
    Rule("cax-eqc1", ((C1, OWL.equivalentClass, C2), (X, _TYPE, C1)), (X, _TYPE, C2)),
    Rule("cax-eqc2", ((C1, OWL.equivalentClass, C2), (X, _TYPE, C2)), (X, _TYPE, C1)),
    Rule("cax-dw", ((C1, OWL.disjointWith, C2), (X, _TYPE, C1), (X, _TYPE, C2)), None),
    # Table 9: schema
    Rule("scm-cls", ((C, _TYPE, OWL.Class),), (C, RDFSNS.subClassOf, C)),
    Rule("scm-cls2", ((C, _TYPE, OWL.Class),), (C, OWL.equivalentClass, C)),
    Rule("scm-cls3", ((C, _TYPE, OWL.Class),), (C, RDFSNS.subClassOf, OWL.Thing)),
    Rule("scm-cls4", ((C, _TYPE, OWL.Class),), (OWL.Nothing, RDFSNS.subClassOf, C)),
    Rule("scm-sco", ((C1, RDFSNS.subClassOf, C2), (C2, RDFSNS.subClassOf, C)),
         (C1, RDFSNS.subClassOf, C)),
    Rule("scm-eqc1", ((C1, OWL.equivalentClass, C2),), (C1, RDFSNS.subClassOf, C2)),
    Rule("scm-eqc1b", ((C1, OWL.equivalentClass, C2),), (C2, RDFSNS.subClassOf, C1)),
    Rule("scm-eqc2", ((C1, RDFSNS.subClassOf, C2), (C2, RDFSNS.subClassOf, C1)),
         (C1, OWL.equivalentClass, C2)),
    Rule("scm-op", ((P, _TYPE, OWL.ObjectProperty),), (P, RDFSNS.subPropertyOf, P)),
    Rule("scm-op2", ((P, _TYPE, OWL.ObjectProperty),), (P, OWL.equivalentProperty, P)),
    Rule("scm-dp", ((P, _TYPE, OWL.DatatypeProperty),), (P, RDFSNS.subPropertyOf, P)),
    Rule("scm-dp2", ((P, _TYPE, OWL.DatatypeProperty),), (P, OWL.equivalentProperty, P)),
    Rule("scm-spo", ((P1, RDFSNS.subPropertyOf, P2), (P2, RDFSNS.subPropertyOf, P)),
         (P1, RDFSNS.subPropertyOf, P)),
    Rule("scm-eqp1", ((P1, OWL.equivalentProperty, P2),), (P1, RDFSNS.subPropertyOf, P2)),
    Rule("scm-eqp1b", ((P1, OWL.equivalentProperty, P2),), (P2, RDFSNS.subPropertyOf, P1)),
    Rule("scm-eqp2", ((P1, RDFSNS.subPropertyOf, P2), (P2, RDFSNS.subPropertyOf, P1)),
         (P1, OWL.equivalentProperty, P2)),
    Rule("scm-dom1", ((P, RDFSNS.domain, C1), (C1, RDFSNS.subClassOf, C2)),
         (P, RDFSNS.domain, C2)),
    Rule("scm-dom2", ((P2, RDFSNS.domain, C), (P1, RDFSNS.subPropertyOf, P2)),
         (P1, RDFSNS.domain, C)),
    Rule("scm-rng1", ((P, RDFSNS.range, C1), (C1, RDFSNS.subClassOf, C2)), (P, RDFSNS.range, C2)),
    Rule("scm-rng2", ((P2, RDFSNS.range, C), (P1, RDFSNS.subPropertyOf, P2)),
         (P1, RDFSNS.range, C)),
    Rule("scm-hv", ((C1, OWL.hasValue, I1), (C1, OWL.onProperty, P1),
                    (C2, OWL.hasValue, I1), (C2, OWL.onProperty, P2),
                    (P1, RDFSNS.subPropertyOf, P2)), (C1, RDFSNS.subClassOf, C2)),
    Rule("scm-svf1", ((C1, OWL.someValuesFrom, Y), (C1, OWL.onProperty, P),
                      (C2, OWL.someValuesFrom, Z), (C2, OWL.onProperty, P),
                      (Y, RDFSNS.subClassOf, Z)), (C1, RDFSNS.subClassOf, C2)),
    Rule("scm-svf2", ((C1, OWL.someValuesFrom, Y), (C1, OWL.onProperty, P1),
                      (C2, OWL.someValuesFrom, Y), (C2, OWL.onProperty, P2),
                      (P1, RDFSNS.subPropertyOf, P2)), (C1, RDFSNS.subClassOf, C2)),
    Rule("scm-avf1", ((C1, OWL.allValuesFrom, Y), (C1, OWL.onProperty, P),
                      (C2, OWL.allValuesFrom, Z), (C2, OWL.onProperty, P),
                      (Y, RDFSNS.subClassOf, Z)), (C1, RDFSNS.subClassOf, C2)),
    Rule("scm-avf2", ((C1, OWL.allValuesFrom, Y), (C1, OWL.onProperty, P1),
                      (C2, OWL.allValuesFrom, Y), (C2, OWL.onProperty, P2),
                      (P1, RDFSNS.subPropertyOf, P2)), (C2, RDFSNS.subClassOf, C1)),
)

OWL2RL_OMITTED = (
    "prp-spo2", "prp-key", "prp-adp", "cls-int1", "cls-int2", "cls-uni", "cls-oo",
    "cax-adc", "eq-diff2", "eq-diff3", "scm-int", "scm-uni", "eq-ref", "cls-thing",
    "cls-nothing1", "dt-type1", "dt-type2", "dt-eq", "dt-diff", "dt-not-type",
)
"""OWL 2 RL/RDF rules not implemented: list-valued rule families, the
axiomatic-only rules (eq-ref, cls-thing, cls-nothing1 add a triple per term or
one fixed triple) and the datatype rules."""

OWL2RL = Regime("owl2rl", RDFS_RULES + LITERAL_RULES + OWL2RL_RULES,
                RDFS_AXIOMS + ((OWL.Thing, _TYPE, OWL.Class), (OWL.Nothing, _TYPE, OWL.Class)))

REGIMES: dict[str, Regime] = {"simple": SIMPLE, "rdfs": RDFS, "owl2rl": OWL2RL}


def custom(name: str, rules: tuple[Rule, ...] | list[Rule], axioms: tuple[Triple, ...] = (),
           *, extends: Regime | None = None) -> Regime:
    """A user regime, optionally extending a shipped one."""
    base_rules = extends.rules if extends else ()
    base_axioms = extends.axioms if extends else ()
    return Regime(name, base_rules + tuple(rules), base_axioms + tuple(axioms))


__all__ = [
    "Var", "Rule", "Regime", "Pattern", "Term", "parse_rule", "custom",
    "RDFS_RULES", "RDFS_AXIOMS", "LITERAL_RULES", "OWL2RL_RULES", "OWL2RL_OMITTED",
    "SIMPLE", "RDFS", "OWL2RL", "REGIMES", "URIRef",
]
