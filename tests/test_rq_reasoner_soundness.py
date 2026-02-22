"""Tests for pynmms.rq.reasoner — containment-leak soundness audit.

Probes every rule for the pattern: a rule places content on one side
that overlaps with the other via Containment, closing the sequent
without the intended content being established.
"""


from pynmms.rq.base import RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner


def _r(language=None, consequences=None, max_depth=15):
    base = RQMaterialBase(
        language=language or set(),
        consequences=consequences or set(),
    )
    return NMMSRQReasoner(base, max_depth=max_depth)


# -------------------------------------------------------------------
# Propositional rules — no leaks
# -------------------------------------------------------------------


class TestPropositionalSoundness:
    def test_left_neg_explosion(self):
        """L~: ~C(a), C(a) => D(b) — explosion is legitimate."""
        r = _r(language={"C(a)", "C(b)", "D(b)"})
        assert r.query(
            frozenset({"~C(a)", "C(a)"}), frozenset({"D(b)"})
        )

    def test_right_neg_no_leak(self):
        r = _r(language={"D(a)", "C(b)"})
        assert not r.query(
            frozenset({"D(a)"}), frozenset({"~D(a)", "C(b)"})
        )

    def test_left_impl_no_leak(self):
        r = _r(language={"C(b)"})
        assert not r.query(
            frozenset({"C(a) -> D(a)"}), frozenset({"C(b)"})
        )

    def test_right_impl_tautology(self):
        r = _r(language={"C(a)"})
        assert r.query(frozenset(), frozenset({"C(a) -> C(a)"}))

    def test_right_impl_no_leak(self):
        r = _r()
        assert not r.query(frozenset(), frozenset({"C(a) -> D(b)"}))

    def test_right_disj_no_leak(self):
        r = _r(language={"C(a)", "D(a)", "D(b)"})
        assert not r.query(
            frozenset({"C(a)"}), frozenset({"D(a) | D(b)"})
        )

    def test_right_disj_containment(self):
        r = _r(language={"C(a)", "D(b)"})
        assert r.query(
            frozenset({"C(a)"}), frozenset({"C(a) | D(b)"})
        )

    def test_containment_multiset(self):
        r = _r(language={"D(a)", "C(b)"})
        assert r.query(
            frozenset({"D(a)"}), frozenset({"D(a)", "C(b)"})
        )


# -------------------------------------------------------------------
# Quantifier rules — no leaks
# -------------------------------------------------------------------


class TestQuantifierSoundness:
    def test_left_all_containment(self):
        """L∀R.C: instantiation yields containment (legitimate)."""
        r = _r(language={"R(a,b)", "C(b)"})
        assert r.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}),
            frozenset({"C(b)"}),
        )

    def test_left_all_no_leak(self):
        """L∀R.C: instantiation does not leak to unrelated conclusions."""
        r = _r(language={"R(a,b)", "D(b)"})
        assert not r.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}),
            frozenset({"D(b)"}),
        )

    def test_left_some_containment(self):
        """L∃R.C: triggered instance yields containment."""
        r = _r(language={"R(a,b)", "C(b)"})
        assert r.query(
            frozenset({"SOME R.C(a)", "R(a,b)"}),
            frozenset({"C(b)"}),
        )

    def test_left_some_no_leak(self):
        r = _r(language={"R(a,b)", "D(b)"})
        assert not r.query(
            frozenset({"SOME R.C(a)", "R(a,b)"}),
            frozenset({"D(b)"}),
        )

    def test_right_some_known_witness(self):
        """R∃R.C: known witness R(a,b), C(b) legitimately proves SOME."""
        r = _r(language={"R(a,b)", "C(b)"})
        assert r.query(
            frozenset({"R(a,b)", "C(b)"}),
            frozenset({"SOME R.C(a)"}),
        )

    def test_right_some_no_concept(self):
        """R∃R.C: R(a,b) alone cannot prove SOME R.C(a)."""
        r = _r(language={"R(a,b)"})
        assert not r.query(
            frozenset({"R(a,b)"}),
            frozenset({"SOME R.C(a)"}),
        )

    def test_right_some_from_nothing(self):
        r = _r()
        assert not r.query(
            frozenset(),
            frozenset({"SOME R.C(a)"}),
        )

    def test_right_all_from_nothing(self):
        r = _r()
        assert not r.query(
            frozenset(),
            frozenset({"ALL R.C(a)"}),
        )

    def test_right_all_specific_not_universal(self):
        """R(a,b), C(b) does NOT prove ALL R.C(a)."""
        r = _r(language={"R(a,b)", "C(b)"})
        assert not r.query(
            frozenset({"R(a,b)", "C(b)"}),
            frozenset({"ALL R.C(a)"}),
        )


# -------------------------------------------------------------------
# Cross-rule interactions — no leaks
# -------------------------------------------------------------------


class TestCrossRuleSoundness:
    def test_all_to_some_with_trigger(self):
        """ALL R.C(a) with trigger => SOME R.C(a) is legitimate."""
        r = _r(language={"R(a,b)", "C(b)"})
        assert r.query(
            frozenset({"ALL R.C(a)", "R(a,b)"}),
            frozenset({"SOME R.C(a)"}),
        )

    def test_all_to_some_no_trigger(self):
        """ALL R.C(a) without trigger cannot prove SOME R.C(a)."""
        r = _r()
        assert not r.query(
            frozenset({"ALL R.C(a)"}),
            frozenset({"SOME R.C(a)"}),
        )

    def test_left_impl_right_some_no_leak(self):
        """C(b) -> D(b), R(a,b) should not prove SOME R.D(a) via leak."""
        r = _r(language={"R(a,b)", "C(b)", "D(b)"})
        assert not r.query(
            frozenset({"C(b) -> D(b)", "R(a,b)"}),
            frozenset({"SOME R.D(a)"}),
        )

    def test_weakening_with_quantifiers(self):
        """No weakening even with quantified sentences in context."""
        r = _r(
            consequences={
                (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
                 frozenset({"ParentHappy(alice)"})),
            },
        )
        # Good
        assert r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )
        # Defeated by extra premise
        assert not r.query(
            frozenset({"hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)"}),
            frozenset({"ParentHappy(alice)"}),
        )
        # Defeated by ALL adding extra premise
        assert not r.query(
            frozenset({
                "hasChild(alice,bob)", "Happy(bob)",
                "ALL hasChild.Grumpy(alice)",
            }),
            frozenset({"ParentHappy(alice)"}),
        )
