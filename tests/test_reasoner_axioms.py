"""Tests for NMMSReasoner — axiom-level derivability.

Corresponds to Demo 1 (axiom-level checks on the toy base).
"""


class TestAxioms:
    """Basic axiom derivability from the toy base."""

    def test_containment_a_derives_a(self, toy_reasoner):
        """A => A via Containment (Gamma ∩ Delta ≠ ∅)."""
        result = toy_reasoner.derives(frozenset({"A"}), frozenset({"A"}))
        assert result.derivable

    def test_base_consequence_a_derives_b(self, toy_reasoner):
        """A => B via base consequence."""
        result = toy_reasoner.derives(frozenset({"A"}), frozenset({"B"}))
        assert result.derivable

    def test_base_consequence_b_derives_c(self, toy_reasoner):
        """B => C via base consequence."""
        result = toy_reasoner.derives(frozenset({"B"}), frozenset({"C"}))
        assert result.derivable

    def test_containment_multi_succedent(self, toy_reasoner):
        """A => A, B — derivable via containment (A in both sides)."""
        result = toy_reasoner.derives(frozenset({"A"}), frozenset({"A", "B"}))
        assert result.derivable

    def test_proof_result_has_trace(self, toy_reasoner):
        """ProofResult should contain a non-empty trace."""
        result = toy_reasoner.derives(frozenset({"A"}), frozenset({"B"}))
        assert result.derivable
        assert len(result.trace) > 0

    def test_proof_result_has_depth(self, toy_reasoner):
        """ProofResult should track depth_reached."""
        result = toy_reasoner.derives(frozenset({"A"}), frozenset({"B"}))
        assert result.depth_reached >= 0
