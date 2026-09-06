"""Tests for pynmms.rdf: triple atoms, graph views, closure, regime bases, CLI."""

# ruff: noqa: E402, I001

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms import NMMSReasoner
from pynmms.cli.main import main
from pynmms.rdf import (
    RDFS as RDFS_REGIME,
)
from pynmms.rdf import (
    SIMPLE,
    GraphView,
    RDFBase,
    RegimeBase,
    Resolver,
    TripleAtom,
    parse_rule,
)
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.closure import ClosureEngine
from pynmms.rdf.rules import custom
from pynmms.robustness import guarded

EX = Namespace("http://ex.org/")
F = frozenset


def tweety_graph() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Bird, RDFS.subClassOf, EX.Animal))
    g.add((EX.Animal, RDFS.subClassOf, EX.Thing))
    g.add((EX.tweety, RDF.type, EX.Bird))
    g.add((EX.hasChild, RDFS.range, EX.Person))
    g.add((EX.hasChild, RDFS.domain, EX.Parent))
    g.add((EX.tweety, EX.name, Literal("Tweety <bird>", lang="en")))
    return g


@pytest.fixture
def regime_base():
    g = tweety_graph()
    rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(g))
    regime = custom("rdfs+ad", [rule], extends=RDFS_REGIME)
    return RegimeBase(MemoryBackend(g, regime=regime))


class TestTripleAtom:
    def test_canonical_name_and_equality(self):
        t = TripleAtom(EX.tweety, RDF.type, EX.Bird)
        assert str(t) == "<http://ex.org/tweety http://www.w3.org/1999/02/22-rdf-syntax-ns#type http://ex.org/Bird>"
        assert t == TripleAtom.from_name(str(t))
        assert t == TripleAtom.from_name("<ex:tweety a ex:Bird>", Resolver(tweety_graph()))
        assert hash(t) == hash(str(t))
        assert isinstance(t, str)

    def test_literal_and_bnode_round_trip(self):
        for term in (Literal("x <y> \"z\"\n", lang="en"), Literal(3), Literal("plain"),
                     BNode("b1")):
            t = TripleAtom(EX.a, EX.p, term)
            assert "<" not in str(t)[1:-1] and ">" not in str(t)[1:-1]
            back = TripleAtom.from_name(str(t))
            assert back == t and back.o == term

    def test_display(self):
        t = TripleAtom(EX.tweety, RDF.type, EX.Bird)
        assert t.display(Resolver(tweety_graph())) == "<ex:tweety a ex:Bird>"

    def test_coerce(self):
        assert TripleAtom.coerce("p") is None
        assert TripleAtom.coerce("<not a triple>") is None
        assert TripleAtom.coerce((EX.a, EX.p, EX.b)) == TripleAtom(EX.a, EX.p, EX.b)

    def test_parses_through_propositional_parser(self):
        from pynmms.syntax import parse_sentence

        s = parse_sentence("<ex:a a ex:B> -> ~<ex:a a ex:C>")
        assert s.type == "impl"


class TestGraphView:
    def test_membership_and_diff(self):
        be = MemoryBackend(tweety_graph())
        v = GraphView(be)
        t = TripleAtom(EX.tweety, RDF.type, EX.Bird)
        assert t in v and str(t) in v
        assert TripleAtom(EX.tweety, RDF.type, EX.Fish) not in v
        w = v.with_added("<http://ex.org/x http://ex.org/p http://ex.org/y>")
        assert len(w) == len(v) + 1 and w.diff_size == 1
        assert w.with_removed(t).diff_size == 2
        assert v.with_added(t) is v

    def test_hash_eq_structural(self):
        be = MemoryBackend(tweety_graph())
        a = GraphView(be).with_added("<http://ex.org/x http://ex.org/p http://ex.org/y>")
        b = GraphView(be).with_added("<http://ex.org/x http://ex.org/p http://ex.org/y>")
        assert a == b and hash(a) == hash(b)
        assert a != GraphView(be)

    def test_generation_invalidates(self):
        be = MemoryBackend(tweety_graph())
        a = GraphView(be)
        be.add([(EX.new, EX.p, EX.q)])
        assert GraphView(be) != a

    def test_intersects_and_iteration(self):
        be = MemoryBackend(tweety_graph())
        v = GraphView(be)
        assert v.intersects(F({TripleAtom(EX.tweety, RDF.type, EX.Bird)}))
        assert not v.intersects(F({"p"}))
        assert len(list(v)) == len(v)


