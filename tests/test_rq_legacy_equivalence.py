"""RQ demo scenario equivalence tests — all 10 original demo scenarios.

Each demo scenario is a pytest class verifying the pynmms.rq subpackage
produces the expected results for the original ALC reasoning examples.
"""

import pytest

from pynmms.rq.base import RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner


def _r(language=None, consequences=None, max_depth=25):
    base = RQMaterialBase(
        language=language or set(),
        consequences=consequences or set(),
    )
    return NMMSRQReasoner(base, max_depth=max_depth)


# -------------------------------------------------------------------
# Demo 1: Propositional backward compatibility
# -------------------------------------------------------------------


class TestDemo1PropositionalBackwardCompat:
    """Legacy lines 1049–1079."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={"A", "B", "C"},
            consequences={
                (frozenset({"A"}), frozenset({"B"})),
                (frozenset({"B"}), frozenset({"C"})),
            },
            max_depth=15,
        )

    def test_containment(self, reasoner):
        assert reasoner.query(frozenset({"A"}), frozenset({"A"}))

    def test_base_consequence_ab(self, reasoner):
        assert reasoner.query(frozenset({"A"}), frozenset({"B"}))

    def test_base_consequence_bc(self, reasoner):
        assert reasoner.query(frozenset({"B"}), frozenset({"C"}))

    def test_nontransitivity(self, reasoner):
        assert not reasoner.query(frozenset({"A"}), frozenset({"C"}))

    def test_nonmonotonicity(self, reasoner):
        assert not reasoner.query(frozenset({"A", "C"}), frozenset({"B"}))

    def test_lem(self, reasoner):
        assert reasoner.query(frozenset(), frozenset({"A | ~A"}))

    def test_ddt(self, reasoner):
        assert reasoner.query(frozenset(), frozenset({"A -> B"}))


# -------------------------------------------------------------------
# Demo 2: Beer Bottles (Hlobil Inf-7/Inf-8)
# -------------------------------------------------------------------


class TestDemo2BeerBottles:
    """Legacy lines 1081–1149."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "inFridge(f,b1)", "inFridge(f,b2)",
                "Full(b1)", "Full(b2)",
                "Empty(b1)", "Empty(b2)",
                "StillBeer(f)",
            },
            consequences={
                (frozenset({"inFridge(f,b1)", "Full(b1)"}),
                 frozenset({"StillBeer(f)"})),
                (frozenset({"inFridge(f,b2)", "Full(b2)"}),
                 frozenset({"StillBeer(f)"})),
            },
            max_depth=15,
        )

    def test_inf7_good(self, reasoner):
        """Known full bottle → still beer."""
        assert reasoner.query(
            frozenset({"inFridge(f,b1)", "Full(b1)"}),
            frozenset({"StillBeer(f)"}),
        )

    def test_inf8_bad(self, reasoner):
        """ALL empty → should fail."""
        assert not reasoner.query(
            frozenset({
                "ALL inFridge.Empty(f)",
                "inFridge(f,b1)", "inFridge(f,b2)",
            }),
            frozenset({"StillBeer(f)"}),
        )

    def test_defeat(self, reasoner):
        """Adding ALL defeats good inference."""
        assert not reasoner.query(
            frozenset({
                "inFridge(f,b1)", "Full(b1)",
                "ALL inFridge.Empty(f)", "inFridge(f,b2)",
            }),
            frozenset({"StillBeer(f)"}),
        )


# -------------------------------------------------------------------
# Demo 3: Medical Diagnosis
# -------------------------------------------------------------------


