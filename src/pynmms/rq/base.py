"""RQ Material Base — placeholder, implemented in Phase 2."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pynmms.base import MaterialBase, Sequent
from pynmms.rq.syntax import (
    ATOM_CONCEPT,
    ATOM_ROLE,
    RQSentence,
    is_rq_atomic,
    make_concept_assertion,
    make_role_assertion,
    parse_rq_sentence,
)

logger = logging.getLogger(__name__)


def _validate_rq_atomic(s: str, context: str) -> None:
    """Raise ValueError if *s* is not an RQ-atomic sentence."""
    if not is_rq_atomic(s):
        raise ValueError(
            f"{context}: '{s}' is not valid in NMMS_RQ. "
            f"Only concept assertions C(a) and role assertions R(a,b) "
            f"are permitted in the RQ material base."
        )


@dataclass
class InferenceSchema:
    """A defeasible material inference schema from a quantified commitment.

    Attributes:
        source: The formal commitment that generated this schema.
        role: The role that scopes the quantification.
        subject_var: The variable being quantified over.
        trigger_concept: Concept in the restriction (or None).
        conclusion_concept: Concept concluded.
    """

    source: str
    role: str
    subject_var: str
    trigger_concept: str | None
    conclusion_concept: str


class RQMaterialBase(MaterialBase):
    """A material base for NMMS with restricted quantifiers.

    Extends ``MaterialBase`` to accept concept/role assertions as atomic,
    track vocabulary (individuals, concepts, roles), and support lazy
    inference schemas.
    """

    def __init__(
        self,
        language: set[str] | frozenset[str] | None = None,
        consequences: (
            set[Sequent] | set[tuple[frozenset[str], frozenset[str]]] | None
        ) = None,
        annotations: dict[str, str] | None = None,
    ) -> None:
        self._individuals: set[str] = set()
        self._concepts: set[str] = set()
        self._roles: set[str] = set()
        self._inference_schemas: list[
            tuple[str, str, str | None, frozenset[str]]
        ] = []
        self._schema_annotations: list[str | None] = []
        # Temporarily bypass parent validation — we override _validate
        self._rq_language: set[str] = set(language) if language else set()
        self._rq_consequences: set[Sequent] = set()

        # Validate RQ-atomic
        for s in self._rq_language:
            _validate_rq_atomic(s, "RQ material base language")
            self._extract_vocab(s)

        if consequences:
            for gamma, delta in consequences:
                for s in gamma | delta:
                    _validate_rq_atomic(s, "RQ material base consequence")
                    self._extract_vocab(s)
                self._rq_consequences.add((gamma, delta))

        # Initialize parent with empty sets — we manage storage ourselves
        super().__init__(annotations=annotations)
        self._language = self._rq_language
        self._consequences = self._rq_consequences

        logger.debug(
            "RQMaterialBase created: %d atoms, %d consequences, "
            "%d individuals, %d concepts, %d roles",
            len(self._language),
            len(self._consequences),
            len(self._individuals),
            len(self._concepts),
            len(self._roles),
        )

    def _extract_vocab(self, s: str) -> None:
        """Extract vocabulary (individuals, concepts, roles) from a sentence."""
        parsed = parse_rq_sentence(s)
        if isinstance(parsed, RQSentence):
            if parsed.type == ATOM_CONCEPT:
                self._individuals.add(parsed.individual)  # type: ignore[arg-type]
                self._concepts.add(parsed.concept)  # type: ignore[arg-type]
            elif parsed.type == ATOM_ROLE:
                self._individuals.add(parsed.arg1)  # type: ignore[arg-type]
                self._individuals.add(parsed.arg2)  # type: ignore[arg-type]
                self._roles.add(parsed.role)  # type: ignore[arg-type]

    # --- Read-only properties ---

    @property
    def individuals(self) -> frozenset[str]:
        """Known individuals (read-only)."""
        return frozenset(self._individuals)

    @property
    def concepts(self) -> frozenset[str]:
        """Known concepts (read-only)."""
        return frozenset(self._concepts)

    @property
    def roles(self) -> frozenset[str]:
        """Known roles (read-only)."""
        return frozenset(self._roles)

    @property
    def schema_annotations(self) -> list[str | None]:
        """Schema annotations (read-only view)."""
        return list(self._schema_annotations)

    # --- Mutation ---

    def add_atom(self, s: str) -> None:
        """Add an RQ-atomic sentence to the language."""
        _validate_rq_atomic(s, "add_atom")
        self._language.add(s)
        self._extract_vocab(s)
        logger.debug("Added atom: %s", s)

    def add_consequence(
        self, antecedent: frozenset[str], consequent: frozenset[str]
    ) -> None:
        """Add a base consequence. All sentences must be RQ-atomic."""
        for s in antecedent | consequent:
            _validate_rq_atomic(s, "add_consequence")
            self._language.add(s)
            self._extract_vocab(s)
        self._consequences.add((antecedent, consequent))
        logger.debug("Added consequence: %s |~ %s", set(antecedent), set(consequent))

    def add_individual(self, role: str, subject: str, obj: str) -> None:
        """Add a role assertion R(subject, obj) to the language."""
        role_assertion = make_role_assertion(role, subject, obj)
        self._language.add(role_assertion)
        self._extract_vocab(role_assertion)
        logger.debug("Added individual: %s", role_assertion)

    # --- Schema registration ---

    def register_concept_schema(
        self,
        role: str,
        subject: str,
        concept: str,
        annotation: str | None = None,
    ) -> None:
        """Register: for all role(subject, x), assert concept(x).

        Stored lazily — not grounded over known individuals.
        """
        self._inference_schemas.append((
            role,
            subject,
            None,
            frozenset({make_concept_assertion(concept, "__OBJ__")}),
        ))
        self._schema_annotations.append(annotation)
        logger.debug(
            "Registered concept schema: %s(%s, x) |~ %s(x)", role, subject, concept
        )

    def register_inference_schema(
        self,
        role: str,
        subject: str,
        premise_concept: str | None,
        conclusion: set[str],
        annotation: str | None = None,
    ) -> None:
        """Register: for all role(subject, x) with premise_concept(x), conclude.

        Conclusion may contain ``__OBJ__`` which is replaced with the
        matched individual at query time.
        """
        conclusion_fs = frozenset(conclusion)
        self._inference_schemas.append(
            (role, subject, premise_concept, conclusion_fs)
        )
        self._schema_annotations.append(annotation)
        logger.debug(
            "Registered inference schema: %s(%s, x), %s(x) |~ %s",
            role,
            subject,
            premise_concept,
            conclusion,
        )

    # --- Axiom check (overrides parent) ---

    def is_axiom(self, gamma: frozenset[str], delta: frozenset[str]) -> bool:
        """Check if Gamma => Delta is an axiom.

        Ax1 (Containment): Gamma & Delta != empty.
        Ax2 (Base consequence): (Gamma, Delta) in |~_B exactly.
        Ax3 (Schema consequence): matches a lazy schema.
        """
        # Ax1: Containment
        if gamma & delta:
            return True
        # Ax2: Explicit base consequence (exact match)
        if (gamma, delta) in self._consequences:
            return True
        # Ax3: Lazy schema evaluation
        if self._inference_schemas and self._check_schemas(gamma, delta):
            return True
        return False

    def _check_schemas(
        self, gamma: frozenset[str], delta: frozenset[str]
    ) -> bool:
        """Check if any schema makes gamma |~ delta hold.

        Exact match (no weakening) preserves nonmonotonicity.
        """
        for schema_role, schema_subject, premise_concept, conclusion_template in (
            self._inference_schemas
        ):
            for s in gamma:
                parsed = parse_rq_sentence(s)
                if (
                    isinstance(parsed, RQSentence)
                    and parsed.type == ATOM_ROLE
                    and parsed.role == schema_role
                    and parsed.arg1 == schema_subject
                ):
                    obj = parsed.arg2

                    # Build expected gamma
                    if premise_concept is not None:
                        premise = make_concept_assertion(premise_concept, obj)  # type: ignore[arg-type]
                        expected_gamma = frozenset({s, premise})
                    else:
                        expected_gamma = frozenset({s})

                    # Build expected delta: substitute __OBJ__ with obj
                    expected_delta = frozenset(
                        c.replace("__OBJ__", obj)  # type: ignore[arg-type]
                        if "__OBJ__" in c
                        else c
                        for c in conclusion_template
                    )

                    # Exact match (no weakening)
                    if gamma == expected_gamma and delta == expected_delta:
                        return True

        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict, including schemas."""
        base_dict = super().to_dict()
        base_dict["individuals"] = sorted(self._individuals)
        base_dict["concepts"] = sorted(self._concepts)
        base_dict["roles"] = sorted(self._roles)
        base_dict["schemas"] = [
            {
                "role": role,
                "subject": subject,
                "premise_concept": premise_concept,
                "conclusion": sorted(conclusion),
                **({"annotation": self._schema_annotations[i]}
                   if i < len(self._schema_annotations)
                   and self._schema_annotations[i]
                   else {}),
            }
            for i, (role, subject, premise_concept, conclusion)
            in enumerate(self._inference_schemas)
        ]
        return base_dict

    @classmethod
    def from_dict(cls, data: dict) -> RQMaterialBase:
        """Deserialize from a dict (as produced by ``to_dict``)."""
        language = set(data.get("language", []))
        consequences: set[Sequent] = set()
        for entry in data.get("consequences", []):
            gamma = frozenset(entry["antecedent"])
            delta = frozenset(entry["consequent"])
            consequences.add((gamma, delta))
        annotations = data.get("annotations", {})

        base = cls(language=language, consequences=consequences, annotations=annotations)

        # Restore schemas
        for schema in data.get("schemas", []):
            base._inference_schemas.append((
                schema["role"],
                schema["subject"],
                schema["premise_concept"],
                frozenset(schema["conclusion"]),
            ))
            base._schema_annotations.append(schema.get("annotation"))

        return base

    def to_file(self, path: str | Path) -> None:
        """Write the base to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.debug("Saved RQ base to %s", path)

    @classmethod
    def from_file(cls, path: str | Path) -> RQMaterialBase:
        """Load a base from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        logger.debug("Loaded RQ base from %s", path)
        return cls.from_dict(data)


