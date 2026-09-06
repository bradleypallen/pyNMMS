# ruff: noqa
# Frozen copy of pyNMMS v0.6.2 (pre-Phase-1 reasoner) for differential testing.
"""Ontology Material Base -- ontology axiom schemas for NMMS.

Extends the propositional ``MaterialBase`` with ontology-style vocabulary
tracking (individuals, concepts, roles) and seven defeasible axiom schema
types: subClassOf, range, domain, subPropertyOf, disjointWith,
disjointProperties, jointCommitment.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .base import MaterialBase, Sequent
from .onto_syntax import (
    ATOM_CONCEPT,
    ATOM_ROLE,
    OntoSentence,
    is_onto_atomic,
    make_concept_assertion,
    make_role_assertion,
    parse_onto_sentence,
)

logger = logging.getLogger(__name__)


def _validate_onto_atomic(s: str, context: str) -> None:
    """Raise ValueError if *s* is not an onto-atomic sentence."""
    if not is_onto_atomic(s):
        raise ValueError(
            f"{context}: '{s}' is not valid in NMMS_Onto. "
            f"Only concept assertions C(a) and role assertions R(a,b) "
            f"are permitted in the ontology material base."
        )


class OntoMaterialBase(MaterialBase):
    """A material base for NMMS with ontology axiom schemas.

    Extends ``MaterialBase`` to accept concept/role assertions as atomic,
    track vocabulary (individuals, concepts, roles), and support seven
    ontology axiom schema types: subClassOf, range, domain, subPropertyOf,
    disjointWith, disjointProperties, jointCommitment.

    Schemas are evaluated lazily at query time -- not grounded over known
    individuals. All use exact match (no weakening) to preserve
    nonmonotonicity.
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
        self._onto_schemas: list[tuple[str, str, str, str | None]] = []
        # Temporarily bypass parent validation -- we override _validate
        self._onto_language: set[str] = set(language) if language else set()
        self._onto_consequences: set[Sequent] = set()

        # Validate onto-atomic
        for s in self._onto_language:
            _validate_onto_atomic(s, "Ontology material base language")
            self._extract_vocab(s)

        if consequences:
            for gamma, delta in consequences:
                for s in gamma | delta:
                    _validate_onto_atomic(s, "Ontology material base consequence")
                    self._extract_vocab(s)
                self._onto_consequences.add((gamma, delta))

        # Initialize parent with empty sets -- we manage storage ourselves
        super().__init__(annotations=annotations)
        self._language = self._onto_language
        self._consequences = self._onto_consequences

        logger.debug(
            "OntoMaterialBase created: %d atoms, %d consequences, "
            "%d individuals, %d concepts, %d roles",
            len(self._language),
            len(self._consequences),
            len(self._individuals),
            len(self._concepts),
            len(self._roles),
        )

    def _extract_vocab(self, s: str) -> None:
        """Extract vocabulary (individuals, concepts, roles) from a sentence."""
        parsed = parse_onto_sentence(s)
        if isinstance(parsed, OntoSentence):
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
    def onto_schemas(self) -> list[tuple[str, str, str, str | None]]:
        """Ontology schemas (read-only copy)."""
        return list(self._onto_schemas)

    # --- Mutation ---

    def add_atom(self, s: str) -> None:
        """Add an onto-atomic sentence to the language."""
        _validate_onto_atomic(s, "add_atom")
        self._language.add(s)
        self._extract_vocab(s)
        logger.debug("Added atom: %s", s)

    def add_consequence(
        self, antecedent: frozenset[str], consequent: frozenset[str]
    ) -> None:
        """Add a base consequence. All sentences must be onto-atomic."""
        for s in antecedent | consequent:
            _validate_onto_atomic(s, "add_consequence")
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

    # --- Ontology schema registration ---

    def register_subclass(
        self,
        sub_concept: str,
        super_concept: str,
        annotation: str | None = None,
    ) -> None:
        """Register subClassOf schema: {sub(x)} |~ {super(x)} for any x.

        Stored lazily -- not grounded over known individuals.
        """
        self._onto_schemas.append(("subClassOf", sub_concept, super_concept, annotation))
        logger.debug(
            "Registered subClassOf schema: %s ⊑ %s", sub_concept, super_concept
        )

    def register_range(
        self,
        role: str,
        concept: str,
        annotation: str | None = None,
    ) -> None:
        """Register range schema: {R(x,y)} |~ {C(y)} for any x, y.

        Stored lazily -- not grounded over known individuals.
        """
        self._onto_schemas.append(("range", role, concept, annotation))
        logger.debug("Registered range schema: range(%s) = %s", role, concept)

    def register_domain(
        self,
        role: str,
        concept: str,
        annotation: str | None = None,
    ) -> None:
        """Register domain schema: {R(x,y)} |~ {C(x)} for any x, y.

        Stored lazily -- not grounded over known individuals.
        """
        self._onto_schemas.append(("domain", role, concept, annotation))
        logger.debug("Registered domain schema: domain(%s) = %s", role, concept)

    def register_subproperty(
        self,
        sub_role: str,
        super_role: str,
        annotation: str | None = None,
    ) -> None:
        """Register subPropertyOf schema: {R(x,y)} |~ {S(x,y)} for any x, y.

        Stored lazily -- not grounded over known individuals.
        """
        self._onto_schemas.append(("subPropertyOf", sub_role, super_role, annotation))
        logger.debug(
            "Registered subPropertyOf schema: %s ⊑ %s", sub_role, super_role
        )

    def register_disjoint(
        self,
        concept1: str,
        concept2: str,
        annotation: str | None = None,
    ) -> None:
        """Register disjointWith schema: {C(x), D(x)} |~_B {} for any x.

        Material incompatibility between two concepts. Stored lazily.
        """
        self._onto_schemas.append(("disjointWith", concept1, concept2, annotation))
        logger.debug(
            "Registered disjointWith schema: %s ⊥ %s", concept1, concept2
        )

    def register_disjoint_properties(
        self,
        role1: str,
        role2: str,
        annotation: str | None = None,
    ) -> None:
        """Register disjointProperties schema: {R(x,y), S(x,y)} |~_B {} for any x, y.

        Material incompatibility between two roles. Stored lazily.
        """
        self._onto_schemas.append(("disjointProperties", role1, role2, annotation))
        logger.debug(
            "Registered disjointProperties schema: %s ⊥ %s", role1, role2
        )

    def register_joint_commitment(
        self,
        antecedent_concepts: list[str],
        consequent_concept: str,
        annotation: str | None = None,
    ) -> None:
        """Register jointCommitment schema: {C1(x), ..., Cn(x)} |~_B {D(x)} for any x.

        Joint material inferential commitment from multiple concepts to a
        consequent concept.  Requires at least 2 antecedent concepts (with 1,
        use ``register_subclass`` instead).  Stored lazily.
        """
        if len(antecedent_concepts) < 2:
            raise ValueError(
                "jointCommitment requires at least 2 antecedent concepts "
                "(use subClassOf for a single antecedent)."
            )
        arg1 = ",".join(antecedent_concepts)
        self._onto_schemas.append(("jointCommitment", arg1, consequent_concept, annotation))
        logger.debug(
            "Registered jointCommitment schema: {%s} |~ {%s}",
            ", ".join(f"{c}(x)" for c in antecedent_concepts),
            f"{consequent_concept}(x)",
        )

    # --- Axiom check (overrides parent) ---

    def is_axiom(self, gamma: frozenset[str], delta: frozenset[str]) -> bool:
        """Check if Gamma => Delta is an axiom.

        Ax1 (Containment): Gamma & Delta != empty.
        Ax2 (Base consequence): (Gamma, Delta) in |~_B exactly.
        Ax3 (Ontology schema consequence): matches a lazy ontology schema.
        """
        # Ax1: Containment
        if gamma & delta:
            return True
        # Ax2: Explicit base consequence (exact match)
        if (gamma, delta) in self._consequences:
            return True
        # Ax3: Ontology schema evaluation
        if self._onto_schemas and self._check_onto_schemas(gamma, delta):
            return True
        return False

    def _check_onto_schemas(
        self, gamma: frozenset[str], delta: frozenset[str]
    ) -> bool:
        """Check if any ontology schema makes gamma |~ delta hold.

        Exact match (no weakening) preserves nonmonotonicity.
        Inference schemas: len(gamma) == 1, len(delta) == 1.
        Incompatibility schemas: len(gamma) == 2, len(delta) == 0.
        Joint commitment schemas: len(gamma) >= 2, len(delta) == 1.
        """
        # --- Inference schemas: singleton antecedent, singleton consequent ---
        if len(gamma) == 1 and len(delta) == 1:
            gamma_str = next(iter(gamma))
            delta_str = next(iter(delta))

            try:
                gamma_parsed = parse_onto_sentence(gamma_str)
                delta_parsed = parse_onto_sentence(delta_str)
            except ValueError:
                return False

            if not isinstance(gamma_parsed, OntoSentence) or not isinstance(
                delta_parsed, OntoSentence
            ):
                return False

            for schema_type, arg1, arg2, _annotation in self._onto_schemas:
                if schema_type == "subClassOf":
                    # {C(x)} |~ {D(x)} -- same individual
                    if (
                        gamma_parsed.type == ATOM_CONCEPT
                        and delta_parsed.type == ATOM_CONCEPT
                        and gamma_parsed.concept == arg1
                        and delta_parsed.concept == arg2
                        and gamma_parsed.individual == delta_parsed.individual
                    ):
                        return True

                elif schema_type == "range":
                    # {R(x,y)} |~ {C(y)} -- role.arg2 == concept.individual
                    if (
                        gamma_parsed.type == ATOM_ROLE
                        and delta_parsed.type == ATOM_CONCEPT
                        and gamma_parsed.role == arg1
                        and delta_parsed.concept == arg2
                        and gamma_parsed.arg2 == delta_parsed.individual
                    ):
                        return True

                elif schema_type == "domain":
                    # {R(x,y)} |~ {C(x)} -- role.arg1 == concept.individual
                    if (
                        gamma_parsed.type == ATOM_ROLE
                        and delta_parsed.type == ATOM_CONCEPT
                        and gamma_parsed.role == arg1
                        and delta_parsed.concept == arg2
                        and gamma_parsed.arg1 == delta_parsed.individual
                    ):
                        return True

                elif schema_type == "subPropertyOf":
                    # {R(x,y)} |~ {S(x,y)} -- same arg1, same arg2
                    if (
                        gamma_parsed.type == ATOM_ROLE
                        and delta_parsed.type == ATOM_ROLE
                        and gamma_parsed.role == arg1
                        and delta_parsed.role == arg2
                        and gamma_parsed.arg1 == delta_parsed.arg1
                        and gamma_parsed.arg2 == delta_parsed.arg2
                    ):
                        return True

            return False

        # --- Incompatibility schemas: two-element antecedent, empty consequent ---
        if len(gamma) == 2 and len(delta) == 0:
            gamma_list = sorted(gamma)  # deterministic iteration
            try:
                parsed_0 = parse_onto_sentence(gamma_list[0])
                parsed_1 = parse_onto_sentence(gamma_list[1])
            except ValueError:
                return False

            if not isinstance(parsed_0, OntoSentence) or not isinstance(
                parsed_1, OntoSentence
            ):
                return False

            for schema_type, arg1, arg2, _annotation in self._onto_schemas:
                if schema_type == "disjointWith":
                    # Both concept assertions, same individual, concepts match {arg1, arg2}
                    if (
                        parsed_0.type == ATOM_CONCEPT
                        and parsed_1.type == ATOM_CONCEPT
                        and parsed_0.individual == parsed_1.individual
                        and {parsed_0.concept, parsed_1.concept} == {arg1, arg2}
                    ):
                        return True

                elif schema_type == "disjointProperties":
                    # Both role assertions, same args, roles match {arg1, arg2}
                    if (
                        parsed_0.type == ATOM_ROLE
                        and parsed_1.type == ATOM_ROLE
                        and parsed_0.arg1 == parsed_1.arg1
                        and parsed_0.arg2 == parsed_1.arg2
                        and {parsed_0.role, parsed_1.role} == {arg1, arg2}
                    ):
                        return True

            return False

        # --- Joint commitment schemas: multi-element antecedent, singleton consequent ---
        if len(gamma) >= 2 and len(delta) == 1:
            delta_str = next(iter(delta))

            try:
                delta_parsed = parse_onto_sentence(delta_str)
            except ValueError:
                return False

            if not isinstance(delta_parsed, OntoSentence):
                return False
            if delta_parsed.type != ATOM_CONCEPT:
                return False

            # Parse all gamma elements -- all must be concept assertions
            gamma_parsed_list: list[OntoSentence] = []
            for g_str in gamma:
                try:
                    g_parsed = parse_onto_sentence(g_str)
                except ValueError:
                    return False
                if not isinstance(g_parsed, OntoSentence):
                    return False
                if g_parsed.type != ATOM_CONCEPT:
                    return False
                gamma_parsed_list.append(g_parsed)

            # All gamma elements must share the same individual as delta
            target_individual = delta_parsed.individual
            if not all(g.individual == target_individual for g in gamma_parsed_list):
                return False

            gamma_concepts = {g.concept for g in gamma_parsed_list}

            for schema_type, arg1, arg2, _annotation in self._onto_schemas:
                if schema_type == "jointCommitment":
                    schema_concepts = set(arg1.split(","))
                    if gamma_concepts == schema_concepts and delta_parsed.concept == arg2:
                        return True

            return False

        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict, including ontology schemas."""
        base_dict = super().to_dict()
        base_dict["individuals"] = sorted(self._individuals)
        base_dict["concepts"] = sorted(self._concepts)
        base_dict["roles"] = sorted(self._roles)
        onto_schema_list = []
        for schema_type, arg1, arg2, annotation in self._onto_schemas:
            entry: dict[str, str | list[str]] = {
                "type": schema_type,
                "arg1": arg1.split(",") if schema_type == "jointCommitment" else arg1,
                "arg2": arg2,
            }
            if annotation:
                entry["annotation"] = annotation
            onto_schema_list.append(entry)
        base_dict["onto_schemas"] = onto_schema_list
        return base_dict

    @classmethod
    def from_dict(cls, data: dict) -> OntoMaterialBase:
        """Deserialize from a dict (as produced by ``to_dict``)."""
        language = set(data.get("language", []))
        consequences: set[Sequent] = set()
        for entry in data.get("consequences", []):
            gamma = frozenset(entry["antecedent"])
            delta = frozenset(entry["consequent"])
            consequences.add((gamma, delta))
        annotations = data.get("annotations", {})

        base = cls(language=language, consequences=consequences, annotations=annotations)

        # Restore ontology schemas
        schemas_data = data.get("onto_schemas", [])
        for schema in schemas_data:
            arg1 = schema["arg1"]
            # jointCommitment stores arg1 as a list in JSON; join for internal repr
            if isinstance(arg1, list):
                arg1 = ",".join(arg1)
            base._onto_schemas.append((
                schema["type"],
                arg1,
                schema["arg2"],
                schema.get("annotation"),
            ))

        return base

    def to_file(self, path: str | Path) -> None:
        """Write the base to a JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.debug("Saved ontology base to %s", path)

    @classmethod
    def from_file(cls, path: str | Path) -> OntoMaterialBase:
        """Load a base from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        logger.debug("Loaded ontology base from %s", path)
        return cls.from_dict(data)


class CommitmentStore:
    """Manages ontology commitments and compiles them to an OntoMaterialBase.

    Higher-level API for managing assertions and ontology schemas, bridging
    natural language commitments to the atomic material base.
    """

    def __init__(self) -> None:
        self.assertions: set[str] = set()
        self._onto_commitments: list[tuple[str, str, str, str]] = []
        self._ground_rules: set[Sequent] = set()
        self._base: OntoMaterialBase | None = None

    def add_assertion(self, s: str) -> None:
        """Add an atomic assertion."""
        _validate_onto_atomic(s, "CommitmentStore.add_assertion")
        self.assertions.add(s)
        self._base = None

    def add_role(self, role: str, subject: str, obj: str) -> None:
        """Add a role assertion R(subject, obj)."""
        self.add_assertion(make_role_assertion(role, subject, obj))

    def add_concept(self, concept: str, individual: str) -> None:
        """Add a concept assertion C(individual)."""
        self.add_assertion(make_concept_assertion(concept, individual))

    def commit_subclass(
        self,
        source: str,
        sub_concept: str,
        super_concept: str,
    ) -> None:
        """Record a subClassOf commitment: {sub(x)} |~ {super(x)}."""
        self._onto_commitments.append((source, "subClassOf", sub_concept, super_concept))
        self._base = None

    def commit_range(
        self,
        source: str,
        role: str,
        concept: str,
    ) -> None:
        """Record a range commitment: {R(x,y)} |~ {C(y)}."""
        self._onto_commitments.append((source, "range", role, concept))
        self._base = None

    def commit_domain(
        self,
        source: str,
        role: str,
        concept: str,
    ) -> None:
        """Record a domain commitment: {R(x,y)} |~ {C(x)}."""
        self._onto_commitments.append((source, "domain", role, concept))
        self._base = None

    def commit_subproperty(
        self,
        source: str,
        sub_role: str,
        super_role: str,
    ) -> None:
        """Record a subPropertyOf commitment: {R(x,y)} |~ {S(x,y)}."""
        self._onto_commitments.append((source, "subPropertyOf", sub_role, super_role))
        self._base = None

    def commit_disjoint(
        self,
        source: str,
        concept1: str,
        concept2: str,
    ) -> None:
        """Record a disjointWith commitment: {C(x), D(x)} |~ {}."""
        self._onto_commitments.append((source, "disjointWith", concept1, concept2))
        self._base = None

    def commit_disjoint_properties(
        self,
        source: str,
        role1: str,
        role2: str,
    ) -> None:
        """Record a disjointProperties commitment: {R(x,y), S(x,y)} |~ {}."""
        self._onto_commitments.append((source, "disjointProperties", role1, role2))
        self._base = None

    def commit_joint_commitment(
        self,
        source: str,
        antecedent_concepts: list[str],
        consequent_concept: str,
    ) -> None:
        """Record a jointCommitment commitment: {C1(x), ..., Cn(x)} |~ {D(x)}."""
        if len(antecedent_concepts) < 2:
            raise ValueError(
                "jointCommitment requires at least 2 antecedent concepts "
                "(use subClassOf for a single antecedent)."
            )
        arg1 = ",".join(antecedent_concepts)
        self._onto_commitments.append((source, "jointCommitment", arg1, consequent_concept))
        self._base = None

    def commit_defeasible_rule(
        self,
        source: str,
        antecedent: frozenset[str],
        consequent: frozenset[str],
    ) -> None:
        """Record a ground defeasible material inference."""
        for s in antecedent | consequent:
            _validate_onto_atomic(s, f"commit_defeasible_rule ({source})")
            self.assertions.add(s)
        self._ground_rules.add((antecedent, consequent))
        self._base = None

    def retract_schema(self, source: str) -> None:
        """Retract all schemas with the given source."""
        self._onto_commitments = [
            c for c in self._onto_commitments if c[0] != source
        ]
        self._base = None

    def compile(self) -> OntoMaterialBase:
        """Compile current commitments into an OntoMaterialBase.

        Schemas are registered lazily -- no eager grounding.
        """
        if self._base is not None:
            return self._base

        language = set(self.assertions)
        consequences: set[Sequent] = set(self._ground_rules)

        self._base = OntoMaterialBase(
            language=language,
            consequences=consequences,
        )

        # Register ontology schemas lazily
        for _source, schema_type, arg1, arg2 in self._onto_commitments:
            if schema_type == "subClassOf":
                self._base.register_subclass(arg1, arg2)
            elif schema_type == "range":
                self._base.register_range(arg1, arg2)
            elif schema_type == "domain":
                self._base.register_domain(arg1, arg2)
            elif schema_type == "subPropertyOf":
                self._base.register_subproperty(arg1, arg2)
            elif schema_type == "disjointWith":
                self._base.register_disjoint(arg1, arg2)
            elif schema_type == "disjointProperties":
                self._base.register_disjoint_properties(arg1, arg2)
            elif schema_type == "jointCommitment":
                self._base.register_joint_commitment(arg1.split(","), arg2)

        return self._base

    def describe(self) -> str:
        """Human-readable description of current commitments."""
        lines = ["Commitment Store:"]
        lines.append(f"  Assertions: {len(self.assertions)}")
        for s in sorted(self.assertions):
            lines.append(f"    {s}")
        lines.append(f"  Ontology Schemas: {len(self._onto_commitments)}")
        for source, schema_type, arg1, arg2 in self._onto_commitments:
            if schema_type == "subClassOf":
                pattern = f"{arg1}(x) |~ {arg2}(x)"
            elif schema_type == "range":
                pattern = f"{arg1}(x,y) |~ {arg2}(y)"
            elif schema_type == "domain":
                pattern = f"{arg1}(x,y) |~ {arg2}(x)"
            elif schema_type == "subPropertyOf":
                pattern = f"{arg1}(x,y) |~ {arg2}(x,y)"
            elif schema_type == "disjointWith":
                pattern = f"{arg1}(x), {arg2}(x) |~"
            elif schema_type == "disjointProperties":
                pattern = f"{arg1}(x,y), {arg2}(x,y) |~"
            elif schema_type == "jointCommitment":
                concepts = arg1.split(",")
                ant_str = ", ".join(f"{c}(x)" for c in concepts)
                pattern = f"{ant_str} |~ {arg2}(x)"
            else:
                pattern = f"{arg1} -> {arg2}"  # pragma: no cover
            lines.append(f"    [{source}] {schema_type}: {pattern}")
        if self._ground_rules:
            lines.append(f"  Ground rules: {len(self._ground_rules)}")
            for ant, con in self._ground_rules:
                lines.append(f"    {set(ant)} |~ {set(con)}")
        return "\n".join(lines)