class TestDemo3MedicalDiagnosis:
    """Legacy lines 1152–1212."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "hasSymptom(patient,chestPain)", "hasSymptom(patient,leftRadiation)",
                "hasTest(patient,ecg)", "hasTest(patient,enzymes)",
                "Normal(ecg)", "Normal(enzymes)",
                "Abnormal(ecg)", "Abnormal(enzymes)",
                "HeartAttack(patient)", "NotHeartAttack(patient)",
            },
            consequences={
                (frozenset({"hasSymptom(patient,chestPain)",
                            "hasSymptom(patient,leftRadiation)"}),
                 frozenset({"HeartAttack(patient)"})),
                (frozenset({"hasTest(patient,ecg)", "Normal(ecg)",
                            "hasTest(patient,enzymes)", "Normal(enzymes)"}),
                 frozenset({"NotHeartAttack(patient)"})),
            },
            max_depth=15,
        )

    def test_inf1_symptoms(self, reasoner):
        assert reasoner.query(
            frozenset({
                "hasSymptom(patient,chestPain)",
                "hasSymptom(patient,leftRadiation)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_inf2_defeated(self, reasoner):
        assert not reasoner.query(
            frozenset({
                "hasSymptom(patient,chestPain)",
                "hasSymptom(patient,leftRadiation)",
                "hasTest(patient,ecg)", "Normal(ecg)",
                "hasTest(patient,enzymes)", "Normal(enzymes)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_normal_tests(self, reasoner):
        assert reasoner.query(
            frozenset({
                "hasTest(patient,ecg)", "Normal(ecg)",
                "hasTest(patient,enzymes)", "Normal(enzymes)",
            }),
            frozenset({"NotHeartAttack(patient)"}),
        )


# -------------------------------------------------------------------
# Demo 4: Restricted Quantifier Logic
# -------------------------------------------------------------------


class TestDemo4RestrictedQuantifierLogic:
    """Legacy lines 1215–1273."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "hasChild(alice,bob)", "hasChild(alice,carol)",
                "Happy(bob)", "Happy(carol)",
                "Sad(bob)", "Sad(carol)",
                "Doctor(bob)", "Doctor(carol)",
                "ParentOfDoctor(alice)",
            },
            consequences={
                (frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
                 frozenset({"ParentOfDoctor(alice)"})),
                (frozenset({"hasChild(alice,carol)", "Doctor(carol)"}),
                 frozenset({"ParentOfDoctor(alice)"})),
            },
            max_depth=20,
        )

    def test_all_instantiation(self, reasoner):
        assert reasoner.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_existential_on_right(self, reasoner):
        assert reasoner.query(
            frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
            frozenset({"SOME hasChild.Doctor(alice)"}),
        )

    def test_all_plus_material_base(self, reasoner):
        assert reasoner.query(
            frozenset({"ALL hasChild.Doctor(alice)", "hasChild(alice,bob)"}),
            frozenset({"ParentOfDoctor(alice)"}),
        )

    def test_ddt_with_quantifier(self, reasoner):
        assert reasoner.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"ALL hasChild.Happy(alice) -> Happy(bob)"}),
        )


# -------------------------------------------------------------------
# Demo 5: Nonmonotonicity + Quantifiers
# -------------------------------------------------------------------


