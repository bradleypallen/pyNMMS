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


def consequences_to_triples(
    base: OntoMaterialBase, ns: Namespace = DEFAULT_NS
) -> Iterable[tuple[frozenset[str], frozenset[str], object]]:
    """Ground consequences of *base* as triple-atom pairs with their policies."""
    for gamma, delta in base.consequences:
        yield (
            frozenset(atom_to_triple(a, ns) for a in gamma),
            frozenset(atom_to_triple(a, ns) for a in delta),
            base.robustness_of(gamma, delta),
        )


__all__ = ["atom_to_triple", "onto_to_graph", "onto_to_rules", "consequences_to_triples",
           "DEFAULT_NS"]
