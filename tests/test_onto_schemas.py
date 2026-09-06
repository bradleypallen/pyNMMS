"""Tests for ontology schema functionality.

Defeasible ontology axiom schemas: subClassOf, range, domain, subPropertyOf,
disjointWith, disjointProperties, jointCommitment.
Tests cover schema matching, nonmonotonicity, non-transitivity, lazy
evaluation, and integration with NMMSReasoner.
"""

import pytest

from pynmms.onto.base import CommitmentStore, OntoMaterialBase
from pynmms.reasoner import NMMSReasoner

# -------------------------------------------------------------------
# subClassOf schemas
# -------------------------------------------------------------------


class TestSubClassOf:
    def test_basic(self):
        """{Man(x)} |~ {Mortal(x)} for any x."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        assert base.is_axiom(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_different_individual(self):
        """Schema works for any individual."""
        base = OntoMaterialBase(language={"Man(socrates)", "Man(plato)"})
        base.register_subclass("Man", "Mortal")
        assert base.is_axiom(
            frozenset({"Man(plato)"}),
            frozenset({"Mortal(plato)"}),
        )

    def test_wrong_concept(self):
        base = OntoMaterialBase(language={"Woman(alice)"})
        base.register_subclass("Man", "Mortal")
        assert not base.is_axiom(
            frozenset({"Woman(alice)"}),
            frozenset({"Mortal(alice)"}),
        )

    def test_no_weakening(self):
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        assert not base.is_axiom(
            frozenset({"Man(socrates)", "Extra(x)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_mismatched_individuals(self):
        """subClassOf requires same individual on both sides."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        assert not base.is_axiom(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(plato)"}),
        )


# -------------------------------------------------------------------
# range schemas
# -------------------------------------------------------------------


class TestRange:
    def test_basic(self):
        """{R(x,y)} |~ {C(y)} -- concept applies to arg2."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Person(bob)"}),
        )

    def test_no_weakening(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)", "Extra(x)"}),
            frozenset({"Person(bob)"}),
        )

    def test_wrong_individual(self):
        """Range applies to arg2, not arg1."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Person(alice)"}),
        )

    def test_different_subject(self):
        """Range schema works for any subject and object."""
        base = OntoMaterialBase(language={"hasChild(carol,dave)"})
        base.register_range("hasChild", "Person")
        assert base.is_axiom(
            frozenset({"hasChild(carol,dave)"}),
            frozenset({"Person(dave)"}),
        )


# -------------------------------------------------------------------
# domain schemas
# -------------------------------------------------------------------


class TestDomain:
    def test_basic(self):
        """{R(x,y)} |~ {C(x)} -- concept applies to arg1."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_domain("hasChild", "Parent")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Parent(alice)"}),
        )

    def test_wrong_individual(self):
        """Domain applies to arg1, not arg2."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_domain("hasChild", "Parent")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Parent(bob)"}),
        )

    def test_no_weakening(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_domain("hasChild", "Parent")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)", "Extra(x)"}),
            frozenset({"Parent(alice)"}),
        )


# -------------------------------------------------------------------
# subPropertyOf schemas
# -------------------------------------------------------------------


class TestSubPropertyOf:
    def test_basic(self):
        """{R(x,y)} |~ {S(x,y)} -- same arguments."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )

    def test_swapped_args(self):
        """Arguments must match exactly."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasDescendant(bob,alice)"}),
        )

    def test_no_weakening(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)", "Extra(x)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )


# -------------------------------------------------------------------
# Onto Nonmonotonicity
# -------------------------------------------------------------------


class TestOntoNonmonotonicity:
    def test_extra_premise_defeats_subclass(self):
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )
        assert not r.query(
            frozenset({"Man(socrates)", "Immortal(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_extra_premise_defeats_range(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Person(bob)"}),
        )
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "Robot(bob)"}),
            frozenset({"Person(bob)"}),
        )

    def test_extra_premise_defeats_domain(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_domain("hasChild", "Parent")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Parent(alice)"}),
        )
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "NonParent(alice)"}),
            frozenset({"Parent(alice)"}),
        )

    def test_extra_premise_defeats_subproperty(self):
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "Extra(x)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )


# -------------------------------------------------------------------
# Onto Non-transitivity (no Cut)
# -------------------------------------------------------------------