class TestDemo5NonmonotonicitQuantifiers:
    """Legacy lines 1276–1331."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "teaches(dept,alice)", "teaches(dept,bob)",
                "Excellent(alice)", "Excellent(bob)",
                "Mediocre(alice)", "Mediocre(bob)",
                "GreatDept(dept)",
            },
            consequences={
                (frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
                 frozenset({"GreatDept(dept)"})),
                (frozenset({"teaches(dept,bob)", "Excellent(bob)"}),
                 frozenset({"GreatDept(dept)"})),
            },
            max_depth=20,
        )

    def test_specific_excellent(self, reasoner):
        assert reasoner.query(
            frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
            frozenset({"GreatDept(dept)"}),
        )

    def test_all_excellent_plus_mediocre_defeated(self, reasoner):
        assert not reasoner.query(
            frozenset({
                "ALL teaches.Excellent(dept)",
                "teaches(dept,alice)", "teaches(dept,bob)",
                "Mediocre(bob)",
            }),
            frozenset({"GreatDept(dept)"}),
        )

    def test_all_excellent_single_trigger(self, reasoner):
        assert reasoner.query(
            frozenset({
                "ALL teaches.Excellent(dept)",
                "teaches(dept,alice)",
            }),
            frozenset({"GreatDept(dept)"}),
        )


# -------------------------------------------------------------------
# Demo 6: Shakespeare (Inf-5/Inf-6)
# -------------------------------------------------------------------


class TestDemo6Shakespeare:
    """Legacy lines 1334–1389."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "authored(shakespeare,rj)", "authored(shakespeare,hamlet)",
                "authored(marlowe,faustus)",
                "GreatWork(rj)", "GreatWork(hamlet)", "GreatWork(faustus)",
                "ImportantAuthor(shakespeare)", "ImportantAuthor(marlowe)",
            },
            consequences={
                (frozenset({"authored(shakespeare,rj)", "GreatWork(rj)"}),
                 frozenset({"ImportantAuthor(shakespeare)"})),
                (frozenset({"authored(shakespeare,hamlet)", "GreatWork(hamlet)"}),
                 frozenset({"ImportantAuthor(shakespeare)"})),
                (frozenset({"authored(marlowe,faustus)", "GreatWork(faustus)"}),
                 frozenset({"ImportantAuthor(marlowe)"})),
            },
            max_depth=15,
        )

    def test_inf5_specific_work(self, reasoner):
        assert reasoner.query(
            frozenset({"authored(shakespeare,rj)", "GreatWork(rj)"}),
            frozenset({"ImportantAuthor(shakespeare)"}),
        )

    def test_some_with_witness(self, reasoner):
        assert reasoner.query(
            frozenset({
                "SOME authored.GreatWork(shakespeare)",
                "authored(shakespeare,rj)", "GreatWork(rj)",
            }),
            frozenset({"ImportantAuthor(shakespeare)"}),
        )


# -------------------------------------------------------------------
# Demo 7: Witness Completeness & Canonical Naming
# -------------------------------------------------------------------


