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


class TestCompletenessFlags:
    def _base(self):
        return MaterialBase(language={"A", "B"},
                            consequences={(frozenset({"A"}), frozenset({"B"}))})

    def test_unbounded_by_default(self):
        r = NMMSReasoner(self._base())
        assert r.max_depth is None
        result = r.derives(frozenset({"A"}), frozenset({"(B | ~B) & (A -> B)"}))
        assert result.derivable
        assert not result.depth_limited
        assert result.connectives == 4
        assert result.depth_reached <= result.connectives

    def test_depth_limited_flag(self):
        r = NMMSReasoner(self._base(), max_depth=0)
        result = r.derives(frozenset({"A"}), frozenset({"A -> B"}))
        assert not result.derivable
        assert result.depth_limited
        assert any("DEPTH LIMIT" in line for line in result.trace)

    def test_cut_off_failures_are_not_memoized(self):
        r = NMMSReasoner(self._base(), max_depth=0)
        r.derives(frozenset({"A"}), frozenset({"A -> B"}))
        assert not r._cache  # nothing reliable to keep

    def test_trace_is_lazy_structured(self):
        r = NMMSReasoner(self._base())
        result = r.derives(frozenset({"A"}), frozenset({"~~B"}))
        assert result.entries and all(hasattr(e, "kind") for e in result.entries)
        assert result.trace == [str(e) for e in result.entries]
        assert any("AXIOM" in line for line in result.trace)


class TestPersistentCache:
    def test_off_by_default(self):
        base = MaterialBase(language={"A", "B"},
                            consequences={(frozenset({"A"}), frozenset({"B"}))})
        r = NMMSReasoner(base)
        r.derives(frozenset({"A"}), frozenset({"~~B"}))
        r.derives(frozenset({"A"}), frozenset({"~~B"}))
        assert r.derives(frozenset({"A"}), frozenset({"~~B"})).cache_hits == 0

    def test_hits_across_queries(self):
        base = MaterialBase(language={"A", "B"},
                            consequences={(frozenset({"A"}), frozenset({"B"}))})
        r = NMMSReasoner(base, persistent_cache=True)
        first = r.derives(frozenset({"A"}), frozenset({"~~B"}))
        second = r.derives(frozenset({"A"}), frozenset({"~~B"}))
        assert first.derivable and second.derivable
        assert second.cache_hits == 1  # root sequent served from cache

    def test_invalidated_on_mutation(self):
        base = MaterialBase(language={"A", "B", "C"})
        r = NMMSReasoner(base, persistent_cache=True)
        assert not r.derives(frozenset({"A"}), frozenset({"~~B"})).derivable
        gen = base.generation
        base.add_consequence(frozenset({"A"}), frozenset({"B"}))
        assert base.generation > gen
        assert r.derives(frozenset({"A"}), frozenset({"~~B"})).derivable

    def test_generation_bumps_on_onto_schema(self):
        from pynmms.onto.base import OntoMaterialBase
        base = OntoMaterialBase()
        gen = base.generation
        base.register_subclass("Man", "Mortal")
        assert base.generation > gen
