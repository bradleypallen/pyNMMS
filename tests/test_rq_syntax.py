"""Tests for pynmms.rq.syntax — RQ sentence parsing and helpers."""

import pytest

from pynmms.rq.syntax import (
    ALL_RESTRICT,
    ATOM_CONCEPT,
    ATOM_ROLE,
    SOME_RESTRICT,
    RQSentence,
    all_rq_atomic,
    collect_individuals,
    concept_label,
    find_blocking_individual,
    find_role_triggers,
    fresh_individual,
    is_rq_atomic,
    make_concept_assertion,
    make_role_assertion,
    parse_rq_sentence,
)
from pynmms.syntax import CONJ, DISJ, IMPL, NEG, Sentence

# -------------------------------------------------------------------
# Parsing: RQ-specific sentence types
# -------------------------------------------------------------------


class TestParseConceptAssertion:
    def test_simple(self):
        p = parse_rq_sentence("Human(alice)")
        assert isinstance(p, RQSentence)
        assert p.type == ATOM_CONCEPT
        assert p.concept == "Human"
        assert p.individual == "alice"

    def test_str_roundtrip(self):
        p = parse_rq_sentence("Happy(bob)")
        assert str(p) == "Happy(bob)"

    def test_with_whitespace(self):
        p = parse_rq_sentence("  Happy(bob)  ")
        assert isinstance(p, RQSentence)
        assert p.type == ATOM_CONCEPT


class TestParseRoleAssertion:
    def test_simple(self):
        p = parse_rq_sentence("hasChild(alice,bob)")
        assert isinstance(p, RQSentence)
        assert p.type == ATOM_ROLE
        assert p.role == "hasChild"
        assert p.arg1 == "alice"
        assert p.arg2 == "bob"

    def test_with_spaces(self):
        p = parse_rq_sentence("hasChild(alice, bob)")
        assert isinstance(p, RQSentence)
        assert p.type == ATOM_ROLE
        assert p.arg2 == "bob"

    def test_str_roundtrip(self):
        p = parse_rq_sentence("teaches(dept,alice)")
        assert str(p) == "teaches(dept,alice)"


class TestParseAllRestrict:
    def test_simple(self):
        p = parse_rq_sentence("ALL hasChild.Happy(alice)")
        assert isinstance(p, RQSentence)
        assert p.type == ALL_RESTRICT
        assert p.role == "hasChild"
        assert p.concept == "Happy"
        assert p.individual == "alice"

    def test_str_roundtrip(self):
        p = parse_rq_sentence("ALL teaches.Excellent(dept)")
        assert str(p) == "ALL teaches.Excellent(dept)"


class TestParseSomeRestrict:
    def test_simple(self):
        p = parse_rq_sentence("SOME hasChild.Doctor(alice)")
        assert isinstance(p, RQSentence)
        assert p.type == SOME_RESTRICT
        assert p.role == "hasChild"
        assert p.concept == "Doctor"
        assert p.individual == "alice"

    def test_str_roundtrip(self):
        p = parse_rq_sentence("SOME supervises.Certified(mgr)")
        assert str(p) == "SOME supervises.Certified(mgr)"


# -------------------------------------------------------------------
# Parsing: propositional fallthrough
# -------------------------------------------------------------------


class TestParsePropositional:
    def test_bare_atom_rejected(self):
        with pytest.raises(ValueError, match="not valid in NMMS_RQ"):
            parse_rq_sentence("A")

    def test_negation(self):
        p = parse_rq_sentence("~A")
        assert isinstance(p, Sentence)
        assert p.type == NEG

    def test_conjunction(self):
        p = parse_rq_sentence("A & B")
        assert isinstance(p, Sentence)
        assert p.type == CONJ

    def test_disjunction(self):
        p = parse_rq_sentence("A | B")
        assert isinstance(p, Sentence)
        assert p.type == DISJ

    def test_implication(self):
        p = parse_rq_sentence("A -> B")
        assert isinstance(p, Sentence)
        assert p.type == IMPL

    def test_nested_parens(self):
        p = parse_rq_sentence("(A & B) -> C")
        assert isinstance(p, Sentence)
        assert p.type == IMPL

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_rq_sentence("")

    def test_negated_quantifier(self):
        """~ALL R.C(a) parses as negation of the string 'ALL R.C(a)'."""
        p = parse_rq_sentence("~ALL hasChild.Happy(alice)")
        assert isinstance(p, Sentence)
        assert p.type == NEG

    def test_quantifier_in_disjunction(self):
        """ALL R.C(a) | B parses as disjunction."""
        p = parse_rq_sentence("ALL hasChild.Happy(alice) | B")
        assert isinstance(p, Sentence)
        assert p.type == DISJ

    def test_quantifier_in_implication(self):
        """ALL R.C(a) -> B parses as implication."""
        p = parse_rq_sentence("ALL hasChild.Happy(alice) -> Happy(bob)")
        assert isinstance(p, Sentence)
        assert p.type == IMPL


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------


class TestMakeAssertions:
    def test_concept(self):
        assert make_concept_assertion("Happy", "bob") == "Happy(bob)"

    def test_role(self):
        assert make_role_assertion("hasChild", "alice", "bob") == "hasChild(alice,bob)"


