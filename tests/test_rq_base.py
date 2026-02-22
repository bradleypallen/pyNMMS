"""Tests for pynmms.rq.base — RQMaterialBase and CommitmentStore."""

import tempfile
from pathlib import Path

import pytest

from pynmms.rq.base import (
    CommitmentStore,
    InferenceSchema,
    RQMaterialBase,
    _validate_rq_atomic,
)

# -------------------------------------------------------------------
# RQMaterialBase construction and validation
# -------------------------------------------------------------------


class TestRQMaterialBaseConstruction:
    def test_empty_base(self):
        base = RQMaterialBase()
        assert base.language == frozenset()
        assert base.consequences == frozenset()
        assert base.individuals == frozenset()
        assert base.concepts == frozenset()
        assert base.roles == frozenset()

    def test_with_concept_assertions(self):
        base = RQMaterialBase(language={"Happy(alice)", "Sad(bob)"})
        assert "Happy(alice)" in base.language
        assert base.individuals == frozenset({"alice", "bob"})
        assert base.concepts == frozenset({"Happy", "Sad"})

    def test_with_role_assertions(self):
        base = RQMaterialBase(language={"hasChild(alice,bob)"})
        assert base.individuals == frozenset({"alice", "bob"})
        assert base.roles == frozenset({"hasChild"})

    def test_with_bare_atoms(self):
        base = RQMaterialBase(language={"A", "B"})
        assert "A" in base.language
        assert base.individuals == frozenset()

    def test_with_consequences(self):
        base = RQMaterialBase(
            language={"Happy(alice)", "Sad(alice)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Sad(alice)"})),
            },
        )
        assert len(base.consequences) == 1

    def test_rejects_quantifier_in_language(self):
        with pytest.raises(ValueError, match="logically complex"):
            RQMaterialBase(language={"ALL hasChild.Happy(alice)"})

    def test_rejects_negation_in_language(self):
        with pytest.raises(ValueError, match="logically complex"):
            RQMaterialBase(language={"~A"})

    def test_rejects_conjunction_in_consequence(self):
        with pytest.raises(ValueError, match="logically complex"):
            RQMaterialBase(
                consequences={
                    (frozenset({"A & B"}), frozenset({"C"})),
                },
            )


class TestRQMaterialBaseValidateAtomic:
    def test_concept_assertion_ok(self):
        _validate_rq_atomic("Happy(alice)", "test")  # no error

    def test_role_assertion_ok(self):
        _validate_rq_atomic("hasChild(alice,bob)", "test")

    def test_bare_atom_ok(self):
        _validate_rq_atomic("A", "test")

    def test_quantifier_rejected(self):
        with pytest.raises(ValueError):
            _validate_rq_atomic("ALL hasChild.Happy(alice)", "test")

    def test_negation_rejected(self):
        with pytest.raises(ValueError):
            _validate_rq_atomic("~A", "test")


# -------------------------------------------------------------------
# Mutation
# -------------------------------------------------------------------


class TestRQMaterialBaseMutation:
    def test_add_atom_concept(self):
        base = RQMaterialBase()
        base.add_atom("Happy(alice)")
        assert "Happy(alice)" in base.language
        assert "alice" in base.individuals
        assert "Happy" in base.concepts

    def test_add_atom_role(self):
        base = RQMaterialBase()
        base.add_atom("hasChild(alice,bob)")
        assert "hasChild" in base.roles

    def test_add_consequence(self):
        base = RQMaterialBase()
        base.add_consequence(
            frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})
        )
        assert len(base.consequences) == 1
        assert "alice" in base.individuals

    def test_add_individual(self):
        base = RQMaterialBase()
        base.add_individual("hasChild", "alice", "bob")
        assert "hasChild(alice,bob)" in base.language
        assert "hasChild" in base.roles

    def test_add_atom_rejects_complex(self):
        base = RQMaterialBase()
        with pytest.raises(ValueError):
            base.add_atom("~A")

    def test_add_consequence_rejects_complex(self):
        base = RQMaterialBase()
        with pytest.raises(ValueError):
            base.add_consequence(frozenset({"A -> B"}), frozenset({"C"}))


# -------------------------------------------------------------------
# Axiom checking
# -------------------------------------------------------------------


