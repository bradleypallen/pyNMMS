"""Ontology Material Base -- ontology axiom schemas for NMMS.

``OntoMaterialBase`` extends ``MaterialBase`` with vocabulary tracking
(individuals, concepts, roles) and seven lazily evaluated ontology axiom
schema types. Schemas are macros over base axioms: they never add proof
rules, only pairs to |~_B, so the plain ``NMMSReasoner`` works unchanged.

Every schema carries a :class:`~pynmms.robustness.Robustness` policy:

* EXACT (default): ``{C(x)} |~ {D(x)}`` matches only that sequent.
* MONOTONE: also matches any ``Γ ⊇ {C(x)}``, ``Δ ⊇ {D(x)}``.
* GUARDED(left): MONOTONE unless some defeater concept ``E`` in ``left`` has
  ``E(i) ∈ Γ`` for an individual ``i`` of the matched consequent.

Schemas are indexed by the consequent's concept or role (and by concept pair
for incompatibilities), so a match costs O(candidates) regardless of how many
schemas are registered, for hits and misses alike. The only O(|Γ|) paths are
MONOTONE/GUARDED ``range``, ``domain`` and incompatibility schemas, which have
to find a role or partner atom somewhere in Γ; a store-backed antecedent
(Phase 3) answers those with a pattern query instead.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from pynmms.base import MaterialBase, Sequent
from pynmms.onto.syntax import (
    ATOM_CONCEPT,
    ATOM_ROLE,
    OntoSentence,
    make_concept_assertion,
    make_role_assertion,
    parse_onto_sentence,
)
from pynmms.robustness import EXACT, Robustness
from pynmms.sequent import AtomsView

logger = logging.getLogger(__name__)

# Canonical atom forms (no internal whitespace).
_CONCEPT_RE = re.compile(r"^(\w+)\((\w+)\)$")
_ROLE_RE = re.compile(r"^(\w+)\((\w+),(\w+)\)$")

INFERENCE_SCHEMAS = ("subClassOf", "range", "domain", "subPropertyOf", "jointCommitment")
INCOMPATIBILITY_SCHEMAS = ("disjointWith", "disjointProperties")
SCHEMA_TYPES = INFERENCE_SCHEMAS + INCOMPATIBILITY_SCHEMAS


def _validate_onto_atomic(s: str, context: str) -> str:
    """Return the canonical form of an onto-atomic sentence, or raise ValueError."""
    try:
        parsed = parse_onto_sentence(s)
    except ValueError:
        parsed = None
    if isinstance(parsed, OntoSentence):
        if parsed.type == ATOM_CONCEPT:
            assert parsed.concept is not None and parsed.individual is not None
            return make_concept_assertion(parsed.concept, parsed.individual)
        if parsed.type == ATOM_ROLE:
            assert parsed.role is not None
            assert parsed.arg1 is not None and parsed.arg2 is not None
            return make_role_assertion(parsed.role, parsed.arg1, parsed.arg2)
    raise ValueError(
        f"{context}: '{s}' is not valid in NMMS_Onto. "
        f"Only concept assertions C(a) and role assertions R(a,b) "
        f"are permitted in the ontology material base."
    )


class SchemaEntry(NamedTuple):
    """A registered ontology schema.

    ``arg1`` is the sub-concept / role / first concept, or for
    ``jointCommitment`` the comma-joined antecedent concepts; ``arg2`` is the
    super-concept / concept / super-role / second concept.
    """

    type: str
    arg1: str
    arg2: str
    annotation: str | None
    robustness: Robustness

    @property
    def concepts(self) -> list[str]:
        """Antecedent concepts of a jointCommitment schema."""
        return self.arg1.split(",")


class OntoMaterialBase(MaterialBase):
    """Material base with vocabulary tracking and ontology axiom schemas.

    Parameters:
        language: Onto-atomic sentences (``C(a)``, ``R(a,b)``).
        consequences: Base consequence pairs over onto-atomic sentences.
        annotations: Optional natural-language descriptions for atoms.
        robustness: Optional per-consequence policies (see ``MaterialBase``).
    """

    def __init__(
        self,
        language: set[str] | frozenset[str] | None = None,
        consequences: (
            set[Sequent] | set[tuple[frozenset[str], frozenset[str]]] | None
        ) = None,
        annotations: dict[str, str] | None = None,
        robustness: dict[Sequent, Robustness] | None = None,
    ) -> None:
        self._individuals: set[str] = set()
        self._concepts: set[str] = set()
        self._roles: set[str] = set()
        self._onto_schemas: list[SchemaEntry] = []
        self._init_schema_index()
        super().__init__(
            language=language,
            consequences=consequences,
            annotations=annotations,
            robustness=robustness,
        )
        logger.debug(
            "OntoMaterialBase created: %d atoms, %d consequences, "
            "%d individuals, %d concepts, %d roles",
            len(self._language),
            len(self._consequences),
            len(self._individuals),
            len(self._concepts),
            len(self._roles),
        )

    # --- Validation and vocabulary ---

    def _validate_atom(self, s: str, context: str) -> str:
        name = _validate_onto_atomic(s, context)
        self._extract_vocab(name)
        return name

    def _extract_vocab(self, s: str) -> None:
        """Record the individuals, concepts, and roles occurring in canonical *s*."""
        m = _CONCEPT_RE.match(s)
        if m:
            self._concepts.add(m.group(1))
            self._individuals.add(m.group(2))
            return
        m = _ROLE_RE.match(s)
        if m:
            self._roles.add(m.group(1))
            self._individuals.add(m.group(2))
            self._individuals.add(m.group(3))

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
    def onto_schemas(self) -> list[SchemaEntry]:
        """Registered ontology schemas, in registration order (read-only copy)."""
        return list(self._onto_schemas)

    # --- Mutation ---

    def add_individual(self, role: str, subject: str, obj: str) -> None:
        """Add a role assertion R(subject, obj) to the language."""
        role_assertion = make_role_assertion(role, subject, obj)
        self._language.add(role_assertion)
        self._extract_vocab(role_assertion)
        self._touch()
        logger.debug("Added individual: %s", role_assertion)

    # --- Ontology schema registration ---

    def _register(self, entry: SchemaEntry, pattern: str) -> None:
        self._onto_schemas.append(entry)
        self._index_schema(entry)
        self._touch()
        logger.debug(
            "Registered %s schema: %s [%s]%s",
            entry.type, pattern, entry.robustness,
            f" -- {entry.annotation}" if entry.annotation else "",
        )

    def register_subclass(
        self,
        sub_concept: str,
        super_concept: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register subClassOf schema: {sub(x)} |~ {super(x)} for any x."""
        self._register(
            SchemaEntry("subClassOf", sub_concept, super_concept, annotation, robustness),
            f"{sub_concept} ⊑ {super_concept}",
        )

    def register_range(
        self,
        role: str,
        concept: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register range schema: {R(x,y)} |~ {C(y)} for any x, y."""
        self._register(
            SchemaEntry("range", role, concept, annotation, robustness),
            f"range({role}) = {concept}",
        )

    def register_domain(
        self,
        role: str,
        concept: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register domain schema: {R(x,y)} |~ {C(x)} for any x, y."""
        self._register(
            SchemaEntry("domain", role, concept, annotation, robustness),
            f"domain({role}) = {concept}",
        )

    def register_subproperty(
        self,
        sub_role: str,
        super_role: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register subPropertyOf schema: {R(x,y)} |~ {S(x,y)} for any x, y."""
        self._register(
            SchemaEntry("subPropertyOf", sub_role, super_role, annotation, robustness),
            f"{sub_role} ⊑ {super_role}",
        )

    def register_disjoint(
        self,
        concept1: str,
        concept2: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register disjointWith schema: {C(x), D(x)} |~ {} for any x."""
        self._register(
            SchemaEntry("disjointWith", concept1, concept2, annotation, robustness),
            f"{concept1} ⊥ {concept2}",
        )

    def register_disjoint_properties(
        self,
        role1: str,
        role2: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register disjointProperties schema: {R(x,y), S(x,y)} |~ {} for any x, y."""
        self._register(
            SchemaEntry("disjointProperties", role1, role2, annotation, robustness),
            f"{role1} ⊥ {role2}",
        )

    def register_joint_commitment(
        self,
        antecedent_concepts: Sequence[str],
        consequent_concept: str,
        annotation: str | None = None,
        robustness: Robustness = EXACT,
    ) -> None:
        """Register jointCommitment schema: {C1(x), ..., Cn(x)} |~ {D(x)} for any x.

        Requires at least 2 antecedent concepts (with 1, use ``register_subclass``).
        """
        concepts = list(antecedent_concepts)
        if len(concepts) < 2:
            raise ValueError(
                "jointCommitment requires at least 2 antecedent concepts "
                "(use subClassOf for a single antecedent)."
            )
        self._register(
            SchemaEntry(
                "jointCommitment", ",".join(concepts), consequent_concept, annotation, robustness
            ),
            f"{{{', '.join(concepts)}}} |~ {consequent_concept}",
        )

    # --- Schema index ---

    def _init_schema_index(self) -> None:
        self._sub_by_super: dict[str, list[SchemaEntry]] = {}
        self._range_by_concept: dict[str, list[SchemaEntry]] = {}
        self._domain_by_concept: dict[str, list[SchemaEntry]] = {}
        self._subprop_by_super: dict[str, list[SchemaEntry]] = {}
        self._joint_by_consequent: dict[str, list[SchemaEntry]] = {}
        self._disjoint_by_pair: dict[frozenset[str], list[SchemaEntry]] = {}
        self._disjoint_by_concept: dict[str, list[SchemaEntry]] = {}
        self._disjoint_props_by_pair: dict[frozenset[str], list[SchemaEntry]] = {}
        self._disjoint_props_by_role: dict[str, list[SchemaEntry]] = {}
        # True once any incompatibility schema is MONOTONE/GUARDED, which is
        # the only case that needs a scan of Γ for a partner atom.
        self._robust_incompat: bool = False

    def _index_schema(self, e: SchemaEntry) -> None:
        if e.type == "subClassOf":
            self._sub_by_super.setdefault(e.arg2, []).append(e)
        elif e.type == "range":
            self._range_by_concept.setdefault(e.arg2, []).append(e)
        elif e.type == "domain":
            self._domain_by_concept.setdefault(e.arg2, []).append(e)
        elif e.type == "subPropertyOf":
            self._subprop_by_super.setdefault(e.arg2, []).append(e)
        elif e.type == "jointCommitment":
            self._joint_by_consequent.setdefault(e.arg2, []).append(e)
        elif e.type == "disjointWith":
            self._disjoint_by_pair.setdefault(frozenset({e.arg1, e.arg2}), []).append(e)
            for c in {e.arg1, e.arg2}:
                self._disjoint_by_concept.setdefault(c, []).append(e)
            self._robust_incompat |= not e.robustness.is_exact
        elif e.type == "disjointProperties":
            self._disjoint_props_by_pair.setdefault(frozenset({e.arg1, e.arg2}), []).append(e)
            for r in {e.arg1, e.arg2}:
                self._disjoint_props_by_role.setdefault(r, []).append(e)
            self._robust_incompat |= not e.robustness.is_exact
        else:  # pragma: no cover
            raise ValueError(f"Unknown schema type {e.type!r}")

    def _reindex(self) -> None:
        super()._reindex()
        self._init_schema_index()
        for e in self._onto_schemas:
            self._index_schema(e)

    # --- Axiom check ---

    def is_axiom(self, gamma: AtomsView, delta: AtomsView) -> bool:
        """Check if Gamma => Delta is an axiom.

        Ax1 (Containment): Gamma & Delta != empty.
        Ax2 (Base consequence): (Gamma, Delta) in |~_B (exact or robust).
        Ax3 (Ontology schema consequence): matches a lazy ontology schema.
        """
        if super().is_axiom(gamma, delta):
            return True
        if self._onto_schemas and self._check_onto_schemas(gamma, delta):
            return True
        return False

    def _check_onto_schemas(self, gamma: AtomsView, delta: AtomsView) -> bool:
        """Index-driven schema match.

        Inference schemas need a singleton consequent; incompatibility schemas
        need an empty one. Dispatch is on the consequent's concept or role, so
        neither hits nor misses scan the schema list.
        """
        if len(delta) == 1:
            return self._check_inference_schemas(gamma, next(iter(delta)))
        if len(delta) == 0:
            return self._check_incompatibility_schemas(gamma)
        return False

    def _applies(
        self, e: SchemaEntry, gamma: AtomsView, individuals: tuple[str, ...], needed: int
    ) -> bool:
        """Policy check once the schema's own antecedent atoms are known to be in Γ.

        *needed* is the size of the schema's antecedent instance; an EXACT
        schema requires Γ to be exactly that instance.
        """
        rob = e.robustness
        if rob.is_exact:
            return len(gamma) == needed
        for defeater in rob.left:
            for i in individuals:
                if make_concept_assertion(defeater, i) in gamma:
                    logger.debug(
                        "%s schema %s/%s defeated by %s(%s)", e.type, e.arg1, e.arg2, defeater, i
                    )
                    return False
        for x, _y in rob.exclusions:
            # a conjunctive defeater fires when all its concepts hold of one individual
            for i in individuals:
                if all(make_concept_assertion(d, i) in gamma for d in x):
                    logger.debug(
                        "%s schema %s/%s defeated by %s on %s", e.type, e.arg1, e.arg2,
                        " & ".join(sorted(x)), i,
                    )
                    return False
        return True

    def _check_inference_schemas(self, gamma: AtomsView, d: str) -> bool:
        m = _CONCEPT_RE.match(d)
        if m:
            concept, x = m.group(1), m.group(2)
            for e in self._sub_by_super.get(concept, ()):
                if make_concept_assertion(e.arg1, x) in gamma and self._applies(e, gamma, (x,), 1):
                    return True
            for e in self._joint_by_consequent.get(concept, ()):
                cs = e.concepts
                if all(make_concept_assertion(c, x) in gamma for c in cs) and self._applies(
                    e, gamma, (x,), len(cs)
                ):
                    return True
            for e in self._range_by_concept.get(concept, ()):
                args = self._find_role(gamma, e.arg1, arg2=x, exact=e.robustness.is_exact)
                if args is not None and self._applies(e, gamma, args, 1):
                    return True
            for e in self._domain_by_concept.get(concept, ()):
                args = self._find_role(gamma, e.arg1, arg1=x, exact=e.robustness.is_exact)
                if args is not None and self._applies(e, gamma, args, 1):
                    return True
            return False
        m = _ROLE_RE.match(d)
        if m:
            role, x, y = m.group(1), m.group(2), m.group(3)
            for e in self._subprop_by_super.get(role, ()):
                if make_role_assertion(e.arg1, x, y) in gamma and self._applies(
                    e, gamma, (x, y), 1
                ):
                    return True
        return False

    @staticmethod
    def _find_role(
        gamma: AtomsView,
        role: str,
        *,
        arg1: str | None = None,
        arg2: str | None = None,
        exact: bool,
    ) -> tuple[str, str] | None:
        """Find ``role(a, b)`` in Γ with the given fixed argument(s).

        An EXACT schema only looks at a singleton Γ; otherwise Γ is scanned.
        """
        if exact and len(gamma) != 1:
            return None
        prefix = role + "("
        for atom in gamma:
            if not atom.startswith(prefix):
                continue
            m = _ROLE_RE.match(atom)
            if not m:
                continue
            a, b = m.group(2), m.group(3)
            if (arg1 is None or a == arg1) and (arg2 is None or b == arg2):
                return (a, b)
        return None

    def _check_incompatibility_schemas(self, gamma: AtomsView) -> bool:
        if len(gamma) < 2:
            return False
        if len(gamma) == 2:
            a, b = sorted(gamma)
            ca, cb = _CONCEPT_RE.match(a), _CONCEPT_RE.match(b)
            if ca and cb and ca.group(2) == cb.group(2):
                pair = frozenset({ca.group(1), cb.group(1)})
                for e in self._disjoint_by_pair.get(pair, ()):
                    if self._applies(e, gamma, (ca.group(2),), 2):
                        return True
                return False
            ra, rb = _ROLE_RE.match(a), _ROLE_RE.match(b)
            if ra and rb and ra.group(2) == rb.group(2) and ra.group(3) == rb.group(3):
                pair = frozenset({ra.group(1), rb.group(1)})
                for e in self._disjoint_props_by_pair.get(pair, ()):
                    if self._applies(e, gamma, (ra.group(2), ra.group(3)), 2):
                        return True
            return False
        if not self._robust_incompat:
            return False
        # MONOTONE/GUARDED incompatibilities inside a larger Γ: scan for a
        # concept or role atom whose disjoint partner is also present.
        for atom in gamma:
            m = _CONCEPT_RE.match(atom)
            if m:
                c, x = m.group(1), m.group(2)
                for e in self._disjoint_by_concept.get(c, ()):
                    if e.robustness.is_exact:
                        continue
                    other = e.arg2 if e.arg1 == c else e.arg1
                    if make_concept_assertion(other, x) in gamma and self._applies(
                        e, gamma, (x,), 2
                    ):
                        return True
                continue
            m = _ROLE_RE.match(atom)
            if m:
                r, x, y = m.group(1), m.group(2), m.group(3)
                for e in self._disjoint_props_by_role.get(r, ()):
                    if e.robustness.is_exact:
                        continue
                    other = e.arg2 if e.arg1 == r else e.arg1
                    if make_role_assertion(other, x, y) in gamma and self._applies(
                        e, gamma, (x, y), 2
                    ):
                        return True
        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict, including ontology schemas."""
        base_dict = super().to_dict()
        base_dict["individuals"] = sorted(self._individuals)
        base_dict["concepts"] = sorted(self._concepts)
        base_dict["roles"] = sorted(self._roles)
        onto_schema_list = []
        for e in self._onto_schemas:
            entry: dict[str, object] = {
                "type": e.type,
                "arg1": e.concepts if e.type == "jointCommitment" else e.arg1,
                "arg2": e.arg2,
            }
            if e.annotation:
                entry["annotation"] = e.annotation
            entry["robustness"] = e.robustness.to_json()
            onto_schema_list.append(entry)
        base_dict["onto_schemas"] = onto_schema_list
        return base_dict

    @classmethod
    def from_dict(cls, data: dict) -> OntoMaterialBase:
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

        base = cls(
            language=language,
            consequences=consequences,
            annotations=annotations,
            robustness=robustness,
        )

        for schema in data.get("onto_schemas", []):
            arg1 = schema["arg1"]
            # jointCommitment stores arg1 as a list in JSON; join for internal repr
            if isinstance(arg1, list):
                arg1 = ",".join(arg1)
            base._register(
                SchemaEntry(
                    schema["type"],
                    arg1,
                    schema["arg2"],
                    schema.get("annotation"),
                    Robustness.from_json(schema.get("robustness")),
                ),
                f"{arg1} -> {schema['arg2']}",
            )
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
    natural language commitments to the atomic material base. Each commitment
    is tagged with a *source* label so that it can be retracted as a group.
    """

    def __init__(self) -> None:
        self.assertions: set[str] = set()
        self._onto_commitments: list[tuple[str, str, str, str, Robustness]] = []
        self._ground_rules: dict[Sequent, Robustness] = {}
        self._base: OntoMaterialBase | None = None

    def add_assertion(self, s: str) -> None:
        """Add an atomic assertion."""
        self.assertions.add(_validate_onto_atomic(s, "CommitmentStore.add_assertion"))
        self._base = None

    def add_role(self, role: str, subject: str, obj: str) -> None:
        """Add a role assertion R(subject, obj)."""
        self.add_assertion(make_role_assertion(role, subject, obj))

    def add_concept(self, concept: str, individual: str) -> None:
        """Add a concept assertion C(individual)."""
        self.add_assertion(make_concept_assertion(concept, individual))

    def _commit(
        self, source: str, schema_type: str, arg1: str, arg2: str, robustness: Robustness
    ) -> None:
        self._onto_commitments.append((source, schema_type, arg1, arg2, robustness))
        self._base = None

    def commit_subclass(
        self, source: str, sub_concept: str, super_concept: str, *,
        robustness: Robustness = EXACT,
    ) -> None:
        """Record a subClassOf commitment: {sub(x)} |~ {super(x)}."""
        self._commit(source, "subClassOf", sub_concept, super_concept, robustness)

    def commit_range(
        self, source: str, role: str, concept: str, *, robustness: Robustness = EXACT
    ) -> None:
        """Record a range commitment: {R(x,y)} |~ {C(y)}."""
        self._commit(source, "range", role, concept, robustness)

    def commit_domain(
        self, source: str, role: str, concept: str, *, robustness: Robustness = EXACT
    ) -> None:
        """Record a domain commitment: {R(x,y)} |~ {C(x)}."""
        self._commit(source, "domain", role, concept, robustness)

    def commit_subproperty(
        self, source: str, sub_role: str, super_role: str, *, robustness: Robustness = EXACT
    ) -> None:
        """Record a subPropertyOf commitment: {R(x,y)} |~ {S(x,y)}."""
        self._commit(source, "subPropertyOf", sub_role, super_role, robustness)

    def commit_disjoint(
        self, source: str, concept1: str, concept2: str, *, robustness: Robustness = EXACT
    ) -> None:
        """Record a disjointWith commitment: {C(x), D(x)} |~ {}."""
        self._commit(source, "disjointWith", concept1, concept2, robustness)

    def commit_disjoint_properties(
        self, source: str, role1: str, role2: str, *, robustness: Robustness = EXACT
    ) -> None:
        """Record a disjointProperties commitment: {R(x,y), S(x,y)} |~ {}."""
        self._commit(source, "disjointProperties", role1, role2, robustness)

    def commit_joint_commitment(
        self,
        source: str,
        antecedent_concepts: Sequence[str],
        consequent_concept: str,
        *,
        robustness: Robustness = EXACT,
    ) -> None:
        """Record a jointCommitment commitment: {C1(x), ..., Cn(x)} |~ {D(x)}."""
        if len(antecedent_concepts) < 2:
            raise ValueError(
                "jointCommitment requires at least 2 antecedent concepts "
                "(use subClassOf for a single antecedent)."
            )
        self._commit(
            source, "jointCommitment", ",".join(antecedent_concepts), consequent_concept,
            robustness,
        )

    def commit_defeasible_rule(
        self,
        source: str,
        antecedent: frozenset[str],
        consequent: frozenset[str],
        *,
        robustness: Robustness = EXACT,
    ) -> None:
        """Record a ground defeasible material inference."""
        ant = frozenset(
            _validate_onto_atomic(s, f"commit_defeasible_rule ({source})") for s in antecedent
        )
        con = frozenset(
            _validate_onto_atomic(s, f"commit_defeasible_rule ({source})") for s in consequent
        )
        self.assertions.update(ant | con)
        self._ground_rules[(ant, con)] = robustness
        self._base = None

    def retract_schema(self, source: str) -> None:
        """Retract all schemas with the given source."""
        self._onto_commitments = [c for c in self._onto_commitments if c[0] != source]
        self._base = None

    def compile(self) -> OntoMaterialBase:
        """Compile current commitments into an OntoMaterialBase (schemas stay lazy)."""
        if self._base is not None:
            return self._base

        self._base = OntoMaterialBase(
            language=set(self.assertions),
            consequences=set(self._ground_rules),
            robustness={k: v for k, v in self._ground_rules.items() if not v.is_exact},
        )

        for _source, schema_type, arg1, arg2, robustness in self._onto_commitments:
            if schema_type == "subClassOf":
                self._base.register_subclass(arg1, arg2, robustness=robustness)
            elif schema_type == "range":
                self._base.register_range(arg1, arg2, robustness=robustness)
            elif schema_type == "domain":
                self._base.register_domain(arg1, arg2, robustness=robustness)
            elif schema_type == "subPropertyOf":
                self._base.register_subproperty(arg1, arg2, robustness=robustness)
            elif schema_type == "disjointWith":
                self._base.register_disjoint(arg1, arg2, robustness=robustness)
            elif schema_type == "disjointProperties":
                self._base.register_disjoint_properties(arg1, arg2, robustness=robustness)
            elif schema_type == "jointCommitment":
                self._base.register_joint_commitment(
                    arg1.split(","), arg2, robustness=robustness
                )

        return self._base

    def describe(self) -> str:
        """Human-readable description of current commitments."""
        lines = ["Commitment Store:"]
        lines.append(f"  Assertions: {len(self.assertions)}")
        for s in sorted(self.assertions):
            lines.append(f"    {s}")
        lines.append(f"  Ontology Schemas: {len(self._onto_commitments)}")
        for source, schema_type, arg1, arg2, robustness in self._onto_commitments:
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
                ant_str = ", ".join(f"{c}(x)" for c in arg1.split(","))
                pattern = f"{ant_str} |~ {arg2}(x)"
            else:
                pattern = f"{arg1} -> {arg2}"  # pragma: no cover
            suffix = "" if robustness.is_exact else f" [{robustness}]"
            lines.append(f"    [{source}] {schema_type}: {pattern}{suffix}")
        if self._ground_rules:
            lines.append(f"  Ground rules: {len(self._ground_rules)}")
            for (ant, con), robustness in self._ground_rules.items():
                suffix = "" if robustness.is_exact else f" [{robustness}]"
                lines.append(f"    {set(ant)} |~ {set(con)}{suffix}")
        return "\n".join(lines)
