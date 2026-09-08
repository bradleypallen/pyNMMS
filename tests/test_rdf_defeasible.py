"""Material entries as patterns (PLAN.md workstream D). Predictions first.

A DefeasibleRule is an entry ⟨A(x̄), D(x̄); E(x̄, ȳ)⟩ with variables: it fires
for a substitution σ when Aσ is derivable, no defeater Eσ has a solution
in the closure, and Dσ, elaborated by the regime, meets Δ. Defeaters are
conjunctions of patterns with optional value guards. Incompatibilities
(⊥ conclusions) count against a position only when its own triples take
part (attribution). No Cut between entries.
"""

# ruff: noqa: E402

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from pynmms import NMMSReasoner
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import Position, RegimeBase, Resolver, TripleAtom
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.defeasible import DefeasibleRule, parse_defeasible_rule

EX = Namespace("http://ex.org/")


def typed(ind: str, cls: str) -> TripleAtom:
    return TripleAtom(EX[ind], RDF.type, EX[cls])


def ontology() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
    g.add((EX.EmperorPenguin, RDFS.subClassOf, EX.Penguin))
    g.add((EX.Flies, RDFS.subClassOf, EX.Moves))
    return g


def resolver() -> Resolver:
    return Resolver(ontology())


def ask(base, antecedent, consequent, **kw) -> bool:
    return NMMSReasoner(base).derives_sequent(base.sequent(antecedent, consequent, **kw)).derivable


class TestParse:
    def test_premises_conclusion_and_alternative_defeaters(self):
        r = parse_defeasible_rule(
            "?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin ; ?x ex:injured \"yes\"",
            resolver())
        assert isinstance(r, DefeasibleRule)
        assert len(r.premises) == 1 and r.conclusion is not None
        assert len(r.defeaters) == 2 and all(len(d.patterns) == 1 for d in r.defeaters)
        assert r.robustness == "guarded"
        assert "unless" in str(r) and ";" in str(r)

    def test_monotone_false_and_guarded_defeater(self):
        r = parse_defeasible_rule("?x a ex:Bird |~ ?x a ex:HasWings monotone", resolver())
        assert r.defeaters == () and r.robustness == "monotone"
        f = parse_defeasible_rule(
            "?x ex:made ?s, ?x ex:maker ?p, ?p ex:died ?d, [year(?s) > year(?d)] |~ false "
            "unless ?x ex:posthumous \"yes\"", resolver())
        assert f.conclusion is None and f.guard_expr is not None and len(f.defeaters) == 1
        d = parse_defeasible_rule(
            "?x ex:maker ?p |~ ?x ex:madeBy ?p unless ?x ex:made ?s, ?p ex:died ?d, "
            "[year(?s) > year(?d)]", resolver())
        assert len(d.defeaters[0].patterns) == 2 and d.defeaters[0].guard_expr is not None

    def test_range_restriction_and_defeater_variables(self):
        with pytest.raises(ValueError):
            parse_defeasible_rule("?x a ex:Bird |~ ?y a ex:Flies", resolver())
        # a defeater may introduce its own variables (existential in the closure)
        r = parse_defeasible_rule(
            "?x a ex:Bird |~ ?x a ex:Flies unless ?x ex:has ?w, ?w a ex:Cast", resolver())
        assert len(r.defeaters[0].patterns) == 2


