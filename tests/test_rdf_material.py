"""The regime-relative material base B_{R,I}.

A pair ⟨Γ, Δ⟩ is good iff (i) Γ is R-inconsistent, or (ii) Δ meets cl_R(Γ),
or (iii) some material entry ⟨A, D; E⟩ has A ⊆ cl_R(Γ), no defeater e ∈ E
with e ⊆ cl_R(Γ), and Δ meets cl_R(Γ ∪ D). Antecedents, defeaters, and
consequents are all read through the regime's closure; there is still no
Cut between material entries. These tests were written before the
implementation and fail on the literal-presence reading.
"""

# ruff: noqa: E402

from __future__ import annotations

import random

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms import NMMSReasoner
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import RegimeBase, TripleAtom
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.closure import ClosureEngine
from pynmms.robustness import EXACT, MONOTONE, guarded

EX = Namespace("http://ex.org/")
F = frozenset


def typed(ind: str, cls: str) -> TripleAtom:
    return TripleAtom(EX[ind], RDF.type, EX[cls])


def ontology() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
    g.add((EX.EmperorPenguin, RDFS.subClassOf, EX.Penguin))
    g.add((EX.Flies, RDFS.subClassOf, EX.Moves))
    return g


def _backend(kind: str):
    if kind == "oxigraph":
        pytest.importorskip("pyoxigraph")
        from pynmms.rdf.backends import OxigraphBackend

        ox = OxigraphBackend(regime=RDFS_REGIME)
        ox.load_graph(ontology())
        return ox
    return MemoryBackend(ontology(), regime=RDFS_REGIME)


@pytest.fixture(params=["memory", "oxigraph"])
def base(request):
    """RDFS regime over the ontology; material: Bird ⊢ Flies unless Penguin, Flies ⊢ HasWings.

    Runs over the in-memory backend and, when pyoxigraph is installed, over
    an Oxigraph store that materialises the regime itself.
    """
    b = RegimeBase(_backend(request.param))
    b.add_consequence(F({typed("tweety", "Bird")}), F({typed("tweety", "Flies")}),
                      robustness=guarded([typed("tweety", "Penguin")]))
    b.add_consequence(F({typed("tweety", "Flies")}), F({typed("tweety", "HasWings")}),
                      robustness=MONOTONE)
    return b


def ask(base, antecedent, consequent) -> bool:
    return NMMSReasoner(base).derives_sequent(base.sequent(antecedent, consequent)).derivable


def test_1_derived_antecedent(base):
    """tweety : Sparrow ⇒ tweety : Flies. Bird is derived, not present."""
    assert ask(base, [typed("tweety", "Sparrow")], [typed("tweety", "Flies")])


def test_2_derived_defeater(base):
    """tweety : EmperorPenguin, tweety : Bird ⇒ NOT tweety : Flies. Penguin is derived."""
    assert not ask(base, [typed("tweety", "EmperorPenguin"), typed("tweety", "Bird")],
                   [typed("tweety", "Flies")])


def test_3_irrelevant_premise(base):
    """tweety : Bird, tweety : Tall ⇒ tweety : Flies. Guarded entries ignore Tall."""
    gamma = [typed("tweety", "Bird"), typed("tweety", "Tall")]
    assert ask(base, gamma, [typed("tweety", "Flies")])


def test_4_consequent_elaborated(base):
    """tweety : Sparrow ⇒ tweety : Moves: Flies ⊑ Moves elaborates the consequent."""
    assert ask(base, [typed("tweety", "Sparrow")], [typed("tweety", "Moves")])
    base.elaborate_consequent = False
    base.clear_caches()
    assert not ask(base, [typed("tweety", "Sparrow")], [typed("tweety", "Moves")])


def test_5_no_material_chaining(base):
    """tweety : Bird ⇒ NOT tweety : HasWings: (iii) uses one entry, never two."""
    assert not ask(base, [typed("tweety", "Bird")], [typed("tweety", "HasWings")])
    # the second entry does fire from its own antecedent
    assert ask(base, [typed("tweety", "Flies")], [typed("tweety", "HasWings")])


def test_8_nonmonotonic_by_design(base):
    """Adding tweety : Penguin to case 1 flips it. That is the point: the material
    layer is defeasible, and the regime only elaborates what defeats it."""
    assert ask(base, [typed("tweety", "Sparrow")], [typed("tweety", "Flies")])
    assert not ask(base, [typed("tweety", "Sparrow"), typed("tweety", "Penguin")],
                   [typed("tweety", "Flies")])


