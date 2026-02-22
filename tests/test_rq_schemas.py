"""Tests for pynmms.rq schema functionality.

Concept schemas, inference schemas, CommitmentStore integration,
lazy evaluation, and nonmonotonicity of schema matching.
"""


from pynmms.rq.base import CommitmentStore, RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner

# -------------------------------------------------------------------
# Concept schemas
# -------------------------------------------------------------------


class TestConceptSchemas:
    def test_basic_concept_schema(self):
        """role(subject, x) |~ concept(x)."""
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_concept_schema_different_individual(self):
        """Schema works for any individual in the role."""
        base = RQMaterialBase(language={
            "hasSymptom(patient,chestPain)",
            "hasSymptom(patient,headache)",
        })
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,headache)"}),
            frozenset({"Serious(headache)"}),
        )

    def test_concept_schema_wrong_role(self):
        base = RQMaterialBase(language={"teaches(dept,alice)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        assert not base.is_axiom(
            frozenset({"teaches(dept,alice)"}),
            frozenset({"Serious(alice)"}),
        )

    def test_concept_schema_no_weakening(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        assert not base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Extra(x)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_concept_schema_with_reasoner(self):
        """Schema fires through proof search."""
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasSymptom(patient,chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )


# -------------------------------------------------------------------
# Inference schemas
# -------------------------------------------------------------------


class TestInferenceSchemas:
    def test_basic_inference_schema(self):
        """role(sub, x), premise(x) |~ conclusion."""
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_inference_schema_obj_template(self):
        """__OBJ__ in conclusion is replaced with matched individual."""
        base = RQMaterialBase(language={"hasChild(alice,bob)"})
        base.register_inference_schema(
            "hasChild", "alice", "Smart",
            {"Praised(__OBJ__)"},
        )
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)", "Smart(bob)"}),
            frozenset({"Praised(bob)"}),
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

    def test_inference_schema_with_quantifier_decomposition(self):
        """ALL decomposes, then schema fires."""
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        r = NMMSRQReasoner(base, max_depth=15)
        # ALL hasSymptom.Serious(patient) → Serious(chestPain) via L∀
        # Then inference schema: hasSymptom + Serious => HeartAttack
        assert r.query(
            frozenset({
                "ALL hasSymptom.Serious(patient)",
                "hasSymptom(patient,chestPain)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )


# -------------------------------------------------------------------
# CommitmentStore integration
# -------------------------------------------------------------------


class TestCommitmentStoreIntegration:
    def test_full_workflow(self):
        """Assertions + universal commitment → compile → query."""
        cs = CommitmentStore()
        cs.add_assertion("hasSymptom(patient,chestPain)")
        cs.commit_universal(
            "serious symptoms",
            "hasSymptom", "patient",
            "Serious", "HeartAttack",
        )
        base = cs.compile()
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(chestPain)"}),
        )

    def test_add_individual_no_recompile(self):
        """Adding an individual after compile: schema still works."""
        cs = CommitmentStore()
        cs.add_assertion("hasSymptom(patient,chestPain)")
        cs.commit_universal(
            "serious",
            "hasSymptom", "patient",
            "Serious", "HeartAttack",
        )
        base = cs.compile()

        # Add new symptom directly to base
        base.add_individual("hasSymptom", "patient", "headache")

        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasSymptom(patient,headache)", "Serious(headache)"}),
            frozenset({"HeartAttack(headache)"}),
        )

    def test_retract_and_recompile(self):
        """Retracting a schema invalidates cached base."""
        cs = CommitmentStore()
        cs.add_assertion("hasSymptom(patient,chestPain)")
        cs.commit_universal(
            "serious",
            "hasSymptom", "patient",
            "Serious", "HeartAttack",
        )
        base1 = cs.compile()
        assert base1.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(chestPain)"}),
        )

        cs.retract_schema("serious")
        base2 = cs.compile()
        assert not base2.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(chestPain)"}),
        )

    def test_ground_rule_with_schema(self):
        """Ground rules and schemas coexist."""
        cs = CommitmentStore()
        cs.add_assertion("hasChild(alice,bob)")
        cs.commit_defeasible_rule(
            "bob happy",
            frozenset({"Happy(bob)"}),
            frozenset({"Good(bob)"}),
        )
        cs.commit_universal(
            "all children smart",
            "hasChild", "alice",
            "Smart", "Praised",
        )
        base = cs.compile()
        # Ground rule
        assert base.is_axiom(
            frozenset({"Happy(bob)"}), frozenset({"Good(bob)"})
        )
        # Schema
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)", "Smart(bob)"}),
            frozenset({"Praised(bob)"}),
        )


# -------------------------------------------------------------------
# Lazy evaluation
# -------------------------------------------------------------------


class TestLazyEvaluation:
    def test_no_eager_grounding(self):
        """Schemas are stored, not expanded to ground entries."""
        base = RQMaterialBase(
            language={
                "hasSymptom(patient,chestPain)",
                "hasSymptom(patient,headache)",
                "hasSymptom(patient,fever)",
            },
        )
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        # Only 1 schema stored, not 3 ground entries
        assert len(base._inference_schemas) == 1
        # But it matches each individual lazily
        for symptom in ["chestPain", "headache", "fever"]:
            assert base.is_axiom(
                frozenset({f"hasSymptom(patient,{symptom})"}),
                frozenset({f"Serious({symptom})"}),
            )

    def test_new_individual_works_without_regrounding(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        # Add new individual
        base.add_individual("hasSymptom", "patient", "nausea")
        # Schema still works for new individual (lazy)
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,nausea)"}),
            frozenset({"Serious(nausea)"}),
        )


# -------------------------------------------------------------------
# Nonmonotonicity of schema matching
# -------------------------------------------------------------------


class TestSchemaNonmonotonicity:
    def test_extra_premise_defeats_concept_schema(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        # Exact match succeeds
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )
        # Extra premise defeats
        assert not base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Mild(chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_extra_premise_defeats_inference_schema(self):
        base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(patient)"}),
        )
        assert not base.is_axiom(
            frozenset({
                "hasSymptom(patient,chestPain)",
                "Serious(chestPain)",
                "Normal(ecg)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )
