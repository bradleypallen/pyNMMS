"""Provenance as entitlement (PLAN.md step 4). Predictions first.

A commitment has a ground: asserted by the holder and undefended, defended
because the position survived a round of the opponent's probes, inherited
from a source (a named graph, an annotation record) with its evidence when
a record is read aloud, or derived from an entry. Sources come from named
graphs and annotation records; commit writes the holder's assertions into
the holder's own graph with PROV attribution; a defeater can read evidence
strength.
"""

# ruff: noqa: E402

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import Position, RegimeBase, Resolver, TripleAtom
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.defeasible import parse_defeasible_rule
from pynmms.rdf.provenance import PROV, RecordPattern
from pynmms.rdf.values import declare_ordering
from pynmms.robustness import MONOTONE

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


class TestGrounds:
    def test_asserted_then_defended_then_challenged(self):
        b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
        b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                          robustness=MONOTONE)
        pos = Position(b, holder="me").assert_(typed("tweety", "Sparrow"))
        assert pos.grounds()[typed("tweety", "Sparrow")].kind == "asserted"
        assert pos.score() == {"committed": 1, "entitled": 0, "open": 1}
        round1 = pos.defend()
        assert round1.stood and round1.open == 1                 # one probe asks for Grounded
        assert pos.grounds()[typed("tweety", "Sparrow")].kind == "defended"
        assert pos.score()["entitled"] == 1
        pos.assert_(typed("tweety", "Grounded"))
        round2 = pos.defend()
        assert not round2.stood and round2.refutations == 1
        g = pos.grounds()
        assert g[typed("tweety", "Sparrow")].kind == "defended"    # earlier standing is kept
        assert g[typed("tweety", "Grounded")].kind == "asserted"   # never defended
        pos.withdraw(typed("tweety", "Grounded"))
        assert pos.defend().stood
        assert [m.kind for m in pos.log][-4:] == ["assert", "defend", "withdraw", "defend"]

    def test_derived_grounds_from_unacknowledged_defaults(self):
        b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
        b.add_rule(parse_defeasible_rule("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin",
                                         Resolver(ontology())))
        pos = Position(b).assert_(typed("tweety", "Sparrow"))
        g = pos.grounds(derived=True)
        assert g[typed("tweety", "Flies")].kind == "derived"
        assert "Bird" in (g[typed("tweety", "Flies")].via or "")


class TestSources:
    def _store(self, tmp_path):
        pytest.importorskip("pyoxigraph")
        from pynmms.rdf.backends import OxigraphBackend

        ox = OxigraphBackend(tmp_path / "store", regime=RDFS_REGIME, prefixes={"ex": str(EX)})
        ox.load_graph(ontology())
        a = Graph()
        a.add((EX.etching, EX.maker, EX.luyken))
        a.add((EX.etching, EX.made, Literal("1727")))
        b = Graph()
        b.add((EX.etching, EX.maker, EX.vianen))
        ox.load_graph(a, source=URIRef("urn:catalogue:1900"))
        ox.load_graph(b, source=URIRef("urn:catalogue:1975"))
        return ox

    def test_reading_aloud_inherits_sources_and_one_source_is_one_account(self, tmp_path):
        ox = self._store(tmp_path)
        base = RegimeBase(ox)
        base.add_rule(parse_defeasible_rule(
            "?x ex:maker ?p, ?x ex:maker ?q, [?p != ?q] |~ false", Resolver(ontology())))
        rec = Position.of(base, EX.etching)
        g = rec.grounds()
        assert g[TripleAtom(EX.etching, EX.maker, EX.luyken)].kind == "inherited"
        assert g[TripleAtom(EX.etching, EX.maker, EX.luyken)].source == "urn:catalogue:1900"
        assert g[TripleAtom(EX.etching, EX.maker, EX.vianen)].source == "urn:catalogue:1975"
        assert not rec.coherent()                                  # the two accounts conflict
        old = Position.of(base, EX.etching, source=URIRef("urn:catalogue:1900"), holder="1900")
        new = Position.of(base, EX.etching, source=URIRef("urn:catalogue:1975"), holder="1975")
        assert old.coherent() and new.coherent()                   # each account alone stands
        assert len(old.accepted) == 2 and len(new.accepted) == 1
        assert rec.score()["entitled"] == 3                        # inherited counts as entitled
        ox.close()

    def test_commit_writes_the_holders_graph_with_attribution(self, tmp_path):
        ox = self._store(tmp_path)
        base = RegimeBase(ox)
        pos = Position(base, holder="curator@museum").assert_(
            TripleAtom(EX.etching, EX.posthumousImpression, Literal("yes")))
        assert pos.commit() == 1
        t = (EX.etching, EX.posthumousImpression, Literal("yes"))
        graphs = ox.graphs_of(t)
        assert graphs == [URIRef("urn:pynmms:holder:curator@museum")]
        assert ox.contains((graphs[0], PROV.wasAttributedTo, Literal("curator@museum")))
        later = Position.of(base, EX.etching)
        assert later.grounds()[TripleAtom(*t)].source == "urn:pynmms:holder:curator@museum"
        ox.close()


class TestEvidence:
    def _go_like(self) -> Graph:
        g = Graph()
        g.bind("ex", EX)
        g.add((EX.Y, RDFS.subClassOf, EX.X))
        for gp, ev, ref in (("gp1", "IDA", "PMID:1"), ("gp2", "IEA", "GO_REF:1")):
            g.add((EX[gp], EX.involved_in, EX.Y))
            rec = EX[f"ann-{gp}"]
            g.add((rec, EX.gene_product, EX[gp]))
            g.add((rec, EX.relation, EX.involved_in))
            g.add((rec, EX.cls, EX.Y))
            g.add((rec, EX.evidence, Literal(ev)))
            g.add((rec, EX.reference, Literal(ref)))
        return g

    def test_record_pattern_gives_evidence_and_a_defeater_can_read_it(self):
        declare_ordering("strength", ["IEA", "ISS", "IMP", "IDA"])
        b = RegimeBase(MemoryBackend(self._go_like(), regime=RDFS_REGIME))
        b.provenance = RecordPattern(subject=EX.gene_product, predicate=EX.relation,
                                     object=EX.cls, evidence=EX.evidence, reference=EX.reference)
        rec = Position.of(b, EX.gp1)
        ground = rec.grounds()[TripleAtom(EX.gp1, EX.involved_in, EX.Y)]
        assert ground.kind == "inherited" and ground.evidence == "IDA"
        assert ground.reference == "PMID:1"
        b.add_rule(parse_defeasible_rule(
            "?g ex:involved_in ?c, ?c rdfs:subClassOf ?d |~ ?g ex:involved_in ?d unless "
            "?r ex:gene_product ?g, ?r ex:cls ?c, ?r ex:evidence ?e, "
            '[rank(strength, ?e) < rank(strength, "IMP")]', Resolver(self._go_like())))
        assert Position.of(b, EX.gp1).commits_to(TripleAtom(EX.gp1, EX.involved_in, EX.X))
        assert not Position.of(b, EX.gp2).commits_to(TripleAtom(EX.gp2, EX.involved_in, EX.X))
        weak = Position.of(b, EX.gp2).grounds()[TripleAtom(EX.gp2, EX.involved_in, EX.Y)]
        assert weak.evidence == "IEA"
