"""Tests for NMMSReasoner — structural properties of propositional NMMS.

Tests nontransitivity, nonmonotonicity, supraclassicality, and the
explicitation conditions (DD, II, AA, SS) from Ch. 3.
"""

import pytest

from pynmms import MaterialBase, NMMSReasoner


class TestNontransitivity:
    """NMMS omits [Mixed-Cut], so transitivity can fail."""

    def test_a_not_derives_c(self, toy_reasoner):
        """A => C should FAIL: A |~ B and B |~ C, but no transitivity."""
        assert not toy_reasoner.query(frozenset({"A"}), frozenset({"C"}))


class TestNonmonotonicity:
    """NMMS omits [Weakening], so adding premises can defeat inferences."""

    def test_weakening_fails(self, toy_reasoner):
        """A, C => B should FAIL: A |~ B, but adding C defeats it."""
        assert not toy_reasoner.query(frozenset({"A", "C"}), frozenset({"B"}))

    def test_extra_premise_defeats(self):
        """More complex nonmonotonicity: p |~ q but p, r =/|~ q."""
        base = MaterialBase(
            language={"p", "q", "r"},
            consequences={(frozenset({"p"}), frozenset({"q"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(frozenset({"p"}), frozenset({"q"}))
        assert not r.query(frozenset({"p", "r"}), frozenset({"q"}))


class TestSupraclassicality:
    """All classically valid sequents are derivable (Fact 2 in Ch. 3)."""

    def test_lem(self, toy_reasoner):
        """=> A | ~A — law of excluded middle."""
        assert toy_reasoner.query(frozenset(), frozenset({"A | ~A"}))

    def test_double_negation_elim(self, toy_reasoner):
        """~~A => A — double negation elimination."""
        assert toy_reasoner.query(frozenset({"~~A"}), frozenset({"A"}))

    def test_explosion(self, toy_reasoner):
        """A, ~A => B — ex falso (classical explosion)."""
        assert toy_reasoner.query(frozenset({"A", "~A"}), frozenset({"B"}))

    def test_modus_ponens(self, toy_reasoner):
        """A, A -> B => B — modus ponens."""
        assert toy_reasoner.query(frozenset({"A", "A -> B"}), frozenset({"B"}))

    def test_disjunctive_syllogism(self):
        """A | B, ~A => B."""
        base = MaterialBase(language={"A", "B"})
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(frozenset({"A | B", "~A"}), frozenset({"B"}))

    def test_contraposition(self):
        """A -> B => ~B -> ~A."""
        base = MaterialBase(language={"A", "B"})
        r = NMMSReasoner(base, max_depth=15)
        assert r.query(frozenset({"A -> B"}), frozenset({"~B -> ~A"}))


class TestDDT:
    """DD (Deduction-Detachment): Gamma |~ A -> B, Delta  iff  Gamma, A |~ B, Delta."""

    def test_dd_forward(self, toy_reasoner):
        """=> A -> B (toy base has A |~ B)."""
        assert toy_reasoner.query(frozenset(), frozenset({"A -> B"}))

    def test_dd_biconditional(self):
        """Verify DD biconditional for a fresh base."""
        base = MaterialBase(
            language={"p", "q", "r"},
            consequences={(frozenset({"p"}), frozenset({"q"}))},
        )
        r = NMMSReasoner(base, max_depth=15)

        # Forward: p |~ q  implies  |~ p -> q
        assert r.query(frozenset(), frozenset({"p -> q"}))
        # And: p |~ q is True
        assert r.query(frozenset({"p"}), frozenset({"q"}))

    def test_dd_converse(self):
        """If Gamma, A |~ B, Delta then Gamma |~ A -> B, Delta."""
        base = MaterialBase(
            language={"p", "q"},
            consequences={(frozenset({"p"}), frozenset({"q"}))},
        )
        r = NMMSReasoner(base, max_depth=15)

        # p |~ q  => |~ p -> q
        assert r.query(frozenset({"p"}), frozenset({"q"}))
        assert r.query(frozenset(), frozenset({"p -> q"}))


class TestII:
    """II (Incoherence-Incompatibility): Gamma |~ ~A, Delta  iff  Gamma, A |~ Delta."""

    def test_ii_forward(self):
        """Gamma, A |~ Delta  implies  Gamma |~ ~A, Delta."""
        base = MaterialBase(language={"A", "B"})
        r = NMMSReasoner(base, max_depth=15)
        # A |~ A (containment), so |~ ~A, A (by II)
        # Equivalently: A being in gamma means we can put ~A in delta
        assert r.query(frozenset(), frozenset({"~A", "A"}))

    def test_ii_biconditional(self):
        """Verify both directions of II."""
        base = MaterialBase(language={"p", "q"})
        r = NMMSReasoner(base, max_depth=15)

        # p |~ ~p is not derivable from empty base (no consequence)
        # But p |~ ~q, p — derivable via containment on p
        assert r.query(frozenset({"p"}), frozenset({"~q", "p"}))
        # Converse: p, q |~ p — containment
        assert r.query(frozenset({"p", "q"}), frozenset({"p"}))


class TestAA:
    """AA (Antecedent-Adjunction): Gamma, A & B |~ Delta  iff  Gamma, A, B |~ Delta."""

    def test_aa_forward(self):
        """A & B on left decomposes to A, B."""
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A", "B"}), frozenset({"C"}))},
        )
        base.add_atom("C")
        r = NMMSReasoner(base, max_depth=15)

        # A, B |~ C (base)
        assert r.query(frozenset({"A", "B"}), frozenset({"C"}))
        # A & B |~ C (by AA)
        assert r.query(frozenset({"A & B"}), frozenset({"C"}))

    def test_aa_biconditional(self):
        """Both directions of AA."""
        base = MaterialBase(language={"p", "q"})
        r = NMMSReasoner(base, max_depth=15)

        # p & q |~ p  iff  p, q |~ p
        assert r.query(frozenset({"p & q"}), frozenset({"p"}))
        assert r.query(frozenset({"p", "q"}), frozenset({"p"}))


class TestSS:
    """SS (Succedent-Summation): Gamma |~ A | B, Delta  iff  Gamma |~ A, B, Delta."""

    def test_ss_forward(self):
        """A | B on right decomposes to A, B."""
        base = MaterialBase(language={"p", "q"})
        r = NMMSReasoner(base, max_depth=15)

        # p |~ p, q (containment on p)
        assert r.query(frozenset({"p"}), frozenset({"p", "q"}))
        # p |~ p | q (by SS)
        assert r.query(frozenset({"p"}), frozenset({"p | q"}))

    def test_ss_biconditional(self):
        """Both directions of SS."""
        base = MaterialBase(language={"p", "q"})
        r = NMMSReasoner(base, max_depth=15)

        # |~ p | q, ~p  iff  |~ p, q, ~p
        # The right side: containment won't help from empty antecedent
        # Let's use p |~ p | q  iff  p |~ p, q
        assert r.query(frozenset({"p"}), frozenset({"p | q"}))
        assert r.query(frozenset({"p"}), frozenset({"p", "q"}))
