"""Entailment regimes as Horn rules over generalized RDF triples.

The paper's ``def:entailmentregime``: a regime is a set of rules ``<A, c>`` with a finite
premise set *A* of triples and a conclusion *c* that is a triple or ⊥,
range-restricted and uniform under substitution. Here a rule is a schema over
variables; its instances are the regime's rules.

Shipped regimes:

* ``SIMPLE`` -- the empty regime (simple entailment, ``cor:simple``).
* ``RDFS``   -- the RDF and RDFS entailment patterns of RDF 1.1 Semantics
  §9.2.1 (rdf1, rdfs2-13 except the literal-typing rules rdfs1 and rdfD1,
  which need a side condition) with the finite axiomatic triples of §9.2.2
  (the container-membership family ``rdf:_i`` excluded). See ``cor:rdfs``.

Custom regimes are built from :func:`parse_rule` lines such as::

    ?x ex:parentOf ?y -> ?y ex:childOf ?x
    ?x a ex:Alive, ?x a ex:Dead -> false
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rdflib import Literal
from rdflib.namespace import OWL, RDF
from rdflib.namespace import RDFS as RDFSNS
from rdflib.term import Node

from pynmms.rdf.atoms import Resolver, _tokens, content_to_term

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

    ``guard`` is an optional side condition on the bindings (``def:entailmentregime``
    admits conditions such as "is a literal" that substitution preserves).
    """

    name: str
    premises: tuple[Pattern, ...]
    conclusion: Pattern | None
    guard: Guard | None = None
    #: A value guard (``pynmms.rdf.values.Guard``) written in the rule; when set and
    #: ``guard`` is not, ``guard`` is its Python evaluation, and the store runs it
    #: as a ``FILTER``.
    guard_expr: Any = None

    def __post_init__(self) -> None:
        premise_vars = {t for p in self.premises for t in p if isinstance(t, Var)}
        if self.conclusion is not None:
            for t in self.conclusion:
                if isinstance(t, Var) and t not in premise_vars:
                    raise ValueError(
                        f"Rule {self.name!r} is not range-restricted: {t} not in premises"
                    )
        if self.guard_expr is not None:
            for v in self.guard_expr.variables:
                if v not in premise_vars:
                    raise ValueError(f"Rule {self.name!r}: guard variable {v} not in premises")
            if self.guard is None:
                object.__setattr__(self, "guard", self.guard_expr.evaluate)

    def __str__(self) -> str:
        prem = ", ".join(" ".join(str(t) for t in p) for p in self.premises)
        if self.guard_expr is not None:
            prem += f", [{self.guard_expr}]"
        concl = "false" if self.conclusion is None else " ".join(str(t) for t in self.conclusion)
        return f"{prem} -> {concl}"


Lookup = Callable[[tuple["Node | None", "Node | None", "Node | None"]], Iterable["Triple"]]


@dataclass(frozen=True)
class ProceduralRule:
    """A rule family implemented in Python rather than as one pattern.

    ``triggers`` are the predicates of triples that can activate it (``None``
    for any predicate); ``fire(t, lookup)`` yields the conclusions that follow
    from a triggering triple *t* given a lookup over the current closure
    (``None`` for ⊥). Used for the OWL 2 RL rules whose premises range over an
    ``rdf:List`` of arbitrary length, and for rdfD1, whose conclusion is
    computed from a literal's datatype.
    """

    name: str
    triggers: tuple[Node | None, ...]
    fire: Callable[[Triple, Lookup], Iterator[Triple | None]]

    def __str__(self) -> str:
        return f"{self.name} (procedural)"


AnyRule = Rule | ProceduralRule


@dataclass(frozen=True)
class Regime:
    """A named rule set plus axiomatic triples."""

    name: str
    rules: tuple[AnyRule, ...] = ()
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


