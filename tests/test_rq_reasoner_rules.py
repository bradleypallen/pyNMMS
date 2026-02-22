"""Tests for pynmms.rq.reasoner — individual rule correctness.

One class per rule, positive and negative cases, plus propositional
backward compatibility.
"""


from pynmms.rq.base import RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner

# -------------------------------------------------------------------
# Helper: build reasoner from base specification
# -------------------------------------------------------------------

def _r(language=None, consequences=None, max_depth=15):
    """Shortcut to create an RQMaterialBase + NMMSRQReasoner."""
    base = RQMaterialBase(
        language=language or set(),
        consequences=consequences or set(),
    )
    return NMMSRQReasoner(base, max_depth=max_depth)


# -------------------------------------------------------------------
# Propositional backward compatibility
# -------------------------------------------------------------------


class TestPropositionalBackwardCompat:
    """The RQ reasoner should produce identical results for propositional queries."""

    def test_containment(self):
        r = _r(language={"A"})
        assert r.query(frozenset({"A"}), frozenset({"A"}))

    def test_base_consequence(self):
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert r.query(frozenset({"A"}), frozenset({"B"}))

    def test_nontransitivity(self):
        r = _r(consequences={
            (frozenset({"A"}), frozenset({"B"})),
            (frozenset({"B"}), frozenset({"C"})),
        })
        assert not r.query(frozenset({"A"}), frozenset({"C"}))

    def test_nonmonotonicity(self):
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert not r.query(frozenset({"A", "C"}), frozenset({"B"}))

    def test_lem(self):
        r = _r(language={"A"})
        assert r.query(frozenset(), frozenset({"A | ~A"}))

    def test_ddt(self):
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert r.query(frozenset(), frozenset({"A -> B"}))

    def test_left_negation(self):
        r = _r(language={"A", "D"})
        assert r.query(frozenset({"~A", "A"}), frozenset({"D"}))

    def test_right_negation(self):
        r = _r(language={"A"})
        assert r.query(frozenset({"A"}), frozenset({"~~A"}))

    def test_left_conjunction(self):
        r = _r(language={"A", "B"})
        assert r.query(frozenset({"A & B"}), frozenset({"A"}))

    def test_right_conjunction(self):
        r = _r(language={"A", "B"})
        assert r.query(frozenset({"A", "B"}), frozenset({"A & B"}))

    def test_left_disjunction(self):
        r = _r(language={"A", "B"})
        # A | B => A, B (both disjuncts land in succedent via containment)
        assert r.query(frozenset({"A | B"}), frozenset({"A", "B"}))

    def test_right_disjunction(self):
        r = _r(language={"A"})
        assert r.query(frozenset({"A"}), frozenset({"A | B"}))

    def test_left_implication(self):
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert r.query(frozenset({"A -> B", "A"}), frozenset({"B"}))

    def test_right_implication(self):
        r = _r(language={"A"})
        assert r.query(frozenset(), frozenset({"A -> A"}))


# -------------------------------------------------------------------
# [L-ALL-R.C] — universal restriction on the left
# -------------------------------------------------------------------


