"""Tests for pynmms.onto.base -- OntoMaterialBase and CommitmentStore."""

import tempfile
from pathlib import Path

import pytest

from pynmms.onto.base import (
    CommitmentStore,
    OntoMaterialBase,
    _validate_onto_atomic,
)

# -------------------------------------------------------------------
# OntoMaterialBase construction and validation
# -------------------------------------------------------------------


class TestOntoMaterialBaseConstruction:
    def test_empty_base(self):
        base = OntoMaterialBase()
        assert base.language == frozenset()
        assert base.consequences == frozenset()
        assert base.individuals == frozenset()
        assert base.concepts == frozenset()
        assert base.roles == frozenset()

    def test_with_concept_assertions(self):
        base = OntoMaterialBase(language={"Happy(alice)", "Sad(bob)"})
        assert "Happy(alice)" in base.language
        assert base.individuals == frozenset({"alice", "bob"})
        assert base.concepts == frozenset({"Happy", "Sad"})

    def test_with_role_assertions(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        assert base.individuals == frozenset({"alice", "bob"})
        assert base.roles == frozenset({"hasChild"})

    def test_rejects_bare_atoms(self):
        with pytest.raises(ValueError, match="not valid in NMMS_Onto"):
            OntoMaterialBase(language={"A", "B"})

    def test_with_consequences(self):
        base = OntoMaterialBase(
            language={"Happy(alice)", "Sad(alice)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Sad(alice)"})),
            },
        )
        assert len(base.consequences) == 1

    def test_rejects_negation_in_language(self):
        with pytest.raises(ValueError, match="not valid in NMMS_Onto"):
            OntoMaterialBase(language={"~A"})

    def test_rejects_conjunction_in_consequence(self):
        with pytest.raises(ValueError, match="not valid in NMMS_Onto"):
            OntoMaterialBase(
                consequences={
                    (frozenset({"P(a) & Q(a)"}), frozenset({"R(a)"})),
                },
            )


class TestOntoMaterialBaseValidateAtomic:
    def test_concept_assertion_ok(self):
        _validate_onto_atomic("Happy(alice)", "test")  # no error

    def test_role_assertion_ok(self):
        _validate_onto_atomic("hasChild(alice,bob)", "test")

    def test_bare_atom_rejected(self):
        with pytest.raises(ValueError, match="not valid in NMMS_Onto"):
            _validate_onto_atomic("A", "test")

    def test_negation_rejected(self):
        with pytest.raises(ValueError):
            _validate_onto_atomic("~A", "test")


# -------------------------------------------------------------------
# Mutation
# -------------------------------------------------------------------


class TestOntoMaterialBaseMutation:
    def test_add_atom_concept(self):
        base = OntoMaterialBase()
        base.add_atom("Happy(alice)")
        assert "Happy(alice)" in base.language
        assert "alice" in base.individuals
        assert "Happy" in base.concepts

    def test_add_atom_role(self):
        base = OntoMaterialBase()
        base.add_atom("hasChild(alice,bob)")
        assert "hasChild" in base.roles

    def test_add_consequence(self):
        base = OntoMaterialBase()
        base.add_consequence(
            frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})
        )
        assert len(base.consequences) == 1
        assert "alice" in base.individuals

    def test_add_individual(self):
        base = OntoMaterialBase()
        base.add_individual("hasChild", "alice", "bob")
        assert "hasChild(alice,bob)" in base.language
        assert "hasChild" in base.roles

    def test_add_atom_rejects_complex(self):
        base = OntoMaterialBase()
        with pytest.raises(ValueError):
            base.add_atom("~Happy(alice)")

    def test_add_consequence_rejects_complex(self):
        base = OntoMaterialBase()
        with pytest.raises(ValueError):
            base.add_consequence(frozenset({"P(a) -> Q(a)"}), frozenset({"R(a)"}))


# -------------------------------------------------------------------
# Axiom checking
# -------------------------------------------------------------------


