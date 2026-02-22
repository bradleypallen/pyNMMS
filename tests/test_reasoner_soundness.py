"""Tests for NMMSReasoner — soundness audit.

Adapted from Demo 9, using propositional atoms (p, q, r) instead of
ALC concept/role assertions.

These tests probe every propositional rule for containment-leak false
positives: cases where a rule might place content on one side that overlaps
with the other side via Containment, closing the sequent without the
intended content being established.
"""

import pytest

from pynmms import MaterialBase, NMMSReasoner


@pytest.fixture
def soundness_base():
    """Base with unrelated atoms for leak testing."""
    return MaterialBase(language={"p", "q", "r", "s"})


@pytest.fixture
def soundness_reasoner(soundness_base):
    return NMMSReasoner(soundness_base, max_depth=15)


class TestLeftNegationSoundness:
    def test_explosion(self, soundness_reasoner):
        """~p, p => q — True: L~ on ~p gives => q, p, then containment on p."""
        assert soundness_reasoner.query(frozenset({"~p", "p"}), frozenset({"q"}))

    def test_no_leak(self, soundness_reasoner):
        """p => ~p, q — should be False: R~ on ~p gives p, p => q, no base match."""
        assert not soundness_reasoner.query(frozenset({"p"}), frozenset({"~p", "q"}))


class TestLeftImplicationSoundness:
    def test_no_leak(self, soundness_reasoner):
        """p -> q => r — False: L-> doesn't connect to r."""
        assert not soundness_reasoner.query(frozenset({"p -> q"}), frozenset({"r"}))


class TestRightImplicationSoundness:
    def test_tautology(self, soundness_reasoner):
        """=> p -> p — True: R-> gives p => p, containment."""
        assert soundness_reasoner.query(frozenset(), frozenset({"p -> p"}))

    def test_no_leak(self, soundness_reasoner):
        """=> p -> q — False: no base consequence from p to q."""
        assert not soundness_reasoner.query(frozenset(), frozenset({"p -> q"}))


class TestRightDisjunctionSoundness:
    def test_no_leak(self, soundness_reasoner):
        """p => q | r — False: R| gives p => q, r, no containment."""
        assert not soundness_reasoner.query(frozenset({"p"}), frozenset({"q | r"}))

    def test_containment(self, soundness_reasoner):
        """p => p | q — True: R| gives p => p, q, containment on p."""
        assert soundness_reasoner.query(frozenset({"p"}), frozenset({"p | q"}))


class TestMultiSuccedent:
    def test_containment_in_multi_succedent(self, soundness_reasoner):
        """p => p, q — True: containment on p."""
        assert soundness_reasoner.query(frozenset({"p"}), frozenset({"p", "q"}))

    def test_no_leak_multi_succedent(self, soundness_reasoner):
        """p => q, r — False: p doesn't overlap with q or r."""
        assert not soundness_reasoner.query(frozenset({"p"}), frozenset({"q", "r"}))


class TestComprehensiveSoundness:
    """Comprehensive soundness checks from Demo 9, propositional only."""

    @pytest.mark.parametrize(
        "label,gamma,delta,expected",
        [
            ("L¬ explosion", {"~p", "p"}, {"q"}, True),
            ("R¬ no leak", {"p"}, {"~p", "q"}, False),
            ("L→ no leak", {"p -> q"}, {"r"}, False),
            ("R→ tautology", set(), {"p -> p"}, True),
            ("R→ no leak", set(), {"p -> q"}, False),
            ("R∨ no leak", {"p"}, {"q | r"}, False),
            ("R∨ containment", {"p"}, {"p | q"}, True),
            ("Containment multi-succ", {"p"}, {"p", "q"}, True),
        ],
    )
    def test_soundness(self, soundness_reasoner, label, gamma, delta, expected):
        result = soundness_reasoner.query(frozenset(gamma), frozenset(delta))
        assert result == expected, f"{label}: got {result}, expected {expected}"
