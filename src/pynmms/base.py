"""Material base for propositional NMMS.

Implements the material base B = <L_B, |~_B> from Hlobil & Brandom 2025, Ch. 3
(Definition 1): an atomic language L_B together with a base consequence
relation |~_B ⊆ P(L_B) × P(L_B) obeying Containment.

Every base entry ``Γ₀ |~ Δ₀`` carries a :class:`~pynmms.robustness.Robustness`
policy. EXACT entries (the default) match only ``Γ₀ ⇒ Δ₀`` itself; MONOTONE
and GUARDED entries also match supersets, the latter unless a registered
defeater is present. See :mod:`pynmms.robustness`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

from pynmms.robustness import EXACT, Robustness
from pynmms.sequent import intersects
from pynmms.syntax import ATOM, parse_sentence

logger = logging.getLogger(__name__)

Sequent = tuple[frozenset[str], frozenset[str]]
"""A base consequence: (antecedent, consequent) pair of atom-name sets."""

# Matches concept assertions C(a) and role assertions R(a,b).
_STRUCTURED_ATOM_RE = re.compile(r"^\w+\(\w+(?:,\s*\w+)?\)$")

# Index key for robust entries with an empty consequent.
_EMPTY_KEY = ""

RobustEntry = tuple[frozenset[str], frozenset[str], Robustness]


def _validate_atomic(s: str, context: str) -> str:
    """Return the canonical atom name for *s*, or raise ValueError.

    Canonical means as the parser reports it (whitespace inside an applied
    atom removed), so that ``R(a, b)`` and ``R(a,b)`` are the same atom.
    """
    try:
        parsed = parse_sentence(s)
    except ValueError as e:
        raise ValueError(f"{context}: {e}") from None
    if parsed.type != ATOM:
        raise ValueError(
            f"{context}: found logically complex sentence '{s}'. "
            f"Only bare atoms are permitted in the material base."
        )
    assert parsed.name is not None
    if _STRUCTURED_ATOM_RE.match(parsed.name):
        raise ValueError(
            f"{context}: '{s}' looks like a concept or role assertion. "
            f"Use --onto mode for NMMS_Onto atoms, or rename to a plain identifier."
        )
    return parsed.name


@dataclass
class MaterialBase:
    """A material base B = <L_B, |~_B> for propositional NMMS.

    Parameters:
        language: Set of atomic sentence strings comprising L_B.
        consequences: Set of (antecedent, consequent) sequent pairs comprising |~_B.
        annotations: Optional natural-language descriptions for atoms.
        robustness: Optional mapping from a consequence pair to its
            :class:`~pynmms.robustness.Robustness`; pairs not listed are EXACT.
    """

    _language: set[str] = field(default_factory=set)
    _consequences: set[Sequent] = field(default_factory=set)
    _robustness: dict[Sequent, Robustness] = field(default_factory=dict)

    def __init__(
        self,
        language: set[str] | frozenset[str] | None = None,
        consequences: (
            set[Sequent]
            | set[tuple[frozenset[str], frozenset[str]]]
            | None
        ) = None,
        annotations: dict[str, str] | None = None,
        robustness: dict[Sequent, Robustness] | None = None,
    ) -> None:
        self._language: set[str] = set()
        self._consequences: set[Sequent] = set()
        self._robustness: dict[Sequent, Robustness] = {}
        self._annotations: dict[str, str] = dict(annotations) if annotations else {}
        # Exact-match index keyed by (|Gamma|, |Delta|) so that is_axiom never
        # hashes or copies a large antecedent (see is_axiom).
        self._by_size: dict[tuple[int, int], list[Sequent]] = {}
        # Robust (MONOTONE / GUARDED) entries keyed by each consequent atom, or
        # by _EMPTY_KEY for entries with an empty consequent.
        self._robust_by_delta: dict[str, list[RobustEntry]] = {}
        # Bumped on every mutation that can change derivability; reasoners use
        # it to invalidate a persistent cache.
        self._generation: int = 0

        for s in language or ():
            self._language.add(self._validate_atom(s, "Material base language"))

        if consequences:
            for gamma, delta in consequences:
                pair = self._canonical_pair(gamma, delta, "Material base consequence")
                self._consequences.add(pair)
                if robustness and (gamma, delta) in robustness:
                    self._set_robustness(pair, robustness[(gamma, delta)])
        self._reindex()

        logger.debug(
            "MaterialBase created: %d atoms, %d consequences (%d robust)",
            len(self._language),
            len(self._consequences),
            len(self._robustness),
        )

    # --- Validation hooks (overridden by OntoMaterialBase) ---

    def _validate_atom(self, s: str, context: str) -> str:
        return _validate_atomic(s, context)

    def _canonical_pair(
        self, gamma: Iterable[str], delta: Iterable[str], context: str
    ) -> Sequent:
        g = frozenset(self._validate_atom(s, context) for s in gamma)
        d = frozenset(self._validate_atom(s, context) for s in delta)
        self._language.update(g)
        self._language.update(d)
        return (g, d)

    # --- Read-only properties ---

    @property
    def language(self) -> frozenset[str]:
        """The atomic language L_B (read-only view)."""
        return frozenset(self._language)

    @property
    def consequences(self) -> frozenset[Sequent]:
        """The base consequence relation |~_B (read-only view)."""
        return frozenset(self._consequences)

    @property
    def annotations(self) -> dict[str, str]:
        """Atom annotations (read-only view)."""
        return dict(self._annotations)

    @property
    def generation(self) -> int:
        """Counter incremented on every derivability-affecting mutation."""
        return self._generation

    def robustness_of(self, antecedent: frozenset[str], consequent: frozenset[str]) -> Robustness:
        """The policy attached to a base consequence (EXACT if unspecified)."""
        return self._robustness.get((antecedent, consequent), EXACT)

    # --- Index maintenance ---

    def _touch(self) -> None:
        self._generation += 1

    def _set_robustness(self, pair: Sequent, robustness: Robustness) -> None:
        if robustness.is_exact:
            self._robustness.pop(pair, None)
        else:
            self._robustness[pair] = robustness

    def _reindex(self) -> None:
        """Rebuild the exact-match and robust indexes from ``_consequences``."""
        self._by_size = {}
        self._robust_by_delta = {}
        for gamma, delta in self._consequences:
            self._index_consequence(gamma, delta)

    def _index_consequence(self, gamma: frozenset[str], delta: frozenset[str]) -> None:
        robustness = self._robustness.get((gamma, delta), EXACT)
        if robustness.is_exact:
            self._by_size.setdefault((len(gamma), len(delta)), []).append((gamma, delta))
            return
        entry: RobustEntry = (gamma, delta, robustness)
        for key in delta or (_EMPTY_KEY,):
            self._robust_by_delta.setdefault(key, []).append(entry)

    # --- Mutation ---

    def add_atom(self, s: str) -> None:
        """Add an atomic sentence to the language L_B."""
        name = self._validate_atom(s, "add_atom")
        self._language.add(name)
        self._touch()
        logger.debug("Added atom: %s", name)

    def annotate(self, atom: str, description: str) -> None:
        """Attach a natural-language description to an atom."""
        self._annotations[atom] = description
        logger.debug("Annotated atom %s: %s", atom, description)

    def add_consequence(
        self,
        antecedent: frozenset[str],
        consequent: frozenset[str],
        robustness: Robustness = EXACT,
    ) -> None:
        """Add a base consequence Gamma |~_B Delta with a robustness policy.

        All sentences in *antecedent* and *consequent* must be atomic. They are
        also implicitly added to the language. Re-adding an existing pair with
        a different policy replaces the policy.
        """
        pair = self._canonical_pair(antecedent, consequent, "add_consequence")
        if pair in self._consequences:
            if self._robustness.get(pair, EXACT) != robustness:
                self._set_robustness(pair, robustness)
                self._reindex()
        else:
            self._consequences.add(pair)
            self._set_robustness(pair, robustness)
            self._index_consequence(*pair)
        self._touch()
        logger.debug(
            "Added consequence: %s |~ %s [%s]", set(pair[0]), set(pair[1]), robustness
        )

    # --- Axiom check ---

    def is_axiom(self, gamma: AbstractSet[str], delta: AbstractSet[str]) -> bool:
        """Check if Gamma => Delta is an axiom of NMMS_B.

        Ax1 (Containment): Gamma ∩ Delta ≠ ∅.
        Ax2 (Base consequence): (Gamma, Delta) ∈ |~_B exactly, or a MONOTONE /
            GUARDED entry (Γ₀, Δ₀) with Γ₀ ⊆ Gamma, Δ₀ ⊆ Delta whose guard
            admits the additions.

        *gamma* and *delta* may be any ``collections.abc.Set`` of atom names
        (the reasoner passes :class:`~pynmms.sequent.AtomSet` views). Both
        checks are index-driven, so a large antecedent is never hashed or
        copied.
        """
        # Ax1: Containment
        if intersects(gamma, delta):
            return True
        # Ax2: exact entries of the same shape
        for g, d in self._by_size.get((len(gamma), len(delta)), ()):
            if all(x in gamma for x in g) and all(x in delta for x in d):
                return True
        # Ax2: robust entries, driven from the consequent side
        if self._robust_by_delta:
            return self._check_robust(gamma, delta)
        return False

    def _check_robust(self, gamma: AbstractSet[str], delta: AbstractSet[str]) -> bool:
        seen: set[int] = set()
        for key in (*delta, _EMPTY_KEY):
            for entry in self._robust_by_delta.get(key, ()):
                if id(entry) in seen:
                    continue
                seen.add(id(entry))
                g, d, robustness = entry
                if not (all(x in gamma for x in g) and all(x in delta for x in d)):
                    continue
                if robustness.allows(gamma, delta):
                    logger.debug("Robust entry %s |~ %s [%s] matched", set(g), set(d), robustness)
                    return True
                logger.debug(
                    "Robust entry %s |~ %s defeated by %s",
                    set(g), set(d), set(robustness.defeated_by(gamma, delta)),
                )
        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict.

        Every consequence carries an explicit ``robustness`` field so that
        files are self-describing if the default policy ever changes.
        """
        d: dict = {
            "language": sorted(self._language),
            "consequences": [
                {
                    "antecedent": sorted(gamma),
                    "consequent": sorted(delta),
                    "robustness": self.robustness_of(gamma, delta).to_json(),
                }
                for gamma, delta in sorted(
                    self._consequences, key=lambda s: (sorted(s[0]), sorted(s[1]))
                )
            ],
        }
        if self._annotations:
            d["annotations"] = dict(sorted(self._annotations.items()))
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MaterialBase:
        """Deserialize from a dict (as produced by ``to_dict``)."""
        language = set(data.get("language", []))
        consequences: set[Sequent] = set()
        robustness: dict[Sequent, Robustness] = {}
        for entry in data.get("consequences", []):
            pair = (frozenset(entry["antecedent"]), frozenset(entry["consequent"]))
            consequences.add(pair)
            policy = Robustness.from_json(entry.get("robustness"))
            if not policy.is_exact:
                robustness[pair] = policy
        annotations = data.get("annotations", {})
        return cls(
            language=language,
            consequences=consequences,
            annotations=annotations,
            robustness=robustness,
        )

    def to_file(self, path: str | Path) -> None:
        """Write the base to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.debug("Saved base to %s", path)

    @classmethod
    def from_file(cls, path: str | Path) -> MaterialBase:
        """Load a base from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        logger.debug("Loaded base from %s", path)
        return cls.from_dict(data)
