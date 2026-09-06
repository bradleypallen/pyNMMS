"""Proof-search data structures: atom sets, sequents, and trace entries.

The reasoner works on parsed sentences, not strings. A proof node is a
:class:`Sequent` whose two sides are each split into an :class:`AtomSet` of
atom names and a small ``frozenset`` of complex :class:`~pynmms.syntax.Sentence`
objects. The left and right rules iterate only the complex part, and the
material base's axiom check receives the atom part directly, so no sentence is
ever re-parsed during proof search.

:class:`AtomSet` is a persistent set represented as a shared base ``frozenset``
plus small ``added`` and ``removed`` diffs. Proof rules only ever move a few
atoms in or out of a side, so every derived node costs O(|diff|) to build,
hash, and compare rather than O(|Γ|). Hashing and equality are structural
(same base content, same diffs); with the normalisation invariants
``added ∩ base = ∅``, ``removed ⊆ base``, ``added ∩ removed = ∅`` this is
exactly content equality for sets derived from the same base, which is what
the memo cache needs. An :class:`AtomSet` is a :class:`collections.abc.Set`,
so it supports ``in``, ``len``, iteration, and the set operators; it is not
hash-compatible with ``frozenset``, so never mix the two as dict keys.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from pynmms.syntax import (
    ATOM,
    CONJ,
    DISJ,
    IMPL,
    NEG,
    PLAIN_ATOM_RE,
    QUOTED_ATOM_RE,
    Sentence,
    parse_sentence,
)

_WS_RE = re.compile(r"\s+")

_EMPTY: frozenset[str] = frozenset()


class AtomsView(Protocol):
    """Read-only view of a set of atom names: what ``is_axiom`` receives.

    Satisfied by ``frozenset``, :class:`AtomSet`, and
    :class:`pynmms.rdf.view.GraphView`.
    """

    def __contains__(self, x: object) -> bool: ...

    def __iter__(self) -> Iterator[str]: ...

    def __len__(self) -> int: ...


class AtomSetLike(AtomsView, Protocol):
    """What a sequent side's atomic part must support (AtomSet, GraphView)."""

    def with_added(self, x: str) -> AtomSetLike: ...

    def with_removed(self, x: str) -> AtomSetLike: ...

    def with_added_all(self, xs: Iterable[str]) -> AtomSetLike: ...

    def intersects(self, other: AtomsView) -> bool: ...


def intersects(a: AtomsView, b: AtomsView) -> bool:
    """True if *a* and *b* share an element; iterates the smaller side."""
    if len(a) > len(b):
        a, b = b, a
    return any(x in b for x in a)


