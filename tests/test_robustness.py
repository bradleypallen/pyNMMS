"""Tests for pynmms.robustness and robust entries in MaterialBase."""

import pytest

from pynmms import MaterialBase, NMMSReasoner
from pynmms.robustness import (
    EXACT,
    MONOTONE,
    Robustness,
    guarded,
    split_robustness_clause,
)

F = frozenset


class TestRobustness:
    def test_kinds_and_normalisation(self):
        assert EXACT.is_exact and not MONOTONE.is_exact
        assert guarded() == MONOTONE  # no defeaters -> monotone
        g = guarded(["Penguin", "Dead"])
        assert g.kind == "guarded" and g.left == {"Penguin", "Dead"} and not g.right

    def test_invalid(self):
        with pytest.raises(ValueError):
            Robustness("fuzzy")
        with pytest.raises(ValueError):
            Robustness("exact", left=F({"x"}))

    def test_allows(self):
        assert not EXACT.allows(F({"a"}), F({"b"}))
        assert MONOTONE.allows(F({"a", "z"}), F({"b"}))
        g = guarded(["x"], ["y"])
        assert g.allows(F({"a"}), F({"b"}))
        assert not g.allows(F({"a", "x"}), F({"b"}))
        assert not g.allows(F({"a"}), F({"b", "y"}))
        assert g.defeated_by(F({"a", "x"}), F({"y"})) == {"x", "y"}

    def test_json_round_trip(self):
        for r in (EXACT, MONOTONE, guarded(["p"]), guarded(["p"], ["q"])):
            assert Robustness.from_json(r.to_json()) == r
        assert Robustness.from_json(None) == EXACT
        assert Robustness.from_json("monotone") == MONOTONE

    def test_str(self):
        assert str(EXACT) == "exact"
        assert str(MONOTONE) == "monotone"
        assert str(guarded(["b", "a"])) == "unless a, b"
        assert str(guarded(["a"], ["c"])) == "unless a |~ c"


class TestClauseParsing:
    def test_no_clause(self):
        assert split_robustness_clause("A, B |~ C") == ("A, B |~ C", EXACT)

    def test_unless(self):
        text, rob = split_robustness_clause("A, B |~ C unless X, Y")
        assert text == "A, B |~ C" and rob == guarded(["X", "Y"])

    def test_monotone(self):
        assert split_robustness_clause("A |~ B monotone") == ("A |~ B", MONOTONE)

    def test_keyword_inside_atom_is_not_a_clause(self):
        text, rob = split_robustness_clause("<unless it rains> |~ dry")
        assert text == "<unless it rains> |~ dry" and rob == EXACT
        text, rob = split_robustness_clause("unlessness |~ monotonely")
        assert rob == EXACT

    def test_unless_without_defeaters(self):
        with pytest.raises(ValueError):
            split_robustness_clause("A |~ B unless")

    def test_schema_line(self):
        text, rob = split_robustness_clause("schema subClassOf Bird Flies unless Penguin, Dead")
        assert text == "schema subClassOf Bird Flies" and rob == guarded(["Penguin", "Dead"])


class TestRobustEntries:
    def test_exact_is_default_and_defeated_by_anything(self):
        base = MaterialBase(consequences={(F({"Bird"}), F({"Flies"}))})
        assert base.is_axiom(F({"Bird"}), F({"Flies"}))
        assert not base.is_axiom(F({"Bird", "Tall"}), F({"Flies"}))
        assert base.robustness_of(F({"Bird"}), F({"Flies"})) == EXACT

    def test_monotone_survives_additions_on_both_sides(self):
        base = MaterialBase()
        base.add_consequence(F({"Bird"}), F({"Flies"}), robustness=MONOTONE)
        assert base.is_axiom(F({"Bird", "Tall", "Old"}), F({"Flies", "Sings"}))
        assert not base.is_axiom(F({"Tall"}), F({"Flies"}))

    def test_guarded_relevant_defeat(self):
        base = MaterialBase()
        base.add_consequence(F({"Bird"}), F({"Flies"}), robustness=guarded(["Penguin"]))
        assert base.is_axiom(F({"Bird"}), F({"Flies"}))
        assert base.is_axiom(F({"Bird", "Tall"}), F({"Flies"}))
        assert not base.is_axiom(F({"Bird", "Penguin"}), F({"Flies"}))

    def test_guarded_right_side_defeater(self):
        base = MaterialBase()
        base.add_consequence(F({"a"}), F({"b"}), robustness=guarded([], ["c"]))
        assert base.is_axiom(F({"a"}), F({"b", "d"}))
        assert not base.is_axiom(F({"a"}), F({"b", "c"}))

    def test_empty_consequent_monotone_entry(self):
        # An incoherent set stays incoherent under additions, and (by
        # succedent monotonicity) implies anything.
        base = MaterialBase()
        base.add_consequence(F({"Alive", "Dead"}), F(), robustness=MONOTONE)
        assert base.is_axiom(F({"Alive", "Dead", "Tall"}), F())
        assert base.is_axiom(F({"Alive", "Dead"}), F({"anything"}))
        assert not base.is_axiom(F({"Alive"}), F())

    def test_policy_can_be_replaced(self):
        base = MaterialBase()
        base.add_consequence(F({"a"}), F({"b"}))
        assert not base.is_axiom(F({"a", "z"}), F({"b"}))
        base.add_consequence(F({"a"}), F({"b"}), robustness=MONOTONE)
        assert base.is_axiom(F({"a", "z"}), F({"b"}))
        assert len(base.consequences) == 1
        base.add_consequence(F({"a"}), F({"b"}), robustness=EXACT)
        assert not base.is_axiom(F({"a", "z"}), F({"b"}))

    def test_large_antecedent_flat(self):
        base = MaterialBase()
        base.add_consequence(F({"Bird"}), F({"Flies"}), robustness=guarded(["Penguin"]))
        big = F(f"p{i}" for i in range(100_000)) | {"Bird"}
        r = NMMSReasoner(base)
        assert r.derives(big, F({"Flies"})).derivable
        assert not r.derives(big | {"Penguin"}, F({"Flies"})).derivable

    def test_serialization_round_trip(self):
        base = MaterialBase()
        base.add_consequence(F({"a"}), F({"b"}))
        base.add_consequence(F({"c"}), F({"d"}), robustness=MONOTONE)
        base.add_consequence(F({"e"}), F({"f"}), robustness=guarded(["x"], ["y"]))
        d = base.to_dict()
        kinds = {tuple(e["antecedent"]): e["robustness"]["kind"] for e in d["consequences"]}
        assert kinds == {("a",): "exact", ("c",): "monotone", ("e",): "guarded"}
        restored = MaterialBase.from_dict(d)
        assert restored.robustness_of(F({"e"}), F({"f"})) == guarded(["x"], ["y"])
        assert restored.is_axiom(F({"c", "z"}), F({"d"}))
        assert not restored.is_axiom(F({"a", "z"}), F({"b"}))
        assert restored == base

    def test_reasoner_with_logic_over_guarded_entry(self):
        base = MaterialBase()
        base.add_consequence(F({"Bird"}), F({"Flies"}), robustness=guarded(["Penguin"]))
        r = NMMSReasoner(base)
        assert r.derives(F({"Bird", "Tall"}), F({"Flies | Swims"})).derivable
        assert r.derives(F({"Bird"}), F({"Penguin -> Flies"})).derivable is False
        assert r.derives(F({"Bird"}), F({"~Penguin -> Flies"})).derivable