class TestLeftAllRestrict:
    def test_basic_instantiation(self):
        """ALL R.C(a) with trigger R(a,b) adds C(b) to premises."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_multiple_triggers(self):
        """ALL with two triggers adds both instances."""
        r = _r(
            language={"hasChild(alice,bob)", "hasChild(alice,carol)"},
            consequences={
                (
                    frozenset({"hasChild(alice,bob)", "hasChild(alice,carol)",
                               "Happy(bob)", "Happy(carol)"}),
                    frozenset({"AllHappy(alice)"}),
                ),
            },
        )
        assert r.query(
            frozenset({
                "ALL hasChild.Happy(alice)",
                "hasChild(alice,bob)",
                "hasChild(alice,carol)",
            }),
            frozenset({"AllHappy(alice)"}),
        )

    def test_no_triggers_inert(self):
        """ALL with no triggers cannot decompose."""
        r = _r(language={"Happy(bob)"})
        assert not r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_containment_through_instantiation(self):
        """Instantiated concept contained in succedent."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_wrong_role(self):
        r = _r(language={"teaches(dept,alice)", "Happy(alice)"})
        assert not r.query(
            frozenset({"ALL hasChild.Happy(dept)", "teaches(dept,alice)"}),
            frozenset({"Happy(alice)"}),
        )

    def test_wrong_subject(self):
        r = _r(language={"hasChild(bob,carol)", "Happy(carol)"})
        assert not r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(bob,carol)"}),
            frozenset({"Happy(carol)"}),
        )

    def test_interacts_with_material_base(self):
        """ALL instantiates, then base consequence fires."""
        r = _r(
            consequences={
                (frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
                 frozenset({"ParentOfDoctor(alice)"})),
            },
        )
        assert r.query(
            frozenset({"ALL hasChild.Doctor(alice)", "hasChild(alice,bob)"}),
            frozenset({"ParentOfDoctor(alice)"}),
        )


# -------------------------------------------------------------------
# [L-SOME-R.C] — existential restriction on the left
# -------------------------------------------------------------------


class TestLeftSomeRestrict:
    def test_single_trigger(self):
        """SOME R.C(a) with one trigger: C(b) must prove conclusion."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"SOME hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_ketonen_two_triggers(self):
        """With 2 triggers, all 3 nonempty subsets must work."""
        r = _r(
            language={
                "hasChild(alice,bob)", "hasChild(alice,carol)",
                "Happy(bob)", "Happy(carol)",
            },
            consequences={
                (frozenset({"hasChild(alice,bob)", "hasChild(alice,carol)", "Happy(bob)"}),
                 frozenset({"Good(alice)"})),
                (frozenset({"hasChild(alice,bob)", "hasChild(alice,carol)", "Happy(carol)"}),
                 frozenset({"Good(alice)"})),
                (frozenset({
                    "hasChild(alice,bob)", "hasChild(alice,carol)",
                    "Happy(bob)", "Happy(carol)",
                }), frozenset({"Good(alice)"})),
            },
        )
        assert r.query(
            frozenset({
                "SOME hasChild.Happy(alice)",
                "hasChild(alice,bob)",
                "hasChild(alice,carol)",
            }),
            frozenset({"Good(alice)"}),
        )

    def test_ketonen_fails_when_subset_missing(self):
        """If one subset fails, the whole rule fails."""
        r = _r(
            language={
                "hasChild(alice,bob)", "hasChild(alice,carol)",
                "Happy(bob)", "Happy(carol)",
            },
            consequences={
                # Only bob alone works, not carol alone
                (frozenset({"hasChild(alice,bob)", "hasChild(alice,carol)", "Happy(bob)"}),
                 frozenset({"Good(alice)"})),
                (frozenset({
                    "hasChild(alice,bob)", "hasChild(alice,carol)",
                    "Happy(bob)", "Happy(carol)",
                }), frozenset({"Good(alice)"})),
                # Missing: carol alone => Good(alice)
            },
        )
        assert not r.query(
            frozenset({
                "SOME hasChild.Happy(alice)",
                "hasChild(alice,bob)",
                "hasChild(alice,carol)",
            }),
            frozenset({"Good(alice)"}),
        )

    def test_no_triggers_inert(self):
        r = _r(language={"Happy(bob)"})
        assert not r.query(
            frozenset({"SOME hasChild.Happy(alice)"}),
            frozenset({"Happy(bob)"}),
        )


# -------------------------------------------------------------------
# [R-SOME-R.C] — existential restriction on the right
# -------------------------------------------------------------------


class TestRightSomeRestrict:
    def test_known_witness(self):
        """Known R-successor with C witnesses SOME."""
        r = _r(language={"hasChild(alice,bob)", "Doctor(bob)"})
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
            frozenset({"SOME hasChild.Doctor(alice)"}),
        )

    def test_known_witness_containment(self):
        """R(a,b) in gamma, C(b) on right via containment."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )

    def test_no_concept_fails(self):
        """R(a,b) present but C(b) not established."""
        r = _r(language={"hasChild(alice,bob)"})
        assert not r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )

    def test_fresh_witness(self):
        """Fresh canonical witness when no known witness works."""
        # Base: R(a,fresh), C(fresh) close via containment
        # This tests the fresh witness path (no known triggers in gamma)
        r = _r(
            language=set(),
            consequences={
                # The fresh witness path assumes R(a,b) and must prove C(b)
                # Since there's no base entry to support it, this should fail
            },
        )
        assert not r.query(
            frozenset(),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )

    def test_from_nothing_fails(self):
        r = _r()
        assert not r.query(
            frozenset(),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )


