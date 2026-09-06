"""Tests for pynmms.rdf: triple atoms, graph views, closure, regime bases, CLI."""

# ruff: noqa: E402, I001

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Slice 2: OWL 2 RL, pattern atoms, tell/repl, converters
# ---------------------------------------------------------------------------

from rdflib.namespace import OWL

from pynmms.onto.base import OntoMaterialBase
from pynmms.rdf import OWL2RL, PatternAtom, onto_to_graph, onto_to_rules
from pynmms.rdf.convert import DEFAULT_NS, atom_to_triple, consequences_to_triples
from pynmms.rdf.rules import OWL2RL_OMITTED
from pynmms.robustness import MONOTONE


class TestOwl2RL:
    def _base(self, g: Graph) -> RegimeBase:
        return RegimeBase(MemoryBackend(g, regime=OWL2RL))

    def test_inverse_symmetric_transitive(self):
        g = Graph()
        g.add((EX.parentOf, OWL.inverseOf, EX.childOf))
        g.add((EX.knows, RDF.type, OWL.SymmetricProperty))
        g.add((EX.ancestorOf, RDF.type, OWL.TransitiveProperty))
        g.add((EX.a, EX.parentOf, EX.b))
        g.add((EX.a, EX.knows, EX.c))
        g.add((EX.a, EX.ancestorOf, EX.b))
        g.add((EX.b, EX.ancestorOf, EX.c))
        base = self._base(g)
        r = NMMSReasoner(base)
        for t in ((EX.b, EX.childOf, EX.a), (EX.c, EX.knows, EX.a), (EX.a, EX.ancestorOf, EX.c)):
            assert r.derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable

    def test_disjointness_and_functional_sameas(self):
        g = Graph()
        g.add((EX.Alive, OWL.disjointWith, EX.Dead))
        g.add((EX.hasMother, RDF.type, OWL.FunctionalProperty))
        g.add((EX.x, EX.hasMother, EX.m1))
        g.add((EX.x, EX.hasMother, EX.m2))
        base = self._base(g)
        r = NMMSReasoner(base)
        same = TripleAtom(EX.m1, OWL.sameAs, EX.m2)
        assert r.derives_sequent(base.sequent([], [same])).derivable
        # cax-dw gives negation-as-incoherence over OWL disjointness
        assert r.derives_sequent(base.sequent(
            [TripleAtom(EX.a, RDF.type, EX.Alive)], ["~" + TripleAtom(EX.a, RDF.type, EX.Dead)]
        )).derivable
        assert not base.is_inconsistent()
        assert base.is_inconsistent([TripleAtom(EX.a, RDF.type, EX.Alive),
                                     TripleAtom(EX.a, RDF.type, EX.Dead)])

    def test_owlrl_oracle_on_fixed_arity_fragment(self):
        import random

        import owlrl

        rnd = random.Random(11)
        classes = [EX[f"C{i}"] for i in range(4)]
        props = [EX[f"p{i}"] for i in range(3)]
        inds = [EX[f"i{i}"] for i in range(4)]
        for _ in range(12):
            g = Graph()
            for _ in range(rnd.randint(2, 6)):
                k = rnd.random()
                if k < 0.2:
                    g.add((rnd.choice(classes), RDFS.subClassOf, rnd.choice(classes)))
                elif k < 0.3:
                    g.add((rnd.choice(classes), OWL.equivalentClass, rnd.choice(classes)))
                elif k < 0.4:
                    g.add((rnd.choice(props), OWL.inverseOf, rnd.choice(props)))
                elif k < 0.5:
                    g.add((rnd.choice(props), RDF.type, rnd.choice(
                        [OWL.SymmetricProperty, OWL.TransitiveProperty])))
                elif k < 0.6:
                    g.add((rnd.choice(props), RDFS.range, rnd.choice(classes)))
                elif k < 0.75:
                    g.add((rnd.choice(inds), RDF.type, rnd.choice(classes)))
                else:
                    g.add((rnd.choice(inds), rnd.choice(props), rnd.choice(inds)))
            oracle = Graph()
            for t in g:
                oracle.add(t)
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, axiomatic_triples=False).expand(oracle)
            base = self._base(g)
            r = NMMSReasoner(base)
            queries = [(i, RDF.type, c) for i in inds for c in classes] + [
                (i, p, j) for i in inds for p in props for j in inds]
            for t in queries:
                ours = r.derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable
                assert ours == (t in oracle), (g.serialize(format="nt"), t)

    def test_omitted_rules_documented(self):
        assert "eq-ref" in OWL2RL_OMITTED and "cls-int1" not in OWL2RL_OMITTED
        assert len(OWL2RL.rules) > 70


