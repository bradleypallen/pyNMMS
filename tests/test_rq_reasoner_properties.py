"""Tests for pynmms.rq.reasoner — structural properties.

Verifies nonmonotonicity, nontransitivity, supraclassicality,
and the DDT/II/AA/SS explicitation conditions with quantifiers.
"""


from pynmms.rq.base import RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner


def _r(language=None, consequences=None, max_depth=25):
    base = RQMaterialBase(
        language=language or set(),
        consequences=consequences or set(),
    )
    return NMMSRQReasoner(base, max_depth=max_depth)


# -------------------------------------------------------------------
# Nonmonotonicity (MOF)
# -------------------------------------------------------------------


class TestNonmonotonicity:
    def test_propositional(self):
        """A => B holds, but A, C => B fails."""
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert r.query(frozenset({"A"}), frozenset({"B"}))
        assert not r.query(frozenset({"A", "C"}), frozenset({"B"}))

    def test_all_defeats_inference(self):
        """ALL R.C adds defeating concept."""
        r = _r(
            consequences={
                (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
                 frozenset({"ParentHappy(alice)"})),
            },
        )
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )
        assert not r.query(
            frozenset({
                "hasChild(alice,bob)", "Happy(bob)",
                "ALL hasChild.Grumpy(alice)",
            }),
            frozenset({"ParentHappy(alice)"}),
        )

    def test_beer_bottles(self):
        """Hlobil's beer bottles: ALL inFridge.Empty defeats StillBeer."""
        r = _r(
            consequences={
                (frozenset({"inFridge(f,b1)", "Full(b1)"}),
                 frozenset({"StillBeer(f)"})),
                (frozenset({"inFridge(f,b2)", "Full(b2)"}),
                 frozenset({"StillBeer(f)"})),
            },
        )
        # Good inference
        assert r.query(
            frozenset({"inFridge(f,b1)", "Full(b1)"}),
            frozenset({"StillBeer(f)"}),
        )
        # Defeated by ALL empty
        assert not r.query(
            frozenset({
                "ALL inFridge.Empty(f)",
                "inFridge(f,b1)", "inFridge(f,b2)",
            }),
            frozenset({"StillBeer(f)"}),
        )

    def test_extra_role_assertion_defeats(self):
        """Extra premise defeats even with matching role."""
        r = _r(
            consequences={
                (frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
                 frozenset({"GreatDept(dept)"})),
            },
        )
        assert r.query(
            frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
            frozenset({"GreatDept(dept)"}),
        )
        assert not r.query(
            frozenset({
                "teaches(dept,alice)", "Excellent(alice)",
                "Mediocre(bob)",
            }),
            frozenset({"GreatDept(dept)"}),
        )


# -------------------------------------------------------------------
# Nontransitivity
# -------------------------------------------------------------------


class TestNontransitivity:
    def test_propositional(self):
        r = _r(consequences={
            (frozenset({"A"}), frozenset({"B"})),
            (frozenset({"B"}), frozenset({"C"})),
        })
        assert r.query(frozenset({"A"}), frozenset({"B"}))
        assert r.query(frozenset({"B"}), frozenset({"C"}))
        assert not r.query(frozenset({"A"}), frozenset({"C"}))

    def test_with_concept_assertions(self):
        r = _r(consequences={
            (frozenset({"Happy(alice)"}), frozenset({"Good(alice)"})),
            (frozenset({"Good(alice)"}), frozenset({"Blessed(alice)"})),
        })
        assert r.query(frozenset({"Happy(alice)"}), frozenset({"Good(alice)"}))
        assert r.query(frozenset({"Good(alice)"}), frozenset({"Blessed(alice)"}))
        assert not r.query(frozenset({"Happy(alice)"}), frozenset({"Blessed(alice)"}))


# -------------------------------------------------------------------
# Supraclassicality (SCL)
# -------------------------------------------------------------------


