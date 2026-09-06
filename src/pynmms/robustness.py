"""Robustness policies for material base entries.

Hlobil & Brandom (2025, Ch. 5) attach to every implication its *range of
subjunctive robustness* (RSR): the set of premise/conclusion additions under
which the implication survives. A base entry ``Γ₀ |~ Δ₀`` in pyNMMS carries a
:class:`Robustness` value that fixes a tractable fragment of its RSR:

``EXACT``
    The entry licenses only ``Γ₀ ⇒ Δ₀`` itself. Any addition to either side
    defeats it. This is the pre-0.7 behaviour of every entry and schema; its
    failure of monotonicity is "by omission rather than by defeat" (Allen,
    "Implication-Space Semantics for RDF", Sec. 3.3).

``MONOTONE``
    The entry licenses every ``Γ ⇒ Δ`` with ``Γ ⊇ Γ₀`` and ``Δ ⊇ Δ₀``. This is
    the reading of a regime base (Definition 25 of the same paper).

``guarded(left, right)``
    MONOTONE except when ``Γ`` meets ``left`` or ``Δ`` meets ``right``. The
    defeater sets are RSR complements restricted to singleton additions, which
    is what distinguishes *relevant* defeat (``Penguin`` defeats
    ``Bird |~ Flies``) from the arbitrary defeat of EXACT entries.

For ontology schemas the ``left`` defeaters are concept names, instantiated
on the individuals of the matched consequent (see
:meth:`pynmms.onto.base.OntoMaterialBase._schema_applies`).

Containment is unaffected by any policy, so every base built from these
entries satisfies Definition 1 of Ch. 3 and the NMMS metatheory applies.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any

from pynmms.sequent import intersects
from pynmms.syntax import find_top_level, split_top_level

EXACT_KIND = "exact"
MONOTONE_KIND = "monotone"
GUARDED_KIND = "guarded"
KINDS = (EXACT_KIND, MONOTONE_KIND, GUARDED_KIND)

_NONE: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Robustness:
    """How far a base entry survives additions to its antecedent and consequent.

    Attributes:
        kind: ``"exact"``, ``"monotone"``, or ``"guarded"``.
        left: Antecedent-side defeaters (atoms, or concept names for schemas).
        right: Succedent-side defeaters.
    """

    kind: str
    left: frozenset[str] = _NONE
    right: frozenset[str] = _NONE

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Unknown robustness kind {self.kind!r}; expected one of {KINDS}")
        if self.kind == GUARDED_KIND and not self.left and not self.right:
            object.__setattr__(self, "kind", MONOTONE_KIND)
        if self.kind != GUARDED_KIND and (self.left or self.right):
            raise ValueError(f"Defeaters are only meaningful for guarded entries, not {self.kind}")

    @property
    def is_exact(self) -> bool:
        return self.kind == EXACT_KIND

    def allows(self, gamma: AbstractSet[str], delta: AbstractSet[str]) -> bool:
        """True if a superset match ``Γ ⊇ Γ₀, Δ ⊇ Δ₀`` is licensed for these sides.

        EXACT entries never subset-match (the caller handles exact equality);
        MONOTONE always does; GUARDED does unless a defeater is present.
        """
        if self.kind == EXACT_KIND:
            return False
        if self.left and intersects(gamma, self.left):
            return False
        if self.right and intersects(delta, self.right):
            return False
        return True

    def defeated_by(self, gamma: AbstractSet[str], delta: AbstractSet[str]) -> frozenset[str]:
        """The defeaters actually present (for logging and explanation)."""
        return frozenset(x for x in self.left if x in gamma) | frozenset(
            x for x in self.right if x in delta
        )

    # --- Serialization ---

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.kind == GUARDED_KIND:
            d["unless"] = {"antecedent": sorted(self.left), "consequent": sorted(self.right)}
        return d

    @classmethod
    def from_json(cls, data: Any) -> Robustness:
        """Parse the ``robustness`` field of a base file. Missing means EXACT."""
        if data is None:
            return EXACT
        if isinstance(data, str):
            return cls(data)
        kind = data.get("kind", EXACT_KIND)
        unless = data.get("unless") or {}
        return cls(
            kind,
            frozenset(unless.get("antecedent", ())),
            frozenset(unless.get("consequent", ())),
        )

    def __str__(self) -> str:
        if self.kind == GUARDED_KIND:
            left = ", ".join(sorted(self.left)) if self.left else "∅"
            if self.right:
                return f"unless {left} |~ {', '.join(sorted(self.right))}"
            return f"unless {left}"
        return self.kind


EXACT = Robustness(EXACT_KIND)
MONOTONE = Robustness(MONOTONE_KIND)


def guarded(left: Iterable[str] = (), right: Iterable[str] = ()) -> Robustness:
    """A GUARDED policy (MONOTONE if both defeater sets are empty)."""
    return Robustness(GUARDED_KIND, frozenset(left), frozenset(right))


# -------------------------------------------------------------------
# Statement syntax: "<statement> unless X, Y" | "<statement> monotone"
# -------------------------------------------------------------------


def _keyword_positions(text: str, keyword: str) -> list[int]:
    out = []
    for i in find_top_level(text, keyword):
        before_ok = i == 0 or text[i - 1].isspace()
        j = i + len(keyword)
        after_ok = j == len(text) or text[j].isspace()
        if before_ok and after_ok:
            out.append(i)
    return out


def split_robustness_clause(text: str) -> tuple[str, Robustness]:
    """Strip a trailing robustness clause from a tell statement or schema line.

    ``"A, B |~ C unless X, Y"`` yields ``("A, B |~ C", guarded({X, Y}))``;
    ``"A |~ B monotone"`` yields ``("A |~ B", MONOTONE)``; anything else is
    returned unchanged with ``EXACT``. The clause is recognised only at
    parenthesis depth 0 and outside quoted atoms.
    """
    stripped = text.strip()
    unless = _keyword_positions(stripped, "unless")
    if unless:
        i = unless[0]
        head = stripped[:i].strip()
        defeaters = split_top_level(stripped[i + len("unless"):], ",")
        if not defeaters:
            raise ValueError("'unless' must be followed by one or more comma-separated defeaters")
        return head, guarded(defeaters)
    mono = _keyword_positions(stripped, "monotone")
    if mono and mono[-1] + len("monotone") == len(stripped):
        return stripped[: mono[-1]].strip(), MONOTONE
    return stripped, EXACT
