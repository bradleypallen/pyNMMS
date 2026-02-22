"""NMMS proof search with restricted quantifier rules.

Extends the propositional ``NMMSReasoner`` with four quantifier rules:

Left rules:
    [L-ALL-R.C]  Gamma, ALL R.C(a) => Delta
                 <- Gamma, {C(b) | R(a,b) in Gamma} => Delta
    [L-SOME-R.C] Gamma, SOME R.C(a) => Delta
                 <- for all nonempty subsets S of triggered {C(b)}:
                    Gamma, S => Delta

Right rules:
    [R-SOME-R.C] Gamma => Delta, SOME R.C(a)
                 <- (i) known witnesses: Gamma => Delta, C(b) for R(a,b) in Gamma
                    (ii) fresh canonical witness with blocking
    [R-ALL-R.C]  Gamma => Delta, ALL R.C(a)
                 <- Gamma, R(a,b) => Delta, C(b)  for fresh eigenvariable b
"""

from __future__ import annotations

import logging
import warnings
from itertools import combinations

from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner
from pynmms.rq.syntax import (
    ALL_RESTRICT,
    SOME_RESTRICT,
    RQSentence,
    collect_individuals,
    find_blocking_individual,
    find_role_triggers,
    fresh_individual,
    make_concept_assertion,
    make_role_assertion,
    parse_rq_sentence,
)
from pynmms.syntax import CONJ, DISJ, IMPL, NEG, Sentence

logger = logging.getLogger(__name__)

_BLOCKING_WARNING_ISSUED = False