class TestDisjointWith:
    def test_basic(self):
        """{Man(x), Woman(x)} |~ {} for any x."""
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(socrates)"})
        base.register_disjoint("Man", "Woman")
        assert base.is_axiom(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset(),
        )

    def test_order_independence(self):
        """Order of concepts in antecedent doesn't matter."""
        base = OntoMaterialBase(language={"Man(alice)", "Woman(alice)"})
        base.register_disjoint("Man", "Woman")
        assert base.is_axiom(
            frozenset({"Woman(alice)", "Man(alice)"}),
            frozenset(),
        )

    def test_wrong_concepts(self):
        base = OntoMaterialBase(language={"Cat(alice)", "Dog(alice)"})
        base.register_disjoint("Man", "Woman")
        assert not base.is_axiom(
            frozenset({"Cat(alice)", "Dog(alice)"}),
            frozenset(),
        )

    def test_mismatched_individuals(self):
        """disjointWith requires same individual for both concepts."""
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(alice)"})
        base.register_disjoint("Man", "Woman")
        assert not base.is_axiom(
            frozenset({"Man(socrates)", "Woman(alice)"}),
            frozenset(),
        )

    def test_no_weakening(self):
        """Extra premise defeats incompatibility."""
        base = OntoMaterialBase(
            language={"Man(socrates)", "Woman(socrates)", "Extra(socrates)"},
        )
        base.register_disjoint("Man", "Woman")
        assert not base.is_axiom(
            frozenset({"Man(socrates)", "Woman(socrates)", "Extra(socrates)"}),
            frozenset(),
        )

    def test_nonempty_consequent_no_match(self):
        """disjointWith is incompatibility -- consequent must be empty."""
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(socrates)"})
        base.register_disjoint("Man", "Woman")
        assert not base.is_axiom(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset({"Extra(socrates)"}),
        )

    def test_lazy_evaluation(self):
        """Schema matches any individual."""
        base = OntoMaterialBase(
            language={"Man(socrates)", "Woman(socrates)", "Man(plato)", "Woman(plato)"},
        )
        base.register_disjoint("Man", "Woman")
        for ind in ["socrates", "plato"]:
            assert base.is_axiom(
                frozenset({f"Man({ind})", f"Woman({ind})"}),
                frozenset(),
            )


class TestDisjointProperties:
    def test_basic(self):
        """{R(x,y), S(x,y)} |~ {} for any x, y."""
        base = OntoMaterialBase(
            language={"hasChild(alice,bob)", "hasParent(alice,bob)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")
        assert base.is_axiom(
            frozenset({"hasChild(alice,bob)", "hasParent(alice,bob)"}),
            frozenset(),
        )

    def test_order_independence(self):
        """Order of roles in antecedent doesn't matter."""
        base = OntoMaterialBase(
            language={"hasChild(alice,bob)", "hasParent(alice,bob)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")
        assert base.is_axiom(
            frozenset({"hasParent(alice,bob)", "hasChild(alice,bob)"}),
            frozenset(),
        )

    def test_wrong_roles(self):
        base = OntoMaterialBase(
            language={"likes(alice,bob)", "hates(alice,bob)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")
        assert not base.is_axiom(
            frozenset({"likes(alice,bob)", "hates(alice,bob)"}),
            frozenset(),
        )

    def test_mismatched_args(self):
        """Both role assertions must share the same arg1 and arg2."""
        base = OntoMaterialBase(
            language={"hasChild(alice,bob)", "hasParent(carol,dave)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)", "hasParent(carol,dave)"}),
            frozenset(),
        )

    def test_no_weakening(self):
        base = OntoMaterialBase(
            language={"hasChild(alice,bob)", "hasParent(alice,bob)", "Extra(alice)"},
        )
        base.register_disjoint_properties("hasChild", "hasParent")
        assert not base.is_axiom(
            frozenset({"hasChild(alice,bob)", "hasParent(alice,bob)", "Extra(alice)"}),
            frozenset(),
        )


# -------------------------------------------------------------------
# Onto Nonmonotonicity (incompatibility schemas)
# -------------------------------------------------------------------


class TestDisjointWithNonmonotonicity:
    def test_extra_premise_defeats_incompatibility(self):
        base = OntoMaterialBase(
            language={"Man(socrates)", "Woman(socrates)", "Extra(socrates)"},
        )
        base.register_disjoint("Man", "Woman")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset(),
        )
        assert not r.query(
            frozenset({"Man(socrates)", "Woman(socrates)", "Extra(socrates)"}),
            frozenset(),
        )


class TestDisjointWithReasonerIntegration:
    def test_ii_condition(self):
        """II condition: {Man(x), Woman(x)} |~ {} implies {Man(x)} |~ {~Woman(x)}."""
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(socrates)"})
        base.register_disjoint("Man", "Woman")
        r = NMMSReasoner(base, max_depth=15)
        # Direct incompatibility
        assert r.query(
            frozenset({"Man(socrates)", "Woman(socrates)"}),
            frozenset(),
        )
        # II condition: Gamma, A |~ Delta iff Gamma |~ ~A, Delta
        assert r.query(
            frozenset({"Man(socrates)"}),
            frozenset({"~Woman(socrates)"}),
        )

    def test_ddt_with_disjoint(self):
        """DDT: Man(a) -> ~Woman(a) derivable via disjointWith + II + R->."""
        base = OntoMaterialBase(language={"Man(socrates)", "Woman(socrates)"})
        base.register_disjoint("Man", "Woman")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset(),
            frozenset({"Man(socrates) -> ~Woman(socrates)"}),
        )