class TestDemo7WitnessCompleteness:
    """Legacy lines 1392–1460."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={
                "supervises(mgr,alice)", "supervises(mgr,bob)",
                "Certified(alice)", "Certified(bob)",
                "Compliant(mgr)",
            },
            consequences={
                (frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
                 frozenset({"Compliant(mgr)"})),
                (frozenset({"supervises(mgr,bob)", "Certified(bob)"}),
                 frozenset({"Compliant(mgr)"})),
            },
            max_depth=20,
        )

    def test_right_some_known_witness(self, reasoner):
        assert reasoner.query(
            frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
            frozenset({"SOME supervises.Certified(mgr)"}),
        )

    def test_memoization_consistency(self, reasoner):
        """Same query twice — canonical naming ensures cache hit."""
        r1 = reasoner.query(
            frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
            frozenset({"SOME supervises.Certified(mgr)"}),
        )
        r2 = reasoner.query(
            frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
            frozenset({"SOME supervises.Certified(mgr)"}),
        )
        assert r1 == r2 is True

    def test_right_all_fails(self, reasoner):
        """Cannot prove ALL from specific instances."""
        assert not reasoner.query(
            frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
            frozenset({"ALL supervises.Certified(mgr)"}),
        )

    def test_all_left_some_right(self, reasoner):
        """ALL R.C(a) with trigger => SOME R.C(a)."""
        assert reasoner.query(
            frozenset({"ALL supervises.Certified(mgr)", "supervises(mgr,bob)"}),
            frozenset({"SOME supervises.Certified(mgr)"}),
        )


# -------------------------------------------------------------------
# Demo 8: Edge Cases & Structural Tests
# -------------------------------------------------------------------


class TestDemo8EdgeCases:
    """Legacy lines 1463–1653."""

    def test_8a_vacuous_all(self):
        r = _r(language={"Happy(alice)", "R(x,y)"}, max_depth=15)
        assert not r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_8a_vacuous_containment(self):
        r = _r(language={"Happy(alice)"}, max_depth=15)
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )

    def test_8b_negated_all_sad(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Sad(bob)"}, max_depth=15)
        assert not r.query(
            frozenset({"~ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Sad(bob)"}),
        )

    def test_8b_lem_quantified(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Sad(bob)"}, max_depth=15)
        assert r.query(
            frozenset(),
            frozenset({"ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice)"}),
        )

    def test_8c_lc_with_quantifiers(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Smart(bob)"}, max_depth=15)
        assert r.query(
            frozenset({
                "ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)",
                "hasChild(alice,bob)",
            }),
            frozenset({"Happy(bob)"}),
        )

    def test_8c_lc_conjunction_right(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Smart(bob)"}, max_depth=15)
        assert r.query(
            frozenset({
                "ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)",
                "hasChild(alice,bob)",
            }),
            frozenset({"Happy(bob) & Smart(bob)"}),
        )

    def test_8d_quantifier_disjunction(self):
        r = _r(
            language={
                "hasChild(alice,bob)", "hasChild(bob,carol)",
                "Happy(bob)", "Happy(carol)",
                "Tall(bob)", "Tall(carol)",
            },
            max_depth=20,
        )
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob) | Tall(bob)"}),
        )

    def test_8e_all_not_derivable_when_sad(self):
        r = _r(
            language={
                "hasChild(alice,bob)", "hasChild(alice,carol)",
                "Happy(bob)", "Sad(carol)",
            },
            max_depth=15,
        )
        assert not r.query(
            frozenset({
                "hasChild(alice,bob)", "Happy(bob)",
                "hasChild(alice,carol)", "Sad(carol)",
            }),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )

    def test_8e_some_no_conjure(self):
        r = _r(
            language={
                "hasChild(alice,bob)", "hasChild(alice,carol)",
                "Happy(bob)", "Sad(carol)",
            },
            max_depth=15,
        )
        assert not r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )

    def test_8e_weakening_with_extra_premise(self):
        r = _r(
            language={"hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)"},
            consequences={
                (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
                 frozenset({"ParentHappy(alice)"})),
            },
            max_depth=15,
        )
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )

    def test_8e_weakening_with_all(self):
        r = _r(
            language={"hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)"},
            consequences={
                (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
                 frozenset({"ParentHappy(alice)"})),
            },
            max_depth=15,
        )
        assert not r.query(
            frozenset({
                "hasChild(alice,bob)", "Happy(bob)",
                "ALL hasChild.Grumpy(alice)",
            }),
            frozenset({"ParentHappy(alice)"}),
        )


# -------------------------------------------------------------------
# Demo 9: Soundness Audit (Containment-Leak Probes)
# -------------------------------------------------------------------


class TestDemo9SoundnessAudit:
    """Legacy lines 1700–1783."""

    @pytest.fixture
    def reasoner(self):
        return _r(
            language={"R(a,b)", "C(a)", "C(b)", "D(a)", "D(b)"},
            max_depth=15,
        )

    # Propositional rules
    def test_left_neg_explosion(self, reasoner):
        assert reasoner.query(frozenset({"~C(a)", "C(a)"}), frozenset({"D(b)"}))

    def test_right_neg_no_leak(self, reasoner):
        assert not reasoner.query(frozenset({"D(a)"}), frozenset({"~D(a)", "C(b)"}))

    def test_left_impl_no_leak(self, reasoner):
        assert not reasoner.query(frozenset({"C(a) -> D(a)"}), frozenset({"C(b)"}))

    def test_right_impl_tautology(self, reasoner):
        assert reasoner.query(frozenset(), frozenset({"C(a) -> C(a)"}))

    def test_right_impl_no_leak(self, reasoner):
        assert not reasoner.query(frozenset(), frozenset({"C(a) -> D(b)"}))

    def test_right_disj_no_leak(self, reasoner):
        assert not reasoner.query(frozenset({"C(a)"}), frozenset({"D(a) | D(b)"}))

    def test_right_disj_containment(self, reasoner):
        assert reasoner.query(frozenset({"C(a)"}), frozenset({"C(a) | D(b)"}))

    def test_containment_schema(self, reasoner):
        assert reasoner.query(frozenset({"D(a)"}), frozenset({"D(a)", "C(b)"}))

    # Quantifier rules
    def test_left_all_containment(self, reasoner):
        assert reasoner.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}), frozenset({"C(b)"})
        )

    def test_left_all_no_leak(self, reasoner):
        assert not reasoner.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}), frozenset({"D(b)"})
        )

    def test_left_some_containment(self, reasoner):
        assert reasoner.query(
            frozenset({"SOME R.C(a)", "R(a,b)"}), frozenset({"C(b)"})
        )

    def test_left_some_no_leak(self, reasoner):
        assert not reasoner.query(
            frozenset({"SOME R.C(a)", "R(a,b)"}), frozenset({"D(b)"})
        )

    def test_right_some_known_witness(self, reasoner):
        assert reasoner.query(
            frozenset({"R(a,b)", "C(b)"}), frozenset({"SOME R.C(a)"})
        )

    def test_right_some_no_concept(self, reasoner):
        assert not reasoner.query(
            frozenset({"R(a,b)"}), frozenset({"SOME R.C(a)"})
        )

    def test_right_some_from_nothing(self, reasoner):
        assert not reasoner.query(frozenset(), frozenset({"SOME R.C(a)"}))

    def test_right_all_from_nothing(self, reasoner):
        assert not reasoner.query(frozenset(), frozenset({"ALL R.C(a)"}))

    def test_right_all_specific_not_universal(self, reasoner):
        assert not reasoner.query(
            frozenset({"R(a,b)", "C(b)"}), frozenset({"ALL R.C(a)"})
        )

    # Cross-rule interactions
    def test_all_to_some_with_trigger(self, reasoner):
        assert reasoner.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}), frozenset({"SOME R.C(a)"})
        )

    def test_all_to_some_no_trigger(self, reasoner):
        assert not reasoner.query(
            frozenset({"ALL R.C(a)"}), frozenset({"SOME R.C(a)"})
        )

    def test_left_impl_right_some_no_leak(self, reasoner):
        assert not reasoner.query(
            frozenset({"C(b) -> D(b)", "R(a,b)"}),
            frozenset({"SOME R.D(a)"}),
        )


# -------------------------------------------------------------------
# Demo 10: Lazy Schema Evaluation
# -------------------------------------------------------------------


class TestDemo10LazySchemas:
    """Legacy lines 1786–1904."""

    @pytest.fixture
    def base(self):
        base = RQMaterialBase(
            language={
                "hasSymptom(patient,chestPain)",
                "hasSymptom(patient,leftRadiation)",
            },
        )
        base.register_concept_schema("hasSymptom", "patient", "Serious")
        base.register_inference_schema(
            "hasSymptom", "patient", "Serious",
            {"HeartAttack(patient)"},
        )
        return base

    def test_concept_schema(self, base):
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)"}),
            frozenset({"Serious(chestPain)"}),
        )

    def test_inference_schema(self, base):
        assert base.is_axiom(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_inference_via_reasoner(self, base):
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_all_triggers_schema(self, base):
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({
                "ALL hasSymptom.Serious(patient)",
                "hasSymptom(patient,chestPain)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_new_individual_no_regrounding(self, base):
        base.add_individual("hasSymptom", "patient", "shortnessOfBreath")
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({
                "hasSymptom(patient,shortnessOfBreath)",
                "Serious(shortnessOfBreath)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )

    def test_concept_schema_new_individual(self, base):
        base.add_individual("hasSymptom", "patient", "shortnessOfBreath")
        r = NMMSRQReasoner(base, max_depth=15)
        assert r.query(
            frozenset({"hasSymptom(patient,shortnessOfBreath)"}),
            frozenset({"Serious(shortnessOfBreath)"}),
        )

    def test_nonmonotonicity_schema(self, base):
        r = NMMSRQReasoner(base, max_depth=15)
        assert not r.query(
            frozenset({
                "hasSymptom(patient,chestPain)",
                "Serious(chestPain)",
                "Normal(ecg)",
            }),
            frozenset({"HeartAttack(patient)"}),
        )