class TestExclusions:
    def test_conjunctive_defeater(self):
        base = MaterialBase()
        base.add_consequence(F({"Bird"}), F({"Flies"}),
                             robustness=guarded(exclusions=[(F({"Penguin", "Injured"}), F())]))
        assert base.is_axiom(F({"Bird", "Penguin"}), F({"Flies"}))
        assert base.is_axiom(F({"Bird", "Injured"}), F({"Flies"}))
        assert not base.is_axiom(F({"Bird", "Penguin", "Injured"}), F({"Flies"}))

    def test_pair_across_sides(self):
        base = MaterialBase()
        base.add_consequence(F({"a"}), F({"b"}),
                             robustness=guarded(exclusions=[(F({"x"}), F({"y"}))]))
        assert base.is_axiom(F({"a", "x"}), F({"b"}))
        assert base.is_axiom(F({"a"}), F({"b", "y"}))
        assert not base.is_axiom(F({"a", "x"}), F({"b", "y"}))

    def test_singleton_pairs_fold_into_defeaters(self):
        r = guarded(exclusions=[(F({"p"}), F()), (F(), F({"q"})), (F({"m", "n"}), F())])
        assert r.left == {"p"} and r.right == {"q"} and len(r.exclusions) == 1
        assert r == guarded(["p"], ["q"], [(F({"m", "n"}), F())])

    def test_json_round_trip_and_str(self):
        r = guarded(["a"], exclusions=[(F({"m", "n"}), F()), (F({"u"}), F({"v"}))])
        assert Robustness.from_json(r.to_json()) == r
        assert r.to_json()["unless"]["pairs"][0] == {"antecedent": ["m", "n"], "consequent": []}
        assert str(r).startswith("unless a, m & n")

    def test_clause_syntax(self):
        text, rob = split_robustness_clause("Bird |~ Flies unless Penguin & Injured, Dead")
        assert text == "Bird |~ Flies"
        assert rob == guarded(["Dead"], exclusions=[(F({"Penguin", "Injured"}), F())])

    def test_cli_clause_end_to_end(self):
        from pynmms.cli.tell import _parse_tell_statement

        kind, ant, con, _ann, rob = _parse_tell_statement("A |~ B unless X & Y")
        assert rob.exclusions == {(F({"X", "Y"}), F())}


class TestSchemaExclusions:
    def test_conjunctive_concept_defeater_same_individual(self):
        from pynmms.onto.base import OntoMaterialBase

        base = OntoMaterialBase()
        base.register_subclass(
            "Bird", "Flies", robustness=guarded(exclusions=[(F({"Penguin", "Injured"}), F())])
        )
        assert base.is_axiom(F({"Bird(a)", "Penguin(a)"}), F({"Flies(a)"}))
        assert not base.is_axiom(F({"Bird(a)", "Penguin(a)", "Injured(a)"}), F({"Flies(a)"}))
        # both concepts must hold of the same individual
        assert base.is_axiom(F({"Bird(a)", "Penguin(a)", "Injured(b)"}), F({"Flies(a)"}))
        restored = OntoMaterialBase.from_dict(base.to_dict())
        assert restored.onto_schemas == base.onto_schemas