class TestSupraclassicality:
    def test_lem(self):
        r = _r()
        assert r.query(frozenset(), frozenset({"A | ~A"}))

    def test_lem_quantified(self):
        r = _r()
        assert r.query(
            frozenset(),
            frozenset({"ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice)"}),
        )

    def test_double_negation(self):
        r = _r(language={"A"})
        assert r.query(frozenset({"A"}), frozenset({"~~A"}))
        assert r.query(frozenset({"~~A"}), frozenset({"A"}))

    def test_explosion(self):
        r = _r(language={"A", "D"})
        assert r.query(frozenset({"A", "~A"}), frozenset({"D"}))

    def test_explosion_with_concept_assertions(self):
        r = _r(language={"Happy(alice)", "Sad(alice)"})
        assert r.query(
            frozenset({"Happy(alice)", "~Happy(alice)"}),
            frozenset({"Sad(alice)"}),
        )

    def test_modus_ponens(self):
        r = _r(language={"A", "B"})
        assert r.query(frozenset({"A", "A -> B"}), frozenset({"B"}))


# -------------------------------------------------------------------
# DDT (Deduction-Detachment)
# -------------------------------------------------------------------


class TestDDT:
    def test_propositional(self):
        r = _r(consequences={(frozenset({"A"}), frozenset({"B"}))})
        assert r.query(frozenset(), frozenset({"A -> B"}))

    def test_with_quantifier_antecedent(self):
        """DDT: hasChild(a,b) => ALL R.C(a) -> C(b)."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        assert r.query(
            frozenset({"hasChild(alice,bob)"}),
            frozenset({"ALL hasChild.Happy(alice) -> Happy(bob)"}),
        )

    def test_conditional_with_existential(self):
        """If Happy(bob) and R(a,b) hold, then SOME => derives."""
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        # hasChild(alice,bob), Happy(bob) => SOME hasChild.Happy(alice)
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )


# -------------------------------------------------------------------
# II (Incoherence-Incompatibility)
# -------------------------------------------------------------------


class TestII:
    def test_negation_left_right(self):
        """Gamma, A => Delta iff Gamma => ~A, Delta."""
        r = _r(language={"A", "B"})
        # A, B => A is containment (True)
        # so B => ~A should be... no wait.
        # II: Gamma |~ ~A, Delta iff Gamma, A |~ Delta
        # Test: {} |~ ~A, A  iff  A |~ A  (containment)
        assert r.query(frozenset(), frozenset({"~A", "A"}))


# -------------------------------------------------------------------
# AA (Antecedent-Adjunction) and SS (Succedent-Summation)
# -------------------------------------------------------------------


class TestAA:
    def test_conjunction_left(self):
        """Gamma, A & B => Delta iff Gamma, A, B => Delta."""
        r = _r(language={"A", "B"})
        assert r.query(frozenset({"A & B"}), frozenset({"A"}))
        assert r.query(frozenset({"A", "B"}), frozenset({"A"}))


class TestSS:
    def test_disjunction_right(self):
        """Gamma => A | B, Delta iff Gamma => A, B, Delta."""
        r = _r(language={"A"})
        assert r.query(frozenset({"A"}), frozenset({"A | B"}))
        assert r.query(frozenset({"A"}), frozenset({"A", "B"}))


# -------------------------------------------------------------------
# Vacuous quantification
# -------------------------------------------------------------------


class TestVacuousQuantification:
    def test_all_no_triggers(self):
        """ALL R.C(a) with no triggers is inert as premise."""
        r = _r(language={"Happy(bob)"})
        assert not r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_some_no_triggers(self):
        """SOME R.C(a) with no triggers is inert as premise."""
        r = _r(language={"Happy(bob)"})
        assert not r.query(
            frozenset({"SOME hasChild.Happy(alice)"}),
            frozenset({"Happy(bob)"}),
        )

    def test_containment_with_quantifiers(self):
        """Quantified sentences still obey containment."""
        r = _r()
        assert r.query(
            frozenset({"ALL hasChild.Happy(alice)"}),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )
        assert r.query(
            frozenset({"SOME hasChild.Happy(alice)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )
