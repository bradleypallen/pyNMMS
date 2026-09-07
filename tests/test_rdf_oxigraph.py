"""OxigraphBackend: the regime closure computed inside an embedded store.

The store runs the pattern rules of the regime as SPARQL updates to a
fixpoint (``thm:closure`` materialised store-side) and answers membership,
pattern, and join queries in microseconds; the extras of a query are still
closed in process with the store as the join partner. These tests check the
backend against ``MemoryBackend`` and owlrl, its incremental ``add()``,
persistence on disk, Skolemization, and the CLI ``--oxigraph`` option.
"""

# ruff: noqa: E402

from __future__ import annotations

import random

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("pyoxigraph")
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

from pynmms import NMMSReasoner
from pynmms.cli.main import main
from pynmms.rdf import OWL2RL, RegimeBase, TripleAtom, parse_rule
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf.backends import GraphBackend, MemoryBackend, OxigraphBackend
from pynmms.rdf.backends.oxigraph import from_ox, to_ox
from pynmms.rdf.rules import Var, custom
from pynmms.rdf.sparql_rules import partition, rule_to_ask, rule_to_update, translatable
from pynmms.robustness import guarded

EX = Namespace("http://ex.org/")


def _norm(t):
    """Skolem IRIs differ between backends only in their labels."""
    return tuple(URIRef("sk") if "genid" in str(n) else n for n in t)


def _closure_set(backend) -> set:
    return {_norm(t) for t in backend.closure_triples((None, None, None))}


def _memory_closure(g: Graph, regime, skolemize: bool = True) -> set:
    mem = MemoryBackend(g, regime=regime, skolemize=skolemize)
    return {_norm(t) for t in mem.closure if not isinstance(t[0], Literal)}


def _random_rdfs_graph(rnd: random.Random) -> Graph:
    classes = [EX[f"C{i}"] for i in range(5)]
    props = [EX[f"p{i}"] for i in range(3)]
    inds = [EX[f"i{i}"] for i in range(4)]
    g = Graph()
    for _ in range(rnd.randint(3, 9)):
        k = rnd.random()
        if k < 0.25:
            g.add((rnd.choice(classes), RDFS.subClassOf, rnd.choice(classes)))
        elif k < 0.4:
            g.add((rnd.choice(props), RDFS.range, rnd.choice(classes)))
        elif k < 0.5:
            g.add((rnd.choice(props), RDFS.domain, rnd.choice(classes)))
        elif k < 0.6:
            g.add((rnd.choice(props), RDFS.subPropertyOf, rnd.choice(props)))
        elif k < 0.8:
            g.add((rnd.choice(inds), RDF.type, rnd.choice(classes)))
        else:
            g.add((rnd.choice(inds), rnd.choice(props), rnd.choice(inds)))
    return g


class TestTranslation:
    def test_pattern_rules_translate_and_guarded_do_not(self):
        rules = partition(RDFS_REGIME)
        assert len(rules.updates) == 14
        assert {r.name for r in rules.in_process} == {"rdfs1", "rdfD1"}
        assert all(not translatable(r) for r in rules.in_process)

    def test_bottom_rule_is_an_ask(self):
        r = parse_rule("?x a http://ex.org/Alive, ?x a http://ex.org/Dead -> false")
        assert rule_to_ask(r).startswith("ASK {")
        with pytest.raises(ValueError):
            rule_to_update(r)

    def test_owl2rl_partition(self):
        rules = partition(OWL2RL, skip=frozenset({"rdfs1", "rdfD1"}))
        assert rules.asks and rules.updates
        assert rules.skipped == ("rdfs1", "rdfD1")
        assert all(hasattr(r, "fire") for r in rules.in_process)


class TestTerms:
    @pytest.mark.parametrize("n", [
        URIRef("http://ex.org/a"), BNode("b1"), Literal("x"), Literal("x", lang="en"),
        Literal(3), Literal("1.5", datatype=XSD.decimal), Literal("2026-09-07", datatype=XSD.date),
    ])
    def test_round_trip(self, n):
        import pyoxigraph as ox

        assert from_ox(to_ox(n, ox), ox) == n


