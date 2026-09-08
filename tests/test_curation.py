"""The curation loop (PLAN.md step 5): propose before writing, against SHACL and SPARQL.

Predictions first. ``Position.propose()`` returns, without writing anything,
whether the position is in bounds, what refutes it and what would rescue
it, what an opponent would ask, what it is committed to (asserted,
inherited, derived) and precluded from, its entitlement score, and the
proof trace. ``bench/curation_loop.py`` runs the same records through
SHACL, the shapes' own SPARQL, and NMMS on one store.
"""

# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import Position, RegimeBase, Resolver, TripleAtom
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.defeasible import parse_defeasible_rule
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


class TestPropose:
    def _base(self) -> RegimeBase:
        b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
        b.add_consequence(F({typed("tweety", "Bird"), typed("tweety", "Grounded")}), F(),
                          robustness=guarded([typed("tweety", "Penguin")]))
        b.add_rule(parse_defeasible_rule("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin",
                                         Resolver(ontology())))
        return b

    def test_a_coherent_proposal_reports_probes_defaults_and_score(self):
        pos = Position(self._base(), holder="me").assert_(typed("tweety", "Sparrow"))
        r = pos.propose()
        assert r.coherent and r.rescue == ()
        assert r.precluded == (typed("tweety", "Grounded"),)          # accepting it refutes
        assert r.defaults == (typed("tweety", "Flies"),)              # committed by default
        assert r.commitments[typed("tweety", "Flies")].kind == "derived"
        assert r.commitments[typed("tweety", "Sparrow")].kind == "asserted"
        assert r.score == {"committed": 1, "entitled": 0, "open": 1}
        assert r.trace and r.ms >= 0
        assert "in bounds" in r.summary() and "Flies" in r.summary()
        assert pos.accepted == F({typed("tweety", "Sparrow")})         # nothing written or changed

    def test_an_incoherent_proposal_names_the_refutation_and_the_rescue(self):
        pos = Position(self._base()).assert_(typed("tweety", "Sparrow"),
                                             typed("tweety", "Grounded"))
        r = pos.propose()
        assert not r.coherent
        assert "Grounded" in (r.coherent.reason or "")
        assert r.rescue == (typed("tweety", "Penguin"),)
        assert r.challenges[0].kind == "refutation"
        assert "out of bounds" in r.summary() and "Penguin" in r.summary()
        # The loop: take the rescue as a hypothesis, propose again, then commit.
        pos.assert_(*r.rescue)
        assert pos.propose().coherent


class TestHarness:
    def test_shacl_sparql_and_nmms_agree_on_a_small_store(self, tmp_path: Path, capsys):
        pytest.importorskip("pyoxigraph")
        pytest.importorskip("pyshacl")
        from bench.curation_loop import main
        from pynmms.rdf.backends import OxigraphBackend

        g = Graph()
        g.bind("ex", EX)
        g.add((EX.ok, RDF.type, EX.Object))
        g.add((EX.ok, EX.start, Literal("1700")))
        g.add((EX.ok, EX.end, Literal("1750")))
        g.add((EX.bad, RDF.type, EX.Object))
        g.add((EX.bad, EX.start, Literal("1780")))
        g.add((EX.bad, EX.end, Literal("1632")))
        g.add((EX.rescued, RDF.type, EX.Object))
        g.add((EX.rescued, EX.start, Literal("1780")))
        g.add((EX.rescued, EX.end, Literal("1632")))
        g.add((EX.rescued, EX.circa, Literal("yes")))
        with OxigraphBackend(tmp_path / "store", regime=RDFS_REGIME,
                             prefixes={"ex": str(EX)}) as ox:
            ox.load_graph(g)
        entries = tmp_path / "entries.txt"
        entries.write_text('?x ex:start ?s, ?x ex:end ?e, [year(?s) > year(?e)] |~ false '
                           'unless ?x ex:circa "yes"\n')
        shapes = tmp_path / "shapes.ttl"
        shapes.write_text("""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://ex.org/> .
ex:ObjectShape a sh:NodeShape ; sh:targetClass ex:Object ;
  sh:sparql [ sh:message "start after end" ;
    sh:select \"\"\"SELECT $this WHERE { $this <http://ex.org/start> ?s ; <http://ex.org/end> ?e
      FILTER(xsd:integer(SUBSTR(STR(?s), 1, 4)) > xsd:integer(SUBSTR(STR(?e), 1, 4)))
      FILTER NOT EXISTS { $this <http://ex.org/circa> "yes" } }\"\"\" ] .
""")
        rc = main(["--store", str(tmp_path / "store"), "--prefix", f"ex={EX}",
                   "--entries", str(entries), "--shapes", str(shapes),
                   "--target-class", str(EX.Object), "--clean-sample", "5",
                   "--fix", '<ex:circa "yes">', "--no-write"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "curation:summary" in out
        # Predictions: the three methods agree on all three records; one is flagged by all;
        # NMMS offers a rescue for it and the proposed fix restores coherence.
        assert "agree 3/3" in out and "flagged 1" in out and "rescued 1/1" in out
        assert "fixed 1/1" in out
