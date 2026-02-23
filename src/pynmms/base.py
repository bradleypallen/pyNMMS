"""Material base for propositional NMMS.

Implements the material base B = <L_B, |~_B> from Hlobil & Brandom 2025, Ch. 3,
Definition 1. The language L_B contains only atomic sentences (bare propositional
atoms). The consequence relation |~_B is a set of sequents over L_B satisfying the
Containment axiom: Gamma |~_B Delta whenever Gamma ∩ Delta ≠ ∅.

The base encodes *defeasible material inferences* among atomic sentences. Logical
vocabulary (negation, conjunction, disjunction, implication) is added by the
proof rules in ``reasoner.py``, not stored in the base.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pynmms.syntax import is_atomic

logger = logging.getLogger(__name__)

# A sequent is a pair of frozensets of atomic sentence strings.
Sequent = tuple[frozenset[str], frozenset[str]]

# Matches concept assertions C(a) and role assertions R(a,b).
_STRUCTURED_ATOM_RE = re.compile(r"^\w+\(\w+(?:,\s*\w+)?\)$")


def _validate_atomic(s: str, context: str) -> None:
    """Raise ValueError if *s* is not an atomic sentence."""
    if not is_atomic(s):
        raise ValueError(
            f"{context}: found logically complex sentence '{s}'. "
            f"Only bare atoms are permitted in the material base."
        )
    if _STRUCTURED_ATOM_RE.match(s):
        raise ValueError(
            f"{context}: '{s}' looks like a concept or role assertion. "
            f"Use --rq mode for NMMS_RQ atoms, or rename to a plain identifier."
        )


@dataclass
class MaterialBase:
    """A material base B = <L_B, |~_B> for propositional NMMS.

    Parameters:
        language: Set of atomic sentence strings comprising L_B.
        consequences: Set of (antecedent, consequent) sequent pairs comprising |~_B.
    """

    _language: set[str] = field(default_factory=set)
    _consequences: set[Sequent] = field(default_factory=set)

    def __init__(
        self,
        language: set[str] | frozenset[str] | None = None,
        consequences: (
            set[Sequent]
            | set[tuple[frozenset[str], frozenset[str]]]
            | None
        ) = None,
        annotations: dict[str, str] | None = None,
    ) -> None:
        self._language: set[str] = set(language) if language else set()
        self._consequences: set[Sequent] = set()
        self._annotations: dict[str, str] = dict(annotations) if annotations else {}

        # Validate all language atoms
        for s in self._language:
            _validate_atomic(s, "Material base language")

        # Validate and store consequences
        if consequences:
            for gamma, delta in consequences:
                for s in gamma | delta:
                    _validate_atomic(s, "Material base consequence")
                self._consequences.add((gamma, delta))

        logger.debug(
            "MaterialBase created: %d atoms, %d consequences",
            len(self._language),
            len(self._consequences),
        )

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

    # --- Mutation ---

    def add_atom(self, s: str) -> None:
        """Add an atomic sentence to the language L_B."""
        _validate_atomic(s, "add_atom")
        self._language.add(s)
        logger.debug("Added atom: %s", s)

    def annotate(self, atom: str, description: str) -> None:
        """Attach a natural-language description to an atom."""
        self._annotations[atom] = description
        logger.debug("Annotated atom %s: %s", atom, description)

    def add_consequence(self, antecedent: frozenset[str], consequent: frozenset[str]) -> None:
        """Add a base consequence Gamma |~_B Delta.

        All sentences in *antecedent* and *consequent* must be atomic. They are
        also implicitly added to the language.
        """
        for s in antecedent | consequent:
            _validate_atomic(s, "add_consequence")
            self._language.add(s)
        self._consequences.add((antecedent, consequent))
        logger.debug("Added consequence: %s |~ %s", set(antecedent), set(consequent))

    # --- Axiom check ---

    def is_axiom(self, gamma: frozenset[str], delta: frozenset[str]) -> bool:
        """Check if Gamma => Delta is an axiom of NMMS_B.

        Ax1 (Containment): Gamma ∩ Delta ≠ ∅.
        Ax2 (Base consequence): (Gamma, Delta) ∈ |~_B exactly.

        No Weakening: the base relation uses exact syntactic match.
        """
        # Ax1: Containment
        if gamma & delta:
            return True
        # Ax2: Explicit base consequence (exact match)
        if (gamma, delta) in self._consequences:
            return True
        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        d: dict = {
            "language": sorted(self._language),
            "consequences": [
                {
                    "antecedent": sorted(gamma),
                    "consequent": sorted(delta),
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
        for entry in data.get("consequences", []):
            gamma = frozenset(entry["antecedent"])
            delta = frozenset(entry["consequent"])
            consequences.add((gamma, delta))
        annotations = data.get("annotations", {})
        return cls(language=language, consequences=consequences, annotations=annotations)

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