class TestClosure:
    def test_is_a_graph_backend(self):
        assert isinstance(OxigraphBackend(regime=RDFS_REGIME), GraphBackend)

    def test_rdfs_closure_matches_memory_backend(self):
        rnd = random.Random(3)
        for _ in range(25):
            g = _random_rdfs_graph(rnd)
            ox = OxigraphBackend(regime=RDFS_REGIME)
            ox.load_graph(g)
            assert _closure_set(ox) == _memory_closure(g, RDFS_REGIME), g.serialize(format="nt")
            assert ox.size() == len(g)

    def test_owl2rl_closure_with_lists_matches_memory_backend(self):
        rnd = random.Random(9)
        classes = [EX[f"C{i}"] for i in range(4)]
        inds = [EX[f"i{i}"] for i in range(3)]
        for trial in range(8):
            g = Graph()
            head = BNode(f"l{trial}")
            Collection(g, head, rnd.sample(classes, 2))
            g.add((EX.Combo, rnd.choice([OWL.intersectionOf, OWL.unionOf]), head))
            g.add((EX.p, RDF.type, OWL.TransitiveProperty))
            for _ in range(rnd.randint(2, 5)):
                g.add((rnd.choice(inds), RDF.type, rnd.choice(classes + [EX.Combo])))
                g.add((rnd.choice(inds), EX.p, rnd.choice(inds)))
            ox = OxigraphBackend(regime=OWL2RL, skolemize=False)
            ox.load_graph(g)
            expected = _memory_closure(g, OWL2RL, skolemize=False)
            assert _closure_set(ox) == expected, g.serialize(format="nt")

    def test_owlrl_oracle(self):
        owlrl = pytest.importorskip("owlrl")
        rnd = random.Random(21)
        inds = [EX[f"i{i}"] for i in range(4)]
        classes = [EX[f"C{i}"] for i in range(5)]
        for _ in range(10):
            g = _random_rdfs_graph(rnd)
            oracle = Graph()
            for t in g:
                oracle.add(t)
            owlrl.DeductiveClosure(owlrl.RDFS_Semantics, axiomatic_triples=True).expand(oracle)
            ox = OxigraphBackend(regime=RDFS_REGIME)
            ox.load_graph(g)
            base = RegimeBase(ox)
            r = NMMSReasoner(base)
            for i in inds:
                for c in classes:
                    t = (i, RDF.type, c)
                    ours = r.derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable
                    assert ours == (t in oracle), (g.serialize(format="nt"), t)

    def test_inconsistency_from_a_bottom_rule(self):
        rule = parse_rule("?x a http://ex.org/Alive, ?x a http://ex.org/Dead -> false")
        regime = custom("rdfs+ad", [rule], extends=RDFS_REGIME)
        g = Graph()
        g.add((EX.Zombie, RDFS.subClassOf, EX.Dead))
        g.add((EX.z, RDF.type, EX.Zombie))
        ox = OxigraphBackend(regime=regime)
        ox.load_graph(g)
        assert not ox.is_inconsistent()
        assert ox.add([(EX.z, RDF.type, EX.Alive)]) == 1
        assert ox.is_inconsistent()
        fresh = OxigraphBackend(regime=regime)
        g.add((EX.z, RDF.type, EX.Alive))
        fresh.load_graph(g)
        assert fresh.is_inconsistent()

    def test_no_regime_means_closure_is_the_graph(self):
        ox = OxigraphBackend()
        ox.load_graph(Graph().add((EX.a, EX.p, EX.b)))
        assert ox.closure_size() == ox.size() == 1
        assert ox.contains((EX.a, EX.p, EX.b)) and ox.closure_contains((EX.a, EX.p, EX.b))