def test_exact_means_r_equivalent_antecedent():
    """exact: A ⊆ cl_R(Γ) and Γ ⊆ cl_R(A)."""
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    b.add_consequence(F({typed("t", "Bird")}), F({typed("t", "Flies")}), robustness=EXACT)
    r = NMMSReasoner(b)
    q = lambda a, c: r.derives_sequent(b.sequent(a, c, include_graph=False)).derivable  # noqa: E731
    assert q([typed("t", "Bird")], [typed("t", "Flies")])
    assert not q([typed("t", "Bird"), typed("t", "Tall")], [typed("t", "Flies")])  # Tall ∉ cl(A)
    assert not q([typed("t", "Sparrow")], [typed("t", "Flies")])  # Sparrow ∉ cl(A)
    # over the stored graph, an exact entry cannot fire unless G ⊆ cl_R(A)
    assert not ask(b, [typed("t", "Bird")], [typed("t", "Flies")])


# --- random cases -------------------------------------------------------------

CLASSES = ["C0", "C1", "C2", "C3"]
INDS = ["a", "b"]


def _random_graph(rnd: random.Random) -> Graph:
    g = Graph()
    g.bind("ex", EX)
    for _ in range(rnd.randint(1, 5)):
        g.add((EX[rnd.choice(CLASSES)], RDFS.subClassOf, EX[rnd.choice(CLASSES)]))
    for _ in range(rnd.randint(0, 3)):
        g.add((EX[rnd.choice(INDS)], RDF.type, EX[rnd.choice(CLASSES)]))
    return g


def _random_side(rnd: random.Random, k: int) -> list[TripleAtom]:
    return [typed(rnd.choice(INDS), rnd.choice(CLASSES)) for _ in range(rnd.randint(0, k))]


def test_6_empty_material_layer_is_the_regime_base():
    """With I empty, B_{R,I} = B_R: agrees with a from-scratch closure and with owlrl."""
    owlrl = pytest.importorskip("owlrl")
    rnd = random.Random(1)
    engine = ClosureEngine(RDFS_REGIME)
    checked = 0
    for _ in range(25):
        g = _random_graph(rnd)
        b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME, skolemize=False))
        r = NMMSReasoner(b)
        oracle = Graph()
        for t in g:
            oracle.add(t)
        owlrl.DeductiveClosure(owlrl.RDFS_Semantics, axiomatic_triples=True).expand(oracle)
        for _ in range(20):
            ant, con = _random_side(rnd, 2), _random_side(rnd, 2)
            got = r.derives_sequent(b.sequent(ant, con)).derivable
            closed, bottom = engine.close([*g, *(a.triple for a in ant)])
            expected = bottom or any(c.triple in closed for c in con)
            assert got == expected, (g.serialize(format="nt"), ant, con)
            if not ant:  # owlrl's closure is the oracle for the stored graph alone
                assert got == any(c.triple in oracle for c in con)
            checked += 1
    assert checked == 500


def test_7_containment_with_material_entries():
    rnd = random.Random(2)
    for _ in range(100):
        g = _random_graph(rnd)
        b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME, skolemize=False))
        for _ in range(rnd.randint(1, 3)):
            b.add_consequence(F(_random_side(rnd, 2) or [typed("a", "C0")]),
                              F(_random_side(rnd, 2) or [typed("b", "C1")]),
                              robustness=rnd.choice([EXACT, MONOTONE,
                                                     guarded([typed("a", "C3")])]))
        shared = typed(rnd.choice(INDS), rnd.choice(CLASSES))
        ant = _random_side(rnd, 2) + [shared]
        con = _random_side(rnd, 2) + [shared]
        assert NMMSReasoner(b).derives_sequent(b.sequent(ant, con)).derivable


def test_incompatibility_entry_makes_gamma_incoherent_through_the_regime():
    """⟨A, ∅; E⟩: a derivable antecedent with no derivable defeater explodes the position."""
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    # A sparrow that also moves on the ground is incoherent unless it is a penguin.
    b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                      robustness=guarded([typed("tweety", "Penguin")]))
    gamma = [typed("tweety", "Sparrow"), typed("tweety", "Grounded")]
    assert ask(b, gamma, [])                                   # Γ ⇒ : incoherent
    assert ask(b, gamma, [typed("tweety", "Fish")])            # explosion
    assert not ask(b, [typed("tweety", "Sparrow")], [])        # antecedent not derivable
    assert not ask(b, gamma + [typed("tweety", "EmperorPenguin")], [])  # defeater derived


