"""Positions as speech acts: the position API (PLAN.md workstream H).

Predictions written before the implementation. A position is what a holder
has said, over the store as background; it speaks for the subjects it
asserts about, so their stored record is set aside while it is checked.
"""

# ruff: noqa: E402

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import RegimeBase, Resolver, TripleAtom, parse_rule
from pynmms.rdf.atoms import skolem
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.position import Position
from pynmms.rdf.rules import custom
from pynmms.robustness import MONOTONE, guarded

EX = Namespace("http://ex.org/")
F = frozenset


def typed(ind: str, cls: str) -> TripleAtom:
    return TripleAtom(EX[ind], RDF.type, EX[cls])


def ontology() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
    g.add((EX.EmperorPenguin, RDFS.subClassOf, EX.Penguin))
    g.add((EX.polly, RDF.type, EX.Sparrow))
    return g


def base_with_bottom(g: Graph | None = None) -> RegimeBase:
    g = g or ontology()
    rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(g))
    return RegimeBase(MemoryBackend(g, regime=custom("rdfs+ad", [rule], extends=RDFS_REGIME)))


def test_empty_position_is_coherent_and_the_background_licenses_stored_facts():
    pos = Position(RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME)), holder="me")
    assert pos.coherent()
    assert pos.commits_to(typed("polly", "Bird"))        # stored, derived: common ground
    assert not pos.commits_to(typed("polly", "Fish"))
    assert pos.holder == "me" and pos.accepted == F() and pos.log == []


def test_assert_commits_through_the_regime_and_precludes_incompatibles():
    pos = Position(base_with_bottom())
    pos.assert_(typed("tweety", "Sparrow"))
    assert pos.commits_to(typed("tweety", "Bird"))
    assert not pos.commits_to(typed("tweety", "Penguin"))
    pos.assert_(typed("tweety", "Alive"))
    assert pos.precludes(typed("tweety", "Dead"))          # Γ, Dead ⇒ ∅
    assert not pos.precludes(typed("tweety", "Fish"))
    assert pos.coherent()
    assert [m.kind for m in pos.log] == ["assert", "assert"]


def test_deny_puts_a_rejected_graph_in_the_succedent():
    pos = Position(RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME)))
    pos.assert_(typed("tweety", "Sparrow"))
    pos.deny([(EX.tweety, RDF.type, EX.Fish)])
    assert pos.coherent()                                   # accepting Sparrow, denying Fish
    pos.deny([(EX.tweety, RDF.type, EX.Bird)])
    v = pos.coherent()
    assert not v                                            # ... but Bird follows from Sparrow
    assert "Bird" in (v.reason or "")


def test_incoherence_names_the_entry_and_the_defeater_that_would_rescue_it():
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                      robustness=guarded([typed("tweety", "Penguin")]))
    pos = Position(b)
    pos.assert_(typed("tweety", "Sparrow"), typed("tweety", "Grounded"))
    v = pos.coherent()
    assert not v
    assert "Grounded" in (v.reason or "")
    assert typed("tweety", "Penguin") in v.rescue
    pos.assert_(typed("tweety", "EmperorPenguin"))          # a derivable defeater
    assert pos.coherent()


def test_a_position_speaks_for_its_subjects_so_their_record_is_set_aside():
    """The chalice: two stored starts; one asserted start is coherent, the record is not."""
    g = ontology()
    g.add((EX.chalice, EX.start, Literal("1780")))
    g.add((EX.chalice, EX.start, Literal("1632")))
    g.add((EX.chalice, EX.name, Literal("Miskelk")))
    b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
    b.add_consequence(F({TripleAtom(EX.chalice, EX.start, Literal("1780")),
                         TripleAtom(EX.chalice, EX.start, Literal("1632"))}), F(),
                      robustness=MONOTONE)
    one = Position(b).assert_(TripleAtom(EX.chalice, EX.start, Literal("1780")))
    assert one.coherent()  # 1632 is set aside: the position speaks for the chalice
    assert not one.commits_to(TripleAtom(EX.chalice, EX.name, Literal("Miskelk")))  # set aside too
    record = Position.of(b, EX.chalice)
    assert record.accepted == F({TripleAtom(EX.chalice, EX.start, Literal("1780")),
                                 TripleAtom(EX.chalice, EX.start, Literal("1632")),
                                 TripleAtom(EX.chalice, EX.name, Literal("Miskelk"))})
    assert not record.coherent()                            # reading the record aloud
    other = Position(b).assert_(typed("tweety", "Sparrow"))
    assert other.coherent()                                 # the chalice is not tweety's business
    assert other.commits_to(TripleAtom(EX.chalice, EX.start, Literal("1780")))  # still background


def test_of_follows_skolem_children_and_still_uses_the_thesaurus():
    g = ontology()
    maker = skolem("m1")
    g.add((EX.etching, EX.maker, maker))
    g.add((maker, RDF.value, EX.luyken))
    g.add((maker, EX.role, Literal("etser")))
    g.add((EX.etching, RDF.type, EX.Sparrow))
    b = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
    rec = Position.of(b, EX.etching, holder="curator")
    assert TripleAtom(maker, EX.role, Literal("etser")) in rec.accepted
    assert rec.subjects == F({EX.etching, maker})
    assert rec.commits_to(typed("etching", "Bird"))         # subclass axiom is not set aside


def test_withdraw_and_commit():
    b = base_with_bottom()
    pos = Position(b, holder="me")
    pos.assert_(typed("tweety", "Sparrow"), typed("tweety", "Alive"))
    pos.withdraw(typed("tweety", "Alive"))
    assert pos.accepted == F({typed("tweety", "Sparrow")})
    assert not pos.precludes(typed("tweety", "Dead"))
    assert [m.kind for m in pos.log] == ["assert", "withdraw"]
    n = pos.commit()
    assert n == 1
    assert b.backend.contains((EX.tweety, RDF.type, EX.Sparrow))
    assert pos.log[-1].kind == "commit" and pos.accepted == F()
    fresh = Position(b)
    assert fresh.commits_to(typed("tweety", "Bird"))        # now common ground, closure extended


def test_sequent_of_a_position_is_over_the_background():
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    pos = Position(b).assert_(typed("tweety", "Sparrow"))
    seq = pos.sequent(consequent=[typed("tweety", "Bird")])
    assert len(seq.gamma_atoms) == 1
    assert seq.gamma_atoms.background