class TestFiring:
    def _base(self, *rules: str, graph: Graph | None = None) -> RegimeBase:
        b = RegimeBase(MemoryBackend(graph or ontology(), regime=RDFS_REGIME))
        for r in rules:
            b.add_rule(parse_defeasible_rule(r, resolver()))
        return b

    def test_default_fires_on_a_derived_antecedent_and_is_defeated_through_the_regime(self):
        b = self._base("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin")
        assert ask(b, [typed("tweety", "Sparrow")], [typed("tweety", "Flies")])
        assert ask(b, [typed("polly", "Bird")], [typed("polly", "Flies")])
        assert not ask(b, [typed("tweety", "Sparrow"), typed("tweety", "EmperorPenguin")],
                       [typed("tweety", "Flies")])
        assert not ask(b, [typed("nemo", "Fish")], [typed("nemo", "Flies")])
        assert not ask(b, [], [typed("tweety", "Flies")])

    def test_consequent_is_elaborated_and_entries_do_not_chain(self):
        b = self._base("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin",
                       "?x a ex:Flies |~ ?x a ex:HasWings monotone")
        assert ask(b, [typed("tweety", "Sparrow")], [typed("tweety", "Moves")])   # Flies ⊑ Moves
        assert not ask(b, [typed("tweety", "Sparrow")], [typed("tweety", "HasWings")])  # no Cut
        assert ask(b, [typed("tweety", "Flies")], [typed("tweety", "HasWings")])

    def test_a_value_guarded_defeater(self):
        g = ontology()
        g.add((EX.p, EX.died, Literal("1712-04-05")))
        b = self._base("?x ex:maker ?p |~ ?x ex:madeBy ?p unless ?x ex:made ?s, ?p ex:died ?d, "
                       "[year(?s) > year(?d)]", graph=g)
        early = [TripleAtom(EX.o, EX.maker, EX.p), TripleAtom(EX.o, EX.made, Literal("1700"))]
        assert ask(b, early, [TripleAtom(EX.o, EX.madeBy, EX.p)])
        assert not ask(b, [TripleAtom(EX.o, EX.maker, EX.p),
                           TripleAtom(EX.o, EX.made, Literal("1727"))],
                       [TripleAtom(EX.o, EX.madeBy, EX.p)])

    def test_an_incompatibility_pattern_is_attributed_to_the_position(self):
        g = ontology()
        g.add((EX.p, EX.died, Literal("1712")))
        g.add((EX.old, EX.maker, EX.p))
        g.add((EX.old, EX.made, Literal("1727")))
        b = self._base("?x ex:maker ?p, ?p ex:died ?d, ?x ex:made ?s, [year(?s) > year(?d)] "
                       "|~ false unless ?x ex:posthumous \"yes\"", graph=g)
        assert not ask(b, [], [])                                    # background only: inventory
        assert not ask(b, [typed("tweety", "Sparrow")], [])
        own = [TripleAtom(EX.o, EX.maker, EX.p), TripleAtom(EX.o, EX.made, Literal("1727"))]
        assert ask(b, own, [])                                       # its own anachronism
        assert ask(b, own, [typed("tweety", "Fish")])                # guarded: explodes
        assert not ask(b, own + [TripleAtom(EX.o, EX.posthumous, Literal("yes"))], [])
        record = Position.of(b, EX.old)
        assert not record.coherent()                                 # read aloud, it is blamed

    def test_go_style_propagation_defeated_by_a_curated_not(self):
        g = Graph()
        g.bind("ex", EX)
        g.add((EX.Y, RDFS.subClassOf, EX.X))
        g.add((EX.X, RDFS.subClassOf, EX.W))
        g.add((EX.gp, EX.involved_in, EX.Y))
        g.add((EX.gp, EX.not_involved_in, EX.X))
        g.add((EX.gq, EX.involved_in, EX.Y))
        b = self._base("?g ex:involved_in ?c, ?c rdfs:subClassOf ?d |~ ?g ex:involved_in ?d "
                       "unless ?g ex:not_involved_in ?d", graph=g)
        rec = Position.of(b, EX.gq)
        assert rec.commits_to(TripleAtom(EX.gq, EX.involved_in, EX.X))       # the default
        assert rec.commits_to(TripleAtom(EX.gq, EX.involved_in, EX.W))       # RDFS makes Y ⊑ W
        rec2 = Position.of(b, EX.gp)
        assert not rec2.commits_to(TripleAtom(EX.gp, EX.involved_in, EX.X))  # defeated by NOT
        assert rec2.commits_to(TripleAtom(EX.gp, EX.involved_in, EX.W))      # not denied: fires


class TestChallenges:
    def test_pattern_entries_yield_probes(self):
        b = RegimeBase(MemoryBackend(ontology(), regime=RDFS_REGIME))
        b.add_rule(parse_defeasible_rule("?x a ex:Bird |~ ?x a ex:Flies unless ?x a ex:Penguin",
                                         resolver()))
        b.add_rule(parse_defeasible_rule("?x a ex:Bird, ?x a ex:Grounded |~ false "
                                         "unless ?x a ex:Penguin", resolver()))
        pos = Position(b).assert_(typed("tweety", "Sparrow"))
        cs = pos.challenges()
        kinds = sorted(c.kind for c in cs)
        assert kinds == ["default", "incompatibility"]
        inc = next(c for c in cs if c.kind == "incompatibility")
        assert inc.asks == (typed("tweety", "Grounded"),)
        assert inc.rescue == (typed("tweety", "Penguin"),)
        dflt = next(c for c in cs if c.kind == "default")
        assert dflt.asks == (typed("tweety", "Flies"),)
        pos.assert_(typed("tweety", "Grounded"))
        assert pos.challenges()[0].kind == "refutation"