class TestMutation:
    def test_add_extends_closure_incrementally(self):
        g = Graph()
        g.add((EX.C0, RDFS.subClassOf, EX.C1))
        g.add((EX.C1, RDFS.subClassOf, EX.C2))
        ox = OxigraphBackend(regime=RDFS_REGIME)
        ox.load_graph(g)
        gen = ox.generation
        assert ox.add([(EX.x, RDF.type, EX.C0)]) == 1
        assert ox.generation == gen + 1
        assert ox.contains((EX.x, RDF.type, EX.C0))
        assert not ox.contains((EX.x, RDF.type, EX.C2))
        assert ox.closure_contains((EX.x, RDF.type, EX.C2))
        assert ox.add([(EX.x, RDF.type, EX.C0)]) == 0
        assert _closure_set(ox) == _memory_closure(g + Graph().add((EX.x, RDF.type, EX.C0)),
                                                    RDFS_REGIME)

    def test_join_free_and_bound(self):
        g = Graph()
        g.add((EX.C0, RDFS.subClassOf, EX.C1))
        g.add((EX.a, RDF.type, EX.C0))
        g.add((EX.b, RDF.type, EX.C0))
        ox = OxigraphBackend(regime=RDFS_REGIME)
        ox.load_graph(g)
        x = Var("x")
        rows = list(ox.join([(x, RDF.type, EX.C1)], {}))
        assert {r[x] for r in rows} == {EX.a, EX.b}
        assert list(ox.join([(x, RDF.type, EX.C1)], {x: EX.a})) == [{x: EX.a}]
        assert list(ox.join([(x, RDF.type, EX.C9)], {x: EX.a})) == []


class TestPersistence:
    def test_reopen_skips_materialisation(self, tmp_path, caplog):
        path = tmp_path / "store"
        g = Graph()
        g.add((EX.C0, RDFS.subClassOf, EX.C1))
        g.add((EX.a, RDF.type, EX.C0))
        ox = OxigraphBackend(path, regime=RDFS_REGIME)
        ox.load_graph(g)
        closed = _closure_set(ox)
        del ox
        with caplog.at_level("INFO", logger="pynmms.rdf.backends.oxigraph"):
            again = OxigraphBackend(path, regime=RDFS_REGIME)
        assert "already materialised" in caplog.text
        assert _closure_set(again) == closed
        assert again.size() == 2

    def test_reopen_with_another_regime_rematerialises(self, tmp_path):
        path = tmp_path / "store"
        g = Graph()
        g.add((EX.p, RDF.type, OWL.SymmetricProperty))
        g.add((EX.a, EX.p, EX.b))
        ox = OxigraphBackend(path, regime=RDFS_REGIME)
        ox.load_graph(g)
        assert not ox.closure_contains((EX.b, EX.p, EX.a))
        del ox
        owl = OxigraphBackend(path, regime=OWL2RL)
        assert owl.closure_contains((EX.b, EX.p, EX.a))
        assert owl.size() == 2

    @pytest.mark.parametrize("in_memory", [True, False])
    def test_disk_materialisation_paths_agree(self, tmp_path, in_memory):
        """The scratch-store path and the direct-on-disk path give the same closure."""
        g = Graph()
        g.add((EX.C0, RDFS.subClassOf, EX.C1))
        g.add((EX.p, RDFS.range, EX.C1))
        g.add((EX.a, RDF.type, EX.C0))
        g.add((EX.a, EX.p, EX.b))
        with OxigraphBackend(tmp_path / f"s{in_memory}", regime=RDFS_REGIME,
                             in_memory=in_memory) as ox:
            ox.load_graph(g)
            assert _closure_set(ox) == _memory_closure(g, RDFS_REGIME)
            assert ox.size() == 4

    def test_load_file_skolemizes_and_binds_prefixes(self, tmp_path):
        ttl = tmp_path / "g.ttl"
        ttl.write_text("@prefix ex: <http://ex.org/> .\n"
                       "ex:a ex:knows [ ex:name \"x\"@en ] .\n")
        ox = OxigraphBackend(regime=RDFS_REGIME)
        assert ox.load(ttl) == 2
        assert not any(isinstance(n, BNode) for t in ox.triples((None, None, None)) for n in t)
        assert ox.resolver.expand("ex:a") == EX.a
        out = tmp_path / "out.nt"
        ox.dump(out)
        assert len(Graph().parse(out)) == 2

    def test_deferred_materialisation(self, tmp_path):
        a = tmp_path / "a.ttl"
        b = tmp_path / "b.ttl"
        a.write_text("<http://ex.org/C0> <http://www.w3.org/2000/01/rdf-schema#subClassOf> "
                     "<http://ex.org/C1> .\n")
        b.write_text("<http://ex.org/x> a <http://ex.org/C0> .\n")
        ox = OxigraphBackend(regime=RDFS_REGIME, materialize=False)
        ox.load(a, materialize=False)
        ox.load(b, materialize=False)
        assert not ox.closure_contains((EX.x, RDF.type, EX.C1))
        ox.materialize()
        assert ox.closure_contains((EX.x, RDF.type, EX.C1))