class TestPatternAtom:
    def test_canonical_name_round_trip(self):
        pat = PatternAtom([(BNode("b"), RDF.type, EX.Bird), (BNode("b"), EX.name, Literal("T"))])
        assert str(pat).startswith("<{ ") and str(pat).endswith(" }>")
        back = PatternAtom.from_name(str(pat))
        assert back == pat and back.bnodes == {BNode("b")}
        res = Resolver(tweety_graph())
        p2 = PatternAtom.from_name('<{ _:b a ex:Bird . _:b ex:name "T" }>', res)
        assert p2 == pat

    def test_existential_consequent(self, regime_base):
        r = NMMSReasoner(regime_base)
        # someone is a Bird with a name: tweety
        seq = regime_base.sequent(
            [], ['<{ _:b a ex:Bird . _:b ex:name "Tweety \\u003Cbird\\u003E"@en }>']
        )
        assert r.derives_sequent(seq).derivable
        # ... but nobody is a Fish
        assert not r.derives_sequent(regime_base.sequent([], ["<{ _:b a ex:Fish }>"])).derivable
        # shared blank node must be the same individual
        seq = regime_base.sequent([], ['<{ _:b a ex:Bird . _:b ex:name "Other" }>'])
        assert not r.derives_sequent(seq).derivable
        # witness may come from the closure, and from the extras
        assert r.derives_sequent(regime_base.sequent([], ["<{ _:b a ex:Thing }>"])).derivable
        seq = regime_base.sequent(["<ex:bob ex:hasChild ex:kim>"], ["<{ _:c a ex:Person }>"])
        assert r.derives_sequent(seq).derivable

    def test_pattern_combines_with_connectives(self, regime_base):
        r = NMMSReasoner(regime_base)
        seq = regime_base.sequent([], ["<{ _:b a ex:Fish }> | <{ _:b a ex:Bird }>"])
        assert r.derives_sequent(seq).derivable

    def test_pattern_not_allowed_in_antecedent(self, regime_base):
        with pytest.raises(ValueError, match="antecedent"):
            regime_base.sequent(["<{ _:b a ex:Bird }>"], [])
        with pytest.raises(ValueError, match="antecedent"):
            regime_base.sequent([], ["<{ _:b a ex:Bird }> -> <ex:x a ex:Y>"])

    def test_bnode_in_antecedent_is_skolemized(self, regime_base):
        seq = regime_base.sequent(["<_:z a ex:Bird>"], ["<_:z a ex:Animal>"])
        # the consequent bnode is NOT skolemized: it is a fresh existential in a
        # single-triple pattern? No: a bare triple atom with a bnode in the
        # succedent denotes that specific blank node, which nothing entails.
        gamma = next(iter(seq.gamma_atoms.added))
        assert "genid" in gamma
        r = NMMSReasoner(regime_base)
        assert not r.derives_sequent(seq).derivable
        # the pattern form asks the existential question and succeeds
        seq = regime_base.sequent(["<_:z a ex:Bird>"], ["<{ _:w a ex:Animal }>"])
        assert r.derives_sequent(seq).derivable