class TestClosureEngine:
    def test_rdfs_closure_transitive(self):
        closed, bottom = ClosureEngine(RDFS_REGIME).close(iter(tweety_graph()))
        assert (EX.tweety, RDF.type, EX.Thing) in closed
        assert (EX.Bird, RDFS.subClassOf, EX.Thing) in closed
        assert not bottom

    def test_extend_only_fires_on_new(self):
        be = MemoryBackend(tweety_graph(), regime=RDFS_REGIME)
        new, bottom = ClosureEngine(RDFS_REGIME).extend(
            [(EX.bob, EX.hasChild, EX.kim)], be.closure_triples, be.closure_contains
        )
        assert (EX.kim, RDF.type, EX.Person) in new
        assert (EX.bob, RDF.type, EX.Parent) in new
        assert (EX.tweety, RDF.type, EX.Thing) not in new  # already in the store
        assert not bottom

    def test_false_concluding(self):
        rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(tweety_graph()))
        engine = ClosureEngine(custom("t", [rule]))
        _, bottom = engine.close([(EX.a, RDF.type, EX.Alive), (EX.a, RDF.type, EX.Dead)])
        assert bottom
        _, bottom = engine.close([(EX.a, RDF.type, EX.Alive), (EX.b, RDF.type, EX.Dead)])
        assert not bottom

    def test_rule_range_restriction(self):
        with pytest.raises(ValueError):
            parse_rule("?x ex:p ?y -> ?x ex:q ?z")


class TestRegimeBase:
    def test_closure_entailment(self, regime_base):
        r = NMMSReasoner(regime_base)
        assert r.derives_sequent(regime_base.sequent([], ["<ex:tweety a ex:Thing>"])).derivable
        assert not r.derives_sequent(regime_base.sequent([], ["<ex:tweety a ex:Fish>"])).derivable

    def test_extras_closure(self, regime_base):
        r = NMMSReasoner(regime_base)
        seq = regime_base.sequent(["<ex:bob ex:hasChild ex:kim>"], ["<ex:kim a ex:Person>"])
        assert r.derives_sequent(seq).derivable
        assert not r.derives_sequent(regime_base.sequent([], ["<ex:kim a ex:Person>"])).derivable

    def test_conditional_and_negation(self, regime_base):
        r = NMMSReasoner(regime_base)
        assert r.derives_sequent(regime_base.sequent(
            [], ["<ex:x a ex:Bird> -> <ex:x a ex:Animal>"])).derivable
        # II: Γ |~ ~Dead(t) iff Γ, Dead(t) |~ ∅
        assert r.derives_sequent(regime_base.sequent(
            ["<ex:tweety a ex:Alive>"], ["~<ex:tweety a ex:Dead>"])).derivable
        assert not r.derives_sequent(regime_base.sequent(
            [], ["~<ex:tweety a ex:Dead>"])).derivable

    def test_incoherence(self, regime_base):
        r = NMMSReasoner(regime_base)
        assert r.derives_sequent(regime_base.sequent(
            ["<ex:tweety a ex:Alive>", "<ex:tweety a ex:Dead>"], [])).derivable
        assert regime_base.is_inconsistent(["<ex:t a ex:Alive>", "<ex:t a ex:Dead>"])
        assert not regime_base.is_inconsistent()
        # an inconsistent Γ implies anything (explosion of the regime base)
        assert r.derives_sequent(regime_base.sequent(
            ["<ex:tweety a ex:Alive>", "<ex:tweety a ex:Dead>"], ["<ex:z a ex:Q>"])).derivable

    def test_standalone_sequent_without_graph(self, regime_base):
        r = NMMSReasoner(regime_base)
        seq = regime_base.sequent(
            ["<ex:a a ex:Bird>", "<ex:Bird rdfs:subClassOf ex:Animal>"],
            ["<ex:a a ex:Animal>"], include_graph=False)
        assert r.derives_sequent(seq).derivable
        seq = regime_base.sequent(["<ex:a a ex:Bird>"], ["<ex:a a ex:Animal>"],
                                  include_graph=False)
        assert not r.derives_sequent(seq).derivable  # G not included

    def test_simple_regime_is_containment(self):
        base = RegimeBase(MemoryBackend(tweety_graph()), regime=SIMPLE)
        r = NMMSReasoner(base)
        assert r.derives_sequent(base.sequent([], ["<ex:tweety a ex:Bird>"])).derivable
        assert not r.derives_sequent(base.sequent([], ["<ex:tweety a ex:Animal>"])).derivable

    def test_guarded_entry_over_graph(self):
        base = RDFBase(MemoryBackend(tweety_graph()))
        flies = TripleAtom(EX.tweety, RDF.type, EX.Flies)
        bird = TripleAtom(EX.tweety, RDF.type, EX.Bird)
        penguin = TripleAtom(EX.tweety, RDF.type, EX.Penguin)
        base.add_consequence(F({bird}), F({flies}), robustness=guarded([penguin]))
        r = NMMSReasoner(base)
        assert r.derives_sequent(base.sequent([], [flies])).derivable
        assert not r.derives_sequent(base.sequent(["<ex:tweety a ex:Penguin>"], [flies])).derivable

    def test_backend_mutation_invalidates_cache(self, regime_base):
        r = NMMSReasoner(regime_base, persistent_cache=True)
        assert not r.derives_sequent(regime_base.sequent([], ["<ex:kim a ex:Person>"])).derivable
        regime_base.backend.add([(EX.bob, EX.hasChild, EX.kim)])
        assert r.derives_sequent(regime_base.sequent([], ["<ex:kim a ex:Person>"])).derivable

    def test_large_graph_flat(self):
        g = tweety_graph()
        for i in range(20_000):
            g.add((EX[f"i{i}"], EX.p, EX[f"j{i}"]))
        base = RegimeBase(MemoryBackend(g, regime=SIMPLE))
        r = NMMSReasoner(base)
        res = r.derives_sequent(base.sequent(
            ["<ex:a a ex:B>"], ["<ex:a a ex:B> & <ex:tweety a ex:Bird>"]))
        assert res.derivable and res.nodes <= 4


