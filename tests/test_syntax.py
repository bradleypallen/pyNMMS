"""Tests for pynmms.syntax — propositional sentence parsing."""

import pytest

from pynmms.syntax import (
    ATOM,
    CONJ,
    DISJ,
    IMPL,
    NEG,
    all_atomic,
    is_atomic,
    parse_sentence,
)


class TestAtoms:
    def test_bare_atom(self):
        s = parse_sentence("A")
        assert s.type == ATOM
        assert s.name == "A"

    def test_atom_with_spaces(self):
        s = parse_sentence("  A  ")
        assert s.type == ATOM
        assert s.name == "A"

    def test_multi_char_atom(self):
        s = parse_sentence("Hello")
        assert s.type == ATOM
        assert s.name == "Hello"


class TestNegation:
    def test_simple_negation(self):
        s = parse_sentence("~A")
        assert s.type == NEG
        assert s.sub is not None
        assert s.sub.type == ATOM
        assert s.sub.name == "A"

    def test_double_negation(self):
        s = parse_sentence("~~A")
        assert s.type == NEG
        assert s.sub is not None
        assert s.sub.type == NEG
        assert s.sub.sub is not None
        assert s.sub.sub.type == ATOM


class TestConjunction:
    def test_simple_conjunction(self):
        s = parse_sentence("A & B")
        assert s.type == CONJ
        assert s.left is not None and s.right is not None
        assert s.left.type == ATOM and s.left.name == "A"
        assert s.right.type == ATOM and s.right.name == "B"

    def test_left_associative_conjunction(self):
        # A & B & C should parse as (A & B) & C
        s = parse_sentence("A & B & C")
        assert s.type == CONJ
        assert s.left is not None
        assert s.left.type == CONJ  # (A & B)
        assert s.right is not None
        assert s.right.type == ATOM and s.right.name == "C"


class TestDisjunction:
    def test_simple_disjunction(self):
        s = parse_sentence("A | B")
        assert s.type == DISJ
        assert s.left is not None and s.right is not None
        assert s.left.type == ATOM and s.left.name == "A"
        assert s.right.type == ATOM and s.right.name == "B"

    def test_left_associative_disjunction(self):
        # A | B | C should parse as (A | B) | C
        s = parse_sentence("A | B | C")
        assert s.type == DISJ
        assert s.left is not None
        assert s.left.type == DISJ  # (A | B)
        assert s.right is not None
        assert s.right.type == ATOM and s.right.name == "C"


class TestImplication:
    def test_simple_implication(self):
        s = parse_sentence("A -> B")
        assert s.type == IMPL
        assert s.left is not None and s.right is not None
        assert s.left.type == ATOM and s.left.name == "A"
        assert s.right.type == ATOM and s.right.name == "B"

    def test_right_associative_implication(self):
        # A -> B -> C should parse as A -> (B -> C)
        s = parse_sentence("A -> B -> C")
        assert s.type == IMPL
        assert s.left is not None
        assert s.left.type == ATOM and s.left.name == "A"
        assert s.right is not None
        assert s.right.type == IMPL  # (B -> C)


class TestPrecedence:
    def test_conj_binds_tighter_than_disj(self):
        # A & B | C should parse as (A & B) | C
        s = parse_sentence("A & B | C")
        assert s.type == DISJ
        assert s.left is not None
        assert s.left.type == CONJ

    def test_disj_binds_tighter_than_impl(self):
        # A | B -> C should parse as (A | B) -> C
        s = parse_sentence("A | B -> C")
        assert s.type == IMPL
        assert s.left is not None
        assert s.left.type == DISJ

    def test_full_precedence_chain(self):
        # ~A & B | C -> D
        # should parse as: ((~A & B) | C) -> D
        s = parse_sentence("~A & B | C -> D")
        assert s.type == IMPL
        assert s.left is not None
        assert s.left.type == DISJ
        assert s.left.left is not None
        assert s.left.left.type == CONJ
        assert s.left.left.left is not None
        assert s.left.left.left.type == NEG


class TestParentheses:
    def test_parens_override_precedence(self):
        # A & (B | C) — parens force disj inside conj
        s = parse_sentence("A & (B | C)")
        assert s.type == CONJ
        assert s.right is not None
        assert s.right.type == DISJ

    def test_redundant_parens(self):
        s = parse_sentence("(A)")
        assert s.type == ATOM and s.name == "A"

    def test_nested_parens(self):
        s = parse_sentence("((A -> B))")
        assert s.type == IMPL


class TestEdgeCases:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_sentence("")

    def test_negation_no_operand_raises(self):
        with pytest.raises(ValueError, match="no operand"):
            parse_sentence("~")

    def test_sentence_is_frozen(self):
        s = parse_sentence("A")
        with pytest.raises(AttributeError):
            s.name = "B"  # type: ignore[misc]

    def test_str_round_trip_atom(self):
        assert str(parse_sentence("A")) == "A"

    def test_str_round_trip_complex(self):
        s = parse_sentence("A -> B")
        assert "A" in str(s) and "B" in str(s)


class TestIsAtomic:
    def test_atom_is_atomic(self):
        assert is_atomic("A")

    def test_negation_not_atomic(self):
        assert not is_atomic("~A")

    def test_conjunction_not_atomic(self):
        assert not is_atomic("A & B")

    def test_implication_not_atomic(self):
        assert not is_atomic("A -> B")


class TestAllAtomic:
    def test_all_atoms(self):
        assert all_atomic(frozenset({"A", "B", "C"}))

    def test_one_complex(self):
        assert not all_atomic(frozenset({"A", "~B"}))

    def test_empty(self):
        assert all_atomic(frozenset())
