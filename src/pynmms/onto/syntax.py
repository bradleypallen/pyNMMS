"""Ontology-style concept/role assertion parsing for NMMS.

Extends the propositional parser with concept assertions (``C(a)``) and
role assertions (``R(a,b)``) for ontology-style reasoning.

Grammar additions (beyond propositional)::

    concept_atom  ::= CONCEPT '(' INDIVIDUAL ')'
    role_atom     ::= ROLE '(' INDIVIDUAL ',' INDIVIDUAL ')'

The parser tries binary connectives first (at depth-0), then ontology-specific
patterns (role assertions, concept assertions). Bare propositional atoms
are rejected -- use concept assertions ``C(a)`` or role assertions
``R(a,b)`` instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pynmms.syntax import (
    CONJ,
    DISJ,
    IMPL,
    NEG,
    Sentence,
    find_top_level,
    is_fully_wrapped,
    parse_sentence,
)

# Ontology-specific sentence type constants
ATOM_CONCEPT = "concept"
ATOM_ROLE = "role"


@dataclass(frozen=True, slots=True)
class OntoSentence:
    """Immutable AST node for an ontology-style sentence.

    Attributes:
        type: One of ATOM_CONCEPT, ATOM_ROLE.
        concept: Concept name (for concept assertions).
        individual: Individual name (for concept assertions).
        role: Role name (for role assertions).
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
        return f"OntoSentence({self.type})"  # pragma: no cover


# Pre-compiled regex patterns
_ROLE_RE = re.compile(r"^(\w+)\((\w+)\s*,\s*(\w+)\)$")
_CONCEPT_RE = re.compile(r"^(\w+)\((\w+)\)$")


def parse_onto_sentence(s: str) -> Sentence | OntoSentence:
    """Parse a string into a propositional Sentence or OntoSentence AST.

    Tries binary connectives first (at depth-0), then ontology-specific patterns
    (role assertions, concept assertions), then falls through to propositional
    negation.
    """
    s = s.strip()
    if not s:
        raise ValueError("Cannot parse empty sentence")

    # Strip outer parens if they wrap the entire expression
    if is_fully_wrapped(s):
        return parse_onto_sentence(s[1:-1])

    # --- Binary connectives at depth 0, lowest precedence first ---
    # Sub-sentences are parsed by the propositional parser; its atom grammar
    # admits the C(a) and R(a,b) forms, so onto atoms survive as ATOM nodes.

    impl_positions = find_top_level(s, "->")
    if impl_positions:
        i = impl_positions[0]
        left_str = s[:i].strip()
        right_str = s[i + 2 :].strip()
        if not left_str or not right_str:
            raise ValueError(f"Malformed implication in: {s!r}")
        return Sentence(
            type=IMPL,
            left=parse_sentence(left_str),
            right=parse_sentence(right_str),
        )

    disj_positions = find_top_level(s, "|")
    if disj_positions:
        i = disj_positions[-1]
        left_str = s[:i].strip()
        right_str = s[i + 1 :].strip()
        if not left_str or not right_str:
            raise ValueError(f"Malformed disjunction in: {s!r}")
        return Sentence(
            type=DISJ,
            left=parse_sentence(left_str),
            right=parse_sentence(right_str),
        )

    conj_positions = find_top_level(s, "&")
    if conj_positions:
        i = conj_positions[-1]
        left_str = s[:i].strip()
        right_str = s[i + 1 :].strip()
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

    # --- Ontology-specific atomic patterns ---

    # Role assertion: R(a,b)
    m = _ROLE_RE.match(s)
    if m:
        return OntoSentence(
            type=ATOM_ROLE,
            role=m.group(1),
            arg1=m.group(2),
            arg2=m.group(3),
        )

    # Concept assertion: C(a)
    m = _CONCEPT_RE.match(s)
    if m:
        return OntoSentence(
            type=ATOM_CONCEPT,
            concept=m.group(1),
            individual=m.group(2),
        )

    # Bare propositional atoms are not valid in NMMS_Onto.
    raise ValueError(
        f"Bare atom {s!r} is not valid in NMMS_Onto. "
        f"Use concept assertions C(a) or role assertions R(a,b)."
    )


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------


def make_concept_assertion(concept: str, individual: str) -> str:
    """Construct ``C(a)`` string."""
    return f"{concept}({individual})"


def make_role_assertion(role: str, arg1: str, arg2: str) -> str:
    """Construct ``R(a,b)`` string."""
    return f"{role}({arg1},{arg2})"


def is_onto_atomic(s: str) -> bool:
    """Return True if *s* is a concept assertion or role assertion."""
    try:
        parsed = parse_onto_sentence(s)
    except ValueError:
        return False
    if isinstance(parsed, OntoSentence):
        return parsed.type in (ATOM_CONCEPT, ATOM_ROLE)
    return False


def all_onto_atomic(sentences: frozenset[str]) -> bool:
    """Return True if every sentence in *sentences* is onto-atomic."""
    return all(is_onto_atomic(s) for s in sentences)