def split_premises(text: str) -> list[str]:
    """Split a premise list on commas outside ``[guards]``, ``(...)``, ``"..."`` and ``<iri>``.

    A guard may contain ``<`` (``[?a < ?b]``), so the quoted-atom rule of
    :func:`pynmms.syntax.split_top_level` cannot apply inside brackets.
    Parts are stripped; empty parts are dropped.
    """
    parts: list[str] = []
    depth = bracket = 0
    quote = ""
    start = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch == '"' or (ch == "<" and not bracket):
            quote = '"' if ch == '"' else ">"
        elif ch == "[":
            bracket += 1
        elif ch == "]" and bracket:
            bracket -= 1
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "," and not depth and not bracket:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _is_guard(part: str) -> bool:
    return part.startswith("[") and part.endswith("]")


def parse_premises(text: str, resolver: Resolver | None) -> tuple[tuple[Pattern, ...], Any]:
    """Parse a premise list ``p1, p2, [guard], ...`` into its patterns and one guard.

    Several ``[...]`` guards are conjoined; the result's guard is ``None``
    when there is none (a :class:`pynmms.rdf.values.Guard` otherwise).
    """
    parts = split_premises(text)
    guards = [p[1:-1].strip() for p in parts if _is_guard(p)]
    patterns = tuple(_parse_pattern(p, resolver) for p in parts if not _is_guard(p))
    guard = None
    if guards:
        from pynmms.rdf.values import parse_guard

        guard = parse_guard(" && ".join(f"({g})" for g in guards) if len(guards) > 1
                            else guards[0])
    return patterns, guard


def parse_rule(text: str, resolver: Resolver | None = None, name: str | None = None) -> Rule:
    """Parse ``p1, p2, ... -> conclusion`` where conclusion is a pattern or ``false``."""
    if "->" not in text:
        raise ValueError(f"Rule must contain '->': {text!r}")
    left, right = text.split("->", 1)
    premises, guard_expr = parse_premises(left, resolver)
    if not premises:
        raise ValueError(f"Rule has no premises: {text!r}")
    right = right.strip()
    conclusion = None if right.lower() in ("false", "⊥", "bottom") else _parse_pattern(
        right, resolver
    )
    return Rule(name or text.strip(), premises, conclusion, guard_expr=guard_expr)


def content_lines(text: str) -> Iterator[str]:
    """The lines of a rules or entries file that carry a rule or an entry.

    Blank lines and ``#`` comments are skipped; ``ordering name: a < b`` lines
    are consumed (the ordering is declared for ``rank`` guards, see
    :func:`pynmms.rdf.values.parse_ordering_line`) and not yielded. Lines
    are stripped.
    """
    from pynmms.rdf.values import parse_ordering_line

    for ln in text.splitlines():
        line = ln.strip()
        if not line or line.startswith("#") or parse_ordering_line(line):
            continue
        yield line


def parse_rules_text(text: str, resolver: Resolver | None = None) -> list[Rule]:
    """Parse a rules file: one rule per line, ``#`` comments, and ``ordering name: a < b``
    lines declaring orderings for ``rank(name, x)`` guards."""
    return [parse_rule(line, resolver) for line in content_lines(text)]


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

# --- Rule families over rdf:List and computed conclusions (procedural) ---


def rdf_list(head: Node, lookup: Lookup) -> list[Node] | None:
    """Members of the rdf:List starting at *head*, or None if malformed.

    A cell may carry several ``rdf:first`` or ``rdf:rest`` values once
    ``owl:sameAs`` substitution has run over it (eq-rep-o); the smallest is
    taken so the walk stays deterministic, and every alternative first value
    is included as a member.
    """
    items: list[Node] = []
    seen: set[Node] = set()
    node = head
    while node != RDF.nil:
        if node in seen:
            return None
        seen.add(node)
        first = sorted((t[2] for t in lookup((node, RDF.first, None))), key=str)
        rest = sorted((t[2] for t in lookup((node, RDF.rest, None))), key=str)
        if not first or not rest:
            return None
        items.extend(first)
        node = rest[0]
    return items