class TestFindRoleTriggers:
    def test_finds_triggers(self):
        gamma = frozenset({"hasChild(alice,bob)", "hasChild(alice,carol)", "Happy(bob)"})
        triggers = find_role_triggers(gamma, "hasChild", "alice")
        assert sorted(triggers) == ["bob", "carol"]

    def test_no_triggers(self):
        gamma = frozenset({"Happy(bob)"})
        triggers = find_role_triggers(gamma, "hasChild", "alice")
        assert triggers == []

    def test_wrong_role(self):
        gamma = frozenset({"teaches(dept,alice)"})
        triggers = find_role_triggers(gamma, "hasChild", "dept")
        assert triggers == []

    def test_wrong_subject(self):
        gamma = frozenset({"hasChild(bob,carol)"})
        triggers = find_role_triggers(gamma, "hasChild", "alice")
        assert triggers == []


class TestCollectIndividuals:
    def test_from_concepts(self):
        sentences = frozenset({"Happy(alice)", "Sad(bob)"})
        assert collect_individuals(sentences) == {"alice", "bob"}

    def test_from_roles(self):
        sentences = frozenset({"hasChild(alice,bob)"})
        assert collect_individuals(sentences) == {"alice", "bob"}

    def test_from_quantifiers(self):
        sentences = frozenset({"ALL hasChild.Happy(alice)", "SOME teaches.Smart(bob)"})
        assert collect_individuals(sentences) == {"alice", "bob"}

    def test_bare_atoms_ignored(self):
        sentences = frozenset({"A", "B"})
        assert collect_individuals(sentences) == set()

    def test_mixed(self):
        sentences = frozenset({
            "Happy(alice)", "hasChild(alice,bob)",
            "ALL teaches.Smart(dept)", "A",
        })
        assert collect_individuals(sentences) == {"alice", "bob", "dept"}


class TestFreshIndividual:
    def test_basic(self):
        assert fresh_individual(set()) == "w0"

    def test_avoids_used(self):
        assert fresh_individual({"w0"}) == "w1"

    def test_custom_prefix(self):
        assert fresh_individual(set(), prefix="_e_R_C_a") == "_e_R_C_a0"

    def test_avoids_collision(self):
        assert fresh_individual({"_e0"}, prefix="_e") == "_e1"


class TestConceptLabel:
    def test_extracts_concepts(self):
        sentences = frozenset({"Happy(alice)", "Smart(alice)", "Sad(bob)"})
        assert concept_label("alice", sentences) == frozenset({"Happy", "Smart"})

    def test_empty_for_unknown(self):
        sentences = frozenset({"Happy(alice)"})
        assert concept_label("bob", sentences) == frozenset()

    def test_ignores_roles(self):
        sentences = frozenset({"hasChild(alice,bob)", "Happy(alice)"})
        assert concept_label("alice", sentences) == frozenset({"Happy"})


class TestFindBlockingIndividual:
    def test_no_blocking(self):
        gamma = frozenset({"Happy(fresh)", "Happy(alice)", "Smart(alice)"})
        result = find_blocking_individual("fresh", gamma, frozenset(), {"alice"})
        # fresh has {Happy}, alice has {Happy, Smart} — fresh ⊆ alice
        assert result == "alice"

    def test_not_blocked_when_superset(self):
        gamma = frozenset({
            "Happy(fresh)", "Smart(fresh)",
            "Happy(alice)",
        })
        result = find_blocking_individual("fresh", gamma, frozenset(), {"alice"})
        # fresh has {Happy, Smart}, alice has {Happy} — NOT subset
        assert result is None

    def test_blocked_by_equal(self):
        gamma = frozenset({"Happy(fresh)", "Happy(existing)"})
        result = find_blocking_individual("fresh", gamma, frozenset(), {"existing"})
        assert result == "existing"

    def test_empty_label_blocked_by_anyone(self):
        gamma = frozenset({"Happy(existing)"})
        result = find_blocking_individual("fresh", gamma, frozenset(), {"existing"})
        # fresh has {}, existing has {Happy} — {} ⊆ {Happy}
        assert result == "existing"


# -------------------------------------------------------------------
# Atomicity checks
# -------------------------------------------------------------------


class TestIsRQAtomic:
    def test_concept_assertion(self):
        assert is_rq_atomic("Happy(alice)") is True

    def test_role_assertion(self):
        assert is_rq_atomic("hasChild(alice,bob)") is True

    def test_bare_atom(self):
        assert is_rq_atomic("A") is False

    def test_quantifier_not_atomic(self):
        assert is_rq_atomic("ALL hasChild.Happy(alice)") is False

    def test_negation_not_atomic(self):
        assert is_rq_atomic("~A") is False

    def test_conjunction_not_atomic(self):
        assert is_rq_atomic("A & B") is False


class TestAllRQAtomic:
    def test_all_atomic(self):
        sentences = frozenset({"Happy(alice)", "hasChild(alice,bob)"})
        assert all_rq_atomic(sentences) is True

    def test_bare_atom_not_atomic(self):
        sentences = frozenset({"Happy(alice)", "A"})
        assert all_rq_atomic(sentences) is False

    def test_has_complex(self):
        sentences = frozenset({"Happy(alice)", "ALL hasChild.Happy(alice)"})
        assert all_rq_atomic(sentences) is False

    def test_empty(self):
        assert all_rq_atomic(frozenset()) is True