class TestConverters:
    def _onto(self) -> OntoMaterialBase:
        base = OntoMaterialBase(language={"Man(socrates)", "hasChild(a,b)"})
        base.register_subclass("Man", "Mortal", robustness=MONOTONE)
        base.register_range("hasChild", "Person")
        base.register_disjoint("Alive", "Dead", robustness=guarded(["Zombie"]))
        base.register_joint_commitment(["A", "B"], "C")
        base.add_consequence(F({"Man(socrates)"}), F({"Wise(socrates)"}), robustness=MONOTONE)
        return base

    def test_atom_to_triple(self):
        assert atom_to_triple("Man(socrates)") == TripleAtom(
            DEFAULT_NS.socrates, RDF.type, DEFAULT_NS.Man)
        assert atom_to_triple("hasChild(a,b)").p == DEFAULT_NS.hasChild

    def test_graph_and_notes(self):
        g, notes = onto_to_graph(self._onto())
        assert (DEFAULT_NS.Man, RDFS.subClassOf, DEFAULT_NS.Mortal) in g
        assert (DEFAULT_NS.socrates, RDF.type, DEFAULT_NS.Man) in g
        assert (DEFAULT_NS.Alive, OWL.disjointWith, DEFAULT_NS.Dead) in g
        assert any("range(hasChild, Person) is exact" in n for n in notes)
        assert any("Zombie" in n or "unless" in n for n in notes)
        assert any("jointCommitment" in n for n in notes)

    def test_rules_and_reasoning_over_converted_graph(self):
        onto = self._onto()
        g, _ = onto_to_graph(onto)
        rules = onto_to_rules(onto)
        assert len(rules) == 1
        regime = custom("onto", rules, extends=RDFS_REGIME)
        base = RegimeBase(MemoryBackend(g, regime=regime))
        for gamma, delta, rob in consequences_to_triples(onto):
            base.add_consequence(gamma, delta, robustness=rob)
        r = NMMSReasoner(base)
        assert r.derives_sequent(base.sequent(
            [], [TripleAtom(DEFAULT_NS.socrates, RDF.type, DEFAULT_NS.Mortal)])).derivable
        assert r.derives_sequent(base.sequent(
            [], [TripleAtom(DEFAULT_NS.socrates, RDF.type, DEFAULT_NS.Wise)])).derivable
        seq = base.sequent([TripleAtom(DEFAULT_NS.x, RDF.type, DEFAULT_NS.A),
                            TripleAtom(DEFAULT_NS.x, RDF.type, DEFAULT_NS.B)],
                           [TripleAtom(DEFAULT_NS.x, RDF.type, DEFAULT_NS.C)])
        assert r.derives_sequent(seq).derivable