class TestRQMaterialBaseIsAxiom:
    def test_containment(self):
        base = RQMaterialBase(language={"Happy(alice)"})
        assert base.is_axiom(
            frozenset({"Happy(alice)"}), frozenset({"Happy(alice)"})
        )

    def test_explicit_consequence(self):
        base = RQMaterialBase(
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        assert base.is_axiom(
            frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})
        )

    def test_no_weakening(self):
        """Extra premises defeat the axiom match."""
        base = RQMaterialBase(
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        assert not base.is_axiom(
            frozenset({"Happy(alice)", "Sad(alice)"}),
            frozenset({"Good(alice)"}),
        )

    def test_concept_schema(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        # hasSymptom(patient, chestPain) |~ Serious(chestPain)
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_concept_schema_no_weakening(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        # Extra premise defeats it
        assert not base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Extra(x)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_inference_schema(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_inference_schema_no_weakening(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        assert not base.is_axiom(
            frozenset({
                "hasSymptom(patient,chestPain)",
                "Serious(chestPain)",
                "Normal(ecg)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_no_match(self):
        base = RQMaterialBase(language={"A"})
        assert not base.is_axiom(frozenset({"A"}), frozenset({"B"}))


# -------------------------------------------------------------------
# Serialization
# -------------------------------------------------------------------


class TestRQMaterialBaseSerialization:
    def test_to_dict_and_back(self):
        base = RQMaterialBase(
            language={"Happy(alice)", "hasChild(alice,bob)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        base.register_concept_schema("hasChild", "alice", "Loved")

        d = base.to_dict()
        assert "schemas" in d
        assert len(d["schemas"]) == 1

        restored = RQMaterialBase.from_dict(d)
        assert restored.language == base.language
        assert restored.consequences == base.consequences
        assert len(restored._inference_schemas) == 1

    def test_to_file_and_back(self):
        base = RQMaterialBase(
            language={"Happy(alice)"},
            consequences={
                (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            },
        )
        base.register_inference_schema(
            "hasChild", "alice", "Happy", {"ParentHappy(alice)"}
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            base.to_file(path)
            restored = RQMaterialBase.from_file(path)
            assert restored.language == base.language
            assert restored.consequences == base.consequences
            assert len(restored._inference_schemas) == 1
        finally:
            Path(path).unlink()


# -------------------------------------------------------------------
# CommitmentStore
# -------------------------------------------------------------------


class TestCommitmentStore:
    def test_empty(self):
        cs = CommitmentStore()
        assert len(cs.assertions) == 0
        assert len(cs.schemas) == 0

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

    def test_commit_universal(self):
        cs = CommitmentStore()
        cs.commit_universal(
            "all children happy",
            "hasChild", "alice",
            "Smart", "Happy",
        )
        assert len(cs.schemas) == 1
        assert cs.schemas[0].role == "hasChild"

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
        cs.commit_universal(
            "children happy", "hasChild", "alice", "Smart", "Happy"
        )
        assert len(cs.schemas) == 1
        cs.retract_schema("children happy")
        assert len(cs.schemas) == 0

    def test_compile_produces_base(self):
        cs = CommitmentStore()
        cs.add_assertion("hasSymptom(patient,chestPain)")
        cs.commit_universal(
            "serious symptoms",
            "hasSymptom", "patient",
            "Serious", "HeartAttack",
        )
        base = cs.compile()
        assert isinstance(base, RQMaterialBase)
        assert "hasSymptom(patient,chestPain)" in base.language

    def test_compile_caches(self):
        cs = CommitmentStore()
        cs.add_assertion("A")
        base1 = cs.compile()
        base2 = cs.compile()
        assert base1 is base2

    def test_compile_invalidated_by_assertion(self):
        cs = CommitmentStore()
        cs.add_assertion("A")
        base1 = cs.compile()
        cs.add_assertion("B")
        base2 = cs.compile()
        assert base1 is not base2

    def test_compile_with_concept_schema(self):
        """Commit a universal with no trigger_concept should use concept schema."""
        cs = CommitmentStore()
        cs.add_assertion("hasSymptom(patient,chestPain)")
        # Add a schema with trigger_concept
        cs.commit_universal(
            "serious",
            "hasSymptom", "patient",
            "Serious", "HeartAttack",
        )
        base = cs.compile()
        # The inference schema should match
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(chestPain)"}),
        )

    def test_describe(self):
        cs = CommitmentStore()
        cs.add_assertion("Happy(alice)")
        cs.commit_universal(
            "test", "hasChild", "alice", "Smart", "Happy"
        )
        desc = cs.describe()
        assert "Happy(alice)" in desc
        assert "test" in desc

    def test_rejects_complex_assertion(self):
        cs = CommitmentStore()
        with pytest.raises(ValueError):
            cs.add_assertion("~A")


class TestInferenceSchema:
    def test_construction(self):
        schema = InferenceSchema(
            source="test",
            role="hasChild",
            subject_var="alice",
            trigger_concept="Smart",
            conclusion_concept="Happy",
        )
        assert schema.source == "test"
        assert schema.role == "hasChild"
        assert schema.trigger_concept == "Smart"
