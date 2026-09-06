"""Oracle for the per-node extras closure.

``RegimeBase`` never closes ``G ∪ extras`` from scratch: the backend holds
``cl_R(G)`` and ``ClosureEngine.extend`` adds only what the extras bring. The
naive full closure ``ClosureEngine.close(G ∪ extras)`` is the simpler
computation and is itself cross-checked against owlrl elsewhere, so this test
demands that, for random graphs and random extras,

    cl_R(G) ∪ extend(G, extras)  ==  close(G ∪ extras)

with the same ⊥ verdict, under RDFS and OWL 2 RL, with an incompatibility
rule, with list constructs, and on both the per-lookup and the batched paths.
"""

# ruff: noqa: E402

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS

from pynmms.rdf import OWL2RL, Resolver, parse_rule
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.closure import ClosureEngine
from pynmms.rdf.rules import custom

EX = Namespace("http://ex.org/")
CLASSES = [EX[f"C{i}"] for i in range(4)]
PROPS = [EX[f"p{i}"] for i in range(3)]
INDS = [EX[f"i{i}"] for i in range(4)]

term = st.sampled_from(CLASSES + PROPS + INDS)


@st.composite
def triples(draw):
    kind = draw(st.integers(0, 9))
    c1, c2 = draw(st.sampled_from(CLASSES)), draw(st.sampled_from(CLASSES))
    p1, p2 = draw(st.sampled_from(PROPS)), draw(st.sampled_from(PROPS))
    i1, i2 = draw(st.sampled_from(INDS)), draw(st.sampled_from(INDS))
    if kind == 0:
        return (c1, RDFS.subClassOf, c2)
    if kind == 1:
        return (p1, RDFS.domain, c1)
    if kind == 2:
        return (p1, RDFS.range, c1)
    if kind == 3:
        return (p1, RDFS.subPropertyOf, p2)
    if kind == 4:
        return (c1, OWL.disjointWith, c2)
    if kind == 5:
        return (p1, OWL.inverseOf, p2)
    if kind == 6:
        return (p1, RDF.type, draw(st.sampled_from(
            [OWL.SymmetricProperty, OWL.TransitiveProperty, OWL.FunctionalProperty])))
    if kind == 7:
        return (i1, RDF.type, c1)
    if kind == 8:
        return (i1, p1, Literal(draw(st.integers(0, 3))))
    return (i1, p1, i2)


@st.composite
def graphs(draw):
    g = Graph()
    g.bind("ex", EX)
    for t in draw(st.lists(triples(), min_size=1, max_size=8)):
        g.add(t)
    if draw(st.booleans()):
        head = BNode("lst")
        Collection(g, head, draw(st.lists(st.sampled_from(CLASSES), min_size=2, max_size=3)))
        g.add((EX.Combo, draw(st.sampled_from([OWL.intersectionOf, OWL.unionOf])), head))
    return g


def _full_closure(regime, g: Graph, extras):
    closed, bottom = ClosureEngine(regime).close([*g, *extras])
    return closed, bottom


def _incremental(regime, g: Graph, extras, batched: bool):
    be = MemoryBackend(g, regime=regime, skolemize=False)
    engine = ClosureEngine(regime)
    new, bottom = engine.extend(
        extras, be.closure_triples, be.closure_contains,
        store_join=be.join if batched else None,
    )
    return set(be.closure) | new.triples, bottom or be.is_inconsistent()


def _regime(base, g):
    rule = parse_rule("?x a ex:C0, ?x a ex:C3 -> false", Resolver(g))
    return custom(f"{base.name}+incompat", [rule], extends=base)


@settings(max_examples=60, deadline=None)
@given(graphs(), st.lists(triples(), min_size=1, max_size=4), st.booleans(), st.booleans())
def test_extras_closure_matches_full_closure(g, extras, use_owl, batched):
    regime = _regime(OWL2RL if use_owl else RDFS_REGIME, g)
    expected, expected_bottom = _full_closure(regime, g, extras)
    actual, actual_bottom = _incremental(regime, g, extras, batched)
    assert actual_bottom == expected_bottom, (g.serialize(format="nt"), extras)
    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        g.serialize(format="nt"), extras, sorted(map(str, missing))[:5],
        sorted(map(str, extra))[:5],
    )


@settings(max_examples=30, deadline=None)
@given(graphs(), st.lists(triples(), min_size=1, max_size=3))
def test_extras_are_disjoint_from_store(g, extras):
    """extend() must never report a store triple as new."""
    be = MemoryBackend(g, regime=RDFS_REGIME, skolemize=False)
    new, _ = ClosureEngine(RDFS_REGIME).extend(extras, be.closure_triples, be.closure_contains)
    assert not any(t in be.closure for t in new.triples)
