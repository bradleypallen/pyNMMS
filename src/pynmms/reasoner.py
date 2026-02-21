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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pynmms.base import MaterialBase
from pynmms.syntax import ATOM, CONJ, DISJ, IMPL, NEG, parse_sentence

logger = logging.getLogger(__name__)


@dataclass
class ProofResult:
    """Result of a proof search.

    Attributes:
        derivable: Whether the sequent is derivable.
        trace: Human-readable proof trace.
        depth_reached: Maximum proof depth reached.
        cache_hits: Number of memoization cache hits.
    """

    derivable: bool
    trace: list[str] = field(default_factory=list)
    depth_reached: int = 0
    cache_hits: int = 0


def _fmt(fs: frozenset[str]) -> str:
    """Format a frozenset for display."""
    if not fs:
        return "\u2205"
    return ", ".join(sorted(fs))


class NMMSReasoner:
    """Proof search for propositional NMMS sequent calculus.

    Performs backward (root-first) proof search with memoization and
    depth-limited search. A sequent Gamma => Delta is derivable iff
    all leaves of its proof tree are axioms of the material base.

    Parameters:
        base: The material base providing axioms.
        max_depth: Maximum proof depth (default 25).
    """

    def __init__(self, base: MaterialBase, *, max_depth: int = 25) -> None:
        self.base = base
        self.max_depth = max_depth
        self._trace: list[str] = []
        self._cache: dict[tuple[frozenset[str], frozenset[str]], bool] = {}
        self._depth_reached: int = 0
        self._cache_hits: int = 0

    def derives(self, antecedent: frozenset[str], consequent: frozenset[str]) -> ProofResult:
        """Check if ``antecedent => consequent`` is derivable in NMMS_B.

        Returns a ``ProofResult`` with derivability, proof trace, and statistics.
        """
        self._trace = []
        self._cache = {}
        self._depth_reached = 0
        self._cache_hits = 0

        logger.debug("Proof search: %s => %s", _fmt(antecedent), _fmt(consequent))
        result = self._prove(antecedent, consequent, depth=0)
        logger.debug("Result: %s (depth %d, cache hits %d)",
                      result, self._depth_reached, self._cache_hits)

        return ProofResult(
            derivable=result,
            trace=list(self._trace),
            depth_reached=self._depth_reached,
            cache_hits=self._cache_hits,
        )

    def query(self, antecedent: frozenset[str], consequent: frozenset[str]) -> bool:
        """Convenience method: return only the derivability boolean."""
        return self.derives(antecedent, consequent).derivable

    # ------------------------------------------------------------------
    # Internal proof search
    # ------------------------------------------------------------------

    def _prove(self, gamma: frozenset[str], delta: frozenset[str], depth: int) -> bool:
        """Backward proof search with memoization."""
        indent = "  " * depth
        self._depth_reached = max(self._depth_reached, depth)

        if depth > self.max_depth:
            msg = f"{indent}DEPTH LIMIT"
            self._trace.append(msg)
            logger.debug(msg)
            return False

        # Memoization
        key = (gamma, delta)
        if key in self._cache:
            self._cache_hits += 1
            return self._cache[key]

        # Check axiom
        if self.base.is_axiom(gamma, delta):
            msg = f"{indent}AXIOM: {_fmt(gamma)} => {_fmt(delta)}"
            self._trace.append(msg)
            logger.debug(msg)
            self._cache[key] = True
            return True

        # Mark as False initially to detect cycles
        self._cache[key] = False

        result = self._try_left_rules(gamma, delta, depth) or self._try_right_rules(
            gamma, delta, depth
        )

        self._cache[key] = result
        if not result:
            msg = f"{indent}FAIL: {_fmt(gamma)} => {_fmt(delta)}"
            self._trace.append(msg)
            logger.debug(msg)
        return result

    # ------------------------------------------------------------------
    # LEFT RULES
    # ------------------------------------------------------------------

    def _try_left_rules(
        self, gamma: frozenset[str], delta: frozenset[str], depth: int
    ) -> bool:
        indent = "  " * depth

        for s in sorted(gamma):  # sorted for determinism
            parsed = parse_sentence(s)
            rest = gamma - {s}

            # [L~]: Gamma, ~A => Delta  <-  Gamma => Delta, A
            if parsed.type == NEG:
                assert parsed.sub is not None
                a = str(parsed.sub)
                msg = f"{indent}[L\u00ac] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if self._prove(rest, delta | {a}, depth + 1):
                    return True

            # [L->]: Gamma, A->B => Delta  <-  (1) Gamma => Delta, A
            #                                   (2) Gamma, B => Delta
            #                                   (3) Gamma, B => Delta, A
            elif parsed.type == IMPL:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[L\u2192] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if (
                    self._prove(rest, delta | {a}, depth + 1)
                    and self._prove(rest | {b}, delta, depth + 1)
                    and self._prove(rest | {b}, delta | {a}, depth + 1)
                ):
                    return True

            # [L&]: Gamma, A & B => Delta  <-  Gamma, A, B => Delta
            elif parsed.type == CONJ:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[L\u2227] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if self._prove(rest | {a, b}, delta, depth + 1):
                    return True

            # [L|]: Gamma, A | B => Delta  <-  (1) Gamma, A => Delta
            #                                   (2) Gamma, B => Delta
            #                                   (3) Gamma, A, B => Delta
            elif parsed.type == DISJ:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[L\u2228] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if (
                    self._prove(rest | {a}, delta, depth + 1)
                    and self._prove(rest | {b}, delta, depth + 1)
                    and self._prove(rest | {a, b}, delta, depth + 1)
                ):
                    return True

        return False

    # ------------------------------------------------------------------
    # RIGHT RULES
    # ------------------------------------------------------------------

    def _try_right_rules(
        self, gamma: frozenset[str], delta: frozenset[str], depth: int
    ) -> bool:
        indent = "  " * depth

        for s in sorted(delta):
            parsed = parse_sentence(s)
            rest = delta - {s}

            # [R~]: Gamma => Delta, ~A  <-  Gamma, A => Delta
            if parsed.type == NEG:
                assert parsed.sub is not None
                a = str(parsed.sub)
                msg = f"{indent}[R\u00ac] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if self._prove(gamma | {a}, rest, depth + 1):
                    return True

            # [R->]: Gamma => Delta, A->B  <-  Gamma, A => Delta, B
            elif parsed.type == IMPL:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[R\u2192] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if self._prove(gamma | {a}, rest | {b}, depth + 1):
                    return True

            # [R&]: Gamma => Delta, A & B  <-  (1) Gamma => Delta, A
            #                                   (2) Gamma => Delta, B
            #                                   (3) Gamma => Delta, A, B
            elif parsed.type == CONJ:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[R\u2227] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if (
                    self._prove(gamma, rest | {a}, depth + 1)
                    and self._prove(gamma, rest | {b}, depth + 1)
                    and self._prove(gamma, rest | {a, b}, depth + 1)
                ):
                    return True

            # [R|]: Gamma => Delta, A | B  <-  Gamma => Delta, A, B
            elif parsed.type == DISJ:
                assert parsed.left is not None and parsed.right is not None
                a, b = str(parsed.left), str(parsed.right)
                msg = f"{indent}[R\u2228] on {s}"
                self._trace.append(msg)
                logger.debug(msg)
                if self._prove(gamma, rest | {a, b}, depth + 1):
                    return True

        return False
