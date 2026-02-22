"""Sentence parsing for NMMS with restricted quantifiers.

Extends the propositional parser with ALC-style restricted quantifiers
(``ALL R.C(a)``, ``SOME R.C(a)``), concept assertions (``C(a)``), and
role assertions (``R(a,b)``).

Grammar additions (beyond propositional)::

    quantified    ::= ('ALL' | 'SOME') ROLE '.' CONCEPT '(' INDIVIDUAL ')'
    concept_atom  ::= CONCEPT '(' INDIVIDUAL ')'
    role_atom     ::= ROLE '(' INDIVIDUAL ',' INDIVIDUAL ')'

The parser tries RQ-specific patterns first (quantifiers, role assertions,
concept assertions), then falls through to propositional binary connectives,
then bare atoms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pynmms.syntax import ATOM, CONJ, DISJ, IMPL, NEG, Sentence, parse_sentence

# RQ-specific sentence type constants
ATOM_CONCEPT = "concept"
ATOM_ROLE = "role"
ALL_RESTRICT = "all_restrict"
SOME_RESTRICT = "some_restrict"


@dataclass(frozen=True, slots=True)
class RQSentence:
    """Immutable AST node for a restricted-quantifier sentence.

    Attributes:
        type: One of ATOM_CONCEPT, ATOM_ROLE, ALL_RESTRICT, SOME_RESTRICT.
        concept: Concept name (for concept assertions and quantifiers).
        individual: Individual name (for concept assertions and quantifiers).
        role: Role name (for role assertions and quantifiers).
        arg1: First argument of role assertion.
        arg2: Second argument of role assertion.
    """

    type: str
    concept: str | None = None
    individual: str | None = None
    role: str | None = None
    arg1: str | None = None
    arg2: str | None = None

    def __str__(self) -> str:
        if self.type == ATOM_CONCEPT:
            return f"{self.concept}({self.individual})"
        if self.type == ATOM_ROLE:
            return f"{self.role}({self.arg1},{self.arg2})"
        if self.type == ALL_RESTRICT:
            return f"ALL {self.role}.{self.concept}({self.individual})"
        if self.type == SOME_RESTRICT:
            return f"SOME {self.role}.{self.concept}({self.individual})"
        return f"RQSentence({self.type})"  # pragma: no cover


# Pre-compiled regex patterns
_ALL_RE = re.compile(r"^ALL\s+(\w+)\.(\w+)\((\w+)\)$")
_SOME_RE = re.compile(r"^SOME\s+(\w+)\.(\w+)\((\w+)\)$")
_ROLE_RE = re.compile(r"^(\w+)\((\w+)\s*,\s*(\w+)\)$")
_CONCEPT_RE = re.compile(r"^(\w+)\((\w+)\)$")


def parse_rq_sentence(s: str) -> Sentence | RQSentence:
    """Parse a string into a propositional Sentence or RQSentence AST.

    Tries RQ patterns first (quantifiers, role assertions, concept assertions),
    then falls through to propositional binary connectives (recursing with
    ``parse_rq_sentence``), then bare atoms via the propositional parser.
    """
    s = s.strip()
    if not s:
        raise ValueError("Cannot parse empty sentence")

    # Strip outer parens if they wrap the entire expression
    if s.startswith("(") and s.endswith(")"):
        depth = 0
        all_wrapped = True
        for i, c in enumerate(s):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if depth == 0 and i < len(s) - 1:
                all_wrapped = False
                break
        if all_wrapped:
            return parse_rq_sentence(s[1:-1])

    # --- Binary connectives at depth 0, lowest precedence first ---

    # Implication (right-associative, lowest precedence)
    depth = 0
    for i in range(len(s)):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and s[i : i + 2] == "->":
            left_str = s[:i].strip()
            right_str = s[i + 2 :].strip()
            if not left_str or not right_str:
                raise ValueError(f"Malformed implication in: {s!r}")
            return Sentence(
                type=IMPL,
                left=parse_sentence(left_str),
                right=parse_sentence(right_str),
            )

    # Disjunction (left-associative) — find last '|' at depth 0
    depth = 0
    last_disj = -1
    for i, c in enumerate(s):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and c == "|":
            last_disj = i
    if last_disj >= 0:
        left_str = s[:last_disj].strip()
        right_str = s[last_disj + 1 :].strip()
        if not left_str or not right_str:
            raise ValueError(f"Malformed disjunction in: {s!r}")
        return Sentence(
            type=DISJ,
            left=parse_sentence(left_str),
            right=parse_sentence(right_str),
        )

    # Conjunction (left-associative) — find last '&' at depth 0
    depth = 0
    last_conj = -1
    for i, c in enumerate(s):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and c == "&":
            last_conj = i
    if last_conj >= 0:
        left_str = s[:last_conj].strip()
        right_str = s[last_conj + 1 :].strip()
        if not left_str or not right_str:
            raise ValueError(f"Malformed conjunction in: {s!r}")
        return Sentence(
            type=CONJ,
            left=parse_sentence(left_str),
            right=parse_sentence(right_str),
        )

    # Negation
    if s.startswith("~"):
        sub_str = s[1:].strip()
        if not sub_str:
            raise ValueError("Negation with no operand")
        return Sentence(type=NEG, sub=parse_sentence(sub_str))

    # --- RQ-specific atomic patterns ---

    # ALL R.C(a) — universal restriction
    m = _ALL_RE.match(s)
    if m:
        return RQSentence(
            type=ALL_RESTRICT,
            role=m.group(1),
            concept=m.group(2),
            individual=m.group(3),
        )

    # SOME R.C(a) — existential restriction
    m = _SOME_RE.match(s)
    if m:
        return RQSentence(
            type=SOME_RESTRICT,
            role=m.group(1),
            concept=m.group(2),
            individual=m.group(3),
        )

    # Role assertion: R(a,b)
    m = _ROLE_RE.match(s)
    if m:
        return RQSentence(
            type=ATOM_ROLE,
            role=m.group(1),
            arg1=m.group(2),
            arg2=m.group(3),
        )

    # Concept assertion: C(a)
    m = _CONCEPT_RE.match(s)
    if m:
        return RQSentence(
            type=ATOM_CONCEPT,
            concept=m.group(1),
            individual=m.group(2),
        )

    # Fall through to bare atom (propositional)
    return Sentence(type=ATOM, name=s)


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------


def make_concept_assertion(concept: str, individual: str) -> str:
    """Construct ``C(a)`` string."""
    return f"{concept}({individual})"


def make_role_assertion(role: str, arg1: str, arg2: str) -> str:
    """Construct ``R(a,b)`` string."""
    return f"{role}({arg1},{arg2})"


def find_role_triggers(
    gamma: frozenset[str], role_name: str, subject: str
) -> list[str]:
    """Find all individuals *b* such that ``R(subject, b)`` is in *gamma*."""
    triggers: list[str] = []
    for s in gamma:
        parsed = parse_rq_sentence(s)
        if (
            isinstance(parsed, RQSentence)
            and parsed.type == ATOM_ROLE
            and parsed.role == role_name
            and parsed.arg1 == subject
            and parsed.arg2 is not None
        ):
            triggers.append(parsed.arg2)
    return triggers


def collect_individuals(sentences: frozenset[str]) -> set[str]:
    """Extract all individual names mentioned in a set of sentences."""
    individuals: set[str] = set()
    for s in sentences:
        parsed = parse_rq_sentence(s)
        if isinstance(parsed, RQSentence):
            if parsed.type == ATOM_CONCEPT:
                individuals.add(parsed.individual)  # type: ignore[arg-type]
            elif parsed.type == ATOM_ROLE:
                individuals.add(parsed.arg1)  # type: ignore[arg-type]
                individuals.add(parsed.arg2)  # type: ignore[arg-type]
            elif parsed.type in (ALL_RESTRICT, SOME_RESTRICT):
                individuals.add(parsed.individual)  # type: ignore[arg-type]
    return individuals


def fresh_individual(used: set[str], prefix: str = "w") -> str:
    """Generate a fresh individual name not in *used*."""
    i = 0
    while f"{prefix}{i}" in used:
        i += 1
    return f"{prefix}{i}"


def concept_label(individual: str, sentences: frozenset[str]) -> frozenset[str]:
    """Extract the concept label of an individual.

    The concept label is the set of concept names asserted of *individual*
    in *sentences*. Used for blocking: if a fresh individual's concept label
    is a subset of some existing individual's label, the fresh individual is
    blocked.
    """
    labels: set[str] = set()
    for s in sentences:
        parsed = parse_rq_sentence(s)
        if (
            isinstance(parsed, RQSentence)
            and parsed.type == ATOM_CONCEPT
            and parsed.individual == individual
        ):
            labels.add(parsed.concept)  # type: ignore[arg-type]
    return frozenset(labels)


def find_blocking_individual(
    fresh: str,
    gamma: frozenset[str],
    delta: frozenset[str],
    used: set[str],
) -> str | None:
    """Check if any existing individual blocks the fresh individual.

    Fresh individual *fresh* is blocked by existing individual *c* if the
    concept label of *fresh* in the current context is a subset of the
    concept label of *c*. Returns the blocking individual or ``None``.
    """
    all_sentences = gamma | delta
    fresh_label = concept_label(fresh, all_sentences)

    for c in sorted(used):  # sorted for determinism
        if c == fresh:
            continue
        c_label = concept_label(c, all_sentences)
        if fresh_label <= c_label:  # subset
            return c
    return None


def is_rq_atomic(s: str) -> bool:
    """Return True if *s* is a concept assertion, role assertion, or bare atom."""
    parsed = parse_rq_sentence(s)
    if isinstance(parsed, RQSentence):
        return parsed.type in (ATOM_CONCEPT, ATOM_ROLE)
    return parsed.type == ATOM


def all_rq_atomic(sentences: frozenset[str]) -> bool:
    """Return True if every sentence in *sentences* is RQ-atomic."""
    return all(is_rq_atomic(s) for s in sentences)