class NMMSRQReasoner(NMMSReasoner):
    """Proof search for NMMS with restricted quantifiers.

    Extends ``NMMSReasoner`` by overriding ``_try_left_rules`` and
    ``_try_right_rules`` to handle both propositional and RQ sentence
    types in a single pass using ``parse_rq_sentence``.
    """

    def __init__(self, base: MaterialBase, *, max_depth: int = 25) -> None:
        super().__init__(base, max_depth=max_depth)

    # ------------------------------------------------------------------
    # LEFT RULES (propositional + quantifier)
    # ------------------------------------------------------------------

    def _try_left_rules(
        self, gamma: frozenset[str], delta: frozenset[str], depth: int
    ) -> bool:
        indent = "  " * depth

        for s in sorted(gamma):  # sorted for determinism
            parsed = parse_rq_sentence(s)
            rest = gamma - {s}

            if isinstance(parsed, Sentence):
                # Propositional rules
                # [L~]: Gamma, ~A => Delta  <-  Gamma => Delta, A
                if parsed.type == NEG:
                    assert parsed.sub is not None
                    a = str(parsed.sub)
                    msg = f"{indent}[L\u00ac] on {s}"
                    self._trace.append(msg)
                    logger.debug(msg)
                    if self._prove(rest, delta | {a}, depth + 1):
                        return True

                # [L->]: 3 subgoals
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

                # [L|]: 3 subgoals
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

            elif isinstance(parsed, RQSentence):
                # [L-ALL-R.C]: Gamma, ALL R.C(a) => Delta
                #   Adjunction (OQ-1, option A): one subgoal adding all
                #   triggered instances.
                if parsed.type == ALL_RESTRICT:
                    role_name = parsed.role
                    concept = parsed.concept
                    subject = parsed.individual
                    assert role_name is not None
                    assert concept is not None
                    assert subject is not None
                    triggers = find_role_triggers(rest, role_name, subject)

                    if triggers:
                        instances = frozenset(
                            make_concept_assertion(concept, b) for b in triggers
                        )
                        msg = (
                            f"{indent}[L\u2200R.C] on {s}, "
                            f"triggers: {sorted(triggers)} "
                            f"\u2192 adding {sorted(instances)}"
                        )
                        self._trace.append(msg)
                        logger.debug(msg)
                        if self._prove(rest | instances, delta, depth + 1):
                            return True

                # [L-SOME-R.C]: Gamma, SOME R.C(a) => Delta
                #   Ketonen pattern: all 2^k - 1 nonempty subsets of
                #   triggered instances must independently prove the
                #   conclusion.
                elif parsed.type == SOME_RESTRICT:
                    role_name = parsed.role
                    concept = parsed.concept
                    subject = parsed.individual
                    assert role_name is not None
                    assert concept is not None
                    assert subject is not None
                    triggers = find_role_triggers(rest, role_name, subject)

                    if triggers:
                        instance_list = [
                            make_concept_assertion(concept, b) for b in triggers
                        ]
                        msg = (
                            f"{indent}[L\u2203R.C] on {s}, "
                            f"triggers: {sorted(triggers)} "
                            f"\u2192 Ketonen over {len(instance_list)} instances "
                            f"({2**len(instance_list) - 1} subsets)"
                        )
                        self._trace.append(msg)
                        logger.debug(msg)

                        all_ok = True
                        for r in range(1, len(instance_list) + 1):
                            for subset in combinations(instance_list, r):
                                if not self._prove(
                                    rest | frozenset(subset), delta, depth + 1
                                ):
                                    all_ok = False
                                    break
                            if not all_ok:
                                break

                        if all_ok:
                            return True

        return False

    # ------------------------------------------------------------------
    # RIGHT RULES (propositional + quantifier)
    # ------------------------------------------------------------------

    def _try_right_rules(
        self, gamma: frozenset[str], delta: frozenset[str], depth: int
    ) -> bool:
        global _BLOCKING_WARNING_ISSUED
        indent = "  " * depth

        for s in sorted(delta):
            parsed = parse_rq_sentence(s)
            rest = delta - {s}

            if isinstance(parsed, Sentence):
                # Propositional rules
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

                # [R&]: 3 subgoals
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

            elif isinstance(parsed, RQSentence):
                # [R-SOME-R.C]: Gamma => Delta, SOME R.C(a)
                #   (i) known witnesses, (ii) fresh canonical with blocking
                if parsed.type == SOME_RESTRICT:
                    role_name = parsed.role
                    concept = parsed.concept
                    subject = parsed.individual
                    assert role_name is not None
                    assert concept is not None
                    assert subject is not None

                    used = collect_individuals(gamma | delta)
                    known_triggers = find_role_triggers(gamma, role_name, subject)

                    msg = (
                        f"{indent}[R\u2203R.C] on {s}, "
                        f"known witnesses: {sorted(known_triggers)}"
                    )
                    self._trace.append(msg)
                    logger.debug(msg)

                    # Strategy (i): known witnesses
                    for b in known_triggers:
                        c_b = make_concept_assertion(concept, b)
                        if self._prove(gamma, rest | {c_b}, depth + 1):
                            return True

                    # Strategy (ii): fresh canonical witness
                    canonical_fresh = f"_w_{role_name}_{concept}_{subject}"

                    if canonical_fresh not in used:
                        blocker = find_blocking_individual(
                            canonical_fresh, gamma, delta, used
                        )
                        if blocker is not None:
                            if not _BLOCKING_WARNING_ISSUED:
                                warnings.warn(
                                    "Concept-label blocking is an experimental "
                                    "conjecture. See RQ documentation for details.",
                                    stacklevel=2,
                                )
                                _BLOCKING_WARNING_ISSUED = True
                            block_msg = (
                                f"{indent}  fresh {canonical_fresh} "
                                f"blocked by {blocker}"
                            )
                            self._trace.append(block_msg)
                            logger.warning(
                                "Blocking fired: %s blocked by %s",
                                canonical_fresh,
                                blocker,
                            )
                        else:
                            c_b = make_concept_assertion(concept, canonical_fresh)
                            r_ab = make_role_assertion(
                                role_name, subject, canonical_fresh
                            )
                            fresh_msg = (
                                f"{indent}  trying fresh witness {canonical_fresh}"
                            )
                            self._trace.append(fresh_msg)
                            logger.debug(fresh_msg)
                            if self._prove(
                                gamma | {r_ab}, rest | {c_b}, depth + 1
                            ):
                                return True

                # [R-ALL-R.C]: Gamma => Delta, ALL R.C(a)
                #   Fresh eigenvariable, prove Gamma, R(a,b) => Delta, C(b)
                elif parsed.type == ALL_RESTRICT:
                    role_name = parsed.role
                    concept = parsed.concept
                    subject = parsed.individual
                    assert role_name is not None
                    assert concept is not None
                    assert subject is not None

                    canonical_eigen = f"_e_{role_name}_{concept}_{subject}"
                    used = collect_individuals(gamma | delta)

                    if canonical_eigen in used:
                        b = fresh_individual(
                            used, prefix=canonical_eigen + "_"
                        )
                    else:
                        b = canonical_eigen

                    r_ab = make_role_assertion(role_name, subject, b)
                    c_b = make_concept_assertion(concept, b)

                    msg = f"{indent}[R\u2200R.C] on {s}, eigen {b}"
                    self._trace.append(msg)
                    logger.debug(msg)

                    if self._prove(gamma | {r_ab}, rest | {c_b}, depth + 1):
                        return True

        return False
