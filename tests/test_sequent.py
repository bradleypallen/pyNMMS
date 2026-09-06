"""Tests for pynmms.sequent — AtomSet, Sequent, TraceEntry."""

import pytest

from pynmms.sequent import AtomSet, Sequent, TraceEntry, connective_count, intersects
from pynmms.syntax import parse_sentence


class TestAtomSet:
    def test_membership_len_iter(self):
        s = AtomSet.of({"a", "b", "c"})
        assert "a" in s and "z" not in s
        assert len(s) == 3
        assert sorted(s) == ["a", "b", "c"]

    def test_with_added_and_removed(self):
        s = AtomSet.of({"a", "b"})
        t = s.with_added("c").with_removed("a")
        assert sorted(t) == ["b", "c"]
        assert len(t) == 2
        assert sorted(s) == ["a", "b"]  # persistent: original unchanged

    def test_normalisation_invariants(self):
        s = AtomSet.of({"a", "b"})
        assert s.with_added("a") is s
        assert s.with_removed("z") is s
        # add then remove a new atom returns to the base representation
        t = s.with_added("c").with_removed("c")
        assert t == s and hash(t) == hash(s) and t.diff_size == 0
        # remove then re-add a base atom likewise
        u = s.with_removed("a").with_added("a")
        assert u == s and hash(u) == hash(s) and u.diff_size == 0

    def test_equality_and_hash_are_content_equality_for_shared_base(self):
        base = frozenset({"a", "b", "c"})
        x = AtomSet(base).with_removed("a").with_added("d")
        y = AtomSet(base).with_added("d").with_removed("a")
        assert x == y and hash(x) == hash(y)
        assert {x: 1}[y] == 1

    def test_equal_content_different_base_objects(self):
        x = AtomSet.of({"a", "b"})
        y = AtomSet(frozenset({"a", "b"}))
        assert x == y and hash(x) == hash(y)

    def test_compare_with_frozenset_by_content(self):
        assert AtomSet.of({"a", "b"}).with_added("c") == frozenset({"a", "b", "c"})
        assert AtomSet.of({"a"}) != frozenset({"b"})

    def test_intersects(self):
        s = AtomSet.of({"a", "b"})
        assert s.intersects(frozenset({"b", "z"}))
        assert not s.intersects(frozenset({"z"}))
        assert intersects(frozenset({"a"}), s)

    def test_to_frozenset(self):
        base = frozenset({"a", "b"})
        s = AtomSet(base)
        assert s.to_frozenset() is base
        assert s.with_added("c").to_frozenset() == {"a", "b", "c"}

    def test_diff_cost_independent_of_base_size(self):
        big = frozenset(f"p{i}" for i in range(100_000))
        s = AtomSet(big)
        hash(s)  # base hash computed once
        t = s.with_added("q").with_removed("p0")
        assert t.diff_size == 2
        assert "q" in t and "p0" not in t and "p1" in t
        assert len(t) == 100_000


class TestSequent:
    def test_from_strings_partitions(self):
        seq = Sequent.from_strings({"a", "b -> c"}, {"d", "~e"})
        assert sorted(seq.gamma_atoms) == ["a"]
        assert {str(s) for s in seq.gamma_complex} == {"(b -> c)"}
        assert sorted(seq.delta_atoms) == ["d"]
        assert {str(s) for s in seq.delta_complex} == {"~e"}
        assert not seq.is_atomic
        assert seq.connectives() == 2

    def test_from_strings_rejects_malformed(self):
        with pytest.raises(ValueError):
            Sequent.from_strings({"(p conj q)"}, set())

    def test_with_and_without(self):
        seq = Sequent.from_strings({"a & b"}, set())
        conj = next(iter(seq.gamma_complex))
        rest = seq.without_left(conj).with_left(conj.left, conj.right)
        assert rest.is_atomic
        assert sorted(rest.gamma_atoms) == ["a", "b"]
        right = seq.with_right(parse_sentence("~c"), parse_sentence("d"))
        assert sorted(right.delta_atoms) == ["d"]
        assert len(right.delta_complex) == 1

    def test_str_matches_legacy_format(self):
        seq = Sequent.from_strings({"b", "a"}, set())
        assert str(seq) == "a, b => ∅"

    def test_hashable_memo_key(self):
        a = Sequent.from_strings({"x", "y -> z"}, {"w"})
        b = Sequent.from_strings({"y -> z", "x"}, {"w"})
        assert a == b and hash(a) == hash(b)


class TestConnectiveCount:
    @pytest.mark.parametrize("text,n", [("a", 0), ("~a", 1), ("a & b", 1),
                                        ("(a | b) -> ~c", 3)])
    def test_counts(self, text, n):
        assert connective_count(parse_sentence(text)) == n


class TestTraceEntry:
    def test_formats(self):
        seq = Sequent.from_strings({"a"}, {"b"})
        assert str(TraceEntry("AXIOM", 1, seq)) == "  AXIOM: a => b"
        assert str(TraceEntry("FAIL", 0, seq)) == "FAIL: a => b"
        assert str(TraceEntry("DEPTH LIMIT", 2)) == "    DEPTH LIMIT"
        s = parse_sentence("~a")
        assert str(TraceEntry("RULE", 0, seq, "L¬", s)) == "[L¬] on ~a"