# -------------------------------------------------------------------
# [R-ALL-R.C] — universal restriction on the right
# -------------------------------------------------------------------


class TestRightAllRestrict:
    def test_eigenvariable_basic(self):
        """ALL R.C(a) on right: fresh eigen b, prove R(a,b) => C(b)."""
        # This can only succeed if C(b) is derivable for arbitrary b
        # Containment on eigenvariable won't help unless the goal matches
        r = _r(language=set())
        # Cannot prove ALL hasChild.Happy(alice) from nothing
        assert not r.query(
            frozenset(),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )

    def test_specific_not_universal(self):
        """R(a,b), C(b) does NOT entail ALL R.C(a)."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )

    def test_all_left_implies_some_right(self):
        """ALL R.C(a) with trigger b implies SOME R.C(a)."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )

    def test_all_left_no_trigger_no_some(self):
        """ALL R.C(a) without triggers cannot prove SOME R.C(a)."""
        r = _r(language=set())
        assert not r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )


# -------------------------------------------------------------------
# Cross-rule interactions
# -------------------------------------------------------------------


class TestCrossRuleInteractions:
    def test_all_plus_material_base(self):
        """ALL decomposes, then material base fires."""
        r = _r(
            consequences={
                (frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
                 frozenset({"ParentOfDoctor(alice)"})),
            },
        )
        assert r.query(
            frozenset({"ALL hasChild.Doctor(alice)", "hasChild(alice,bob)"}),
            frozenset({"ParentOfDoctor(alice)"}),
        )

    def test_negated_quantifier(self):
        """~ALL R.C(a) on left flips to ALL R.C(a) on right."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        # ~ALL hasChild.Happy(alice) on left => ALL hasChild.Happy(alice) on right
        # Then R∀ needs eigen proof for arbitrary child — should fail
        assert not r.query(
            frozenset({"~ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Sad(bob)"}),
        )

    def test_lem_with_quantifiers(self):
        """LEM holds for quantified sentences."""
        r = _r(language=set())
        assert r.query(
            frozenset(),
            frozenset({"ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice)"}),
        )

    def test_conjunction_with_quantifiers(self):
        """L∧ decomposes conjunction of quantifiers."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Smart(bob)"})
        assert r.query(
            frozenset({
                "ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)",
                "hasChild(alice,bob)",
            }),
            frozenset({"Happy(bob)"}),
        )

    def test_implication_with_quantifier(self):
        """DDT: hasChild(a,b) => (ALL hasChild.Happy(a) -> Happy(b))."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"ALL hasChild.Happy(alice) -> Happy(bob)"}),
        )

    def test_disjunction_with_quantifier_right(self):
        """ALL R.C(a) instantiates, then R∨ simplifies."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)", "Tall(bob)"})
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob) | Tall(bob)"}),
        )

    def test_defeat_through_all(self):
        """Adding ALL R.C defeats an otherwise good inference."""
        r = _r(
            consequences={
                (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
                 frozenset({"ParentHappy(alice)"})),
            },
        )
        # Without ALL: good
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )
        # With ALL hasChild.Grumpy: defeated (adds Grumpy(bob))
        assert not r.query(
            frozenset({
                "hasChild(alice,bob)", "Happy(bob)",
                "ALL hasChild.Grumpy(alice)",
            }),
            frozenset({"ParentHappy(alice)"}),
        )