class TestQueries:
    def test_negation_and_material_entry_round_trips_are_bounded(self):
        rule = parse_rule("?x a http://ex.org/Alive, ?x a http://ex.org/Dead -> false")
        regime = custom("rdfs+ad", [rule], extends=RDFS_REGIME)
        g = Graph()
        g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
        g.add((EX.tweety, RDF.type, EX.Sparrow))
        ox = OxigraphBackend(regime=regime)
        ox.load_graph(g)
        base = RegimeBase(ox)
        base.add_consequence(frozenset({TripleAtom(EX.tweety, RDF.type, EX.Bird)}),
                             frozenset({TripleAtom(EX.tweety, RDF.type, EX.Flies)}),
                             robustness=guarded([TripleAtom(EX.tweety, RDF.type, EX.Penguin)]))
        r = NMMSReasoner(base)
        ox.round_trips = 0
        assert r.derives_sequent(base.sequent(
            ["<http://ex.org/tweety a http://ex.org/Alive>"],
            ["~<http://ex.org/tweety a http://ex.org/Dead>"])).derivable
        assert r.derives_sequent(base.sequent(
            [], ["<http://ex.org/tweety a http://ex.org/Flies>"])).derivable
        assert ox.round_trips < 400


class TestCLI:
    def test_ask_tell_and_position_over_a_store(self, tmp_path, capsys):
        ttl = tmp_path / "g.ttl"
        ttl.write_text("@prefix ex: <http://ex.org/> .\n"
                       "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                       "ex:Sparrow rdfs:subClassOf ex:Bird .\n"
                       "ex:tweety a ex:Sparrow .\n")
        store = str(tmp_path / "store")
        rc = main(["rdf", "ask", "--oxigraph", store, "-g", str(ttl), "--regime", "rdfs",
                   "<ex:tweety a ex:Bird>"])
        assert rc == 0
        # The store persists the graph and its closure; no -g needed now.
        rc = main(["rdf", "ask", "--oxigraph", store, "--regime", "rdfs",
                   "--prefix", "ex=http://ex.org/", "<ex:tweety a ex:Bird>"])
        assert rc == 0
        rc = main(["rdf", "tell", "--oxigraph", store, "--regime", "rdfs",
                   "--prefix", "ex=http://ex.org/", "<ex:polly a ex:Sparrow>"])
        assert rc == 0
        assert "Added 1" in capsys.readouterr().out
        rc = main(["rdf", "ask", "--oxigraph", store, "--regime", "rdfs",
                   "--prefix", "ex=http://ex.org/", "<ex:polly a ex:Bird>"])
        assert rc == 0
        rc = main(["rdf", "ask", "--oxigraph", store, "--regime", "rdfs",
                   "--prefix", "ex=http://ex.org/", "<ex:polly a ex:Fish>"])
        assert rc == 2
        reject = tmp_path / "r.ttl"
        reject.write_text("@prefix ex: <http://ex.org/> .\nex:polly a ex:Bird .\n")
        rc = main(["rdf", "position", "--oxigraph", store, "--regime", "rdfs",
                   "--reject", str(reject)])
        assert rc == 0

    def test_oxigraph_and_store_are_exclusive(self, tmp_path, capsys):
        rc = main(["rdf", "ask", "--oxigraph", str(tmp_path / "s"), "--store", "http://x/",
                   "<http://ex.org/a http://ex.org/p http://ex.org/b>"])
        assert rc == 1
