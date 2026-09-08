"""The ontology extension as a surface syntax for pattern entries. Predictions first.

Each NMMS_Onto schema with its robustness policy compiles to one
DefeasibleRule over rdf:type and role triples; guarded defeater concepts
become pattern defeaters on the matched individuals, conjunctive exclusions
become conjunctions, and exact schemas (any addition defeats) have no
pattern counterpart and are compiled as monotone with a note.
"""

# ruff: noqa: E402

from __future__ import annotations

import random

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Namespace
from rdflib.namespace import RDF

from pynmms import NMMSReasoner
from pynmms.onto.base import OntoMaterialBase
from pynmms.rdf import SIMPLE, RegimeBase
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.convert import atom_to_triple, install_onto, onto_to_defeasible
from pynmms.rdf.rules import Var
from pynmms.robustness import EXACT, MONOTONE, Robustness, guarded

NS = Namespace("http://pynmms.dev/onto/")


def _onto() -> OntoMaterialBase:
    b = OntoMaterialBase()
    b.register_subclass("Bird", "Flies", robustness=guarded(["Penguin"]))
    b.register_subclass("Sparrow", "Bird", robustness=MONOTONE)
    b.register_range("hasPet", "Animal", robustness=guarded(["Robot"]))
    b.register_domain("hasPet", "Person", robustness=MONOTONE)
    b.register_subproperty("hasDog", "hasPet", robustness=MONOTONE)
    b.register_disjoint("Alive", "Dead", robustness=guarded(["Zombie"]))
    b.register_disjoint_properties("loves", "hates", robustness=MONOTONE)
    b.register_joint_commitment(["Student", "Employed"], "Busy", robustness=MONOTONE)
    b.register_subclass("Man", "Mortal", robustness=EXACT)
    b.add_consequence(frozenset({"Cat(tom)"}), frozenset({"Purrs(tom)"}),
                      robustness=Robustness("guarded", frozenset({"Angry(tom)"})))
    return b


class TestTranslation:
    def test_every_schema_type_becomes_one_rule(self):
        rules = onto_to_defeasible(_onto())
        by_name = {r.name: r for r in rules}
        assert len(rules) == 9
        r = by_name["subClassOf:Bird->Flies"]
        assert r.premises == ((Var("x"), RDF.type, NS.Bird),)
        assert r.conclusion == (Var("x"), RDF.type, NS.Flies)
        assert r.defeaters[0].patterns == ((Var("x"), RDF.type, NS.Penguin),)
        assert str(r).endswith("unless ?x http://www.w3.org/1999/02/22-rdf-syntax-ns#type "
                               "http://pynmms.dev/onto/Penguin")
        rng = by_name["range:hasPet->Animal"]
        assert len(rng.defeaters) == 2                      # Robot on x, or on y
        assert str(by_name["disjointWith:Alive/Dead"]).endswith(
            "|~ false unless ?x http://www.w3.org/1999/02/22-rdf-syntax-ns#type "
            "http://pynmms.dev/onto/Zombie")
        assert by_name["disjointProperties:loves/hates"].is_incompatibility
        assert len(by_name["jointCommitment:Student,Employed->Busy"].premises) == 2
        assert by_name["subPropertyOf:hasDog->hasPet"].robustness == "monotone"
        assert by_name["subClassOf:Man->Mortal"].robustness == "monotone"   # exact: no counterpart

    def test_conjunctive_exclusions_become_conjunctions(self):
        b = OntoMaterialBase()
        b.register_subclass("Bird", "Flies",
                            robustness=Robustness("guarded", exclusions=frozenset(
                                {(frozenset({"Injured", "Wing"}), frozenset())})))
        (r,) = onto_to_defeasible(b)
        assert len(r.defeaters) == 1 and len(r.defeaters[0].patterns) == 2

    def test_install_adds_rules_and_ground_entries(self):
        rb = RegimeBase(MemoryBackend(Graph(), regime=SIMPLE))
        n_rules, n_entries = install_onto(rb, _onto())
        assert (n_rules, n_entries) == (9, 1)
        r = NMMSReasoner(rb)
        q = lambda a, c: r.derives_sequent(rb.sequent(a, c, include_graph=False)).derivable  # noqa: E731
        bird, flies, penguin = (atom_to_triple(f"{c}(tweety)")
                                for c in ("Bird", "Flies", "Penguin"))
        assert q([bird], [flies]) and not q([bird, penguin], [flies])
        assert q([atom_to_triple("Cat(tom)")], [atom_to_triple("Purrs(tom)")])
        assert not q([atom_to_triple("Cat(tom)"), atom_to_triple("Angry(tom)")],
                     [atom_to_triple("Purrs(tom)")])
        assert q([atom_to_triple("Alive(z)"), atom_to_triple("Dead(z)")], [])
        assert not q([atom_to_triple("Alive(z)"), atom_to_triple("Dead(z)"),
                      atom_to_triple("Zombie(z)")], [])