class AtomSet(AbstractSet[str]):
    """Persistent set of atom names: a shared base plus small diffs."""

    __slots__ = ("_base", "_added", "_removed", "_hashcode")

    def __init__(
        self,
        base: frozenset[str],
        added: frozenset[str] = _EMPTY,
        removed: frozenset[str] = _EMPTY,
    ) -> None:
        self._base = base
        self._added = added
        self._removed = removed
        self._hashcode: int | None = None

    @classmethod
    def of(cls, atoms: Iterable[str]) -> AtomSet:
        """Build an AtomSet whose base is *atoms* (no diffs)."""
        return cls(atoms if isinstance(atoms, frozenset) else frozenset(atoms))

    # --- Set protocol ---

    def __contains__(self, x: object) -> bool:
        return x in self._added or (x in self._base and x not in self._removed)

    def __iter__(self) -> Iterator[str]:
        yield from self._added
        if self._removed:
            for x in self._base:
                if x not in self._removed:
                    yield x
        else:
            yield from self._base

    def __len__(self) -> int:
        return len(self._base) + len(self._added) - len(self._removed)

    def __hash__(self) -> int:
        if self._hashcode is None:
            # frozenset caches its own hash, so hash(self._base) is O(|base|)
            # once per base object and O(1) thereafter.
            self._hashcode = hash((hash(self._base), self._added, self._removed))
        return self._hashcode

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AtomSet):
            return (
                self._added == other._added
                and self._removed == other._removed
                and (self._base is other._base or self._base == other._base)
            )
        if isinstance(other, AbstractSet):
            return len(self) == len(other) and all(x in self for x in other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"AtomSet({sorted(self)!r})"

    # --- Persistent updates (keep the normalisation invariants) ---

    def with_added(self, x: str) -> AtomSet:
        if x in self:
            return self
        if x in self._removed:
            return AtomSet(self._base, self._added, self._removed - {x})
        return AtomSet(self._base, self._added | {x}, self._removed)

    def with_removed(self, x: str) -> AtomSet:
        if x not in self:
            return self
        if x in self._added:
            return AtomSet(self._base, self._added - {x}, self._removed)
        return AtomSet(self._base, self._added, self._removed | {x})

    def with_added_all(self, xs: Iterable[str]) -> AtomSet:
        out = self
        for x in xs:
            out = out.with_added(x)
        return out

    # --- Convenience ---

    def intersects(self, other: AtomsView) -> bool:
        return intersects(self, other)

    def to_frozenset(self) -> frozenset[str]:
        """Materialise the content (O(|Γ|); for display and diagnostics only)."""
        if not self._added and not self._removed:
            return self._base
        return (self._base - self._removed) | self._added

    @property
    def diff_size(self) -> int:
        return len(self._added) + len(self._removed)


def connective_count(s: Sentence) -> int:
    """Number of connective occurrences in *s*."""
    if s.type == ATOM:
        return 0
    if s.type == NEG:
        assert s.sub is not None
        return 1 + connective_count(s.sub)
    assert s.left is not None and s.right is not None
    return 1 + connective_count(s.left) + connective_count(s.right)


def _side_str(atoms: AtomsView, complex_: frozenset[Sentence]) -> str:
    items = sorted([*atoms, *(str(c) for c in complex_)])
    return ", ".join(items) if items else "∅"


@dataclass(frozen=True, slots=True)
class Sequent:
    """A proof node Γ ⇒ Δ with each side partitioned into atoms and complex sentences."""

    gamma_atoms: AtomSetLike
    gamma_complex: frozenset[Sentence]
    delta_atoms: AtomSetLike
    delta_complex: frozenset[Sentence]

    @classmethod
    def from_strings(cls, antecedent: Iterable[str], consequent: Iterable[str]) -> Sequent:
        """Parse each side once and partition it. Raises ValueError on a bad sentence.

        Partitions are cached for the most recently seen side sets, so
        repeated queries against the same (large) antecedent object pay the
        O(|Γ|) parse only once.
        """
        ga, gc = _partition_cached(_as_frozenset(antecedent))
        da, dc = _partition_cached(_as_frozenset(consequent))
        return cls(ga, gc, da, dc)

    @classmethod
    def from_atoms(cls, antecedent: AbstractSet[str], consequent: AbstractSet[str]) -> Sequent:
        """Build an atomic sequent without parsing (both sides are atom names)."""
        return cls(AtomSet.of(antecedent), frozenset(), AtomSet.of(consequent), frozenset())

    @property
    def is_atomic(self) -> bool:
        return not self.gamma_complex and not self.delta_complex

    def connectives(self) -> int:
        return sum(connective_count(s) for s in self.gamma_complex) + sum(
            connective_count(s) for s in self.delta_complex
        )

    # --- Rule support: return new sequents, never mutate ---

    def without_left(self, s: Sentence) -> Sequent:
        return Sequent(self.gamma_atoms, self.gamma_complex - {s},
                       self.delta_atoms, self.delta_complex)

    def without_right(self, s: Sentence) -> Sequent:
        return Sequent(self.gamma_atoms, self.gamma_complex,
                       self.delta_atoms, self.delta_complex - {s})

    def with_left(self, *ss: Sentence) -> Sequent:
        atoms, complex_ = self.gamma_atoms, self.gamma_complex
        for s in ss:
            if s.type == ATOM:
                assert s.name is not None
                atoms = atoms.with_added(s.name)
            else:
                complex_ = complex_ | {s}
        return Sequent(atoms, complex_, self.delta_atoms, self.delta_complex)

    def with_right(self, *ss: Sentence) -> Sequent:
        atoms, complex_ = self.delta_atoms, self.delta_complex
        for s in ss:
            if s.type == ATOM:
                assert s.name is not None
                atoms = atoms.with_added(s.name)
            else:
                complex_ = complex_ | {s}
        return Sequent(self.gamma_atoms, self.gamma_complex, atoms, complex_)

    # --- Display ---

    def gamma_str(self) -> str:
        return _side_str(self.gamma_atoms, self.gamma_complex)

    def delta_str(self) -> str:
        return _side_str(self.delta_atoms, self.delta_complex)

    def __str__(self) -> str:
        return f"{self.gamma_str()} => {self.delta_str()}"


def _as_frozenset(sentences: Iterable[str]) -> frozenset[str]:
    return sentences if isinstance(sentences, frozenset) else frozenset(sentences)


def _partition(sentences: Iterable[str]) -> tuple[AtomSet, frozenset[Sentence]]:
    atoms: set[str] = set()
    complex_: set[Sentence] = set()
    for text in sentences:
        # Fast path: well-formed atom names need no parse. This is the same
        # test the parser applies in atom position, so the result is identical.
        stripped = text.strip()
        if QUOTED_ATOM_RE.match(stripped):
            atoms.add(stripped)
            continue
        if PLAIN_ATOM_RE.match(stripped):
            atoms.add(_WS_RE.sub("", stripped) if "(" in stripped else stripped)
            continue
        parsed = parse_sentence(text)
        if parsed.type == ATOM:
            assert parsed.name is not None
            atoms.add(parsed.name)
        else:
            complex_.add(parsed)
    return AtomSet(frozenset(atoms)), frozenset(complex_)


@lru_cache(maxsize=16)
def _partition_cached(sentences: frozenset[str]) -> tuple[AtomSet, frozenset[Sentence]]:
    return _partition(sentences)


# Rule labels as they appear in traces.
RULE_LABELS = {
    ("L", NEG): "L¬",
    ("L", IMPL): "L→",
    ("L", CONJ): "L∧",
    ("L", DISJ): "L∨",
    ("R", NEG): "R¬",
    ("R", IMPL): "R→",
    ("R", CONJ): "R∧",
    ("R", DISJ): "R∨",
}


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One structured line of a proof trace; formatted only when ``str()`` is called.

    Attributes:
        kind: ``"AXIOM"``, ``"FAIL"``, ``"DEPTH LIMIT"``, or ``"RULE"``.
        depth: Proof depth of the node (used for indentation).
        sequent: The node's sequent (``None`` for a depth-limit entry).
        rule: Rule label such as ``"L¬"`` when ``kind == "RULE"``.
        principal: The principal sentence a rule was applied to.
    """

    kind: str
    depth: int
    sequent: Sequent | None = None
    rule: str | None = None
    principal: Sentence | None = None

    def __str__(self) -> str:
        indent = "  " * self.depth
        if self.kind == "RULE":
            return f"{indent}[{self.rule}] on {self.principal}"
        if self.kind == "DEPTH LIMIT":
            return f"{indent}DEPTH LIMIT"
        assert self.sequent is not None
        return f"{indent}{self.kind}: {self.sequent}"