class TestSkolemization:
    def test_blank_nodes_skolemized_on_load(self):
        g = Graph()
        b = BNode()
        g.add((EX.a, EX.p, b))
        g.add((b, EX.q, EX.c))
        be = MemoryBackend(g)
        assert not any(isinstance(n, BNode) for t in be.graph for n in t)
        assert be.size() == 2


@pytest.mark.skipif(importlib.util.find_spec("owlrl") is None, reason="owlrl not installed")
class TestOwlrlOracle:
    """Theorem 35 / Corollary 37: NMMS over B_RDFS agrees with RDFS entailment."""

    def _owlrl_closure(self, g: Graph) -> Graph:
        import owlrl

        c = Graph()
        for t in g:
            c.add(t)
        owlrl.DeductiveClosure(owlrl.RDFS_Semantics, axiomatic_triples=True).expand(c)
        return c

    def test_agrees_on_user_triples(self):
        import random

        rnd = random.Random(7)
        classes = [EX[f"C{i}"] for i in range(5)]
        props = [EX[f"p{i}"] for i in range(3)]
        inds = [EX[f"i{i}"] for i in range(4)]
        for _ in range(15):
            g = Graph()
            for _ in range(rnd.randint(2, 6)):
                kind = rnd.random()
                if kind < 0.3:
                    g.add((rnd.choice(classes), RDFS.subClassOf, rnd.choice(classes)))
                elif kind < 0.45:
                    g.add((rnd.choice(props), RDFS.domain, rnd.choice(classes)))
                elif kind < 0.6:
                    g.add((rnd.choice(props), RDFS.range, rnd.choice(classes)))
                elif kind < 0.7:
                    g.add((rnd.choice(props), RDFS.subPropertyOf, rnd.choice(props)))
                elif kind < 0.85:
                    g.add((rnd.choice(inds), RDF.type, rnd.choice(classes)))
                else:
                    g.add((rnd.choice(inds), rnd.choice(props), rnd.choice(inds)))
            oracle = self._owlrl_closure(g)
            base = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
            r = NMMSReasoner(base)
            queries = [(i, RDF.type, c) for i in inds for c in classes] + [
                (i, p, j) for i in inds for p in props for j in inds]
            for t in queries:
                ours = r.derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable
                assert ours == (t in oracle), (g.serialize(format="nt"), t)


class TestRdfCli:
    def _write_graph(self, tmp: Path) -> Path:
        p = tmp / "g.ttl"
        tweety_graph().serialize(destination=str(p), format="turtle")
        return p

    def test_ask_rdfs(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_graph(Path(d))
            assert main(["rdf", "ask", "-g", str(p), "--regime", "rdfs",
                         "<ex:tweety a ex:Thing>"]) == 0
            assert main(["rdf", "ask", "-g", str(p), "<ex:tweety a ex:Thing>"]) == 2
            assert main(["rdf", "ask", "-g", str(p), "--regime", "rdfs", "--json",
                         "<ex:bob ex:hasChild ex:kim> => <ex:kim a ex:Person>"]) == 0
            data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
            assert data["status"] == "DERIVABLE" and data["regime"] == "rdfs"

    def test_ask_with_rules_and_negation(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_graph(Path(d))
            rules = Path(d) / "rules.txt"
            rules.write_text(
                "# alive and dead are incompatible\n?x a ex:Alive, ?x a ex:Dead -> false\n"
            )
            assert main(["rdf", "ask", "-g", str(p), "--regime", "rdfs", "--rules", str(rules),
                         "--trace", "<ex:tweety a ex:Alive> => ~<ex:tweety a ex:Dead>"]) == 0
            out = capsys.readouterr().out
            assert "DERIVABLE" in out and "[R¬]" in out

    def test_malformed_query(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_graph(Path(d))
            assert main(["rdf", "ask", "-g", str(p), "tweety"]) == 1
            assert "triple atom" in capsys.readouterr().err
