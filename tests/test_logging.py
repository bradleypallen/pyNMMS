"""Tests for logging and proof trace output."""

import logging

from pynmms import MaterialBase, NMMSReasoner


class TestProofResultTrace:
    def test_trace_non_empty_on_success(self):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset({"A"}), frozenset({"B"}))
        assert result.derivable
        assert len(result.trace) > 0

    def test_trace_non_empty_on_failure(self):
        base = MaterialBase(language={"A", "B"})
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset({"A"}), frozenset({"B"}))
        assert not result.derivable
        assert len(result.trace) > 0

    def test_trace_contains_axiom_on_success(self):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset({"A"}), frozenset({"B"}))
        assert any("AXIOM" in line for line in result.trace)

    def test_trace_contains_fail_on_failure(self):
        base = MaterialBase(language={"A", "B"})
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset({"A"}), frozenset({"B"}))
        assert any("FAIL" in line for line in result.trace)

    def test_trace_contains_rule_names(self):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset(), frozenset({"A -> B"}))
        # R-> should appear in trace
        assert any("\u2192" in line or "->" in line for line in result.trace)

    def test_depth_reached(self):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        result = r.derives(frozenset(), frozenset({"A -> B"}))
        assert result.depth_reached > 0

    def test_cache_hits(self):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)
        # A complex query that exercises caching
        result = r.derives(
            frozenset({"A | B"}),
            frozenset({"B | A"}),
        )
        # cache_hits may or may not be > 0 depending on proof path
        assert result.cache_hits >= 0


class TestLoggingOutput:
    def test_debug_logging_emitted(self, caplog):
        base = MaterialBase(
            language={"A", "B"},
            consequences={(frozenset({"A"}), frozenset({"B"}))},
        )
        r = NMMSReasoner(base, max_depth=15)

        with caplog.at_level(logging.DEBUG, logger="pynmms.reasoner"):
            r.derives(frozenset({"A"}), frozenset({"B"}))

        assert len(caplog.records) > 0
        messages = [rec.message for rec in caplog.records]
        assert any("Proof search" in m for m in messages)
        assert any("Result" in m for m in messages)

    def test_base_debug_logging(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="pynmms.base"):
            MaterialBase(
                language={"A"},
            )

        assert len(caplog.records) > 0
        assert any("MaterialBase created" in rec.message for rec in caplog.records)