class TestDifferential:
    """NMMS_Onto and its compiled pattern entries agree on atomic sequents."""

    CONCEPTS = ["A", "B", "C", "D", "E"]
    ROLES = ["r", "s"]
    INDS = ["a", "b"]

    def _random_onto(self, rnd: random.Random) -> OntoMaterialBase:
        b = OntoMaterialBase()
        for _ in range(rnd.randint(1, 4)):
            rob = rnd.choice([MONOTONE, guarded([rnd.choice(self.CONCEPTS)])])
            kind = rnd.choice(["sub", "range", "domain", "subprop", "disjoint", "joint"])
            c1, c2, c3 = rnd.sample(self.CONCEPTS, 3)
            r1, r2 = rnd.sample(self.ROLES, 2)
            if kind == "sub":
                b.register_subclass(c1, c2, robustness=rob)
            elif kind == "range":
                b.register_range(r1, c1, robustness=rob)
            elif kind == "domain":
                b.register_domain(r1, c1, robustness=rob)
            elif kind == "subprop":
                b.register_subproperty(r1, r2, robustness=rob)
            elif kind == "disjoint":
                b.register_disjoint(c1, c2, robustness=rob)
            else:
                b.register_joint_commitment([c1, c2], c3, robustness=rob)
        return b

    def _random_atoms(self, rnd: random.Random, n: int) -> list[str]:
        out = []
        for _ in range(n):
            if rnd.random() < 0.7:
                out.append(f"{rnd.choice(self.CONCEPTS)}({rnd.choice(self.INDS)})")
            else:
                out.append(f"{rnd.choice(self.ROLES)}({rnd.choice(self.INDS)},"
                           f"{rnd.choice(self.INDS)})")
        return out

    def test_agreement_up_to_explosion(self):
        rnd = random.Random(4)
        agreed = explosions = 0
        for _ in range(300):
            onto = self._random_onto(rnd)
            rb = RegimeBase(MemoryBackend(Graph(), regime=SIMPLE))
            install_onto(rb, onto)
            reasoner = NMMSReasoner(rb)
            for _ in range(5):
                gamma = self._random_atoms(rnd, rnd.randint(1, 3))
                delta = self._random_atoms(rnd, rnd.randint(0, 1))
                left = onto.is_axiom(frozenset(gamma), frozenset(delta))
                right = reasoner.derives_sequent(rb.sequent(
                    [atom_to_triple(a) for a in gamma], [atom_to_triple(a) for a in delta],
                    include_graph=False)).derivable
                if left == right:
                    agreed += 1
                    continue
                # The one licensed difference: NMMS_Onto's incompatibility schemas never
                # explode, while a monotone or guarded pattern incompatibility does.
                assert right and not left and delta, (gamma, delta, onto.onto_schemas)
                assert onto.is_axiom(frozenset(gamma), frozenset())
                explosions += 1
        assert agreed > 1000 and explosions >= 0


class TestCLI:
    def test_onto_and_entries_flags(self, tmp_path, capsys):
        from pynmms.cli.main import main

        onto = _onto()
        onto_path = tmp_path / "onto.json"
        onto.to_file(onto_path)
        g = tmp_path / "g.ttl"
        g.write_text("@prefix onto: <http://pynmms.dev/onto/> .\n"
                     "onto:tweety a onto:Sparrow .\nonto:opus a onto:Sparrow, onto:Penguin .\n")
        entries = tmp_path / "entries.txt"
        entries.write_text("?x a onto:Flies |~ ?x a onto:HasWings monotone\n")
        args = ["rdf", "ask", "-g", str(g), "--regime", "simple", "--onto", str(onto_path),
                "--entries", str(entries), "--prefix", "onto=http://pynmms.dev/onto/"]
        # Sparrow -> Bird and Bird -> Flies are entries, and entries do not chain, so a
        # sparrow is a bird but not, without asserting Bird, a flier.
        assert main(args + ["<onto:tweety a onto:Flies>"]) == 2
        assert main(args + ["<onto:tweety a onto:Bird>"]) == 0
        assert main(args + ["<onto:opus a onto:Bird>"]) == 0
        assert main(args + ["<onto:opus a onto:Bird> -> <onto:opus a onto:Flies>"]) == 2  # penguin
        assert main(args + ["<onto:tweety a onto:Bird> -> <onto:tweety a onto:Flies>"]) == 0
        assert main(args + ["<onto:tweety a onto:Flies> -> <onto:tweety a onto:HasWings>"]) == 0
