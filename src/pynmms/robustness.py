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

``guarded(left, right, exclusions)``
    MONOTONE except when ``Γ`` meets ``left``, ``Δ`` meets ``right``, or some
    exclusion pair ``⟨x, y⟩`` has ``x ⊆ Γ`` and ``y ⊆ Δ``. ``left`` and
    ``right`` are singleton defeaters; ``exclusions`` are finite conjunctive
    ones (``Penguin`` *and* ``Injured`` together defeat ``Bird |~ Flies``,
    neither alone). Together they describe the complement of the RSR up to
    finite additions, which is what distinguishes *relevant* defeat from the
    arbitrary defeat of EXACT entries. The guard costs O(|left| + |right| +
    Σ|pair|) membership tests, independent of |Γ|.

For ontology schemas the ``left`` defeaters are concept names, instantiated
on the individuals of the matched consequent (see
:meth:`pynmms.onto.base.OntoMaterialBase._schema_applies`).

Containment is unaffected by any policy, so every base built from these
entries satisfies Definition 1 of Ch. 3 and the NMMS metatheory applies.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pynmms.sequent import AtomsView, intersects
from pynmms.syntax import find_top_level, split_top_level

EXACT_KIND = "exact"
MONOTONE_KIND = "monotone"
GUARDED_KIND = "guarded"
KINDS = (EXACT_KIND, MONOTONE_KIND, GUARDED_KIND)

_NONE: frozenset[str] = frozenset()

Exclusion = tuple[frozenset[str], frozenset[str]]
"""A conjunctive defeater ⟨x, y⟩: the entry fails when x ⊆ Γ and y ⊆ Δ."""


def exclusion(left: Iterable[str] = (), right: Iterable[str] = ()) -> Exclusion:
    x, y = frozenset(left), frozenset(right)
    if not x and not y:
        raise ValueError("An exclusion pair needs at least one atom")
    return (x, y)


@dataclass(frozen=True, slots=True)
class Robustness:
    """How far a base entry survives additions to its antecedent and consequent.

    Attributes:
        kind: ``"exact"``, ``"monotone"``, or ``"guarded"``.
        left: Antecedent-side singleton defeaters (atoms, or concept names
            for schemas).
        right: Succedent-side singleton defeaters.
        exclusions: Conjunctive defeaters ``⟨x, y⟩``; the entry is defeated
            when every atom of ``x`` is in Γ and every atom of ``y`` is in Δ.
    """

    kind: str
    left: frozenset[str] = _NONE
    right: frozenset[str] = _NONE
    exclusions: frozenset[Exclusion] = frozenset()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Unknown robustness kind {self.kind!r}; expected one of {KINDS}")
        # Singleton exclusions are just defeaters; fold them in.
        singles_l = {next(iter(x)) for x, y in self.exclusions if len(x) == 1 and not y}
        singles_r = {next(iter(y)) for x, y in self.exclusions if len(y) == 1 and not x}
        if singles_l or singles_r:
            object.__setattr__(self, "left", self.left | frozenset(singles_l))
            object.__setattr__(self, "right", self.right | frozenset(singles_r))
            object.__setattr__(self, "exclusions", frozenset(
                (x, y) for x, y in self.exclusions
                if not ((len(x) == 1 and not y) or (len(y) == 1 and not x))
            ))
        if self.kind == GUARDED_KIND and not self.has_defeaters:
            object.__setattr__(self, "kind", MONOTONE_KIND)
        if self.kind != GUARDED_KIND and self.has_defeaters:
            raise ValueError(f"Defeaters are only meaningful for guarded entries, not {self.kind}")

    @property
    def has_defeaters(self) -> bool:
        return bool(self.left or self.right or self.exclusions)

    @property
    def is_exact(self) -> bool:
        return self.kind == EXACT_KIND

    def allows(self, gamma: AtomsView, delta: AtomsView) -> bool:
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
        for x, y in self.exclusions:
            if all(a in gamma for a in x) and all(b in delta for b in y):
                return False
        return True

    def defeated_by(self, gamma: AtomsView, delta: AtomsView) -> frozenset[str]:
        """The defeaters actually present (for logging and explanation)."""
        found = frozenset(x for x in self.left if x in gamma) | frozenset(
            x for x in self.right if x in delta
        )
        for x, y in self.exclusions:
            if all(a in gamma for a in x) and all(b in delta for b in y):
                found |= x | y
        return found

    # --- Serialization ---

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.kind == GUARDED_KIND:
            unless: dict[str, Any] = {
                "antecedent": sorted(self.left), "consequent": sorted(self.right),
            }
            if self.exclusions:
                unless["pairs"] = [
                    {"antecedent": sorted(x), "consequent": sorted(y)}
                    for x, y in sorted(self.exclusions, key=lambda e: (sorted(e[0]), sorted(e[1])))
                ]
            d["unless"] = unless
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
        pairs = frozenset(
            exclusion(p.get("antecedent", ()), p.get("consequent", ()))
            for p in unless.get("pairs", ())
        )
        return cls(
            kind,
            frozenset(unless.get("antecedent", ())),
            frozenset(unless.get("consequent", ())),
            pairs,
        )

    def __str__(self) -> str:
        if self.kind == GUARDED_KIND:
            items = sorted(self.left)
            items += [" & ".join(sorted(x)) for x, y in sorted(self.exclusions, key=str) if not y]
            text = "unless " + (", ".join(items) if items else "∅")
            rights = sorted(self.right)
            rights += [
                (" & ".join(sorted(x)) + " |~ " if x else "") + " & ".join(sorted(y))
                for x, y in sorted(self.exclusions, key=str) if y
            ]
            if rights:
                sep = " |~ " if not self.exclusions else "; "
                text += sep + ", ".join(rights)
            return text
        return self.kind


EXACT = Robustness(EXACT_KIND)
MONOTONE = Robustness(MONOTONE_KIND)


def guarded(
    left: Iterable[str] = (),
    right: Iterable[str] = (),
    exclusions: Iterable[Exclusion] = (),
) -> Robustness:
    """A GUARDED policy (MONOTONE if there are no defeaters at all)."""
    return Robustness(GUARDED_KIND, frozenset(left), frozenset(right), frozenset(exclusions))


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
    ``"A |~ B unless X & Y, Z"`` makes ``X & Y`` a conjunctive exclusion and
    ``Z`` a singleton defeater; ``"A |~ B monotone"`` yields
    ``("A |~ B", MONOTONE)``; anything else is returned unchanged with
    ``EXACT``. The clause is recognised only at parenthesis depth 0 and
    outside quoted atoms.
    """
    stripped = text.strip()
    unless = _keyword_positions(stripped, "unless")
    if unless:
        i = unless[0]
        head = stripped[:i].strip()
        items = split_top_level(stripped[i + len("unless"):], ",")
        if not items:
            raise ValueError("'unless' must be followed by one or more comma-separated defeaters")
        singles: list[str] = []
        pairs: list[Exclusion] = []
        for item in items:
            conj = split_top_level(item, "&")
            if len(conj) == 1:
                singles.append(conj[0])
            else:
                pairs.append(exclusion(conj))
        return head, guarded(singles, exclusions=pairs)
    mono = _keyword_positions(stripped, "monotone")
    if mono and mono[-1] + len("monotone") == len(stripped):
        return stripped[: mono[-1]].strip(), MONOTONE
    return stripped, EXACT
