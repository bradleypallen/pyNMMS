"""Converters between the ontology extension and the RDF layer.

The onto vocabulary is the ``rdf:type`` fragment of the triple encoding
(``def:triplebearers``): ``C(x)`` is ``(x rdf:type C)`` and ``R(x, y)`` is ``(x R y)``.
Schema commitments become schema triples, read by a regime's rules:

| schema                          | triple(s)                              |
|---------------------------------|----------------------------------------|
| subClassOf(C, D)                | C rdfs:subClassOf D                    |
| range(R, C) / domain(R, C)      | R rdfs:range C / R rdfs:domain C       |
| subPropertyOf(R, S)             | R rdfs:subPropertyOf S                 |
| disjointWith(C, D)              | C owl:disjointWith D                   |
| disjointProperties(R, S)        | R owl:propertyDisjointWith S           |
| jointCommitment([C1..Cn], D)    | a rule ``?x a C1, ..., ?x a Cn -> ?x a D`` |

The RDF reading is *monotone*: a schema triple licenses every instance
regardless of context, which is the MONOTONE policy. EXACT schemas lose their
brittleness and GUARDED schemas lose their defeaters in the conversion; both
are reported in the returned notes so the caller can add explicit guarded
entries on the :class:`~pynmms.rdf.base.RDFBase` instead.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from pynmms.onto.base import OntoMaterialBase
from pynmms.rdf.atoms import TripleAtom
from pynmms.rdf.rules import Rule, Var

logger = logging.getLogger(__name__)

DEFAULT_NS = Namespace("http://pynmms.dev/onto/")

_CONCEPT_RE = __import__("re").compile(r"^(\w+)\((\w+)\)$")
_ROLE_RE = __import__("re").compile(r"^(\w+)\((\w+),(\w+)\)$")


def _iri(name: str, ns: Namespace) -> URIRef:
    return ns[name]


def atom_to_triple(atom: str, ns: Namespace = DEFAULT_NS) -> TripleAtom:
    """``C(x)`` -> ``(x rdf:type C)``; ``R(x,y)`` -> ``(x R y)``."""
    m = _CONCEPT_RE.match(atom)
    if m:
        return TripleAtom(_iri(m.group(2), ns), RDF.type, _iri(m.group(1), ns))
    m = _ROLE_RE.match(atom)
    if m:
        return TripleAtom(_iri(m.group(2), ns), _iri(m.group(1), ns), _iri(m.group(3), ns))
    raise ValueError(f"{atom!r} is not an onto-atomic sentence")


def onto_to_graph(
    base: OntoMaterialBase, ns: Namespace = DEFAULT_NS, *, prefix: str = "onto"
) -> tuple[Graph, list[str]]:
    """The ABox and schema triples of *base*; returns ``(graph, notes)``.

    *notes* lists every schema whose robustness policy is not representable
    in RDF (EXACT brittleness and GUARDED defeaters are dropped) and every
    jointCommitment (which needs a rule; see :func:`onto_to_rules`).
    """
    g = Graph()
    g.bind(prefix, ns)
    notes: list[str] = []
    for atom in base.language:
        g.add(atom_to_triple(atom, ns).triple)
    for e in base.onto_schemas:
        if e.type == "subClassOf":
            g.add((_iri(e.arg1, ns), RDFS.subClassOf, _iri(e.arg2, ns)))
        elif e.type == "range":
            g.add((_iri(e.arg1, ns), RDFS.range, _iri(e.arg2, ns)))
        elif e.type == "domain":
            g.add((_iri(e.arg1, ns), RDFS.domain, _iri(e.arg2, ns)))
        elif e.type == "subPropertyOf":
            g.add((_iri(e.arg1, ns), RDFS.subPropertyOf, _iri(e.arg2, ns)))
        elif e.type == "disjointWith":
            g.add((_iri(e.arg1, ns), OWL.disjointWith, _iri(e.arg2, ns)))
        elif e.type == "disjointProperties":
            g.add((_iri(e.arg1, ns), OWL.propertyDisjointWith, _iri(e.arg2, ns)))
        elif e.type == "jointCommitment":
            notes.append(f"jointCommitment({e.arg1} -> {e.arg2}) needs a rule; see onto_to_rules")
        if e.annotation:
            subj = _iri(e.arg1.split(",")[0], ns)
            g.add((subj, RDFS.comment, __import__("rdflib").Literal(e.annotation)))
        if e.robustness.kind != "monotone" and e.type != "jointCommitment":
            notes.append(
                f"{e.type}({e.arg1}, {e.arg2}) is {e.robustness}; RDF schema triples are monotone"
            )
    for note in notes:
        logger.info("onto_to_graph: %s", note)
    return g, notes


def onto_to_rules(base: OntoMaterialBase, ns: Namespace = DEFAULT_NS) -> list[Rule]:
    """Rules for the schemas a regime cannot read from triples (jointCommitment).

    Guarded jointCommitments become unguarded rules; the defeaters are logged.
    """
    x = Var("x")
    rules: list[Rule] = []
    for e in base.onto_schemas:
        if e.type != "jointCommitment":
            continue
        premises = tuple((x, RDF.type, _iri(c, ns)) for c in e.concepts)
        rules.append(Rule(f"jointCommitment:{e.arg1}->{e.arg2}", premises,
                          (x, RDF.type, _iri(e.arg2, ns))))
        if e.robustness.kind == "guarded":
            logger.info("onto_to_rules: defeaters %s of %s dropped", sorted(e.robustness.left),
                        rules[-1].name)
    return rules


def onto_to_defeasible(base: OntoMaterialBase, ns: Namespace = DEFAULT_NS,
                       *, exact: str = "monotone") -> list[Any]:
    """Every schema of *base* as a pattern entry (``pynmms.rdf.defeasible``).

    ``subClassOf(C, D)`` becomes ``?x a C |~ ?x a D``; ``range(R, C)``
    ``?x R ?y |~ ?y a C``; ``domain(R, C)`` ``?x R ?y |~ ?x a C``;
    ``subPropertyOf(R, S)`` ``?x R ?y |~ ?x S ?y``; ``disjointWith(C, D)``
    ``?x a C, ?x a D |~ false``; ``disjointProperties(R, S)`` ``?x R ?y, ?x S ?y
    |~ false``; ``jointCommitment([C1..Cn], D)`` ``?x a C1, ..., ?x a Cn |~ ?x a D``.
    A guarded schema's defeater concepts become defeaters on each individual of
    the match (``?x a E`` ; ``?y a E``), conjunctive exclusions conjunctions on
    one individual. An exact schema, defeated by any addition, has no pattern
    counterpart: with ``exact="monotone"`` (default) it is compiled as monotone
    and logged, with ``exact="skip"`` it is left out.
    """
    from pynmms.rdf.defeasible import DefeasibleRule, Defeater
    from pynmms.rdf.rules import Var

    x, y = Var("x"), Var("y")
    rules: list[Any] = []
    for e in base.onto_schemas:
        t = e.type
        premises: tuple[tuple[Any, Any, Any], ...]
        if t == "subClassOf":
            premises = ((x, RDF.type, _iri(e.arg1, ns)),)
            conclusion: Any = (x, RDF.type, _iri(e.arg2, ns))
            individuals: tuple[Var, ...] = (x,)
            name = f"subClassOf:{e.arg1}->{e.arg2}"
        elif t == "range":
            premises = ((x, _iri(e.arg1, ns), y),)
            conclusion = (y, RDF.type, _iri(e.arg2, ns))
            individuals = (x, y)
            name = f"range:{e.arg1}->{e.arg2}"
        elif t == "domain":
            premises = ((x, _iri(e.arg1, ns), y),)
            conclusion = (x, RDF.type, _iri(e.arg2, ns))
            individuals = (x, y)
            name = f"domain:{e.arg1}->{e.arg2}"
        elif t == "subPropertyOf":
            premises = ((x, _iri(e.arg1, ns), y),)
            conclusion = (x, _iri(e.arg2, ns), y)
            individuals = (x, y)
            name = f"subPropertyOf:{e.arg1}->{e.arg2}"
        elif t == "disjointWith":
            premises = ((x, RDF.type, _iri(e.arg1, ns)), (x, RDF.type, _iri(e.arg2, ns)))
            conclusion = None
            individuals = (x,)
            name = f"disjointWith:{e.arg1}/{e.arg2}"
        elif t == "disjointProperties":
            premises = ((x, _iri(e.arg1, ns), y), (x, _iri(e.arg2, ns), y))
            conclusion = None
            individuals = (x, y)
            name = f"disjointProperties:{e.arg1}/{e.arg2}"
        elif t == "jointCommitment":
            premises = tuple((x, RDF.type, _iri(c, ns)) for c in e.concepts)
            conclusion = (x, RDF.type, _iri(e.arg2, ns))
            individuals = (x,)
            name = f"jointCommitment:{e.arg1}->{e.arg2}"
        else:  # pragma: no cover - the extension has seven types
            logger.warning("onto_to_defeasible: unknown schema type %s", t)
            continue
        rob = e.robustness
        if rob.is_exact:
            if exact == "skip":
                logger.info("onto_to_defeasible: exact schema %s skipped", name)
                continue
            logger.info("onto_to_defeasible: exact schema %s compiled as monotone "
                        "(exact matching has no pattern counterpart)", name)
            rules.append(DefeasibleRule(name, premises, conclusion, (), "monotone"))
            continue
        defeaters: list[Defeater] = []
        for d in sorted(rob.left):
            for ind in individuals:
                defeaters.append(Defeater(((ind, RDF.type, _iri(d, ns)),)))
        for xs, _ys in rob.exclusions:
            for ind in individuals:
                defeaters.append(Defeater(tuple((ind, RDF.type, _iri(d, ns)) for d in sorted(xs))))
        rules.append(DefeasibleRule(name, premises, conclusion, tuple(defeaters),
                                    "guarded" if defeaters else "monotone"))
    return rules


def install_onto(target: Any, base: OntoMaterialBase, ns: Namespace = DEFAULT_NS,
                 *, exact: str = "monotone") -> tuple[int, int]:
    """Install *base*'s schemas as pattern entries and its consequences as ground entries
    of an ``RDFBase``/``RegimeBase``; returns (rules, entries) added."""
    rules = onto_to_defeasible(base, ns, exact=exact)
    for r in rules:
        target.add_rule(r)
    n = 0
    for gamma, delta, rob in consequences_to_triples(base, ns):
        target.add_consequence(gamma, delta, robustness=rob)
        n += 1
    return len(rules), n


def consequences_to_triples(
    base: OntoMaterialBase, ns: Namespace = DEFAULT_NS
) -> Iterable[tuple[frozenset[str], frozenset[str], object]]:
    """Ground consequences of *base* as triple-atom pairs with their policies.

    The policy's defeaters are translated too, so a guarded entry keeps its
    defeaters as triple atoms.
    """
    from pynmms.robustness import Robustness

    def tr(name: str) -> str:
        return str(atom_to_triple(name, ns))

    for gamma, delta in base.consequences:
        rob = base.robustness_of(gamma, delta)
        rob = Robustness(
            rob.kind,
            frozenset(tr(a) for a in rob.left),
            frozenset(tr(a) for a in rob.right),
            frozenset((frozenset(tr(a) for a in xs), frozenset(tr(a) for a in ys))
                      for xs, ys in rob.exclusions),
        )
        yield (
            frozenset(atom_to_triple(a, ns) for a in gamma),
            frozenset(atom_to_triple(a, ns) for a in delta),
            rob,
        )


__all__ = ["atom_to_triple", "onto_to_graph", "onto_to_rules", "onto_to_defeasible",
           "install_onto", "consequences_to_triples", "DEFAULT_NS"]