class TestOntoMaterialBaseIsAxiom:
    def test_containment(self):
        base = OntoMaterialBase(language={"Happy(alice)"})
        assert base.is_axiom(
            frozenset({"Happy(alice)"}), frozenset({"Happy(alice)"})
        )

    def test_explicit_consequence(self):
        base = OntoMaterialBase(
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        assert base.is_axiom(
            frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})
        )

    def test_no_weakening(self):
        """Extra premises defeat the axiom match."""
        base = OntoMaterialBase(
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        assert not base.is_axiom(
            frozenset({"Happy(alice)", "Sad(alice)"}),
            frozenset({"Good(alice)"}),
        )

    def test_onto_subclass(self):
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        assert base.is_axiom(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_onto_range(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Person(bob)"}),
        )

    def test_onto_domain(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_domain("hasChild", "Parent")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Parent(alice)"}),
        )

    def test_onto_subproperty(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )

    def test_onto_no_weakening(self):
        """Extra premises defeat Onto schema match."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        assert not base.is_axiom(
            frozenset({"Man(socrates)", "Extra(x)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_onto_joint_commitment(self):
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert base.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_onto_joint_commitment_no_weakening(self):
        base = OntoMaterialBase(
            language={
                "ChestPain(patient)",
                "ElevatedTroponin(patient)",
                "Extra(patient)",
            },
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert not base.is_axiom(
            frozenset({
                "ChestPain(patient)",
                "ElevatedTroponin(patient)",
                "Extra(patient)",
            }),
            frozenset({"MI(patient)"}),
        )

    def test_no_match(self):
        base = OntoMaterialBase(language={"P(a)"})
        assert not base.is_axiom(frozenset({"P(a)"}), frozenset({"Q(a)"}))


# -------------------------------------------------------------------
# Serialization
# -------------------------------------------------------------------


class TestOntoMaterialBaseSerialization:
    def test_to_dict_and_back(self):
        base = OntoMaterialBase(
            language={"Happy(alice)", "hasChild(alice,bob)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        base.register_subclass("Man", "Mortal")

        d = base.to_dict()
        assert "onto_schemas" in d
        assert len(d["onto_schemas"]) == 1

        restored = OntoMaterialBase.from_dict(d)
        assert restored.language == base.language
        assert restored.consequences == base.consequences
        assert len(restored._onto_schemas) == 1

    def test_disjoint_with_round_trip(self):
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(socrates)"})
        base.register_disjoint("Man", "Woman", annotation="Men and women are disjoint")

        d = base.to_dict()
        assert len(d["onto_schemas"]) == 1
        assert d["onto_schemas"][0]["type"] == "disjointWith"
        assert d["onto_schemas"][0]["annotation"] == "Men and women are disjoint"

        restored = OntoMaterialBase.from_dict(d)
        assert len(restored._onto_schemas) == 1
        assert restored.is_axiom(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset(),
        )

    def test_disjoint_properties_round_trip(self):
        base = OntoMaterialBase(
            language={"hasChild(alice,bob)", "hasParent(alice,bob)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")

        d = base.to_dict()
        assert len(d["onto_schemas"]) == 1
        assert d["onto_schemas"][0]["type"] == "disjointProperties"

        restored = OntoMaterialBase.from_dict(d)
        assert restored.is_axiom(
            frozenset({"hasChild(alice,bob)", "hasParent(alice,bob)"}),
            frozenset(),
        )

    def test_joint_commitment_round_trip(self):
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(
            ["ChestPain", "ElevatedTroponin"], "MI",
            annotation="Chest pain plus troponin implies MI",
        )

        d = base.to_dict()
        assert len(d["onto_schemas"]) == 1
        assert d["onto_schemas"][0]["type"] == "jointCommitment"
        assert d["onto_schemas"][0]["arg1"] == ["ChestPain", "ElevatedTroponin"]
        assert d["onto_schemas"][0]["arg2"] == "MI"
        assert d["onto_schemas"][0]["annotation"] == "Chest pain plus troponin implies MI"

        restored = OntoMaterialBase.from_dict(d)
        assert len(restored._onto_schemas) == 1
        assert restored.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_joint_commitment_json_arg1_is_list(self):
        """JSON serialization emits arg1 as a list, not comma-separated string."""
        base = OntoMaterialBase()
        base.register_joint_commitment(["A", "B", "C"], "D")
        d = base.to_dict()
        assert isinstance(d["onto_schemas"][0]["arg1"], list)
        assert d["onto_schemas"][0]["arg1"] == ["A", "B", "C"]

    def test_to_file_and_back(self):
        base = OntoMaterialBase(
            language={"Happy(alice)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        base.register_range("hasChild", "Person")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            base.to_file(path)
            restored = OntoMaterialBase.from_file(path)
            assert restored.language == base.language
            assert restored.consequences == base.consequences
            assert len(restored._onto_schemas) == 1
        finally:
            Path(path).unlink()


# -------------------------------------------------------------------
# CommitmentStore
# -------------------------------------------------------------------


class TestCommitmentStore:
    def test_empty(self):
        cs = CommitmentStore()
        assert len(cs.assertions) == 0
        assert len(cs._onto_commitments) == 0

    def test_add_assertion(self):
        cs = CommitmentStore()
        cs.add_assertion("Happy(alice)")
        assert "Happy(alice)" in cs.assertions

    def test_add_role(self):
        cs = CommitmentStore()
        cs.add_role("hasChild", "alice", "bob")
        assert "hasChild(alice,bob)" in cs.assertions

    def test_add_concept(self):
        cs = CommitmentStore()
        cs.add_concept("Happy", "alice")
        assert "Happy(alice)" in cs.assertions

    def test_commit_subclass(self):
        cs = CommitmentStore()
        cs.commit_subclass("man_mortal", "Man", "Mortal")
        assert len(cs._onto_commitments) == 1
        assert cs._onto_commitments[0][:4] == ("man_mortal", "subClassOf", "Man", "Mortal")

    def test_commit_range(self):
        cs = CommitmentStore()
        cs.commit_range("child_person", "hasChild", "Person")
        assert len(cs._onto_commitments) == 1

    def test_commit_domain(self):
        cs = CommitmentStore()
        cs.commit_domain("child_parent", "hasChild", "Parent")
        assert len(cs._onto_commitments) == 1

    def test_commit_subproperty(self):
        cs = CommitmentStore()
        cs.commit_subproperty("child_desc", "hasChild", "hasDescendant")
        assert len(cs._onto_commitments) == 1

    def test_commit_disjoint(self):
        cs = CommitmentStore()
        cs.commit_disjoint("man_woman", "Man", "Woman")
        assert len(cs._onto_commitments) == 1
        assert cs._onto_commitments[0][:4] == ("man_woman", "disjointWith", "Man", "Woman")

    def test_commit_disjoint_properties(self):
        cs = CommitmentStore()
        cs.commit_disjoint_properties("child_parent", "hasChild", "hasParent")
        assert len(cs._onto_commitments) == 1
        assert cs._onto_commitments[0][:4] == (
            "child_parent", "disjointProperties", "hasChild", "hasParent",
        )

    def test_compile_with_disjoint_schema(self):
        cs = CommitmentStore()
        cs.add_assertion("Man(socrates)")
        cs.add_assertion("Woman(socrates)")
        cs.commit_disjoint("man_woman", "Man", "Woman")
        base = cs.compile()
        assert base.is_axiom(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset(),
        )

    def test_compile_with_disjoint_properties_schema(self):
        cs = CommitmentStore()
        cs.add_assertion("hasChild(alice,bob)")
        cs.add_assertion("hasParent(alice,bob)")
        cs.commit_disjoint_properties("child_parent", "hasChild", "hasParent")
        base = cs.compile()
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)", "hasParent(alice,bob)"}),
            frozenset(),
        )

    def test_describe_disjoint(self):
        cs = CommitmentStore()
        cs.commit_disjoint("test", "Man", "Woman")
        desc = cs.describe()
        assert "disjointWith" in desc
        assert "Man(x), Woman(x) |~" in desc

    def test_describe_disjoint_properties(self):
        cs = CommitmentStore()
        cs.commit_disjoint_properties("test", "hasChild", "hasParent")
        desc = cs.describe()
        assert "disjointProperties" in desc
        assert "hasChild(x,y), hasParent(x,y) |~" in desc

    def test_commit_defeasible_rule(self):
        cs = CommitmentStore()
        cs.commit_defeasible_rule(
            "bob's happiness",
            frozenset({"Happy(bob)"}),
            frozenset({"Good(bob)"}),
        )
        base = cs.compile()
        assert base.is_axiom(
            frozenset({"Happy(bob)"}), frozenset({"Good(bob)"})
        )

    def test_retract_schema(self):
        cs = CommitmentStore()
        cs.commit_subclass("man_mortal", "Man", "Mortal")
        assert len(cs._onto_commitments) == 1
        cs.retract_schema("man_mortal")
        assert len(cs._onto_commitments) == 0

    def test_compile_produces_base(self):
        cs = CommitmentStore()
        cs.add_assertion("Man(socrates)")
        cs.commit_subclass("man_mortal", "Man", "Mortal")
        base = cs.compile()
        assert isinstance(base, OntoMaterialBase)
        assert "Man(socrates)" in base.language

    def test_compile_caches(self):
        cs = CommitmentStore()
        cs.add_assertion("P(a)")
        base1 = cs.compile()
        base2 = cs.compile()
        assert base1 is base2

    def test_compile_invalidated_by_assertion(self):
        cs = CommitmentStore()
        cs.add_assertion("P(a)")
        base1 = cs.compile()
        cs.add_assertion("Q(a)")
        base2 = cs.compile()
        assert base1 is not base2

    def test_compile_with_subclass_schema(self):
        cs = CommitmentStore()
        cs.add_assertion("Man(socrates)")
        cs.commit_subclass("man_mortal", "Man", "Mortal")
        base = cs.compile()
        assert base.is_axiom(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_describe(self):
        cs = CommitmentStore()
        cs.add_assertion("Happy(alice)")
        cs.commit_subclass("test", "Man", "Mortal")
        desc = cs.describe()
        assert "Happy(alice)" in desc
        assert "test" in desc
        assert "subClassOf" in desc

    def test_commit_joint_commitment(self):
        cs = CommitmentStore()
        cs.commit_joint_commitment("mi_rule", ["ChestPain", "ElevatedTroponin"], "MI")
        assert len(cs._onto_commitments) == 1
        assert cs._onto_commitments[0][:4] == (
            "mi_rule", "jointCommitment", "ChestPain,ElevatedTroponin", "MI",
        )

    def test_commit_joint_commitment_minimum_two(self):
        cs = CommitmentStore()
        with pytest.raises(ValueError, match="at least 2"):
            cs.commit_joint_commitment("bad", ["OnlyOne"], "D")

    def test_compile_with_joint_commitment_schema(self):
        cs = CommitmentStore()
        cs.add_assertion("ChestPain(patient)")
        cs.add_assertion("ElevatedTroponin(patient)")
        cs.commit_joint_commitment("mi_rule", ["ChestPain", "ElevatedTroponin"], "MI")
        base = cs.compile()
        assert base.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_describe_joint_commitment(self):
        cs = CommitmentStore()
        cs.commit_joint_commitment("mi_rule", ["ChestPain", "ElevatedTroponin"], "MI")
        desc = cs.describe()
        assert "jointCommitment" in desc
        assert "ChestPain(x)" in desc
        assert "ElevatedTroponin(x)" in desc
        assert "MI(x)" in desc

    def test_rejects_complex_assertion(self):
        cs = CommitmentStore()
        with pytest.raises(ValueError):
            cs.add_assertion("~Happy(alice)")
