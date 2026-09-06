"""NMMS proof search for propositional sequent calculus.

Implements root-first backward proof search for the Non-Monotonic Multi-Succedent
sequent calculus from Hlobil & Brandom 2025, Ch. 3 (Definition 20 in the appendix).

The 8 propositional rules (Ketonen-style with third top sequent):

Left rules:
    [L~]  Gamma, ~A => Delta        <-  Gamma => Delta, A
    [L->] Gamma, A->B => Delta      <-  Gamma => Delta, A
                                     AND Gamma, B => Delta
                                     AND Gamma, B => Delta, A
    [L&]  Gamma, A & B => Delta      <-  Gamma, A, B => Delta
    [L|]  Gamma, A | B => Delta      <-  Gamma, A => Delta
                                     AND Gamma, B => Delta
                                     AND Gamma, A, B => Delta

Right rules:
    [R~]  Gamma => Delta, ~A         <-  Gamma, A => Delta
    [R->] Gamma => Delta, A->B       <-  Gamma, A => Delta, B
    [R&]  Gamma => Delta, A & B      <-  Gamma => Delta, A
                                     AND Gamma => Delta, B
                                     AND Gamma => Delta, A, B
    [R|]  Gamma => Delta, A | B      <-  Gamma => Delta, A, B

The multi-premise rules include a third top sequent containing all active formulae
from the other premises on the same sides. This compensates for the absence of
structural contraction while preserving idempotency (see Ch. 3, Section 3.2).

Completeness. Every rule replaces one connective occurrence by premises with
strictly fewer connectives, so proof depth is bounded by the number of
connective occurrences in the queried sequent and a sequent can never recur on
its own search path. The search is therefore complete when ``max_depth`` is
``None`` (the default). A caller-supplied ``max_depth`` can make the search
give up; ``ProofResult.depth_limited`` reports when that happened, and results
that depended on a cut-off branch are not memoized.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from pynmms.base import MaterialBase
from pynmms.sequent import RULE_LABELS, Sequent, TraceEntry
from pynmms.syntax import CONJ, DISJ, IMPL, NEG, Sentence

logger = logging.getLogger(__name__)


@dataclass
class ProofResult:
    """Result of a proof search.

    Attributes:
        derivable: Whether the sequent is derivable.
        entries: Structured proof trace; ``str(entry)`` gives the display line.
        depth_reached: Maximum proof depth reached.
        cache_hits: Number of memoization cache hits.
        depth_limited: True if the search gave up on some branch because of
            ``max_depth``. When True, ``derivable == False`` does not mean the
            sequent is underivable.
        connectives: Number of connective occurrences in the queried sequent,
            which bounds the proof depth.
        nodes: Number of distinct proof nodes examined (axiom checks), i.e.
            ``_prove`` calls not served from the cache or cut off by depth.
    """

    derivable: bool
    entries: list[TraceEntry] = field(default_factory=list)
    depth_reached: int = 0
    cache_hits: int = 0
    depth_limited: bool = False
    connectives: int = 0
    nodes: int = 0

    @property
    def trace(self) -> list[str]:
        """Human-readable proof trace, formatted on access."""
        return [str(e) for e in self.entries]


class NMMSReasoner:
    """Proof search for propositional NMMS sequent calculus.

    Performs backward (root-first) proof search with memoization. A sequent
    Gamma => Delta is derivable iff all leaves of its proof tree are axioms of
    the material base.

    Parameters:
        base: The material base providing axioms.
        max_depth: Optional cap on proof depth. ``None`` (default) means no
            cap; depth is then bounded by the query's connective count.
        persistent_cache: Keep the memo cache across ``derives`` calls. It is
            cleared automatically whenever the base's ``generation`` changes,
            so it is only worth enabling for many queries against a fixed base.
    """

    def __init__(
        self,
        base: MaterialBase,
        *,
        max_depth: int | None = None,
        persistent_cache: bool = False,
    ) -> None:
        self.base = base
        self.max_depth = max_depth
        self.persistent_cache = persistent_cache
        self._trace: list[TraceEntry] = []
        self._cache: dict[Sequent, bool] = {}
        self._cache_generation: int = -1
        self._depth_reached: int = 0
        self._cache_hits: int = 0
        self._limit_hits: int = 0
        self._nodes: int = 0

    def derives(self, antecedent: Iterable[str], consequent: Iterable[str]) -> ProofResult:
        """Check if ``antecedent => consequent`` is derivable in NMMS_B.

        Sentences are parsed once here; a malformed sentence raises ValueError.
        Returns a ``ProofResult`` with derivability, proof trace, and statistics.
        """
        sequent = Sequent.from_strings(antecedent, consequent)
        return self.derives_sequent(sequent)

    def derives_sequent(self, sequent: Sequent) -> ProofResult:
        """Run proof search on an already-parsed :class:`Sequent`."""
        self._trace = []
        self._depth_reached = 0
        self._cache_hits = 0
        self._limit_hits = 0
        self._nodes = 0
        generation = self.base.generation
        if not self.persistent_cache or self._cache_generation != generation:
            self._cache = {}
            self._cache_generation = generation

        logger.debug("Proof search: %s", sequent)
        result = self._prove(sequent, depth=0)
        depth_limited = self._limit_hits > 0
        logger.debug(
            "Result: %s (nodes %d, depth %d, cache hits %d, depth limited %s)",
            result, self._nodes, self._depth_reached, self._cache_hits, depth_limited,
        )
        if depth_limited and self.persistent_cache:
            # Never carry results from a truncated search into later queries.
            self._cache = {}

        return ProofResult(
            derivable=result,
            entries=list(self._trace),
            depth_reached=self._depth_reached,
            cache_hits=self._cache_hits,
            depth_limited=depth_limited,
            connectives=sequent.connectives(),
            nodes=self._nodes,
        )

    def query(self, antecedent: Iterable[str], consequent: Iterable[str]) -> bool:
        """Convenience method: return only the derivability boolean."""
        return self.derives(antecedent, consequent).derivable

    # ------------------------------------------------------------------
    # Internal proof search
    # ------------------------------------------------------------------

    def _record(self, entry: TraceEntry) -> None:
        self._trace.append(entry)
        logger.debug("%s", entry)

    def _is_axiom(self, seq: Sequent) -> bool:
        """Axiom check: Containment on either partition, then the base."""
        if seq.gamma_complex and seq.delta_complex and not seq.gamma_complex.isdisjoint(
            seq.delta_complex
        ):
            return True
        if seq.gamma_atoms.intersects(seq.delta_atoms):
            return True
        if seq.is_atomic:
            return self.base.is_axiom(seq.gamma_atoms, seq.delta_atoms)
        return False

    def _prove(self, seq: Sequent, depth: int) -> bool:
        """Backward proof search with memoization."""
        self._depth_reached = max(self._depth_reached, depth)

        if self.max_depth is not None and depth > self.max_depth:
            self._limit_hits += 1
            self._record(TraceEntry("DEPTH LIMIT", depth))
            return False

        cached = self._cache.get(seq)
        if cached is not None:
            self._cache_hits += 1
            return cached

        self._nodes += 1
        if self._is_axiom(seq):
            self._record(TraceEntry("AXIOM", depth, seq))
            self._cache[seq] = True
            return True

        limit_hits_before = self._limit_hits
        result = self._try_left_rules(seq, depth) or self._try_right_rules(seq, depth)

        if result or self._limit_hits == limit_hits_before:
            self._cache[seq] = result
        # else: a failure that depended on a cut-off branch is not a real result.
        if not result:
            self._record(TraceEntry("FAIL", depth, seq))
        return result

    # ------------------------------------------------------------------
    # LEFT RULES
    # ------------------------------------------------------------------

    def _try_left_rules(self, seq: Sequent, depth: int) -> bool:
        for s in sorted(seq.gamma_complex, key=str):  # sorted for determinism
            rest = seq.without_left(s)
            self._record(TraceEntry("RULE", depth, seq, RULE_LABELS[("L", s.type)], s))

            # [L~]: Gamma, ~A => Delta  <-  Gamma => Delta, A
            if s.type == NEG:
                a = _sub(s)
                if self._prove(rest.with_right(a), depth + 1):
                    return True

            # [L->]: Gamma, A->B => Delta  <-  (1) Gamma => Delta, A
            #                                   (2) Gamma, B => Delta
            #                                   (3) Gamma, B => Delta, A
            elif s.type == IMPL:
                a, b = _operands(s)
                if (
                    self._prove(rest.with_right(a), depth + 1)
                    and self._prove(rest.with_left(b), depth + 1)
                    and self._prove(rest.with_left(b).with_right(a), depth + 1)
                ):
                    return True

            # [L&]: Gamma, A & B => Delta  <-  Gamma, A, B => Delta
            elif s.type == CONJ:
                a, b = _operands(s)
                if self._prove(rest.with_left(a, b), depth + 1):
                    return True

            # [L|]: Gamma, A | B => Delta  <-  (1) Gamma, A => Delta
            #                                   (2) Gamma, B => Delta
            #                                   (3) Gamma, A, B => Delta
            elif s.type == DISJ:
                a, b = _operands(s)
                if (
                    self._prove(rest.with_left(a), depth + 1)
                    and self._prove(rest.with_left(b), depth + 1)
                    and self._prove(rest.with_left(a, b), depth + 1)
                ):
                    return True

        return False

    # ------------------------------------------------------------------
    # RIGHT RULES
    # ------------------------------------------------------------------

    def _try_right_rules(self, seq: Sequent, depth: int) -> bool:
        for s in sorted(seq.delta_complex, key=str):
            rest = seq.without_right(s)
            self._record(TraceEntry("RULE", depth, seq, RULE_LABELS[("R", s.type)], s))

            # [R~]: Gamma => Delta, ~A  <-  Gamma, A => Delta
            if s.type == NEG:
                a = _sub(s)
                if self._prove(rest.with_left(a), depth + 1):
                    return True

            # [R->]: Gamma => Delta, A->B  <-  Gamma, A => Delta, B
            elif s.type == IMPL:
                a, b = _operands(s)
                if self._prove(rest.with_left(a).with_right(b), depth + 1):
                    return True

            # [R&]: Gamma => Delta, A & B  <-  (1) Gamma => Delta, A
            #                                   (2) Gamma => Delta, B
            #                                   (3) Gamma => Delta, A, B
            elif s.type == CONJ:
                a, b = _operands(s)
                if (
                    self._prove(rest.with_right(a), depth + 1)
                    and self._prove(rest.with_right(b), depth + 1)
                    and self._prove(rest.with_right(a, b), depth + 1)
                ):
                    return True

            # [R|]: Gamma => Delta, A | B  <-  Gamma => Delta, A, B
            elif s.type == DISJ:
                a, b = _operands(s)
                if self._prove(rest.with_right(a, b), depth + 1):
                    return True

        return False


def _sub(s: Sentence) -> Sentence:
    assert s.sub is not None
    return s.sub


def _operands(s: Sentence) -> tuple[Sentence, Sentence]:
    assert s.left is not None and s.right is not None
    return s.left, s.right