class TestOntoNontransitivity:
    def test_subclass_no_chain(self):
        """Man ⊑ Mortal + Mortal ⊑ Physical does NOT yield Man(x) |~ Physical(x)."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        base.register_subclass("Mortal", "Physical")
        r = NMMSReasoner(base, max_depth=15)
        assert not r.query(
            frozenset({"Man(socrates)"}),
            frozenset({"Physical(socrates)"}),
        )

    def test_subproperty_no_chain(self):
        """hasChild ⊑ hasDescendant + hasDescendant ⊑ hasRelative does NOT chain."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_subproperty("hasChild", "hasDescendant")
        base.register_subproperty("hasDescendant", "hasRelative")
        r = NMMSReasoner(base, max_depth=15)
        assert not r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasRelative(alice,bob)"}),
        )


# -------------------------------------------------------------------
# Lazy evaluation
# -------------------------------------------------------------------


class TestOntoLazyEvaluation:
    def test_no_eager_grounding(self):
        """Schemas are stored, not expanded to ground entries."""
        base = OntoMaterialBase(
            language={"Man(socrates)", "Man(plato)", "Man(aristotle)"},
        )
        base.register_subclass("Man", "Mortal")
        assert len(base._onto_schemas) == 1
        for individual in ["socrates", "plato", "aristotle"]:
            assert base.is_axiom(
                frozenset({f"Man({individual})"}),
                frozenset({f"Mortal({individual})"}),
            )

    def test_new_individual_works_without_regrounding(self):
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        base.add_atom("Man(plato)")
        assert base.is_axiom(
            frozenset({"Man(plato)"}),
            frozenset({"Mortal(plato)"}),
        )


# -------------------------------------------------------------------
# Reasoner integration
# -------------------------------------------------------------------


