"""Propositional sentence parsing for NMMS.

Implements a recursive descent parser for the propositional fragment of the
NMMS sequent calculus (Hlobil & Brandom 2025, Ch. 3). Parses sentences built
from atoms, negation (~), conjunction (&), disjunction (|), and implication (->).

Grammar (informal, precedence from low to high):
    sentence   ::= impl_expr
    impl_expr  ::= disj_expr ( '->' disj_expr )*     (right-assoc, lowest)
    disj_expr  ::= conj_expr ( '|' conj_expr )*      (left-assoc)
    conj_expr  ::= unary_expr ( '&' unary_expr )*    (left-assoc)
    unary_expr ::= '~' unary_expr | atom | '(' sentence ')'
    atom       ::= IDENT ( '(' IDENT ( ',' IDENT )* ')' )?
                 | '<' any characters except '<' and '>' '>'
    IDENT      ::= [A-Za-z_][A-Za-z0-9_]*

Atoms are either plain identifiers, identifiers applied to comma-separated
identifier arguments (the ``C(a)`` and ``R(a,b)`` forms used by NMMS_Onto), or
*quoted atoms* ``<...>`` whose content is taken verbatim. Quoted atoms let
tokens that would otherwise be misread as connectives (IRIs, sentences with
spaces) appear as atomic sentences; the angle brackets are part of the atom's
name so that ``str(parse_sentence(s)) == s`` round-trips.

Anything else in atom position is a parse error. In particular a string such
as ``(p conj q)`` is rejected rather than silently accepted as an atom named
``"p conj q"``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Sentence type constants
ATOM = "atom"
NEG = "neg"
CONJ = "conj"
DISJ = "disj"
IMPL = "impl"

# Atom grammar
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
PLAIN_ATOM_RE = re.compile(rf"^{_IDENT}(?:\(\s*{_IDENT}(?:\s*,\s*{_IDENT})*\s*\))?$")
QUOTED_ATOM_RE = re.compile(r"^<[^<>]*>$")
_WS_RE = re.compile(r"\s+")

# Words that suggest the user wrote a connective in the wrong notation.
_CONNECTIVE_WORDS = frozenset(
    {"conj", "disj", "impl", "neg", "and", "or", "not", "implies", "iff", "then"}
)


@dataclass(frozen=True, slots=True)
class Sentence:
    """Immutable AST node for a propositional sentence.

    Attributes:
        type: One of ATOM, NEG, CONJ, DISJ, IMPL.
        name: The atom name (only when type == ATOM).
        sub: The sub-sentence (only when type == NEG).
        left: Left operand (only when type in {CONJ, DISJ, IMPL}).
        right: Right operand (only when type in {CONJ, DISJ, IMPL}).
    """

    type: str
    name: str | None = None
    sub: Sentence | None = None
    left: Sentence | None = None
    right: Sentence | None = None

    def __str__(self) -> str:
        if self.type == ATOM:
            return self.name  # type: ignore[return-value]
        if self.type == NEG:
            return f"~{self.sub}"
        if self.type == CONJ:
            return f"({self.left} & {self.right})"
        if self.type == DISJ:
            return f"({self.left} | {self.right})"
        if self.type == IMPL:
            return f"({self.left} -> {self.right})"
        return f"Sentence({self.type})"  # pragma: no cover


# -------------------------------------------------------------------
# Lexical helpers (shared with pynmms.onto.syntax and the CLI)
# -------------------------------------------------------------------


def find_top_level(s: str, token: str) -> list[int]:
    """Return the start indices of *token* at parenthesis depth 0 in *s*.

    Occurrences inside a quoted atom ``<...>`` are ignored, as are occurrences
    nested inside parentheses.
    """
    positions: list[int] = []
    depth = 0
    quoted = False
    n = len(token)
    i = 0
    while i < len(s):
        c = s[i]
        if quoted:
            if c == ">":
                quoted = False
        elif c == "<":
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and s.startswith(token, i):
            positions.append(i)
            i += n
            continue
        i += 1
    return positions


def is_fully_wrapped(s: str) -> bool:
    """True if *s* is a single parenthesized group ``( ... )``."""
    if not (s.startswith("(") and s.endswith(")")):
        return False
    depth = 0
    quoted = False
    for i, c in enumerate(s):
        if quoted:
            if c == ">":
                quoted = False
            continue
        if c == "<":
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0 and i < len(s) - 1:
            return False
    return True


def split_top_level(s: str, sep: str) -> list[str]:
    """Split *s* on every top-level occurrence of *sep*.

    Top-level means outside parentheses and outside quoted atoms, so
    ``split_top_level("R(a,b), <x, y>, C(a)", ",")`` yields three parts.
    Parts are stripped; empty parts are dropped.
    """
    parts: list[str] = []
    start = 0
    for i in find_top_level(s, sep):
        parts.append(s[start:i])
        start = i + len(sep)
    parts.append(s[start:])
    return [p.strip() for p in parts if p.strip()]


def validate_atom_name(s: str) -> str:
    """Return *s* if it is a well-formed atom name, else raise ValueError."""
    # Fast path: a plain identifier needs no regex (this runs at every proof
    # node for every element of Γ until Phase 1 removes the re-parse).
    if s.isidentifier() or QUOTED_ATOM_RE.match(s):
        return s
    if PLAIN_ATOM_RE.match(s):
        # Canonical form of an applied atom has no internal whitespace, so
        # R(a, b) and R(a,b) name the same atom.
        return _WS_RE.sub("", s)
    hint = ""
    words = {w.lower() for w in s.replace("(", " ").replace(")", " ").split()}
    if words & _CONNECTIVE_WORDS:
        hint = " Did you mean a connective? Use ~ (not), & (and), | (or), -> (implies)."
    raise ValueError(
        f"Malformed sentence: {s!r} is not a valid atom. Atoms are identifiers, "
        f"identifiers applied to comma-separated identifiers such as C(a) or R(a,b), "
        f"or quoted as <...>.{hint}"
    )


# -------------------------------------------------------------------
# Parser
# -------------------------------------------------------------------


def parse_sentence(s: str) -> Sentence:
    """Parse a string into a propositional Sentence AST.

    Examples:
        >>> parse_sentence("A")
        Sentence(type='atom', name='A', ...)
        >>> parse_sentence("A -> B")
        Sentence(type='impl', ..., left=Sentence(type='atom', name='A', ...),
                 right=Sentence(type='atom', name='B', ...))

    Raises:
        ValueError: on empty input, a dangling connective, or a malformed atom.
    """
    s = s.strip()
    if not s:
        raise ValueError("Cannot parse empty sentence")

    # Strip outer parens if they wrap the entire expression
    if is_fully_wrapped(s):
        return parse_sentence(s[1:-1])

    # --- Binary connectives at depth 0, lowest precedence first ---

    # Implication (right-associative, lowest precedence): first match
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

    # Disjunction (left-associative): last match
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

    # Conjunction (left-associative): last match
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

    # Atom (validated)
    return Sentence(type=ATOM, name=validate_atom_name(s))


def is_atomic(s: str) -> bool:
    """Return True if *s* parses to a bare atom (no logical connectives).

    Raises ValueError if *s* does not parse at all (e.g. a malformed atom).
    """
    return parse_sentence(s).type == ATOM


def all_atomic(sentences: frozenset[str]) -> bool:
    """Return True if every sentence in *sentences* is atomic."""
    return all(is_atomic(s) for s in sentences)