# --- attribution: incoherence belongs to the position that derives it ----------


def _regime_with_bottom():
    from pynmms.rdf import Resolver, parse_rule
    from pynmms.rdf.rules import custom

    rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(ontology()))
    return custom("rdfs+ad", [rule], extends=RDFS_REGIME)


def test_background_contradiction_is_inventory_not_explosion():
    """A contradiction in the store is reported, and does not make every position incoherent."""
    g = ontology()
    g.add((EX.z, RDF.type, EX.Alive))
    g.add((EX.z, RDF.type, EX.Dead))
    b = RegimeBase(MemoryBackend(g, regime=_regime_with_bottom()))
    assert b.background_inconsistent()
    assert not ask(b, [], [])                                   # the empty position is coherent
    assert not ask(b, [], [typed("tweety", "Fish")])             # no explosion
    assert not b.is_inconsistent()
    # A position that commits to a contradiction of its own is incoherent, and explodes.
    gamma = [typed("tweety", "Alive"), typed("tweety", "Dead")]
    assert ask(b, gamma, [])
    assert ask(b, gamma, [typed("tweety", "Fish")])
    assert b.is_inconsistent(gamma)
    # The regime base of def:fitness is explosive; that reading is still available.
    b.attribution = "global"
    assert ask(b, [], [typed("tweety", "Fish")])
    assert b.is_inconsistent()


def test_material_incompatibility_is_attributed_to_the_position():
    """⟨A, ∅⟩ makes a position incoherent only if the position contributes to A."""
    g = ontology()
    g.add((EX.tweety, RDF.type, EX.Sparrow))
    g.add((EX.tweety, RDF.type, EX.Grounded))
    b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
    b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                      robustness=MONOTONE)
    r = NMMSReasoner(b)
    # Both antecedent atoms are background: no position over the graph is blamed.
    assert not ask(b, [], [])
    assert not ask(b, [], [typed("tweety", "Fish")])
    # A position that takes the record as its own commitments, over the background, is.
    pos = b.sequent([typed("tweety", "Sparrow"), typed("tweety", "Grounded")], [],
                    include_graph="background")
    assert r.derives_sequent(pos).derivable
    # Without the background the subclass axiom is missing and Bird is not derivable.
    assert not r.derives_sequent(b.sequent(
        [typed("tweety", "Sparrow"), typed("tweety", "Grounded")], [], include_graph=False)
    ).derivable
    # A position that contributes the missing antecedent atom is blamed.
    g2 = ontology()
    g2.add((EX.tweety, RDF.type, EX.Sparrow))
    b2 = RegimeBase(MemoryBackend(g2, regime=RDFS_REGIME))
    b2.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                       robustness=MONOTONE)
    assert ask(b2, [typed("tweety", "Grounded")], [])
    assert not ask(b2, [], [])


def test_background_positions_use_the_store_for_closure_and_consequents():
    """include_graph="background": Γ is the position, the store licenses the closure."""
    g = ontology()
    g.add((EX.polly, RDF.type, EX.Sparrow))
    b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
    r = NMMSReasoner(b)
    seq = b.sequent([typed("tweety", "Sparrow")], [typed("tweety", "Bird")],
                    include_graph="background")
    assert r.derives_sequent(seq).derivable
    # A stored fact follows from the empty position: the background licenses it.
    assert r.derives_sequent(b.sequent([], [typed("polly", "Bird")],
                                       include_graph="background")).derivable
    assert not r.derives_sequent(b.sequent([], [typed("polly", "Fish")],
                                           include_graph="background")).derivable
    # Γ itself holds only the position's atoms.
    assert len(seq.gamma_atoms) == 1


def test_exact_incompatibility_fires_only_at_empty_delta():
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    b.add_consequence(F({typed("t", "Bird"), typed("t", "Grounded")}), F(), robustness=EXACT)
    r = NMMSReasoner(b)
    q = lambda a, c: r.derives_sequent(b.sequent(a, c, include_graph=False)).derivable  # noqa: E731
    assert q([typed("t", "Bird"), typed("t", "Grounded")], [])
    assert not q([typed("t", "Bird"), typed("t", "Grounded")], [typed("t", "Fish")])