class TestOntoReasonerIntegration:
    def test_subclass_with_reasoner(self):
        """NMMSReasoner works transparently with OntoMaterialBase."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )

    def test_ddt_with_subclass(self):
        """DDT: Man(a) -> Mortal(a) derivable via R-> decomposition."""
        base = OntoMaterialBase(language={"Man(socrates)"})
        base.register_subclass("Man", "Mortal")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset(),
            frozenset({"Man(socrates) -> Mortal(socrates)"}),
        )

    def test_multiple_schemas(self):
        """Multiple schemas coexist."""
        base = OntoMaterialBase(language={"hasChild(alice,bob)"})
        base.register_range("hasChild", "Person")
        base.register_domain("hasChild", "Parent")
        base.register_subproperty("hasChild", "hasDescendant")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Person(bob)"}),
        )
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"Parent(alice)"}),
        )
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"hasDescendant(alice,bob)"}),
        )

    def test_commitment_store_integration(self):
        """CommitmentStore + NMMSReasoner end-to-end."""
        cs = CommitmentStore()
        cs.add_assertion("Man(socrates)")
        cs.commit_subclass("man_mortal", "Man", "Mortal")
        base = cs.compile()
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"Man(socrates)"}),
            frozenset({"Mortal(socrates)"}),
        )


# -------------------------------------------------------------------
# jointCommitment schemas
# -------------------------------------------------------------------


class TestJointCommitment:
    def test_basic(self):
        """{ChestPain(x), ElevatedTroponin(x)} |~ {MI(x)} for any x."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert base.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_order_independence(self):
        """Order of concepts in antecedent doesn't matter."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert base.is_axiom(
            frozenset({"ElevatedTroponin(patient)", "ChestPain(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_different_individual(self):
        """Schema works for any individual."""
        base = OntoMaterialBase(
            language={"ChestPain(alice)", "ElevatedTroponin(alice)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert base.is_axiom(
            frozenset({"ChestPain(alice)", "ElevatedTroponin(alice)"}),
            frozenset({"MI(alice)"}),
        )

    def test_wrong_concepts(self):
        base = OntoMaterialBase(
            language={"Headache(patient)", "Fever(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert not base.is_axiom(
            frozenset({"Headache(patient)", "Fever(patient)"}),
            frozenset({"MI(patient)"}),
        )

    def test_mismatched_individuals(self):
        """All antecedent concepts and consequent must share the same individual."""
        base = OntoMaterialBase(
            language={"ChestPain(alice)", "ElevatedTroponin(bob)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert not base.is_axiom(
            frozenset({"ChestPain(alice)", "ElevatedTroponin(bob)"}),
            frozenset({"MI(alice)"}),
        )

    def test_no_weakening(self):
        """Extra premise defeats the inference."""
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

    def test_empty_consequent_no_match(self):
        """jointCommitment requires a non-empty consequent."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert not base.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset(),
        )

    def test_extra_consequent_no_match(self):
        """Consequent must be exactly one concept."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        assert not base.is_axiom(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)", "Extra(patient)"}),
        )

    def test_lazy_evaluation(self):
        """Schema matches any individual without re-grounding."""
        base = OntoMaterialBase(
            language={
                "ChestPain(alice)", "ElevatedTroponin(alice)",
                "ChestPain(bob)", "ElevatedTroponin(bob)",
            },
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        for ind in ["alice", "bob"]:
            assert base.is_axiom(
                frozenset({f"ChestPain({ind})", f"ElevatedTroponin({ind})"}),
                frozenset({f"MI({ind})"}),
            )

    def test_three_concepts(self):
        """jointCommitment works with 3+ antecedent concepts."""
        base = OntoMaterialBase(
            language={"A(x)", "B(x)", "C(x)"},
        )
        base.register_joint_commitment(["A", "B", "C"], "D")
        assert base.is_axiom(
            frozenset({"A(x)", "B(x)", "C(x)"}),
            frozenset({"D(x)"}),
        )

    def test_minimum_two_required(self):
        """register_joint_commitment rejects fewer than 2 antecedent concepts."""
        base = OntoMaterialBase()
        with pytest.raises(ValueError, match="at least 2"):
            base.register_joint_commitment(["ChestPain"], "MI")


class TestJointCommitmentNonmonotonicity:
    def test_extra_premise_defeats_inference(self):
        base = OntoMaterialBase(
            language={
                "ChestPain(patient)",
                "ElevatedTroponin(patient)",
                "Antacid(patient)",
            },
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )
        assert not r.query(
            frozenset({
                "ChestPain(patient)",
                "ElevatedTroponin(patient)",
                "Antacid(patient)",
            }),
            frozenset({"MI(patient)"}),
        )


class TestJointCommitmentReasonerIntegration:
    def test_ddt_through_joint_commitment(self):
        """DDT: ChestPain(a) -> (ElevatedTroponin(a) -> MI(a)) derivable."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        r = NMMSReasoner(base, max_depth=25)
        # {ChestPain(p), ElevatedTroponin(p)} |~ {MI(p)}
        assert r.query(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )
        # DDT: {ChestPain(p)} |~ {ElevatedTroponin(p) -> MI(p)}
        assert r.query(
            frozenset({"ChestPain(patient)"}),
            frozenset({"ElevatedTroponin(patient) -> MI(patient)"}),
        )

    def test_interaction_with_subclass(self):
        """jointCommitment + subClassOf coexist without interference."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        base.register_subclass("ChestPain", "Symptom")
        r = NMMSReasoner(base, max_depth=15)
        # jointCommitment still works
        assert r.query(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )
        # subClassOf still works
        assert r.query(
            frozenset({"ChestPain(patient)"}),
            frozenset({"Symptom(patient)"}),
        )


class TestJointCommitmentNontransitivity:
    def test_no_chain_with_subclass(self):
        """jointCommitment({A,B}, C) + subClassOf(C, D) does NOT yield {A,B} |~ D."""
        base = OntoMaterialBase(
            language={"ChestPain(patient)", "ElevatedTroponin(patient)"},
        )
        base.register_joint_commitment(["ChestPain", "ElevatedTroponin"], "MI")
        base.register_subclass("MI", "CardiacEvent")
        r = NMMSReasoner(base, max_depth=15)
        # Each individually holds
        assert r.query(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"MI(patient)"}),
        )
        assert r.query(
            frozenset({"MI(patient)"}),
            frozenset({"CardiacEvent(patient)"}),
        )
        # But chaining does NOT hold (no Mixed-Cut)
        assert not r.query(
            frozenset({"ChestPain(patient)", "ElevatedTroponin(patient)"}),
            frozenset({"CardiacEvent(patient)"}),
        )


# -------------------------------------------------------------------
# Robustness policies on schemas (Phase 2)
# -------------------------------------------------------------------

from pynmms.robustness import MONOTONE, guarded  # noqa: E402

F = frozenset


class TestSchemaRobustness:
    def test_bird_tall_penguin(self):
        """The canonical relevant-defeat example from the change notes."""
        base = OntoMaterialBase()
        base.register_subclass("Bird", "Flies", robustness=guarded(["Penguin"]))
        assert base.is_axiom(F({"Bird(a)"}), F({"Flies(a)"}))
        assert base.is_axiom(F({"Bird(a)", "Tall(a)"}), F({"Flies(a)"}))
        assert not base.is_axiom(F({"Bird(a)", "Penguin(a)"}), F({"Flies(a)"}))
        # defeater on a different individual does not defeat
        assert base.is_axiom(F({"Bird(a)", "Penguin(b)"}), F({"Flies(a)"}))

    def test_exact_schema_still_exact(self):
        base = OntoMaterialBase()
        base.register_subclass("Bird", "Flies")
        assert not base.is_axiom(F({"Bird(a)", "Tall(a)"}), F({"Flies(a)"}))

    def test_monotone_subclass_with_large_antecedent(self):
        base = OntoMaterialBase()
        base.register_subclass("Man", "Mortal", robustness=MONOTONE)
        big = F(f"P{i}(x{i})" for i in range(50_000)) | {"Man(a)"}
        assert NMMSReasoner(base).derives(big, F({"Mortal(a)"})).derivable

    def test_range_guarded(self):
        base = OntoMaterialBase()
        base.register_range("hasChild", "Person", robustness=guarded(["Robot"]))
        assert base.is_axiom(F({"hasChild(a,b)", "Tall(a)"}), F({"Person(b)"}))
        assert not base.is_axiom(F({"hasChild(a,b)", "Robot(b)"}), F({"Person(b)"}))
        # defeater applies to the individuals of the matched role atom
        assert not base.is_axiom(F({"hasChild(a,b)", "Robot(a)"}), F({"Person(b)"}))
        assert not base.is_axiom(F({"hasChild(a,c)"}), F({"Person(b)"}))

    def test_domain_monotone(self):
        base = OntoMaterialBase()
        base.register_domain("hasChild", "Parent", robustness=MONOTONE)
        assert base.is_axiom(F({"Old(a)", "hasChild(a,b)"}), F({"Parent(a)"}))
        assert not base.is_axiom(F({"Old(a)", "hasChild(b,a)"}), F({"Parent(a)"}))

    def test_subproperty_guarded(self):
        base = OntoMaterialBase()
        base.register_subproperty("hasChild", "hasDescendant", robustness=guarded(["Adopted"]))
        assert base.is_axiom(F({"hasChild(a,b)", "Tall(a)"}), F({"hasDescendant(a,b)"}))
        assert not base.is_axiom(F({"hasChild(a,b)", "Adopted(b)"}), F({"hasDescendant(a,b)"}))

    def test_joint_commitment_guarded(self):
        base = OntoMaterialBase()
        base.register_joint_commitment(
            ["ChestPain", "ElevatedTroponin"], "MI", robustness=guarded(["Athlete"])
        )
        g = F({"ChestPain(p)", "ElevatedTroponin(p)", "Tall(p)"})
        assert base.is_axiom(g, F({"MI(p)"}))
        assert not base.is_axiom(g | {"Athlete(p)"}, F({"MI(p)"}))
        assert not base.is_axiom(F({"ChestPain(p)", "Tall(p)"}), F({"MI(p)"}))

    def test_disjoint_with_monotone_in_larger_context(self):
        base = OntoMaterialBase()
        base.register_disjoint("Alive", "Dead", robustness=MONOTONE)
        assert base.is_axiom(F({"Alive(a)", "Dead(a)", "Tall(a)", "Q(b)"}), F())
        assert not base.is_axiom(F({"Alive(a)", "Dead(b)", "Tall(a)"}), F())
        # exact disjointness is defeated by any extra premise
        exact = OntoMaterialBase()
        exact.register_disjoint("Alive", "Dead")
        assert exact.is_axiom(F({"Alive(a)", "Dead(a)"}), F())
        assert not exact.is_axiom(F({"Alive(a)", "Dead(a)", "Tall(a)"}), F())

    def test_disjoint_guarded_pair_defeated(self):
        base = OntoMaterialBase()
        base.register_disjoint("Alive", "Dead", robustness=guarded(["Zombie"]))
        assert base.is_axiom(F({"Alive(a)", "Dead(a)"}), F())
        assert not base.is_axiom(F({"Alive(a)", "Dead(a)", "Zombie(a)"}), F())

    def test_disjoint_properties_monotone(self):
        base = OntoMaterialBase()
        base.register_disjoint_properties("employs", "isEmployedBy", robustness=MONOTONE)
        assert base.is_axiom(F({"employs(a,b)", "isEmployedBy(a,b)", "Big(a)"}), F())
        assert not base.is_axiom(F({"employs(a,b)", "isEmployedBy(b,a)", "Big(a)"}), F())

    def test_negation_as_incoherence_with_monotone_disjointness(self):
        """II: Γ |~ ~Dead(a) iff Γ, Dead(a) |~ ∅."""
        base = OntoMaterialBase()
        base.register_disjoint("Alive", "Dead", robustness=MONOTONE)
        r = NMMSReasoner(base)
        assert r.derives(F({"Alive(a)", "Tall(a)"}), F({"~Dead(a)"})).derivable
        assert not r.derives(F({"Tall(a)"}), F({"~Dead(a)"})).derivable

    def test_schema_serialization_round_trip(self):
        base = OntoMaterialBase()
        base.register_subclass("Bird", "Flies", annotation="birds fly",
                               robustness=guarded(["Penguin"]))
        base.register_disjoint("Alive", "Dead", robustness=MONOTONE)
        base.register_range("hasChild", "Person")
        d = base.to_dict()
        assert d["onto_schemas"][0]["robustness"] == {
            "kind": "guarded", "unless": {"antecedent": ["Penguin"], "consequent": []}
        }
        assert d["onto_schemas"][2]["robustness"] == {"kind": "exact"}
        restored = OntoMaterialBase.from_dict(d)
        assert restored.onto_schemas == base.onto_schemas
        assert restored.is_axiom(F({"Bird(a)", "Tall(a)"}), F({"Flies(a)"}))
        assert not restored.is_axiom(F({"Bird(a)", "Penguin(a)"}), F({"Flies(a)"}))

    def test_commitment_store_robustness(self):
        cs = CommitmentStore()
        cs.commit_subclass("src", "Bird", "Flies", robustness=guarded(["Penguin"]))
        base = cs.compile()
        assert base.is_axiom(F({"Bird(a)", "Tall(a)"}), F({"Flies(a)"}))
        assert "unless Penguin" in cs.describe()

    def test_whitespace_in_role_assertion_is_canonicalised(self):
        base = OntoMaterialBase(language={"hasChild(alice, bob)"})
        assert "hasChild(alice,bob)" in base.language
        base.register_range("hasChild", "Person")
        r = NMMSReasoner(base)
        assert r.derives(F({"hasChild(alice, bob)"}), F({"Person(bob)"})).derivable


class TestSchemaIndex:
    def test_many_schemas_hit_and_miss(self):
        base = OntoMaterialBase()
        for i in range(2000):
            base.register_subclass(f"C{i}", f"C{i + 1}")
        assert base.is_axiom(F({"C1000(a)"}), F({"C1001(a)"}))
        assert not base.is_axiom(F({"C1000(a)"}), F({"C1002(a)"}))
        assert not base.is_axiom(F({"Zed(a)"}), F({"Nope(a)"}))
        assert len(base.onto_schemas) == 2000

    def test_index_rebuilt_on_load(self):
        base = OntoMaterialBase()
        base.register_subclass("A", "B")
        restored = OntoMaterialBase.from_dict(base.to_dict())
        assert restored.is_axiom(F({"A(x)"}), F({"B(x)"}))