class CommitmentStore:
    """Manages quantified commitments and compiles them to an RQMaterialBase.

    Higher-level API for managing assertions and schemas, bridging natural
    language commitments to the atomic material base.
    """

    def __init__(self) -> None:
        self.assertions: set[str] = set()
        self.schemas: list[InferenceSchema] = []
        self._ground_rules: set[Sequent] = set()
        self._base: RQMaterialBase | None = None

    def add_assertion(self, s: str) -> None:
        """Add an atomic assertion."""
        _validate_rq_atomic(s, "CommitmentStore.add_assertion")
        self.assertions.add(s)
        self._base = None

    def add_role(self, role: str, subject: str, obj: str) -> None:
        """Add a role assertion R(subject, obj)."""
        self.add_assertion(make_role_assertion(role, subject, obj))

    def add_concept(self, concept: str, individual: str) -> None:
        """Add a concept assertion C(individual)."""
        self.add_assertion(make_concept_assertion(concept, individual))

    def commit_universal(
        self,
        source: str,
        role: str,
        subject_var: str,
        trigger_concept: str,
        conclusion_concept: str,
    ) -> None:
        """Record a universal quantified commitment."""
        schema = InferenceSchema(
            source=source,
            role=role,
            subject_var=subject_var,
            trigger_concept=trigger_concept,
            conclusion_concept=conclusion_concept,
        )
        self.schemas.append(schema)
        self._base = None

    def commit_defeasible_rule(
        self,
        source: str,
        antecedent: frozenset[str],
        consequent: frozenset[str],
    ) -> None:
        """Record a ground defeasible material inference."""
        for s in antecedent | consequent:
            _validate_rq_atomic(s, f"commit_defeasible_rule ({source})")
            self.assertions.add(s)
        self._ground_rules.add((antecedent, consequent))
        self._base = None

    def retract_schema(self, source: str) -> None:
        """Retract all schemas with the given source."""
        self.schemas = [s for s in self.schemas if s.source != source]
        self._base = None

    def compile(self) -> RQMaterialBase:
        """Compile current commitments into an RQMaterialBase.

        Schemas are registered lazily — no eager grounding.
        """
        if self._base is not None:
            return self._base

        language = set(self.assertions)
        consequences: set[Sequent] = set(self._ground_rules)

        self._base = RQMaterialBase(
            language=language,
            consequences=consequences,
        )

        # Register schemas lazily
        for schema in self.schemas:
            if schema.trigger_concept:
                conclusion = make_concept_assertion(
                    schema.conclusion_concept, "__OBJ__"
                )
                self._base.register_inference_schema(
                    schema.role,
                    schema.subject_var,
                    schema.trigger_concept,
                    {conclusion},
                )
            else:
                self._base.register_concept_schema(
                    schema.role,
                    schema.subject_var,
                    schema.conclusion_concept,
                )

        return self._base

    def describe(self) -> str:
        """Human-readable description of current commitments."""
        lines = ["Commitment Store:"]
        lines.append(f"  Assertions: {len(self.assertions)}")
        for s in sorted(self.assertions):
            lines.append(f"    {s}")
        lines.append(f"  Schemas: {len(self.schemas)}")
        for schema in self.schemas:
            lines.append(f"    [{schema.source}]")
            lines.append(
                f"      {schema.role}({schema.subject_var}, x)"
                f", {schema.trigger_concept}(x)"
                if schema.trigger_concept
                else f"      {schema.role}({schema.subject_var}, x)"
                f" |~ {schema.conclusion_concept}(x)"
            )
        if self._ground_rules:
            lines.append(f"  Ground rules: {len(self._ground_rules)}")
            for ant, con in self._ground_rules:
                lines.append(f"    {set(ant)} |~ {set(con)}")
        return "\n".join(lines)
