"""The Elenchus loop over a knowledge graph (PLAN.md step 6). Predictions first.

A Dialogue holds the dialectical state <[C : D], T, I> of the AIAA4KE
Elenchus paper: the position, the open tensions (sequents Γ |~ Δ with
Γ ⊆ C, Δ ⊆ D that the opponent claims incoherent), and the material
implications from accepted tensions. The respondent commits, denies,
withdraws, accepts a tension by retraction or refinement, or contests it
with an exception; the opponent, computed from the base by default,
detects tensions and raises probes. Accepting a tension the base did not
already license adds it to the base; contesting one that it did proposes
an exception to the responsible entry. A positum cannot be withdrawn, and
aporia is the stopping rule.
"""

# ruff: noqa: E402

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import RegimeBase, Resolver, TripleAtom
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.defeasible import parse_defeasible_rule
from pynmms.rdf.dialogue import Dialogue, Tension
from pynmms.robustness import guarded

EX = Namespace("http://ex.org/")
F = frozenset


def typed(ind: str, cls: str) -> TripleAtom:
    return TripleAtom(EX[ind], RDF.type, EX[cls])


def ontology() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
    g.add((EX.EmperorPenguin, RDFS.subClassOf, EX.Penguin))
    return g


def base() -> RegimeBase:
    b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
    b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                      robustness=guarded([typed("tweety", "Penguin")]))
    b.add_rule(parse_defeasible_rule("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin",
                                     Resolver(ontology())))
    return b


class TestTensions:
    def test_a_commitment_that_completes_an_incompatibility_raises_a_tension(self):
        d = Dialogue(base(), holder="me", positum=[typed("tweety", "Sparrow")])
        turn = d.commit(typed("tweety", "Grounded"))
        assert len(d.open) == 1 and turn.tensions == tuple(d.open.values())
        t = next(iter(d.open.values()))
        assert isinstance(t, Tension)
        assert set(t.gamma) == {typed("tweety", "Sparrow"), typed("tweety", "Grounded")}
        assert t.delta == () and typed("tweety", "Penguin") in t.rescue
        assert d.status() == "tensions open"
        assert [x.move for x in d.transcript] == ["commit", "commit"]   # positum, then Grounded

    def test_accept_by_retraction_moves_the_tension_to_i(self):
        d = Dialogue(base(), holder="me", positum=[typed("tweety", "Sparrow")])
        d.commit(typed("tweety", "Grounded"))
        (tid,) = d.open
        d.accept(tid, retract=[typed("tweety", "Grounded")])
        assert not d.open and len(d.accepted) == 1 and d.status() == "coherent"
        assert typed("tweety", "Grounded") not in d.position.accepted
        with pytest.raises(ValueError):
            d.accept(tid, retract=[typed("tweety", "Sparrow")])       # already resolved

    def test_accept_by_refinement_of_a_denial(self):
        d = Dialogue(base(), holder="me")
        d.commit(typed("tweety", "Sparrow"))
        turn = d.deny([(EX.tweety, RDF.type, EX.Bird)])
        assert len(turn.tensions) == 1
        t = turn.tensions[0]
        assert t.gamma == (typed("tweety", "Sparrow"),) and t.delta == (typed("tweety", "Bird"),)
        d.accept(t.id, refine=([typed("tweety", "Sparrow")], [typed("tweety", "Finch")]))
        assert d.status() == "coherent" and typed("tweety", "Finch") in d.position.accepted
        assert d.accepted[0].sequent() == (f"{typed('tweety', 'Sparrow')} |~ "
                                           f"{typed('tweety', 'Bird')}")

    def test_contest_with_an_exception_revises_the_base(self):
        b = base()
        d = Dialogue(b, holder="me", positum=[typed("tweety", "Sparrow")])
        d.commit(typed("tweety", "Grounded"))
        (tid,) = d.open
        d.contest(tid, exception=[typed("tweety", "Flightless")])
        assert not d.open and len(d.contested) == 1 and d.proposals[0].exception
        assert d.status() == "tensions open"                # still refuted: exception not held
        d.commit(typed("tweety", "Flightless"))                       # the exception holds
        assert d.status() == "coherent"                              # entry now yields to it

    def test_an_external_tension_accepted_enters_the_base(self):
        b = base()
        d = Dialogue(b, holder="me")
        d.commit(typed("tweety", "Sparrow"), typed("tweety", "Nocturnal"))
        assert d.status() == "coherent"
        t = d.propose_tension([typed("tweety", "Sparrow"), typed("tweety", "Nocturnal")], (),
                              source="oracle: sparrows are diurnal")
        assert t.id in d.open and d.status() == "tensions open"
        d.accept(t.id, retract=[typed("tweety", "Nocturnal")])
        assert d.status() == "coherent"
        # The accepted tension is now material: re-committing raises it from the base itself.
        turn = d.commit(typed("tweety", "Nocturnal"))
        assert turn.tensions and "oracle" not in turn.tensions[0].source
        d2 = Dialogue(b, holder="other")
        d2.commit(typed("tweety", "Sparrow"), typed("tweety", "Nocturnal"))
        assert d2.status() == "tensions open"
        d3 = Dialogue(base(), holder="me")
        d3.commit(typed("tweety", "Sparrow"))
        t3 = d3.propose_tension([typed("tweety", "Sparrow")], (), source="oracle")
        d3.contest(t3.id)
        assert not d3.open and d3.status() == "coherent"

    def test_positum_and_aporia(self):
        d = Dialogue(base(), holder="me", positum=[typed("tweety", "Bird"),
                                                   typed("tweety", "Grounded")])
        assert d.status() == "tensions open"                # refuted, but a rescue is open
        with pytest.raises(ValueError):
            d.withdraw(typed("tweety", "Bird"))
        d.commit(typed("tweety", "EmperorPenguin"))          # the rescue
        assert d.status() == "coherent"
        # With no defeater to appeal to and Γ the positum itself, nothing can be done.
        from pynmms.robustness import MONOTONE

        b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
        b.add_consequence(F({typed("t", "Bird"), typed("t", "Grounded")}), F(),
                          robustness=MONOTONE)
        stuck = Dialogue(b, holder="me", positum=[typed("t", "Bird"), typed("t", "Grounded")])
        assert stuck.status() == "aporia"


class TestPersistence:
    def test_save_and_load_round_trip(self, tmp_path: Path):
        b = base()
        d = Dialogue(b, holder="me", positum=[typed("tweety", "Sparrow")])
        d.commit(typed("tweety", "Grounded"))
        (tid,) = d.open
        d.contest(tid, exception=[typed("tweety", "Flightless")])
        path = tmp_path / "state.json"
        d.save(path)
        data = json.loads(path.read_text())
        assert data["holder"] == "me" and len(data["transcript"]) == 3
        e = Dialogue.load(path, b)
        assert e.position.accepted == d.position.accepted and e.positum == d.positum
        assert [t.id for t in e.contested] == [tid] and e.proposals[0].exception
        assert [x.move for x in e.transcript] == ["commit", "commit", "contest"]


class TestPlay:
    def test_scripted_respondent_with_predictions(self):
        d = Dialogue(base(), holder="me")
        script = """
commit <ex:tweety a ex:Sparrow>
status? ## coherent
commit <ex:tweety a ex:Grounded>
status? ## tensions open
tensions? ## 1
accept 1 retract <ex:tweety a ex:Grounded>
status? ## coherent
probes? ## 2
"""
        outcome = d.play(script)
        assert outcome.predicted == "5/5", outcome.failures
