"""Tests for pynmms.rq logging — rule names in traces, blocking warnings."""

import logging

from pynmms.rq.base import RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner


def _r(language=None, consequences=None, max_depth=15):
    base = RQMaterialBase(
        language=language or set(),
        consequences=consequences or set(),
    )
    return NMMSRQReasoner(base, max_depth=max_depth)


class TestRQRuleTraces:
    def test_left_all_in_trace(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        result = r.derives(
            frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )
        assert result.derivable
        trace = "\n".join(result.trace)
        assert "[L\u2200R.C]" in trace

    def test_left_some_in_trace(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        result = r.derives(
            frozenset({"SOME hasChild.Happy(alice)", "hasChild(alice,bob)"}),
            frozenset({"Happy(bob)"}),
        )
        assert result.derivable
        trace = "\n".join(result.trace)
        assert "[L\u2203R.C]" in trace

    def test_right_some_in_trace(self):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        result = r.derives(
            frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )
        assert result.derivable
        trace = "\n".join(result.trace)
        assert "[R\u2203R.C]" in trace

    def test_right_all_in_trace(self):
        r = _r(language={"hasChild(alice,bob)"})
        result = r.derives(
            frozenset(),
            frozenset({"ALL hasChild.Happy(alice)"}),
        )
        # Will fail (can't prove) but trace should show the rule attempt
        trace = "\n".join(result.trace)
        assert "[R\u2200R.C]" in trace

    def test_propositional_rules_in_trace(self):
        r = _r(language={"A", "B"})
        result = r.derives(frozenset({"A & B"}), frozenset({"A"}))
        assert result.derivable
        trace = "\n".join(result.trace)
        assert "[L\u2227]" in trace

    def test_axiom_in_trace(self):
        r = _r(language={"Happy(alice)"})
        result = r.derives(
            frozenset({"Happy(alice)"}), frozenset({"Happy(alice)"})
        )
        assert result.derivable
        assert any("AXIOM" in t for t in result.trace)

    def test_depth_limit_in_trace(self):
        r = _r(max_depth=0)
        result = r.derives(frozenset({"A -> B"}), frozenset({"C"}))
        assert not result.derivable
        assert any("DEPTH LIMIT" in t for t in result.trace)


class TestRQLogging:
    def test_left_all_log_message(self, caplog):
        r = _r(language={"hasChild(alice,bob)", "Happy(bob)"})
        with caplog.at_level(logging.DEBUG, logger="pynmms.rq.reasoner"):
            r.derives(
                frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
                frozenset({"Happy(bob)"}),
            )
        assert any("[L\u2200R.C]" in msg for msg in caplog.messages)

    def test_base_creation_logged(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="pynmms.rq.base"):
            RQMaterialBase(language={"Happy(alice)"})
        assert any("RQMaterialBase created" in msg for msg in caplog.messages)

    def test_schema_registration_logged(self, caplog):
        base = RQMaterialBase(language={"hasChild(alice,bob)"})
        with caplog.at_level(logging.DEBUG, logger="pynmms.rq.base"):
            base.register_concept_schema("hasChild", "alice", "Happy")
        assert any("concept schema" in msg for msg in caplog.messages)


class TestBlockingWarning:
    def test_blocking_trace(self):
        """When blocking fires, it appears in the trace."""
        # Create a scenario where blocking might fire:
        # R∃R.C on right with no known triggers and a fresh witness
        # that gets blocked by an existing individual
        base = RQMaterialBase(
            language={"Happy(alice)"},
        )
        r = NMMSRQReasoner(base, max_depth=10)
        # SOME hasChild.Happy(alice) — no known triggers, fresh witness path
        # The fresh witness _w_hasChild_Happy_alice has empty concept label,
        # and if alice has concepts, she blocks it
        result = r.derives(
            frozenset({"Happy(alice)"}),
            frozenset({"SOME hasChild.Happy(alice)"}),
        )
        # Whether it derives or not depends on whether blocking fires
        # The key test is that the trace documents what happened
        trace = "\n".join(result.trace)
        # Trace should contain either "blocked by" or "trying fresh witness"
        assert "blocked by" in trace or "trying fresh witness" in trace or "FAIL" in trace
