"""Tests for pynmms.base — MaterialBase."""

import json
import tempfile
from pathlib import Path

import pytest

from pynmms.base import MaterialBase


class TestConstruction:
    def test_empty_base(self, empty_base):
        assert len(empty_base.language) == 0
        assert len(empty_base.consequences) == 0

    def test_base_with_language(self):
        base = MaterialBase(language={"A", "B", "C"})
        assert base.language == frozenset({"A", "B", "C"})

    def test_base_with_consequences(self, toy_base):
        assert len(toy_base.consequences) == 2
        assert len(toy_base.language) >= 3


class TestValidation:
    def test_rejects_complex_in_language(self):
        with pytest.raises(ValueError, match="logically complex"):
            MaterialBase(language={"~A"})

    def test_rejects_complex_in_consequence_antecedent(self):
        with pytest.raises(ValueError, match="logically complex"):
            MaterialBase(
                consequences={(frozenset({"A & B"}), frozenset({"C"}))}
            )

    def test_rejects_complex_in_consequence_consequent(self):
        with pytest.raises(ValueError, match="logically complex"):
            MaterialBase(
                consequences={(frozenset({"A"}), frozenset({"B -> C"}))}
            )


class TestAddAtom:
    def test_add_atom(self, empty_base):
        empty_base.add_atom("X")
        assert "X" in empty_base.language

    def test_add_atom_rejects_complex(self, empty_base):
        with pytest.raises(ValueError):
            empty_base.add_atom("~A")


class TestAddConsequence:
    def test_add_consequence(self, empty_base):
        empty_base.add_consequence(frozenset({"A"}), frozenset({"B"}))
        assert (frozenset({"A"}), frozenset({"B"})) in empty_base.consequences
        assert "A" in empty_base.language
        assert "B" in empty_base.language

    def test_add_consequence_rejects_complex(self, empty_base):
        with pytest.raises(ValueError):
            empty_base.add_consequence(frozenset({"A -> B"}), frozenset({"C"}))


class TestIsAxiom:
    def test_containment(self, toy_base):
        # Gamma ∩ Delta ≠ ∅
        assert toy_base.is_axiom(frozenset({"A"}), frozenset({"A"}))

    def test_containment_multi(self, toy_base):
        assert toy_base.is_axiom(frozenset({"A", "B"}), frozenset({"B", "C"}))

    def test_base_consequence(self, toy_base):
        assert toy_base.is_axiom(frozenset({"A"}), frozenset({"B"}))

    def test_base_consequence_other(self, toy_base):
        assert toy_base.is_axiom(frozenset({"B"}), frozenset({"C"}))

    def test_no_weakening(self, toy_base):
        # {A, X} => {B} should NOT be an axiom (exact match required)
        assert not toy_base.is_axiom(frozenset({"A", "X"}), frozenset({"B"}))

    def test_not_axiom(self, toy_base):
        # A => C is not a base axiom
        assert not toy_base.is_axiom(frozenset({"A"}), frozenset({"C"}))

    def test_empty_sets(self, toy_base):
        # ∅ => ∅ — no containment, no base match
        assert not toy_base.is_axiom(frozenset(), frozenset())


class TestSerialization:
    def test_to_dict(self, toy_base):
        d = toy_base.to_dict()
        assert "language" in d
        assert "consequences" in d
        assert len(d["consequences"]) == 2

    def test_from_dict_round_trip(self, toy_base):
        d = toy_base.to_dict()
        restored = MaterialBase.from_dict(d)
        assert restored.language == toy_base.language
        assert restored.consequences == toy_base.consequences

    def test_to_file_from_file_round_trip(self, toy_base):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        toy_base.to_file(path)
        restored = MaterialBase.from_file(path)
        assert restored.language == toy_base.language
        assert restored.consequences == toy_base.consequences

        Path(path).unlink()

    def test_json_format(self, toy_base):
        d = toy_base.to_dict()
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert json_str  # non-empty
