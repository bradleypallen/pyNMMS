"""Propositional sentence parsing for NMMS.

Implements a recursive descent parser for the propositional fragment of the
NMMS sequent calculus (Hlobil & Brandom 2025, Ch. 3). Parses sentences built
from atoms, negation (~), conjunction (&), disjunction (|), and implication (->).

Grammar (informal, precedence from low to high):
    sentence  ::= impl_expr
    impl_expr ::= disj_expr ( '->' disj_expr )*     (right-assoc, lowest)
    disj_expr ::= conj_expr ( '|' conj_expr )*      (left-assoc)
    conj_expr ::= unary_expr ( '&' unary_expr )*     (left-assoc)
    unary_expr ::= '~' unary_expr | atom | '(' sentence ')'
    atom       ::= identifier
"""

from __future__ import annotations

from dataclasses import dataclass

# Sentence type constants
ATOM = "atom"
NEG = "neg"
CONJ = "conj"
DISJ = "disj"
IMPL = "impl"


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


def parse_sentence(s: str) -> Sentence:
    """Parse a string into a propositional Sentence AST.

    Examples:
        >>> parse_sentence("A")
        Sentence(type='atom', name='A', ...)
        >>> parse_sentence("A -> B")
        Sentence(type='impl', ..., left=Sentence(type='atom', name='A', ...),
                 right=Sentence(type='atom', name='B', ...))
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
            return parse_sentence(s[1:-1])

    # --- Binary connectives at depth 0, lowest precedence first ---

    # Implication (right-associative, lowest precedence)
    # Scan left-to-right: first match gives right-associativity
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

    # Bare atom
    return Sentence(type=ATOM, name=s)


def is_atomic(s: str) -> bool:
    """Return True if *s* parses to a bare atom (no logical connectives)."""
    return parse_sentence(s).type == ATOM


def all_atomic(sentences: frozenset[str]) -> bool:
    """Return True if every sentence in *sentences* is atomic."""
    return all(is_atomic(s) for s in sentences)