class TestRdfTellAndRepl:
    def test_tell_creates_and_extends_file(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "new.ttl"
            g = Graph()
            g.bind("ex", EX)
            g.serialize(destination=str(p), format="turtle")
            # an empty Turtle file carries no prefix declarations: bind explicitly
            assert main(["rdf", "tell", "-g", str(p),
                         "<ex:tweety a ex:Bird>, <ex:tweety ex:name \"Tweety\"@en>"]) == 1
            assert main(["rdf", "tell", "-g", str(p), "--prefix", "ex=http://ex.org/",
                         "<ex:tweety a ex:Bird>, <ex:tweety ex:name \"Tweety\"@en>"]) == 0
            assert main(["rdf", "tell", "-g", str(p), "--json",
                         "<ex:Bird rdfs:subClassOf ex:Animal>"]) == 0
            data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
            assert data["added"] == 1 and data["graph_triples"] == 3
            assert main(["rdf", "ask", "-g", str(p), "--regime", "rdfs",
                         "<ex:tweety a ex:Animal>"]) == 0
            assert main(["rdf", "tell", "-g", str(p), "nonsense"]) == 1

    def test_repl_session(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.ttl"
            tweety_graph().serialize(destination=str(p), format="turtle")
            inputs = iter([
                "show",
                "ask <ex:tweety a ex:Thing>",
                "tell <ex:kim a ex:Fish>",
                "ask <ex:kim a ex:Fish>",
                "trace on",
                "ask <ex:tweety a ex:Bird> -> <ex:tweety a ex:Animal>",
                "save",
                "quit",
            ])
            with patch("builtins.input", lambda _: next(inputs)):
                assert main(["rdf", "repl", "-g", str(p), "--regime", "rdfs"]) == 0
            out = capsys.readouterr().out
            assert "regime: rdfs" in out
            assert out.count("DERIVABLE") >= 3 and "[R→]" in out
            assert "Added 1 triple(s)" in out and "Saved" in out
            assert (EX.kim, RDF.type, EX.Fish) in Graph().parse(str(p))


class TestOwl2RLListRules:
    def _base(self, g: Graph) -> RegimeBase:
        return RegimeBase(MemoryBackend(g, regime=OWL2RL))

    def _ask(self, base: RegimeBase, t) -> bool:
        return NMMSReasoner(base).derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable

    def test_intersection_union_oneof(self):
        from rdflib.collection import Collection

        g = Graph()
        g.bind("ex", EX)
        Collection(g, BNode("l1"), [EX.A, EX.B])
        g.add((EX.AB, OWL.intersectionOf, BNode("l1")))
        Collection(g, BNode("l2"), [EX.C, EX.D])
        g.add((EX.CD, OWL.unionOf, BNode("l2")))
        Collection(g, BNode("l3"), [EX.e1, EX.e2])
        g.add((EX.Enum, OWL.oneOf, BNode("l3")))
        g.add((EX.x, RDF.type, EX.A))
        g.add((EX.x, RDF.type, EX.B))
        g.add((EX.y, RDF.type, EX.AB))
        g.add((EX.z, RDF.type, EX.C))
        base = self._base(g)
        assert self._ask(base, (EX.x, RDF.type, EX.AB))          # cls-int1
        assert self._ask(base, (EX.y, RDF.type, EX.A))           # cls-int2
        assert self._ask(base, (EX.z, RDF.type, EX.CD))          # cls-uni
        assert self._ask(base, (EX.e1, RDF.type, EX.Enum))       # cls-oo
        assert self._ask(base, (EX.AB, RDFS.subClassOf, EX.A))   # scm-int
        assert self._ask(base, (EX.C, RDFS.subClassOf, EX.CD))   # scm-uni
        # extras: typing x's twin only with A is not enough
        r = NMMSReasoner(base)
        assert not r.derives_sequent(base.sequent(
            ["<ex:w a ex:A>"], [TripleAtom(EX.w, RDF.type, EX.AB)])).derivable
        assert r.derives_sequent(base.sequent(
            ["<ex:w a ex:A>", "<ex:w a ex:B>"], [TripleAtom(EX.w, RDF.type, EX.AB)])).derivable

    def test_property_chain_and_key(self):
        from rdflib.collection import Collection

        g = Graph()
        g.bind("ex", EX)
        Collection(g, BNode("c"), [EX.parentOf, EX.parentOf])
        g.add((EX.grandparentOf, OWL.propertyChainAxiom, BNode("c")))
        g.add((EX.a, EX.parentOf, EX.b))
        g.add((EX.b, EX.parentOf, EX.c))
        Collection(g, BNode("k"), [EX.ssn])
        g.add((EX.Person, OWL.hasKey, BNode("k")))
        g.add((EX.p1, RDF.type, EX.Person))
        g.add((EX.p2, RDF.type, EX.Person))
        g.add((EX.p1, EX.ssn, Literal("123")))
        g.add((EX.p2, EX.ssn, Literal("123")))
        base = self._base(g)
        assert self._ask(base, (EX.a, EX.grandparentOf, EX.c))   # prp-spo2
        assert self._ask(base, (EX.p1, OWL.sameAs, EX.p2))       # prp-key
        r = NMMSReasoner(base)
        seq = base.sequent(["<ex:c ex:parentOf ex:d>"], [TripleAtom(EX.b, EX.grandparentOf, EX.d)])
        assert r.derives_sequent(seq).derivable                   # chain extended by an extra

    def test_all_disjoint_and_all_different(self):
        from rdflib.collection import Collection

        g = Graph()
        g.bind("ex", EX)
        Collection(g, BNode("d"), [EX.Cat, EX.Dog])
        g.add((BNode("adc"), RDF.type, OWL.AllDisjointClasses))
        g.add((BNode("adc"), OWL.members, BNode("d")))
        Collection(g, BNode("m"), [EX.i, EX.j])
        g.add((BNode("ad"), RDF.type, OWL.AllDifferent))
        g.add((BNode("ad"), OWL.members, BNode("m")))
        base = self._base(MemoryBackend(g, skolemize=False).graph)
        assert not base.is_inconsistent()
        assert base.is_inconsistent([TripleAtom(EX.x, RDF.type, EX.Cat),
                                     TripleAtom(EX.x, RDF.type, EX.Dog)])
        assert base.is_inconsistent([TripleAtom(EX.i, OWL.sameAs, EX.j)])

    def test_rdfD1(self):
        g = Graph()
        g.add((EX.a, EX.age, Literal(3)))
        base = RegimeBase(MemoryBackend(g, regime=RDFS_REGIME))
        from rdflib.namespace import XSD

        assert self._ask(base, (Literal(3), RDF.type, XSD.integer))

    def test_owlrl_oracle_with_lists(self):
        import random

        import owlrl
        from rdflib.collection import Collection

        rnd = random.Random(5)
        classes = [EX[f"C{i}"] for i in range(4)]
        inds = [EX[f"i{i}"] for i in range(3)]
        for trial in range(10):
            g = Graph()
            head = BNode(f"l{trial}")
            members = rnd.sample(classes, 2)
            Collection(g, head, members)
            g.add((EX.Combo, rnd.choice([OWL.intersectionOf, OWL.unionOf]), head))
            for _ in range(rnd.randint(2, 5)):
                g.add((rnd.choice(inds), RDF.type, rnd.choice(classes + [EX.Combo])))
            oracle = Graph()
            for t in g:
                oracle.add(t)
            owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, axiomatic_triples=False).expand(oracle)
            base = RegimeBase(MemoryBackend(g, regime=OWL2RL, skolemize=False))
            r = NMMSReasoner(base)
            for i in inds:
                for c in classes + [EX.Combo]:
                    t = (i, RDF.type, c)
                    ours = r.derives_sequent(base.sequent([], [TripleAtom(*t)])).derivable
                    assert ours == (t in oracle), (g.serialize(format="nt"), t)


class TestBatchedJoin:
    """Batched firing must derive exactly what per-lookup firing derives."""

    def _graph(self) -> Graph:
        g = tweety_graph()
        g.add((EX.hasChild, RDFS.subPropertyOf, EX.hasRelative))
        g.add((EX.hasRelative, RDFS.domain, EX.Kin))
        g.add((EX.Person, RDFS.subClassOf, EX.Agent))
        return g

    def test_same_derivations_with_and_without_join(self):
        be = MemoryBackend(self._graph(), regime=OWL2RL)
        engine = ClosureEngine(OWL2RL)
        extras = [(EX.bob, EX.hasChild, EX.kim), (EX.kim, RDF.type, EX.Alive)]
        plain, b1 = engine.extend(extras, be.closure_triples, be.closure_contains)
        batched, b2 = engine.extend(extras, be.closure_triples, be.closure_contains,
                                    store_join=be.join)
        assert plain.triples == batched.triples and b1 == b2
        assert (EX.bob, EX.hasRelative, EX.kim) in batched
        assert (EX.bob, RDF.type, EX.Kin) in batched
        assert (EX.kim, RDF.type, EX.Agent) in batched

    def test_mixed_new_and_store_premises(self):
        # cax-sco needs (C1 subClassOf C2) from the store and (x type C1) from
        # new, and also the reverse split when the subclass triple is new.
        be = MemoryBackend(tweety_graph(), regime=RDFS_REGIME)
        engine = ClosureEngine(RDFS_REGIME)
        new, _ = engine.extend([(EX.x, RDF.type, EX.Bird)], be.closure_triples,
                               be.closure_contains, store_join=be.join)
        assert (EX.x, RDF.type, EX.Thing) in new
        new, _ = engine.extend([(EX.Thing, RDFS.subClassOf, EX.Entity)], be.closure_triples,
                               be.closure_contains, store_join=be.join)
        assert (EX.tweety, RDF.type, EX.Entity) in new
        new, _ = engine.extend([(EX.y, RDF.type, EX.Q), (EX.Q, RDFS.subClassOf, EX.R)],
                               be.closure_triples, be.closure_contains, store_join=be.join)
        assert (EX.y, RDF.type, EX.R) in new  # both premises new

    def test_regime_base_uses_join_by_default(self, regime_base):
        assert regime_base.batched
        r = NMMSReasoner(regime_base)
        seq = regime_base.sequent(["<ex:bob ex:hasChild ex:kim>"], ["<ex:kim a ex:Person>"])
        assert r.derives_sequent(seq).derivable
        regime_base.batched = False
        regime_base._extras_cache.clear()
        assert r.derives_sequent(seq).derivable