def _lists_with(pred: Node, lookup: Lookup) -> Iterator[tuple[Node, list[Node]]]:
    for subj, _p, head in lookup((None, pred, None)):
        items = rdf_list(head, lookup)
        if items:
            yield subj, items


def _types_of(y: Node, lookup: Lookup) -> set[Node]:
    return {t[2] for t in lookup((y, _TYPE, None))}


def _fire_cls_int1(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """cls-int1: c intersectionOf (c1..cn), y type c1..cn -> y type c."""
    if t[1] == OWL.intersectionOf:
        c, items = t[0], rdf_list(t[2], lookup)
        if items:
            for _y, _p, _c1 in list(lookup((None, _TYPE, items[0]))):
                y = _y
                if all(_ in _types_of(y, lookup) for _ in items):
                    yield (y, _TYPE, c)
    elif t[1] == _TYPE:
        y, ci = t[0], t[2]
        for c, items in _lists_with(OWL.intersectionOf, lookup):
            if ci in items and all(_ in _types_of(y, lookup) for _ in items):
                yield (y, _TYPE, c)


def _fire_cls_int2(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """cls-int2: c intersectionOf (c1..cn), y type c -> y type ci."""
    if t[1] == OWL.intersectionOf:
        c, items = t[0], rdf_list(t[2], lookup)
        if items:
            for y, _p, _c in list(lookup((None, _TYPE, c))):
                for ci in items:
                    yield (y, _TYPE, ci)
    elif t[1] == _TYPE:
        y, c = t[0], t[2]
        for head in [tr[2] for tr in lookup((c, OWL.intersectionOf, None))]:
            for ci in rdf_list(head, lookup) or ():
                yield (y, _TYPE, ci)


def _fire_cls_uni(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """cls-uni: c unionOf (c1..cn), y type ci -> y type c."""
    if t[1] == OWL.unionOf:
        c, items = t[0], rdf_list(t[2], lookup)
        for ci in items or ():
            for y, _p, _c in list(lookup((None, _TYPE, ci))):
                yield (y, _TYPE, c)
    elif t[1] == _TYPE:
        y, ci = t[0], t[2]
        for c, items in _lists_with(OWL.unionOf, lookup):
            if ci in items:
                yield (y, _TYPE, c)


def _fire_cls_oo(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """cls-oo: c oneOf (y1..yn) -> yi type c."""
    if t[1] == OWL.oneOf:
        for y in rdf_list(t[2], lookup) or ():
            yield (y, _TYPE, t[0])


def _fire_cax_adc(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """cax-adc: x type AllDisjointClasses, x members (c1..cn), y type ci, y type cj -> false."""
    if t[1] == OWL.members:
        if (t[0], _TYPE, OWL.AllDisjointClasses) in set(lookup((t[0], _TYPE, None))):
            items = rdf_list(t[2], lookup) or []
            for i, ci in enumerate(items):
                for y, _p, _c in list(lookup((None, _TYPE, ci))):
                    if any(cj in _types_of(y, lookup) for cj in items[i + 1:]):
                        yield None
                        return
    elif t[1] == _TYPE:
        y, ci = t[0], t[2]
        for x, items in _lists_with(OWL.members, lookup):
            if (x, _TYPE, OWL.AllDisjointClasses) not in set(lookup((x, _TYPE, None))):
                continue
            if ci in items:
                others = _types_of(y, lookup)
                if any(cj in others and cj != ci for cj in items):
                    yield None
                    return


def _fire_prp_spo2(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """prp-spo2: p propertyChainAxiom (p1..pn), u0 p1 u1 ... pn un -> u0 p un."""

    def chains() -> Iterator[tuple[Node, list[Node]]]:
        yield from _lists_with(OWL.propertyChainAxiom, lookup)

    def walk(start: Node, props: list[Node]) -> Iterator[Node]:
        if not props:
            yield start
            return
        for _s, _p, nxt in list(lookup((start, props[0], None))):
            yield from walk(nxt, props[1:])

    if t[1] == OWL.propertyChainAxiom:
        p, props = t[0], rdf_list(t[2], lookup)
        if props:
            for u0, _p1, _u1 in list(lookup((None, props[0], None))):
                for un in walk(u0, props):
                    yield (u0, p, un)
    else:
        for p, props in chains():
            if t[1] not in props:
                continue
            # Every way t can sit at position i of the chain.
            for i, pi in enumerate(props):
                if pi != t[1]:
                    continue
                # walk backwards from t[0] over props[:i]
                starts: list[Node] = [t[0]]
                for pj in reversed(props[:i]):
                    starts = [s for u in starts for s, _p, _o in lookup((None, pj, u))]
                for u0 in starts:
                    for un in walk(t[2], props[i + 1:]):
                        yield (u0, p, un)


def _fire_prp_key(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """prp-key: c hasKey (p1..pn), x type c, y type c, x pi zi, y pi zi -> x sameAs y."""
    keys = list(_lists_with(OWL.hasKey, lookup))
    if not keys:
        return
    for c, props in keys:
        members = [tr[0] for tr in lookup((None, _TYPE, c))]
        if t[1] == OWL.hasKey and t[0] != c:
            continue
        if t[1] not in (OWL.hasKey, _TYPE) and t[1] not in props:
            continue
        for x in members:
            vals = [{tr[2] for tr in lookup((x, p, None))} for p in props]
            if any(not v for v in vals):
                continue
            for y in members:
                if y == x:
                    continue
                if all(any((y, p, z) in set(lookup((y, p, None))) for z in vs)
                       for p, vs in zip(props, vals)):
                    yield (x, OWL.sameAs, y)


def _fire_prp_adp(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """prp-adp: x type AllDisjointProperties, x members (p1..pn), u pi v, u pj v -> false."""
    for x, props in _lists_with(OWL.members, lookup):
        if (x, _TYPE, OWL.AllDisjointProperties) not in set(lookup((x, _TYPE, None))):
            continue
        if t[1] == OWL.members and t[0] != x:
            continue
        if t[1] not in (OWL.members, _TYPE) and t[1] not in props:
            continue
        for i, pi in enumerate(props):
            for u, _p, v in list(lookup((None, pi, None))):
                for pj in props[i + 1:]:
                    if (u, pj, v) in set(lookup((u, pj, v))):
                        yield None
                        return


def _fire_eq_diff23(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """eq-diff2/3: x type AllDifferent with members (z1..zn), zi sameAs zj -> false."""
    for pred in (OWL.members, OWL.distinctMembers):
        for x, items in _lists_with(pred, lookup):
            if (x, _TYPE, OWL.AllDifferent) not in set(lookup((x, _TYPE, None))):
                continue
            for i, zi in enumerate(items):
                for zj in items[i + 1:]:
                    if (zi, OWL.sameAs, zj) in set(lookup((zi, OWL.sameAs, zj))):
                        yield None
                        return


def _fire_scm_int(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """scm-int: c intersectionOf (c1..cn) -> c subClassOf ci."""
    if t[1] == OWL.intersectionOf:
        for ci in rdf_list(t[2], lookup) or ():
            yield (t[0], RDFSNS.subClassOf, ci)


def _fire_scm_uni(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """scm-uni: c unionOf (c1..cn) -> ci subClassOf c."""
    if t[1] == OWL.unionOf:
        for ci in rdf_list(t[2], lookup) or ():
            yield (ci, RDFSNS.subClassOf, t[0])


def _fire_rdfD1(t: Triple, lookup: Lookup) -> Iterator[Triple | None]:
    """rdfD1: x p l with l a typed literal of datatype d -> l type d."""
    lit = t[2]
    if isinstance(lit, Literal) and lit.datatype is not None:
        yield (lit, _TYPE, lit.datatype)


_LIST_TRIGGERS = (RDF.first, RDF.rest)

OWL2RL_LIST_RULES: tuple[ProceduralRule, ...] = (
    ProceduralRule("cls-int1", (OWL.intersectionOf, _TYPE, *_LIST_TRIGGERS), _fire_cls_int1),
    ProceduralRule("cls-int2", (OWL.intersectionOf, _TYPE, *_LIST_TRIGGERS), _fire_cls_int2),
    ProceduralRule("cls-uni", (OWL.unionOf, _TYPE, *_LIST_TRIGGERS), _fire_cls_uni),
    ProceduralRule("cls-oo", (OWL.oneOf, *_LIST_TRIGGERS), _fire_cls_oo),
    ProceduralRule("cax-adc", (OWL.members, _TYPE, *_LIST_TRIGGERS), _fire_cax_adc),
    ProceduralRule("prp-spo2", (None,), _fire_prp_spo2),
    ProceduralRule("prp-key", (None,), _fire_prp_key),
    ProceduralRule("prp-adp", (None,), _fire_prp_adp),
    ProceduralRule("eq-diff2/3", (OWL.members, OWL.distinctMembers, OWL.sameAs, _TYPE,
                                  *_LIST_TRIGGERS), _fire_eq_diff23),
    ProceduralRule("scm-int", (OWL.intersectionOf, *_LIST_TRIGGERS), _fire_scm_int),
    ProceduralRule("scm-uni", (OWL.unionOf, *_LIST_TRIGGERS), _fire_scm_uni),
)

RDFD1 = ProceduralRule("rdfD1", (None,), _fire_rdfD1)

OWL2RL_OMITTED = (
    "eq-ref", "cls-thing", "cls-nothing1", "dt-type1", "dt-type2", "dt-eq", "dt-diff",
    "dt-not-type",
)
"""OWL 2 RL/RDF rules not implemented: the axiomatic-only rules (eq-ref,
cls-thing, cls-nothing1 add a triple per term or one fixed triple) and the
datatype rules, which need the datatype value spaces. The list-valued rule
families are implemented procedurally (``OWL2RL_LIST_RULES``)."""

RDFS = Regime("rdfs", RDFS_RULES + LITERAL_RULES + (RDFD1,), RDFS_AXIOMS)

OWL2RL = Regime(
    "owl2rl",
    RDFS_RULES + LITERAL_RULES + (RDFD1,) + OWL2RL_RULES + OWL2RL_LIST_RULES,
    RDFS_AXIOMS + ((OWL.Thing, _TYPE, OWL.Class), (OWL.Nothing, _TYPE, OWL.Class)),
)

REGIMES: dict[str, Regime] = {"simple": SIMPLE, "rdfs": RDFS, "owl2rl": OWL2RL}


def custom(
    name: str,
    rules: tuple[AnyRule, ...] | list[AnyRule],
    axioms: tuple[Triple, ...] = (),
    *,
    extends: Regime | None = None,
) -> Regime:
    """A user regime, optionally extending a shipped one."""
    base_rules = extends.rules if extends else ()
    base_axioms = extends.axioms if extends else ()
    return Regime(name, base_rules + tuple(rules), base_axioms + tuple(axioms))


__all__ = [
    "Var", "Rule", "Regime", "Pattern", "Term", "parse_rule", "parse_rules_text",
    "split_premises", "parse_premises", "content_lines", "custom",
    "ProceduralRule", "AnyRule", "Lookup", "rdf_list",
    "RDFS_RULES", "RDFS_AXIOMS", "LITERAL_RULES", "OWL2RL_RULES", "OWL2RL_LIST_RULES",
    "RDFD1", "OWL2RL_OMITTED", "SIMPLE", "RDFS", "OWL2RL", "REGIMES",
]
