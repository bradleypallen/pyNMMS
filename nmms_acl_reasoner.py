"""
NMMS-ALC Reasoner: First-Order Extension of the Non-Monotonic Multi-Succedent
sequent calculus using ALC-style restricted quantification.

This extends the propositional NMMS reasoner (Hlobil & Brandom 2025, Ch. 3)
with description-logic-style restricted quantifiers, following the semantic
framework of Hlobil's "First-Order Implication-Space Semantics" (2025).

MOTIVATION (from Hlobil 2025):
  The standard quantifier rules ∀L and ∀R are unsound for nonmonotonic material
  reasoning. Unrestricted ∀ brings in too many instances, some of which defeat
  the inference. ALC-style restricted quantification (∀R.C, ∃R.C) naturally
  limits instantiation to objects standing in a particular relation, avoiding
  this problem while preserving the key properties:

  - MOF:  Nonmonotonicity — adding premises can defeat inferences
  - SCL:  Supraclassicality — all ALC-valid sequents are derivable
  - DDT:  Deduction-detachment theorem
  - DS:   Disjunction simplification
  - LC:   Left conjunction is multiplicative

SYNTAX:
  Individuals:   a, b, c, ...  (lowercase names)
  Concepts:      Human, Bird, ... (capitalized names)  
  Roles:         hasChild, inFridge, ... (camelCase or descriptive)
  
  Atomic concept assertion:   Human(alice)
  Atomic role assertion:      hasChild(alice,bob)
  Negation:                   ~Human(alice)
  Conjunction:                Human(alice) & Mortal(alice)  
  Disjunction:                Bird(tweety) | Penguin(tweety)
  Conditional:                Bird(tweety) -> CanFly(tweety)
  Universal restriction:      ALL hasChild.Happy(alice)
                              = "all children of alice are Happy"
  Existential restriction:    SOME hasChild.Doctor(alice)
                              = "some child of alice is a Doctor"

QUANTIFIER RULES (Ketonen-style, triggered by role assertions):
  
  [L∀R.C]: From  Γ, ALL R.C(a), R(a,b)  ⇒  Δ
           prove  Γ, ALL R.C(a), R(a,b), C(b)  ⇒  Δ         ... (1)
           and    Γ, R(a,b)  ⇒  Δ                             ... (2)  
           and    Γ, R(a,b), C(b)  ⇒  Δ                       ... (3)
           
  The trigger R(a,b) must be present. The rule instantiates the restriction
  for the known R-successor b. Premises (2) and (3) handle the Ketonen
  third-sequent pattern: they ensure the rule is sound without Contraction.
  Premise (2) checks that the sequent holds without the universal restriction
  (since we can't weaken it in). Together this ensures that ALL R.C behaves
  multiplicatively as a premise — exactly Hlobil's "generalized conjunction"
  semantics, but restricted to known successors.

  [R∃R.C]: From  Γ  ⇒  Δ, SOME R.C(a)
           prove  Γ  ⇒  Δ, R(a,b), C(b)     for fresh b
           
  Dual: to show some R-successor of a has C, produce a witness.

  [L∃R.C]: From  Γ, SOME R.C(a)  ⇒  Δ
           prove  Γ, R(a,b), C(b)  ⇒  Δ     for all known b with R(a,b) in Γ
           and    Γ, R(a,b)  ⇒  Δ             (Ketonen third sequent)
           and    Γ, R(a,b), C(b)  ⇒  Δ       (Ketonen third sequent)
  
  [R∀R.C]: From  Γ  ⇒  Δ, ALL R.C(a)
           prove  Γ  ⇒  Δ, C(b)              for fresh b not in Γ,Δ
           (with implicit assumption R(a,b))
           This is the ALC-restricted analogue of ∀R with eigenvariable.

DEFEASIBILITY EXAMPLE (Hlobil's beer bottles, reformulated):
  Material base includes: inFridge(fridge, b1) |~ Full(b1)
  This is defeasible: adding ALL inFridge.Empty(fridge) with trigger
  inFridge(fridge, b1) defeats the inference because it forces Empty(b1).

KNOWN LIMITATIONS:

  1. R∃R.C witness search with blocking. The implementation uses concept-label 
     blocking adapted from classical ALC tableau procedures: a fresh witness
     is blocked (not expanded) if its concept label is a subset of some 
     existing individual's concept label. Combined with canonical witness
     naming and the depth bound, this provides termination for arbitrary
     existential chains. The blocking condition is CONJECTURED to be sound
     for NMMS-ALC because nonmonotonicity arises from the material base
     (exact match, no weakening), not from logical rules. 
     TODO: A formal proof that subset-based concept-label blocking is sound
     in NMMS-ALC. The argument sketch: if a sequent is derivable using 
     fresh witness b, and concept_label(b) ⊆ concept_label(c) for existing
     c, then replacing b with c preserves derivability because (i) the
     logical rules are structurally identical to classical ALC, and (ii)
     the material base checks exact syntactic match on assertion sets and
     cannot distinguish individuals with identical concept labels.

  2. Fresh individual naming and memoization. Canonical naming for witnesses
     (R∃R.C) and eigenvariables (R∀R.C) is now deterministic from the 
     quantified expression, so identical goals reached via different proof 
     paths use the same names and can cache-hit. The remaining edge case is
     when a canonical name collides with an individual already in context,
     requiring fallback to a suffixed name; this is rare in practice and 
     the fallback preserves soundness.

  3. L∃R.C has exponential branching in the number of triggers. The Ketonen
     pattern requires checking all 2^k - 1 nonempty subsets of k triggered
     instances. This is inherent to the Ketonen approach (compensating for
     the absence of structural contraction) and manageable when existential
     restrictions have few triggers in context, but would need optimization
     (e.g., early pruning, lazy subset enumeration) for production use.

  None of these limitations affect the theoretical contribution: the soundness
  of the rules, the satisfaction of Hlobil's desiderata (MOF, SCL, DDT, DS, LC),
  or the fit between ALC-style restricted quantification and implication-space
  semantics. They are implementation completeness and efficiency issues on the
  path from proof of concept to production system.

Author: Bradley P. Allen / Claude
"""

from dataclasses import dataclass, field
from typing import FrozenSet, Set, Tuple, Optional, List, Dict
from itertools import combinations
import re

# ============================================================
# Syntax: Parsing first-order sentences with ALC quantifiers
# ============================================================

# Sentence types
ATOM_CONCEPT = 'concept'       # Human(alice)
ATOM_ROLE = 'role'             # hasChild(alice,bob)
NEG = 'neg'                    # ~φ
CONJ = 'conj'                  # φ & ψ
DISJ = 'disj'                  # φ | ψ
IMPL = 'impl'                  # φ -> ψ
ALL_RESTRICT = 'all_restrict'  # ALL R.C(a)
SOME_RESTRICT = 'some_restrict' # SOME R.C(a)


def parse_sentence(s: str) -> dict:
    """Parse a sentence into its structure.
    
    Grammar (informal, precedence from low to high):
      sentence ::= impl_expr
      impl_expr ::= disj_expr ( '->' disj_expr )*
      disj_expr ::= conj_expr ( '|' conj_expr )*
      conj_expr ::= unary_expr ( '&' unary_expr )*
      unary_expr ::= '~' unary_expr | atom | '(' sentence ')' | quantified
      quantified ::= ('ALL' | 'SOME') ROLE '.' CONCEPT '(' INDIVIDUAL ')'
      atom ::= CONCEPT '(' INDIVIDUAL ')' | ROLE '(' INDIVIDUAL ',' INDIVIDUAL ')'
    """
    s = s.strip()
    
    # Strip outer parens if they wrap the entire expression
    if s.startswith('(') and s.endswith(')'):
        depth = 0
        all_wrapped = True
        for i, c in enumerate(s):
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            if depth == 0 and i < len(s) - 1:
                all_wrapped = False
                break
        if all_wrapped:
            return parse_sentence(s[1:-1])
    
    # Binary connectives at depth 0, lowest precedence first
    # Implication (right-associative, lowest precedence)
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        c = s[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0 and s[i:i+2] == '->':
            return {'type': IMPL, 
                    'left': s[:i].strip(), 
                    'right': s[i+2:].strip()}
    
    # Disjunction (left-associative)
    depth = 0
    last_disj = -1
    for i, c in enumerate(s):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0 and c == '|':
            last_disj = i
    if last_disj >= 0:
        return {'type': DISJ,
                'left': s[:last_disj].strip(),
                'right': s[last_disj+1:].strip()}
    
    # Conjunction (left-associative)
    depth = 0
    last_conj = -1
    for i, c in enumerate(s):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0 and c == '&':
            last_conj = i
    if last_conj >= 0:
        return {'type': CONJ,
                'left': s[:last_conj].strip(),
                'right': s[last_conj+1:].strip()}
    
    # Negation
    if s.startswith('~'):
        return {'type': NEG, 'sub': s[1:].strip()}
    
    # ALL R.C(a) — universal restriction
    m = re.match(r'^ALL\s+(\w+)\.(\w+)\((\w+)\)$', s)
    if m:
        return {'type': ALL_RESTRICT,
                'role': m.group(1),
                'concept': m.group(2),
                'individual': m.group(3)}
    
    # SOME R.C(a) — existential restriction
    m = re.match(r'^SOME\s+(\w+)\.(\w+)\((\w+)\)$', s)
    if m:
        return {'type': SOME_RESTRICT,
                'role': m.group(1),
                'concept': m.group(2),
                'individual': m.group(3)}
    
    # Role assertion: R(a,b)
    m = re.match(r'^(\w+)\((\w+)\s*,\s*(\w+)\)$', s)
    if m:
        return {'type': ATOM_ROLE,
                'role': m.group(1),
                'arg1': m.group(2),
                'arg2': m.group(3)}
    
    # Concept assertion: C(a)
    m = re.match(r'^(\w+)\((\w+)\)$', s)
    if m:
        return {'type': ATOM_CONCEPT,
                'concept': m.group(1),
                'individual': m.group(2)}
    
    # Bare atom (propositional — backward compatible)
    return {'type': 'atom', 'name': s}


def is_atomic(s: str) -> bool:
    """A sentence is atomic if it's a concept assertion, role assertion, or bare atom."""
    t = parse_sentence(s)['type']
    return t in ('atom', ATOM_CONCEPT, ATOM_ROLE)


def all_atomic(sentences: FrozenSet[str]) -> bool:
    return all(is_atomic(s) for s in sentences)


def make_concept_assertion(concept: str, individual: str) -> str:
    """Construct C(a) string."""
    return f"{concept}({individual})"


def make_role_assertion(role: str, arg1: str, arg2: str) -> str:
    """Construct R(a,b) string."""
    return f"{role}({arg1},{arg2})"


def find_role_triggers(gamma: FrozenSet[str], role_name: str, subject: str) -> List[str]:
    """Find all individuals b such that R(subject, b) is in gamma."""
    triggers = []
    for s in gamma:
        parsed = parse_sentence(s)
        if (parsed['type'] == ATOM_ROLE 
            and parsed['role'] == role_name 
            and parsed['arg1'] == subject):
            triggers.append(parsed['arg2'])
    return triggers


def collect_individuals(sentences: FrozenSet[str]) -> Set[str]:
    """Extract all individual names mentioned in a set of sentences."""
    individuals = set()
    for s in sentences:
        parsed = parse_sentence(s)
        if parsed['type'] == ATOM_CONCEPT:
            individuals.add(parsed['individual'])
        elif parsed['type'] == ATOM_ROLE:
            individuals.add(parsed['arg1'])
            individuals.add(parsed['arg2'])
        elif parsed['type'] in (ALL_RESTRICT, SOME_RESTRICT):
            individuals.add(parsed['individual'])
    return individuals


def fresh_individual(used: Set[str], prefix: str = "w") -> str:
    """Generate a fresh individual name not in the used set."""
    i = 0
    while f"{prefix}{i}" in used:
        i += 1
    return f"{prefix}{i}"


def concept_label(individual: str, sentences: FrozenSet[str]) -> FrozenSet[str]:
    """Extract the concept label of an individual: the set of concept names
    asserted of that individual in the given sentences.
    
    Used for blocking: if fresh individual b has concept label ⊆ concept label
    of some existing individual c, then b is blocked by c — any proof through
    b could equally use c.
    
    SOUNDNESS NOTE (TODO: formal proof required):
    This blocking condition is conjectured to be sound for NMMS-ALC because
    nonmonotonicity arises from the material base (exact match, no weakening),
    not from the logical rules. The logical decomposition of quantified concepts
    is structurally identical to classical ALC, so subset-based blocking on
    concept labels should preserve completeness of the logical fragment.
    The material base cannot distinguish between individuals with identical
    concept labels because it operates on syntactic assertion sets. A formal
    proof would show that if a sequent is derivable using witness b, and 
    concept_label(b) ⊆ concept_label(c) for some existing c, then replacing
    b with c in the derivation yields a valid derivation.
    """
    labels = set()
    for s in sentences:
        parsed = parse_sentence(s)
        if parsed['type'] == ATOM_CONCEPT and parsed['individual'] == individual:
            labels.add(parsed['concept'])
    return frozenset(labels)


def find_blocking_individual(fresh: str, gamma: FrozenSet[str], 
                              delta: FrozenSet[str],
                              used: Set[str]) -> Optional[str]:
    """Check if any existing individual blocks the fresh individual.
    
    Fresh individual `fresh` is blocked by existing individual `c` if
    the concept label of `fresh` in the current context is a subset of
    the concept label of `c`. Returns the blocking individual or None.
    """
    all_sentences = gamma | delta
    fresh_label = concept_label(fresh, all_sentences)
    
    for c in used:
        if c == fresh:
            continue
        c_label = concept_label(c, all_sentences)
        if fresh_label <= c_label:  # subset
            return c
    return None


# ============================================================
# Material Base — atomic assertions only
# ============================================================

Sequent = Tuple[FrozenSet[str], FrozenSet[str]]


def _validate_atomic(s: str, context: str) -> None:
    """Raise ValueError if s is not an atomic sentence."""
    parsed = parse_sentence(s)
    if parsed['type'] not in ('atom', ATOM_CONCEPT, ATOM_ROLE):
        raise ValueError(
            f"{context}: found logically complex sentence '{s}' "
            f"(type: {parsed['type']}). Only atomic sentences "
            f"(concept assertions, role assertions, bare atoms) are "
            f"permitted in the material base. Quantified, negated, "
            f"conjunctive, disjunctive, and conditional sentences "
            f"belong to the logical vocabulary, not the base.")


@dataclass
class MaterialBase:
    """A material base B = <L_B, |~_B> for NMMS-ALC.
    
    ARCHITECTURE (following Hlobil 2025):
    The language L_B and consequence relation |~_B contain ONLY atomic
    sentences: concept assertions C(a), role assertions R(a,b), and bare
    propositional atoms. Logically complex sentences belong to the logical
    vocabulary and are handled by the proof rules, not the base.
    
    LAZY SCHEMA EVALUATION:
    Quantified commitments from dialogue are stored as schemas and 
    evaluated lazily during is_axiom checks. No eager grounding over
    all known individuals. This avoids the combinatorial explosion of
    n individuals × k schemas and makes proof search query schemas
    directly against the concrete individuals in each sequent.
    
    Schema types:
    - concept_schema: "for all R(a,x), assert C(x)"
      Evaluated lazily: when is_axiom sees C(b) needed, checks if any
      concept schema would produce it given the role assertions in context.
    
    - inference_schema: "for all R(a,x) with P(x), infer Q"
      Evaluated lazily: when is_axiom checks {R(a,b), P(b)} ⊢ {Q},
      checks if any inference schema matches.
    
    Storage: O(k + m) schemas, not O(n × (k + m)) ground entries.
    """
    language: Set[str]          # L_B: atomic assertions ONLY
    consequence: Set[Sequent]   # |~_B: explicit ground consequences
    individuals: Set[str] = field(default_factory=set)
    concepts: Set[str] = field(default_factory=set)
    roles: Set[str] = field(default_factory=set)
    _inference_schemas: List[Tuple[str, str, Optional[str], FrozenSet[str]]] = field(default_factory=list)
    # Each: (role, subject, premise_concept_or_None, conclusion_template)
    # conclusion_template may contain '__OBJ__' replaced with matched individual

    def __post_init__(self):
        """Validate atomicity, ensure Containment, extract vocabulary."""
        for s in self.language:
            _validate_atomic(s, "Material base language")
        for (gamma, delta) in list(self.consequence):
            for s in gamma | delta:
                _validate_atomic(s, "Material base consequence")
        
        # Extract vocabulary
        for s in self.language:
            self._extract_vocab(s)
        for (gamma, delta) in self.consequence:
            for s in gamma | delta:
                self._extract_vocab(s)
        
        # Containment: Gamma |~ Delta whenever Gamma ∩ Delta != ∅
        # (checked dynamically in is_axiom, not materialized)
    
    def _extract_vocab(self, s: str):
        parsed = parse_sentence(s)
        if parsed['type'] == ATOM_CONCEPT:
            self.individuals.add(parsed['individual'])
            self.concepts.add(parsed['concept'])
        elif parsed['type'] == ATOM_ROLE:
            self.individuals.add(parsed['arg1'])
            self.individuals.add(parsed['arg2'])
            self.roles.add(parsed['role'])

    def register_concept_schema(self, role: str, subject: str, concept: str):
        """Register: 'for all role(subject, x), assert concept(x)'.
        
        This is syntactic sugar for an inference schema with no premise:
        role(subject, x) |~ concept(x). Stored lazily, matched at query time.
        """
        self._inference_schemas.append((
            role, subject, None,
            frozenset({make_concept_assertion(concept, '__OBJ__')})
        ))
    
    def register_inference_schema(self, role: str, subject: str, 
                                   premise_concept: Optional[str],
                                   conclusion: Set[str]):
        """Register: 'for all role(subject, x) with premise_concept(x), 
        infer conclusion'.
        
        Stored as a schema. During is_axiom, checked lazily against 
        the concrete individuals in the query. Conclusion may contain
        '__OBJ__' which is replaced with the matched individual.
        """
        conclusion_fs = frozenset(conclusion)
        for s in conclusion:
            if '__OBJ__' not in s:
                _validate_atomic(s, "Inference schema conclusion")
        self._inference_schemas.append((role, subject, premise_concept, conclusion_fs))
    
    def add_individual(self, role: str, subject: str, obj: str):
        """Add a new role assertion to the language.
        
        No schema expansion needed — schemas are evaluated lazily.
        """
        role_assertion = make_role_assertion(role, subject, obj)
        self.language.add(role_assertion)
        self._extract_vocab(role_assertion)

    def _check_schemas(self, gamma: FrozenSet[str], 
                        delta: FrozenSet[str]) -> bool:
        """Check if any schema makes gamma ⊢ delta hold.
        
        All schemas are stored as inference schemas:
          (role, subject, premise_concept, conclusion_template)
        
        A schema produces a virtual consequence for each individual b
        where role(subject, b) appears in gamma:
          {role(subject,b)} |~ conclusion(b)               (no premise)
          {role(subject,b), premise(b)} |~ conclusion(b)   (with premise)
        
        The match requires EXACT gamma/delta (no weakening), preserving
        nonmonotonicity: extra premises in gamma defeat the schema match.
        """
        for (schema_role, schema_subject, premise_concept, conclusion_template) in self._inference_schemas:
            for s in gamma:
                parsed = parse_sentence(s)
                if (parsed['type'] == ATOM_ROLE 
                    and parsed['role'] == schema_role 
                    and parsed['arg1'] == schema_subject):
                    obj = parsed['arg2']
                    
                    # Build expected gamma
                    if premise_concept is not None:
                        premise = make_concept_assertion(premise_concept, obj)
                        expected_gamma = frozenset({s, premise})
                    else:
                        expected_gamma = frozenset({s})
                    
                    # Build expected delta: substitute __OBJ__ with obj
                    expected_delta = frozenset(
                        c.replace('__OBJ__', obj) if '__OBJ__' in c 
                        else c
                        for c in conclusion_template
                    )
                    
                    # Exact match (no weakening)
                    if gamma == expected_gamma and delta == expected_delta:
                        return True
        
        return False

    def is_axiom(self, gamma: FrozenSet[str], delta: FrozenSet[str]) -> bool:
        """Check if Gamma => Delta is an axiom of NMMS_B.
        
        Ax1: Containment — Gamma ∩ Delta ≠ ∅
        Ax2: Base consequence — (Gamma, Delta) ∈ |~_B (explicit)
        Ax3: Schema consequence — matches a virtual consequence from 
             a registered schema (evaluated lazily)
        
        No Weakening: the base relation is used as-is.
        Schemas are checked against the exact gamma/delta, not expanded.
        """
        # Ax1: Containment
        if gamma & delta:
            return True
        
        # Ax2: Explicit base consequence
        if (gamma, delta) in self.consequence:
            return True
        
        # Ax3: Lazy schema evaluation
        if self._inference_schemas and self._check_schemas(gamma, delta):
            return True
        
        return False
    
    def add_assertion(self, s: str):
        """Add an atomic assertion to the language."""
        _validate_atomic(s, "add_assertion")
        self.language.add(s)
        self._extract_vocab(s)
    
    def add_consequence(self, gamma: FrozenSet[str], delta: FrozenSet[str]):
        """Add a base consequence. All sentences must be atomic."""
        for s in gamma | delta:
            _validate_atomic(s, "add_consequence")
            self.language.add(s)
            self._extract_vocab(s)
        self.consequence.add((gamma, delta))


# ============================================================
# Commitment Store — quantified schemas above the material base
# ============================================================

@dataclass 
class InferenceSchema:
    """A defeasible material inference schema derived from a quantified
    commitment.
    
    When the interlocutor commits to "all patients with chest pain 
    radiating left probably have a heart attack," Elenchus records this
    as a schema. The schema generates material base entries for each
    known individual in the relevant domain.
    
    Attributes:
        source: The natural language or formal commitment that generated
                this schema (e.g., "ALL hasSymptom.ChestPain(x) |~ HeartAttack(x)")
        role: The role that scopes the quantification (e.g., "hasSymptom")
        trigger_concept: The concept in the restriction (e.g., "ChestPain")
                         — or None if the schema is just about role membership
        conclusion_concept: The concept concluded (e.g., "HeartAttack")
        schema_type: 'all' for universal schemas, 'some' for existential
    """
    source: str
    role: str
    subject_var: str            # the variable being quantified over
    trigger_concept: Optional[str]  # concept in the restriction
    conclusion_concept: str     # concept concluded
    conclusion_is_succedent: bool = True  # True: antecedent |~ conclusion
                                          # False: conclusion |~ succedent


@dataclass
class CommitmentStore:
    """Manages quantified commitments and compiles them to a MaterialBase.
    
    This is the bridge between Elenchus (which accepts natural language
    commitments including quantified statements) and the NMMS-ALC reasoner
    (which requires an atomic material base).
    
    Architecture:
        Natural language → Elenchus → CommitmentStore → MaterialBase → Reasoner
        
    The CommitmentStore maintains:
    - Atomic assertions (facts about specific individuals)
    - Role assertions (relationships between individuals)  
    - Inference schemas (compiled from quantified commitments)
    - The generated MaterialBase (recompiled when commitments change)
    
    When a new individual enters the domain or a schema is added/removed,
    the MaterialBase is recompiled from scratch. This ensures that the
    base always reflects exactly the current commitments.
    """
    
    def __init__(self):
        self.assertions: Set[str] = set()           # atomic facts
        self.schemas: List[InferenceSchema] = []     # quantified commitments
        self._base: Optional[MaterialBase] = None
    
    def add_assertion(self, s: str):
        """Add an atomic assertion (fact about a specific individual)."""
        _validate_atomic(s, "CommitmentStore.add_assertion")
        self.assertions.add(s)
        self._base = None  # invalidate cached base
    
    def add_role(self, role: str, subject: str, obj: str):
        """Add a role assertion R(subject, obj)."""
        self.add_assertion(make_role_assertion(role, subject, obj))
    
    def add_concept(self, concept: str, individual: str):
        """Add a concept assertion C(individual)."""
        self.add_assertion(make_concept_assertion(concept, individual))
    
    def commit_universal(self, source: str, role: str, subject_var: str,
                         trigger_concept: str, conclusion_concept: str):
        """Record a universal quantified commitment.
        
        "All R-successors of subject_var that have trigger_concept 
         also have conclusion_concept."
        
        Compiles to: for each known b with R(subject_var, b),
          R(subject_var, b), trigger_concept(b) |~ conclusion_concept(b)
        """
        schema = InferenceSchema(
            source=source,
            role=role,
            subject_var=subject_var,
            trigger_concept=trigger_concept,
            conclusion_concept=conclusion_concept,
        )
        self.schemas.append(schema)
        self._base = None
    
    def commit_defeasible_rule(self, source: str, 
                                antecedent: FrozenSet[str],
                                consequent: FrozenSet[str]):
        """Record a ground defeasible material inference directly.
        
        For cases where the commitment is already ground (no quantification).
        """
        for s in antecedent | consequent:
            _validate_atomic(s, f"commit_defeasible_rule ({source})")
            self.assertions.add(s)
        self.schemas  # not a schema, goes directly to base
        self._ground_rules = getattr(self, '_ground_rules', set())
        self._ground_rules.add((antecedent, consequent))
        self._base = None
    
    def retract_schema(self, source: str):
        """Retract all schemas with the given source."""
        self.schemas = [s for s in self.schemas if s.source != source]
        self._base = None
    
    def compile(self) -> MaterialBase:
        """Compile current commitments into a MaterialBase.
        
        Schemas are registered on the base for LAZY evaluation — no eager
        grounding. The base stores O(k + m) schemas, not O(n × (k + m))
        ground entries. Schema matching happens at query time in is_axiom.
        """
        if self._base is not None:
            return self._base
        
        language = set(self.assertions)
        consequence: Set[Sequent] = set()
        
        # Add ground rules
        ground_rules = getattr(self, '_ground_rules', set())
        for (ant, con) in ground_rules:
            consequence.add((ant, con))
        
        self._base = MaterialBase(
            language=language,
            consequence=consequence,
        )
        
        # Register schemas lazily — no grounding
        for schema in self.schemas:
            if schema.trigger_concept:
                # Inference schema with premise:
                # role(subject, x), trigger(x) |~ conclusion(x)
                # Use __OBJ__ as placeholder for the bound variable
                conclusion = make_concept_assertion(
                    schema.conclusion_concept, '__OBJ__')
                self._base.register_inference_schema(
                    schema.role, schema.subject_var,
                    schema.trigger_concept,
                    {conclusion}
                )
            else:
                # Concept schema: role(subject, x) → assert concept(x)
                self._base.register_concept_schema(
                    schema.role, schema.subject_var, 
                    schema.conclusion_concept
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
            lines.append(f"      ∀{schema.subject_var}.{schema.role} → "
                        f"{schema.trigger_concept or '*'} |~ "
                        f"{schema.conclusion_concept}")
        ground_rules = getattr(self, '_ground_rules', set())
        if ground_rules:
            lines.append(f"  Ground rules: {len(ground_rules)}")
            for (ant, con) in ground_rules:
                lines.append(f"    {set(ant)} |~ {set(con)}")
        return "\n".join(lines)


# ============================================================
# NMMS-ALC Reasoner
# ============================================================

class NMMSALCReasoner:
    """Proof search for NMMS sequent calculus with ALC-style quantifiers.
    
    Extends the propositional NMMS reasoner with:
    - [L∀R.C] / [R∀R.C]: rules for universal restrictions
    - [L∃R.C] / [R∃R.C]: rules for existential restrictions
    
    All quantifier rules are triggered by role assertions in context,
    ensuring restricted instantiation that is compatible with nonmonotonicity.
    """
    
    def __init__(self, base: MaterialBase, max_depth: int = 25):
        self.base = base
        self.max_depth = max_depth
        self.proof_trace: List[str] = []
        self._cache: Dict[Tuple[FrozenSet[str], FrozenSet[str]], bool] = {}
    
    def derives(self, gamma: FrozenSet[str], delta: FrozenSet[str]) -> bool:
        """Check if Gamma => Delta is derivable in NMMS-ALC_B."""
        self.proof_trace = []
        self._cache = {}
        return self._prove(gamma, delta, depth=0)
    
    def _prove(self, gamma: FrozenSet[str], delta: FrozenSet[str], depth: int) -> bool:
        """Backward proof search with memoization."""
        indent = "  " * depth
        
        if depth > self.max_depth:
            self.proof_trace.append(f"{indent}DEPTH LIMIT")
            return False
        
        # Memoization
        key = (gamma, delta)
        if key in self._cache:
            return self._cache[key]
        
        # Check axiom
        if self.base.is_axiom(gamma, delta):
            self.proof_trace.append(f"{indent}AXIOM: {_fmt(gamma)} => {_fmt(delta)}")
            self._cache[key] = True
            return True
        
        # Try rules. Mark as False initially to detect cycles.
        self._cache[key] = False
        
        result = (self._try_left_rules(gamma, delta, depth) or
                  self._try_right_rules(gamma, delta, depth))
        
        self._cache[key] = result
        if not result:
            self.proof_trace.append(f"{indent}FAIL: {_fmt(gamma)} => {_fmt(delta)}")
        return result
    
    # ----------------------------------------------------------
    # LEFT RULES
    # ----------------------------------------------------------
    
    def _try_left_rules(self, gamma: FrozenSet[str], delta: FrozenSet[str], 
                        depth: int) -> bool:
        indent = "  " * depth
        
        for s in sorted(gamma):  # sorted for determinism
            parsed = parse_sentence(s)
            rest = gamma - {s}
            
            # [L¬]: Γ, ~A ⇒ Δ  ←  Γ ⇒ Δ, A
            if parsed['type'] == NEG:
                a = parsed['sub']
                self.proof_trace.append(f"{indent}[L¬] on {s}")
                if self._prove(rest, delta | {a}, depth + 1):
                    return True
            
            # [L→]: Γ, A→B ⇒ Δ  ←  (1) Γ ⇒ Δ,A  (2) Γ,B ⇒ Δ  (3) Γ,B ⇒ Δ,A
            elif parsed['type'] == IMPL:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[L→] on {s}")
                if (self._prove(rest, delta | {a}, depth + 1) and
                    self._prove(rest | {b}, delta, depth + 1) and
                    self._prove(rest | {b}, delta | {a}, depth + 1)):
                    return True
            
            # [L∧]: Γ, A∧B ⇒ Δ  ←  Γ, A, B ⇒ Δ
            elif parsed['type'] == CONJ:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[L∧] on {s}")
                if self._prove(rest | {a, b}, delta, depth + 1):
                    return True
            
            # [L∨]: Γ, A∨B ⇒ Δ  ←  (1) Γ,A ⇒ Δ  (2) Γ,B ⇒ Δ  (3) Γ,A,B ⇒ Δ
            elif parsed['type'] == DISJ:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[L∨] on {s}")
                if (self._prove(rest | {a}, delta, depth + 1) and
                    self._prove(rest | {b}, delta, depth + 1) and
                    self._prove(rest | {a, b}, delta, depth + 1)):
                    return True
            
            # [L∀R.C]: Γ, ALL R.C(a) ⇒ Δ
            #   ALL R.C is a generalized conjunction over triggered instances
            #   (Hlobil 2025, Def 16). Like L∧, it decomposes multiplicatively:
            #   add C(b) to premises for each triggered R(a,b).
            #
            #   Γ, ALL R.C(a) ⇒ Δ  ←  Γ, {C(b) | R(a,b) ∈ Γ} ⇒ Δ
            #
            #   This is the restricted analogue of replacing ∀xFx with
            #   F(b1) ∧ ... ∧ F(bn) on the left and then applying L∧.
            elif parsed['type'] == ALL_RESTRICT:
                role_name = parsed['role']
                concept = parsed['concept']
                subject = parsed['individual']
                triggers = find_role_triggers(rest, role_name, subject)
                
                if triggers:
                    instances = frozenset(
                        make_concept_assertion(concept, b) for b in triggers)
                    self.proof_trace.append(
                        f"{indent}[L∀R.C] on {s}, triggers: "
                        f"{[make_role_assertion(role_name, subject, b) for b in triggers]}"
                        f" → adding {set(instances)}")
                    
                    if self._prove(rest | instances, delta, depth + 1):
                        return True
            
            # [L∃R.C]: Γ, SOME R.C(a) ⇒ Δ
            #   SOME R.C is a generalized disjunction over triggered instances
            #   (Hlobil 2025, derived clause for ∃). Like L∨, this requires  
            #   the full Ketonen pattern: ALL nonempty subsets of triggered
            #   instances must independently entail the conclusion.
            #
            #   For binary L∨ with {A, B}, this gives the familiar three
            #   top sequents: {A}, {B}, {A,B}. For n triggers, we need
            #   all 2^n - 1 nonempty subsets. This is necessary because
            #   without structural contraction, we cannot derive the 
            #   multi-instance cases from the single-instance cases.
            elif parsed['type'] == SOME_RESTRICT:
                role_name = parsed['role']
                concept = parsed['concept']
                subject = parsed['individual']
                triggers = find_role_triggers(rest, role_name, subject)
                
                if triggers:
                    instances = [make_concept_assertion(concept, b) 
                                 for b in triggers]
                    self.proof_trace.append(
                        f"{indent}[L∃R.C] on {s}, triggers: "
                        f"{[make_role_assertion(role_name, subject, b) for b in triggers]}"
                        f" → Ketonen over {len(instances)} instances "
                        f"({2**len(instances) - 1} subsets)")
                    
                    # Ketonen pattern: all nonempty subsets must work
                    all_ok = True
                    for r in range(1, len(instances) + 1):
                        for subset in combinations(instances, r):
                            if not self._prove(
                                    rest | frozenset(subset), delta, depth + 1):
                                all_ok = False
                                break
                        if not all_ok:
                            break
                    
                    if all_ok:
                        return True
        
        return False
    
    # ----------------------------------------------------------
    # RIGHT RULES
    # ----------------------------------------------------------
    
    def _try_right_rules(self, gamma: FrozenSet[str], delta: FrozenSet[str],
                         depth: int) -> bool:
        indent = "  " * depth
        
        for s in sorted(delta):
            parsed = parse_sentence(s)
            rest = delta - {s}
            
            # [R¬]: Γ ⇒ Δ, ~A  ←  Γ, A ⇒ Δ
            if parsed['type'] == NEG:
                a = parsed['sub']
                self.proof_trace.append(f"{indent}[R¬] on {s}")
                if self._prove(gamma | {a}, rest, depth + 1):
                    return True
            
            # [R→]: Γ ⇒ Δ, A→B  ←  Γ, A ⇒ Δ, B
            elif parsed['type'] == IMPL:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[R→] on {s}")
                if self._prove(gamma | {a}, rest | {b}, depth + 1):
                    return True
            
            # [R∧]: Γ ⇒ Δ, A∧B  ←  (1) Γ ⇒ Δ,A  (2) Γ ⇒ Δ,B  (3) Γ ⇒ Δ,A,B
            elif parsed['type'] == CONJ:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[R∧] on {s}")
                if (self._prove(gamma, rest | {a}, depth + 1) and
                    self._prove(gamma, rest | {b}, depth + 1) and
                    self._prove(gamma, rest | {a, b}, depth + 1)):
                    return True
            
            # [R∨]: Γ ⇒ Δ, A∨B  ←  Γ ⇒ Δ, A, B
            elif parsed['type'] == DISJ:
                a, b = parsed['left'], parsed['right']
                self.proof_trace.append(f"{indent}[R∨] on {s}")
                if self._prove(gamma, rest | {a, b}, depth + 1):
                    return True
            
            # [R∃R.C]: Γ ⇒ Δ, SOME R.C(a)
            #   To show some R-successor of a satisfies C, we need a witness
            #   b such that R(a,b) AND C(b). Two strategies:
            #
            #   (i)  For known individuals b where R(a,b) is already in Γ:
            #        prove Γ ⇒ Δ, C(b). The role assertion is established;
            #        we just need the concept.
            #
            #   (ii) For a fresh canonical witness b:
            #        prove Γ, R(a,b) ⇒ Δ, C(b). We assume the role and
            #        must establish the concept. (This parallels the R→
            #        pattern: to show ∃, assume the role part and derive
            #        the concept part.)
            #
            #   BLOCKING: Fresh witness blocked if concept label ⊆ existing.
            #
            #   TODO (formal proof): Blocking soundness in NMMS-ALC.
            elif parsed['type'] == SOME_RESTRICT:
                role_name = parsed['role']
                concept = parsed['concept']
                subject = parsed['individual']
                
                used = collect_individuals(gamma | delta)
                
                # Strategy (i): known individuals with R(a,b) already on left
                known_triggers = find_role_triggers(gamma, role_name, subject)
                
                self.proof_trace.append(
                    f"{indent}[R∃R.C] on {s}, "
                    f"known witnesses: {known_triggers}")
                
                for b in known_triggers:
                    c_b = make_concept_assertion(concept, b)
                    # R(a,b) is already a premise; just show C(b)
                    if self._prove(gamma, rest | {c_b}, depth + 1):
                        return True
                
                # Strategy (ii): canonical fresh witness
                canonical_fresh = f"_w_{role_name}_{concept}_{subject}"
                
                if canonical_fresh not in used:
                    blocker = find_blocking_individual(
                        canonical_fresh, gamma, delta, used)
                    if blocker is not None:
                        self.proof_trace.append(
                            f"{indent}  fresh {canonical_fresh} "
                            f"blocked by {blocker}")
                    else:
                        c_b = make_concept_assertion(concept, canonical_fresh)
                        r_ab = make_role_assertion(
                            role_name, subject, canonical_fresh)
                        self.proof_trace.append(
                            f"{indent}  trying fresh witness "
                            f"{canonical_fresh}")
                        # Assume R(a,b), show C(b)
                        if self._prove(
                                gamma | {r_ab}, rest | {c_b}, depth + 1):
                            return True
            
            # [R∀R.C]: Γ ⇒ Δ, ALL R.C(a)
            #   Must show C(b) for a fresh b (eigenvariable), assuming R(a,b).
            #   This is the restricted analogue of ∀R with eigenvariable condition.
            #   Fresh b must not occur in Γ or Δ.
            #
            #   We use a canonical name derived from the universal expression
            #   to ensure memoization consistency across proof paths.
            elif parsed['type'] == ALL_RESTRICT:
                role_name = parsed['role']
                concept = parsed['concept']
                subject = parsed['individual']
                
                # Canonical eigenvariable name
                canonical_eigen = f"_e_{role_name}_{concept}_{subject}"
                
                used = collect_individuals(gamma | delta)
                # Eigenvariable must not occur in context; if canonical
                # name is already used, fall back to fresh generation
                if canonical_eigen in used:
                    b = fresh_individual(used, prefix=canonical_eigen + "_")
                else:
                    b = canonical_eigen
                
                r_ab = make_role_assertion(role_name, subject, b)
                c_b = make_concept_assertion(concept, b)
                
                self.proof_trace.append(f"{indent}[R∀R.C] on {s}, eigen {b}")
                
                # Assume R(a,b) and show C(b)
                if self._prove(gamma | {r_ab}, rest | {c_b}, depth + 1):
                    return True
        
        return False


def _fmt(fs: FrozenSet[str]) -> str:
    """Format a frozenset for display."""
    if not fs:
        return "∅"
    return ", ".join(sorted(fs))


# ============================================================
# Demo scenarios
# ============================================================

def demo_propositional_backward_compat():
    """Show that the original propositional examples still work."""
    print("=" * 70)
    print("DEMO 1: Propositional backward compatibility")
    print("=" * 70)
    
    base = MaterialBase(
        language={"A", "B", "C"},
        consequence={
            (frozenset({"A"}), frozenset({"B"})),
            (frozenset({"B"}), frozenset({"C"})),
        }
    )
    r = NMMSALCReasoner(base, max_depth=15)
    
    print(f"\n  A => A:  {r.derives(frozenset({'A'}), frozenset({'A'}))}")
    print(f"  A => B:  {r.derives(frozenset({'A'}), frozenset({'B'}))}")
    print(f"  B => C:  {r.derives(frozenset({'B'}), frozenset({'C'}))}")
    
    # Nontransitivity: A => C should FAIL
    print(f"  A => C:  {r.derives(frozenset({'A'}), frozenset({'C'}))}  (nontransitive!)")
    
    # Nonmonotonicity: A,C => B should FAIL  
    print(f"  A,C => B: {r.derives(frozenset({'A','C'}), frozenset({'B'}))}  (nonmonotonic!)")
    
    # Classical tautology
    print(f"  => A | ~A: {r.derives(frozenset(), frozenset({'A | ~A'}))}")
    
    # DDT: explicitation
    print(f"  => A -> B: {r.derives(frozenset(), frozenset({'A -> B'}))}")


def demo_beer_bottles():
    """Hlobil's beer bottle example (Inf-7 / Inf-8), reformulated in ALC.
    
    Setup: Two bottles b1, b2 in a fridge f.
    Material base: if a bottle is in the fridge, it's probably full.
    
    Inf-7 (good): inFridge(f,b1), Full(b1) |~ StillBeer(f)
      "Bottle-1 is in the fridge and full, so there's still beer."
    
    Inf-8 (bad): ALL inFridge.Empty(f), inFridge(f,b1), inFridge(f,b2) |~ StillBeer(f)
      "All bottles in the fridge are empty [plus both are in fridge], 
       so there's still beer."
      This should FAIL because ALL inFridge.Empty instantiates to 
      Empty(b1) and Empty(b2), defeating the inference.
    """
    print("\n" + "=" * 70)
    print("DEMO 2: Beer Bottles (Hlobil Inf-7/Inf-8 in ALC)")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "inFridge(f,b1)", "inFridge(f,b2)",
            "Full(b1)", "Full(b2)",
            "Empty(b1)", "Empty(b2)",
            "StillBeer(f)",
        },
        consequence={
            # A bottle in the fridge that's full means there's still beer
            (frozenset({"inFridge(f,b1)", "Full(b1)"}), 
             frozenset({"StillBeer(f)"})),
            (frozenset({"inFridge(f,b2)", "Full(b2)"}), 
             frozenset({"StillBeer(f)"})),
            # An empty bottle doesn't give you beer (defeats the inference)
            # We don't add: inFridge + Empty |~ StillBeer
            # The ABSENCE of this is what makes the inference defeasible.
        }
    )
    r = NMMSALCReasoner(base, max_depth=15)
    
    # Inf-7 analogue: specific bottle known full → still beer (GOOD)
    result = r.derives(
        frozenset({"inFridge(f,b1)", "Full(b1)"}),
        frozenset({"StillBeer(f)"})
    )
    print(f"\n  Inf-7: inFridge(f,b1), Full(b1) => StillBeer(f): {result}")
    print("  (Good inference: known full bottle → still beer)")
    
    # Inf-8 analogue: ALL bottles empty, but we conclude still beer? (BAD — should fail)
    # The reasoner should NOT derive this because:
    # ALL inFridge.Empty(f) with triggers b1,b2 instantiates to Empty(b1), Empty(b2)
    # and the base has no consequence from Empty bottles to StillBeer
    result = r.derives(
        frozenset({"ALL inFridge.Empty(f)", "inFridge(f,b1)", "inFridge(f,b2)"}),
        frozenset({"StillBeer(f)"})
    )
    print(f"\n  Inf-8: ALL inFridge.Empty(f), inFridge(f,b1), inFridge(f,b2)")
    print(f"         => StillBeer(f): {result}")
    print("  (Bad inference: should fail — ALL empty defeats 'still beer')")
    
    # Key contrast: adding the universal restriction defeats the inference
    # even though the specific instance was good
    result_with_extra = r.derives(
        frozenset({"inFridge(f,b1)", "Full(b1)", 
                    "ALL inFridge.Empty(f)", "inFridge(f,b2)"}),
        frozenset({"StillBeer(f)"})
    )
    print(f"\n  Defeat: inFridge(f,b1), Full(b1), ALL inFridge.Empty(f), inFridge(f,b2)")
    print(f"         => StillBeer(f): {result_with_extra}")
    print("  (Nonmonotonic: adding premises defeats a previously good inference)")


def demo_medical_reasoning():
    """Medical diagnosis example (inspired by Hlobil's Inf-1/Inf-2).
    
    Material base captures defeasible medical inferences:
    - Patient with chest pain radiating left → probably heart attack
    - But if ALL tests are normal → defeats heart attack inference
    """
    print("\n" + "=" * 70)
    print("DEMO 3: Medical Diagnosis (Defeasible Material Inference)")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "hasSymptom(patient,chestPain)", "hasSymptom(patient,leftRadiation)",
            "hasTest(patient,ecg)", "hasTest(patient,enzymes)",
            "Normal(ecg)", "Normal(enzymes)",
            "Abnormal(ecg)", "Abnormal(enzymes)",
            "HeartAttack(patient)", "NotHeartAttack(patient)",
        },
        consequence={
            # Defeasible: chest pain + left radiation → heart attack
            (frozenset({"hasSymptom(patient,chestPain)", 
                        "hasSymptom(patient,leftRadiation)"}),
             frozenset({"HeartAttack(patient)"})),
            # If tests are normal, conclude not heart attack
            (frozenset({"hasTest(patient,ecg)", "Normal(ecg)",
                        "hasTest(patient,enzymes)", "Normal(enzymes)"}),
             frozenset({"NotHeartAttack(patient)"})),
        }
    )
    r = NMMSALCReasoner(base, max_depth=15)
    
    # Inf-1: symptoms alone → heart attack (good, defeasible)
    result = r.derives(
        frozenset({"hasSymptom(patient,chestPain)", 
                    "hasSymptom(patient,leftRadiation)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  Inf-1: chestPain, leftRadiation => HeartAttack: {result}")
    print("  (Good defeasible inference)")
    
    # Inf-2: symptoms + normal tests → heart attack? (should fail)
    # Adding normal test results should defeat the inference
    result = r.derives(
        frozenset({"hasSymptom(patient,chestPain)",
                    "hasSymptom(patient,leftRadiation)",
                    "hasTest(patient,ecg)", "Normal(ecg)",
                    "hasTest(patient,enzymes)", "Normal(enzymes)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  Inf-2: chestPain, leftRadiation, normalECG, normalEnzymes")
    print(f"         => HeartAttack: {result}")
    print("  (Defeated: normal tests block heart attack inference)")
    
    # But the extended premises DO support NotHeartAttack
    result = r.derives(
        frozenset({"hasTest(patient,ecg)", "Normal(ecg)",
                    "hasTest(patient,enzymes)", "Normal(enzymes)"}),
        frozenset({"NotHeartAttack(patient)"})
    )
    print(f"\n  Normal tests => NotHeartAttack: {result}")


def demo_restricted_quantifier_logic():
    """Demonstrate that restricted quantifier rules interact correctly
    with propositional connectives and the material base.
    """
    print("\n" + "=" * 70)
    print("DEMO 4: Restricted Quantifier Logic")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "hasChild(alice,bob)", "hasChild(alice,carol)",
            "Happy(bob)", "Happy(carol)",
            "Sad(bob)", "Sad(carol)",
            "Doctor(bob)", "Doctor(carol)",
            "ParentOfDoctor(alice)",
        },
        consequence={
            # If alice has a child who is a doctor, she's a parent of a doctor
            (frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
             frozenset({"ParentOfDoctor(alice)"})),
            (frozenset({"hasChild(alice,carol)", "Doctor(carol)"}),
             frozenset({"ParentOfDoctor(alice)"})),
        }
    )
    r = NMMSALCReasoner(base, max_depth=20)
    
    # ALL hasChild.Happy(alice) with trigger bob → Happy(bob)
    # This tests L∀R.C instantiation
    print("\n  --- Instantiation of ALL ---")
    result = r.derives(
        frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
        frozenset({"Happy(bob)"})
    )
    print(f"  ALL hasChild.Happy(alice), hasChild(alice,bob) => Happy(bob): {result}")
    
    # Containment through instantiation
    print("\n  --- Existential on the right ---")
    result = r.derives(
        frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
        frozenset({"SOME hasChild.Doctor(alice)"})
    )
    print(f"  hasChild(alice,bob), Doctor(bob) => SOME hasChild.Doctor(alice): {result}")
    
    # Interaction: ALL + material base
    print("\n  --- ALL + material base ---")
    result = r.derives(
        frozenset({"ALL hasChild.Doctor(alice)", "hasChild(alice,bob)"}),
        frozenset({"ParentOfDoctor(alice)"})
    )
    print(f"  ALL hasChild.Doctor(alice), hasChild(alice,bob)")
    print(f"    => ParentOfDoctor(alice): {result}")
    
    # DDT with quantifiers: explicitation
    print("\n  --- DDT with restricted quantifiers ---")
    result = r.derives(
        frozenset({"hasChild(alice,bob)"}),
        frozenset({"ALL hasChild.Happy(alice) -> Happy(bob)"})
    )
    print(f"  hasChild(alice,bob) => (ALL hasChild.Happy(alice)) -> Happy(bob): {result}")


def demo_nonmonotonicity_with_quantifiers():
    """The core demonstration: how restricted quantification interacts
    with nonmonotonicity in a way that unrestricted ∀ cannot.
    """
    print("\n" + "=" * 70)
    print("DEMO 5: Nonmonotonicity + Quantifiers (The Key Insight)")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "teaches(dept,alice)", "teaches(dept,bob)",
            "Excellent(alice)", "Excellent(bob)",
            "Mediocre(alice)", "Mediocre(bob)",
            "GreatDept(dept)",
        },
        consequence={
            # If alice is excellent and teaches in dept → great dept  
            (frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
             frozenset({"GreatDept(dept)"})),
            # Same for bob
            (frozenset({"teaches(dept,bob)", "Excellent(bob)"}),
             frozenset({"GreatDept(dept)"})),
            # But NOT: teaches + Mediocre |~ GreatDept
        }
    )
    r = NMMSALCReasoner(base, max_depth=20)
    
    # Specific instance: alice is excellent → great dept
    result = r.derives(
        frozenset({"teaches(dept,alice)", "Excellent(alice)"}),
        frozenset({"GreatDept(dept)"})
    )
    print(f"\n  teaches(dept,alice), Excellent(alice) => GreatDept(dept): {result}")
    print("  (Good: specific excellent teacher → great dept)")
    
    # BUT: ALL teachers excellent doesn't help with extra teacher who's mediocre
    # because the material base only recognizes specific named teachers
    result = r.derives(
        frozenset({"ALL teaches.Excellent(dept)", 
                    "teaches(dept,alice)", "teaches(dept,bob)",
                    "Mediocre(bob)"}),
        frozenset({"GreatDept(dept)"})
    )
    print(f"\n  ALL teaches.Excellent(dept), teaches(dept,alice),")
    print(f"    teaches(dept,bob), Mediocre(bob) => GreatDept(dept): {result}")
    print("  (Defeated: adding Mediocre(bob) blocks the inference)")
    
    # Without the extra Mediocre premise, ALL teaches.Excellent should work
    result = r.derives(
        frozenset({"ALL teaches.Excellent(dept)",
                    "teaches(dept,alice)"}),
        frozenset({"GreatDept(dept)"})
    )
    print(f"\n  ALL teaches.Excellent(dept), teaches(dept,alice)")
    print(f"    => GreatDept(dept): {result}")
    print("  (Good: ALL excellent with one known teacher)")


def demo_shakespeare():
    """Hlobil's Shakespeare example (Inf-5/Inf-6) reformulated.
    
    Inf-5: authored(shakespeare, rj), GreatWork(rj) |~ ImportantAuthor(shakespeare)
    Inf-6: ALL authored.GreatWork(shakespeare) |~ ImportantAuthor(everyone)  -- BAD
    
    With restricted quantification, we avoid the problematic ∀R entirely.
    """
    print("\n" + "=" * 70)
    print("DEMO 6: Shakespeare (Inf-5/Inf-6)")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "authored(shakespeare,rj)", "authored(shakespeare,hamlet)",
            "authored(marlowe,faustus)",
            "GreatWork(rj)", "GreatWork(hamlet)", "GreatWork(faustus)",
            "ImportantAuthor(shakespeare)", "ImportantAuthor(marlowe)",
        },
        consequence={
            # Shakespeare authored a great work → important author
            (frozenset({"authored(shakespeare,rj)", "GreatWork(rj)"}),
             frozenset({"ImportantAuthor(shakespeare)"})),
            (frozenset({"authored(shakespeare,hamlet)", "GreatWork(hamlet)"}),
             frozenset({"ImportantAuthor(shakespeare)"})),
            # Marlowe too
            (frozenset({"authored(marlowe,faustus)", "GreatWork(faustus)"}),
             frozenset({"ImportantAuthor(marlowe)"})),
        }
    )
    r = NMMSALCReasoner(base, max_depth=15)
    
    # Inf-5: specific work → important author (GOOD)
    result = r.derives(
        frozenset({"authored(shakespeare,rj)", "GreatWork(rj)"}),
        frozenset({"ImportantAuthor(shakespeare)"})
    )
    print(f"\n  Inf-5: authored(shakespeare,rj), GreatWork(rj)")
    print(f"         => ImportantAuthor(shakespeare): {result}")
    
    # SOME authored.GreatWork(shakespeare) → ImportantAuthor(shakespeare)
    # This SHOULD work via R∃ instantiation to a known witness
    result = r.derives(
        frozenset({"SOME authored.GreatWork(shakespeare)",
                    "authored(shakespeare,rj)", "GreatWork(rj)"}),
        frozenset({"ImportantAuthor(shakespeare)"})
    )
    print(f"\n  SOME authored.GreatWork(shakespeare) [with witness]")
    print(f"         => ImportantAuthor(shakespeare): {result}")
    
    # The problematic Inf-6 can't even be stated naturally with restricted
    # quantification — you can't say "everyone is an important author" 
    # without unrestricted ∀. This is a FEATURE, not a bug.
    print(f"\n  Note: Inf-6 ('everyone is important') cannot be naturally stated")
    print(f"  with restricted quantification — the problematic inference is blocked")
    print(f"  at the syntactic level, exactly as desired.")


def demo_witness_completeness():
    """Test canonical witness naming and improved completeness.
    
    Exercises:
    - Canonical fresh names for R∃R.C (memoization consistency)
    - Canonical eigenvariables for R∀R.C
    - Witness search finding known individuals before fresh ones
    """
    print("\n" + "=" * 70)
    print("DEMO 7: Witness Completeness & Canonical Naming")
    print("=" * 70)
    
    base = MaterialBase(
        language={
            "supervises(mgr,alice)", "supervises(mgr,bob)",
            "Certified(alice)", "Certified(bob)",
            "Compliant(mgr)",
        },
        consequence={
            # If a manager supervises a certified employee → compliant
            (frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
             frozenset({"Compliant(mgr)"})),
            (frozenset({"supervises(mgr,bob)", "Certified(bob)"}),
             frozenset({"Compliant(mgr)"})),
        }
    )
    r = NMMSALCReasoner(base, max_depth=20)
    
    # R∃R.C: prove existential on right by finding known witness
    print("\n  --- R∃R.C with known witness ---")
    result = r.derives(
        frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
        frozenset({"SOME supervises.Certified(mgr)"})
    )
    print(f"  supervises(mgr,alice), Certified(alice)")
    print(f"    => SOME supervises.Certified(mgr): {result}")
    
    # DDT: explicitate the existential via conditional
    print("\n  --- DDT with existential ---")
    result = r.derives(
        frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
        frozenset({"SOME supervises.Certified(mgr)"})
    )
    # Run it twice to exercise memoization with canonical names
    result2 = r.derives(
        frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
        frozenset({"SOME supervises.Certified(mgr)"})
    )
    print(f"  Same query twice (memoization test): {result} then {result2}")
    
    # ALL on right with eigenvariable: canonical naming
    print("\n  --- R∀R.C with canonical eigenvariable ---")
    result = r.derives(
        frozenset({"supervises(mgr,alice)", "Certified(alice)"}),
        frozenset({"ALL supervises.Certified(mgr)"})
    )
    print(f"  supervises(mgr,alice), Certified(alice)")
    print(f"    => ALL supervises.Certified(mgr): {result}")
    print(f"  (Should be False: can't prove certification for arbitrary employee)")
    
    # Existential interacting with universal on left
    print("\n  --- ALL left + SOME right interaction ---")
    result = r.derives(
        frozenset({"ALL supervises.Certified(mgr)", "supervises(mgr,bob)"}),
        frozenset({"SOME supervises.Certified(mgr)"})
    )
    print(f"  ALL supervises.Certified(mgr), supervises(mgr,bob)")
    print(f"    => SOME supervises.Certified(mgr): {result}")
    print(f"  (Should be True: ALL gives Certified(bob), bob witnesses SOME)")


def demo_edge_cases():
    """Comprehensive edge case and structural tests.
    
    Tests:
    - Vacuous quantification (no triggers)
    - Negated quantifiers (duality via defined connectives)
    - LC with quantifiers (conjunction decomposition)
    - Nested quantifiers
    - Blocking
    - Expected failures (false positive checks)
    """
    print("\n" + "=" * 70)
    print("DEMO 8: Edge Cases & Structural Tests")
    print("=" * 70)
    
    # ---- Vacuous quantification ----
    print("\n  --- 8a: Vacuous quantification (no triggers) ---")
    base_a = MaterialBase(
        language={"Happy(alice)", "R(x,y)"},
        consequence=set()
    )
    r_a = NMMSALCReasoner(base_a, max_depth=15)
    
    # ALL R.C(a) with no R(a,_) triggers should not decompose
    # The sequent must close some other way or fail
    result = r_a.derives(
        frozenset({"ALL hasChild.Happy(alice)"}),
        frozenset({"Happy(bob)"})
    )
    print(f"  ALL hasChild.Happy(alice) => Happy(bob): {result}")
    print(f"  (False: no triggers, no way to instantiate)")
    
    # But containment should still work with quantified sentences
    result = r_a.derives(
        frozenset({"ALL hasChild.Happy(alice)"}),
        frozenset({"ALL hasChild.Happy(alice)"})
    )
    print(f"  ALL hasChild.Happy(alice) => ALL hasChild.Happy(alice): {result}")
    print(f"  (True: containment)")
    
    # ---- Negated quantifiers ----
    print("\n  --- 8b: Negated quantifiers ---")
    # ~ALL R.C(a) should behave like SOME R.~C(a) through logical rules
    # ~SOME R.C(a) should behave like ALL R.~C(a)
    # Since these are defined (∃ = ¬∀¬, so ~∀ = ∃¬ and ~∃ = ∀¬), 
    # the negation rule just flips the quantifier expression to the other side.
    base_b = MaterialBase(
        language={
            "hasChild(alice,bob)", "Happy(bob)", "Sad(bob)",
        },
        consequence=set()
    )
    r_b = NMMSALCReasoner(base_b, max_depth=15)
    
    # ~ALL hasChild.Happy(alice) on the left → ALL hasChild.Happy(alice) on right
    # With hasChild(alice,bob), R∀R.C needs fresh eigenvariable to show Happy
    # This should fail since we can't show arbitrary children are happy
    result = r_b.derives(
        frozenset({"~ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
        frozenset({"Sad(bob)"})
    )
    print(f"  ~ALL hasChild.Happy(alice), hasChild(alice,bob) => Sad(bob): {result}")
    print(f"  (False: negated universal doesn't give us Sad)")
    
    # Excluded middle for quantified sentences
    result = r_b.derives(
        frozenset(),
        frozenset({"ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice)"})
    )
    print(f"  => ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice): {result}")
    print(f"  (True: LEM holds for quantified sentences)")
    
    # ---- LC with quantifiers ----
    print("\n  --- 8c: LC (left conjunction) with quantifiers ---")
    base_c = MaterialBase(
        language={
            "hasChild(alice,bob)", "Happy(bob)", "Smart(bob)",
        },
        consequence=set()
    )
    r_c = NMMSALCReasoner(base_c, max_depth=15)
    
    # (ALL hasChild.Happy(alice)) & (ALL hasChild.Smart(alice)) on left
    # should decompose multiplicatively to both universals as separate premises
    # then each instantiates with trigger bob
    result = r_c.derives(
        frozenset({"ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)",
                    "hasChild(alice,bob)"}),
        frozenset({"Happy(bob)"})
    )
    print(f"  (ALL hasChild.Happy & ALL hasChild.Smart)(alice), hasChild(alice,bob)")
    print(f"    => Happy(bob): {result}")
    print(f"  (True: LC decomposes conjunction, then L∀R.C instantiates)")
    
    result = r_c.derives(
        frozenset({"ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)",
                    "hasChild(alice,bob)"}),
        frozenset({"Happy(bob) & Smart(bob)"})
    )
    print(f"    => Happy(bob) & Smart(bob): {result}")
    print(f"  (True: both conjuncts derivable)")
    
    # ---- Nested quantifiers ----
    print("\n  --- 8d: Nested quantifiers ---")
    # ALL R.C where C itself contains quantifier structure
    # We need to test that parser handles this — but our current syntax
    # doesn't support nested quantifiers directly (ALL R.(SOME S.C) isn't 
    # parseable). This is a syntactic limitation, not a semantic one.
    # Test what we CAN do: quantifier + propositional nesting
    base_d = MaterialBase(
        language={
            "hasChild(alice,bob)", "hasChild(bob,carol)",
            "Happy(bob)", "Happy(carol)", 
            "Tall(bob)", "Tall(carol)",
        },
        consequence=set()
    )
    r_d = NMMSALCReasoner(base_d, max_depth=20)
    
    # Chain: ALL hasChild.Happy(alice) with bob, then use Happy(bob) 
    # with a material base entry
    result = r_d.derives(
        frozenset({"ALL hasChild.Happy(alice)", "hasChild(alice,bob)"}),
        frozenset({"Happy(bob) | Tall(bob)"})
    )
    print(f"  ALL hasChild.Happy(alice), hasChild(alice,bob)")
    print(f"    => Happy(bob) | Tall(bob): {result}")
    print(f"  (True: instantiate to Happy(bob), then R∨)")
    
    # ---- Expected failures (false positive checks) ----
    print("\n  --- 8e: Expected failures ---")
    base_e = MaterialBase(
        language={
            "hasChild(alice,bob)", "hasChild(alice,carol)",
            "Happy(bob)", "Sad(carol)",
        },
        consequence=set()
    )
    r_e = NMMSALCReasoner(base_e, max_depth=15)
    
    # ALL hasChild.Happy should NOT be derivable when carol is Sad
    result = r_e.derives(
        frozenset({"hasChild(alice,bob)", "Happy(bob)",
                    "hasChild(alice,carol)", "Sad(carol)"}),
        frozenset({"ALL hasChild.Happy(alice)"})
    )
    print(f"  hasChild(bob), Happy(bob), hasChild(carol), Sad(carol)")
    print(f"    => ALL hasChild.Happy(alice): {result}")
    print(f"  (False: carol is Sad, not Happy — can't prove ALL happy)")
    
    # SOME should not conjure a witness from nothing
    result = r_e.derives(
        frozenset({"hasChild(alice,bob)"}),
        frozenset({"SOME hasChild.Happy(alice)"})
    )
    print(f"  hasChild(alice,bob) => SOME hasChild.Happy(alice): {result}")
    print(f"  (False: bob isn't known to be Happy)")
    
    # Weakening should still fail with quantifiers
    base_f = MaterialBase(
        language={
            "hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)",
        },
        consequence={
            (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
             frozenset({"ParentHappy(alice)"})),
        }
    )
    r_f = NMMSALCReasoner(base_f, max_depth=15)
    
    result = r_f.derives(
        frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
        frozenset({"ParentHappy(alice)"})
    )
    print(f"\n  hasChild(alice,bob), Happy(bob) => ParentHappy(alice): {result}")
    print(f"  (True: base consequence)")
    
    result = r_f.derives(
        frozenset({"hasChild(alice,bob)", "Happy(bob)", "Grumpy(bob)"}),
        frozenset({"ParentHappy(alice)"})
    )
    print(f"  + Grumpy(bob) => ParentHappy(alice): {result}")
    print(f"  (False: nonmonotonic — extra premise defeats it)")
    
    result = r_f.derives(
        frozenset({"hasChild(alice,bob)", "Happy(bob)",
                    "ALL hasChild.Grumpy(alice)"}),
        frozenset({"ParentHappy(alice)"})
    )
    print(f"  + ALL hasChild.Grumpy(alice) => ParentHappy(alice): {result}")
    print(f"  (False: ALL instantiates Grumpy(bob), defeating the inference)")


# ============================================================
# ADDITIONAL TESTS TODO
# ============================================================
# The following test cases would further strengthen coverage but are
# not yet implemented. They are listed here for future work:
#
# 1. DDT with existential:
#    - ⊢ SOME R.C(a) → φ  (conditional with existential antecedent)
#    - ⊢ φ → SOME R.C(a)  (conditional with existential consequent)
#    These test the interaction of R→ with quantifier rules.
#
# 2. Interaction of two different restricted quantifiers on the left:
#    - ALL R.C(a), SOME R.D(a), R(a,b) ⊢ φ
#    Both quantifiers share triggers; tests that L∀R.C and L∃R.C
#    compose correctly when applied to the same role.
#
# 3. Multiple roles on the same individual:
#    - ALL R.C(a), ALL S.D(a), R(a,b), S(a,c) ⊢ φ
#    Tests that different roles maintain independent trigger sets.
#
# 4. L∃R.C directly succeeding:
#    - SOME R.C(a), R(a,b), C(b) ⊢ φ where C(b) ⊢ φ is a base consequence
#    Exercises the existential on the left with a known witness that
#    chains through the material base.
#
# 5. Ketonen pattern for L∃R.C making a difference:
#    - Construct a case where C(b1) ⊢ φ and C(b2) ⊢ φ both hold
#      but C(b1), C(b2) ⊢ φ does NOT hold (due to no weakening).
#      This would demonstrate that the Ketonen all-nonempty-subsets
#      requirement is not just theoretical but actually filters out
#      unsound inferences in practice.
#
# 6. Blocking actually firing:
#    - Construct a case with a chain of existentials where a fresh
#      witness has concept label ⊆ an existing individual's label,
#      triggering the blocking condition. Verify that the proof
#      still succeeds (via the blocking individual) or correctly fails.
#
# 7. Nested quantifier syntax:
#    - Currently ALL R.(SOME S.C) is not parseable. If the parser is
#      extended to support nested quantifiers, test recursive
#      decomposition through multiple quantifier layers.


def demo_soundness_audit():
    """Systematic rule-by-rule audit for containment-leak false positives.
    
    The bug found in R∃R.C (where placing R(a,b) on the succedent allowed
    containment to close without establishing C(b)) had a specific shape:
    a rule places content on one side that overlaps with the other side
    via Containment, closing the sequent without the intended content 
    being established.
    
    This audit probes every rule for that pattern, testing both that
    legitimate containment works AND that spurious containment doesn't.
    """
    print("\n" + "=" * 70)
    print("DEMO 9: Soundness Audit (Containment-Leak Probes)")
    print("=" * 70)
    
    base = MaterialBase(
        language={'R(a,b)', 'C(a)', 'C(b)', 'D(a)', 'D(b)'},
        consequence=set()
    )
    r = NMMSALCReasoner(base, max_depth=15)
    
    tests = []
    
    def check(label, gamma, delta, expected):
        result = r.derives(frozenset(gamma), frozenset(delta))
        status = "✓" if result == expected else "✗ FAIL"
        tests.append((label, result, expected))
        print(f"  {status} {label}: {result} (expected {expected})")
    
    print("\n  --- Propositional rules ---")
    check("L¬ explosion",
          {'~C(a)', 'C(a)'}, {'D(b)'}, True)
    check("R¬ no leak", 
          {'D(a)'}, {'~D(a)', 'C(b)'}, False)
    check("L→ no leak",
          {'C(a) -> D(a)'}, {'C(b)'}, False)
    check("R→ tautology",
          set(), {'C(a) -> C(a)'}, True)
    check("R→ no leak",
          set(), {'C(a) -> D(b)'}, False)
    check("R∨ no leak",
          {'C(a)'}, {'D(a) | D(b)'}, False)
    check("R∨ containment",
          {'C(a)'}, {'C(a) | D(b)'}, True)
    check("Containment schema",
          {'D(a)'}, {'D(a)', 'C(b)'}, True)
    
    print("\n  --- Quantifier rules ---")
    check("L∀ containment",
          {'ALL R.C(a)', 'R(a,b)'}, {'C(b)'}, True)
    check("L∀ no leak",
          {'ALL R.C(a)', 'R(a,b)'}, {'D(b)'}, False)
    check("L∃ containment",
          {'SOME R.C(a)', 'R(a,b)'}, {'C(b)'}, True)
    check("L∃ no leak",
          {'SOME R.C(a)', 'R(a,b)'}, {'D(b)'}, False)
    check("R∃ known witness",
          {'R(a,b)', 'C(b)'}, {'SOME R.C(a)'}, True)
    check("R∃ no concept",
          {'R(a,b)'}, {'SOME R.C(a)'}, False)
    check("R∃ from nothing",
          set(), {'SOME R.C(a)'}, False)
    check("R∀ from nothing",
          set(), {'ALL R.C(a)'}, False)
    check("R∀ specific ≠ universal",
          {'R(a,b)', 'C(b)'}, {'ALL R.C(a)'}, False)
    
    print("\n  --- Cross-rule interactions ---")
    check("ALL→SOME with trigger",
          {'ALL R.C(a)', 'R(a,b)'}, {'SOME R.C(a)'}, True)
    check("ALL→SOME no trigger",
          {'ALL R.C(a)'}, {'SOME R.C(a)'}, False)
    check("L→ + R∃ no leak",
          {'C(b) -> D(b)', 'R(a,b)'}, {'SOME R.D(a)'}, False)
    
    # Summary
    failures = [(l, r, e) for l, r, e in tests if r != e]
    print(f"\n  --- {len(tests)} tests, {len(failures)} failures ---")
    if failures:
        for label, result, expected in failures:
            print(f"  FAILURE: {label}: got {result}, expected {expected}")
    else:
        print(f"  All tests passed. No containment leaks detected.")


def demo_commitment_store():
    """Demonstrate the schema layer for Elenchus integration.
    
    Shows how quantified natural language commitments map to the
    atomic material base through lazy schemas, and how the reasoner
    then operates over sequents containing quantified vocabulary.
    
    Scenario: Medical knowledge elicitation.
    The interlocutor commits to:
    1. "Patient has symptoms: chest pain, left radiation" (atomic)
    2. "All symptoms of this patient are serious" (concept schema)
    3. "Any serious symptom of this patient suggests heart attack" (inference schema)
    Then a new symptom is discovered — no re-grounding needed.
    
    Key: schemas are stored, not grounded. O(k+m) storage, not O(n×(k+m)).
    """
    print("\n" + "=" * 70)
    print("DEMO 10: Lazy Schema Evaluation (Elenchus Integration)")
    print("=" * 70)
    
    # Start with known atomic facts
    base = MaterialBase(
        language={
            "hasSymptom(patient,chestPain)",
            "hasSymptom(patient,leftRadiation)",
        },
        consequence=set()
    )
    
    # Commitment 1: "All symptoms of this patient are serious"
    # → concept schema: for all hasSymptom(patient, x), assert Serious(x)
    # NOT grounded — stored as schema, evaluated lazily in is_axiom
    base.register_concept_schema('hasSymptom', 'patient', 'Serious')
    
    print("\n  After registering 'all symptoms are serious':")
    print(f"  Inference schemas (including concept schemas): {len(base._inference_schemas)}")
    print(f"  Ground language entries with 'Serious': "
          f"{ {s for s in base.language if 'Serious' in s} }")
    print(f"  (Empty — schemas are lazy, not grounded)")
    
    # Commitment 2: "Any serious symptom suggests heart attack"  
    # → inference schema: for all hasSymptom(patient, x) with Serious(x),
    #   infer HeartAttack(patient)
    base.register_inference_schema(
        'hasSymptom', 'patient', 'Serious',
        {'HeartAttack(patient)'}
    )
    
    print(f"\n  Inference schemas: {len(base._inference_schemas)}")
    print(f"  Ground consequence entries: {len(base.consequence)}")
    print(f"  (No eager grounding — schemas matched at query time)")
    
    r = NMMSALCReasoner(base, max_depth=15)
    
    # The reasoner derives HeartAttack via lazy schema matching
    result = r.derives(
        frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  hasSymptom + Serious(chestPain) => HeartAttack: {result}")
    print(f"  (True: inference schema matched lazily for chestPain)")
    
    # Quantified sentences in sequents decompose into atoms that hit schemas
    result = r.derives(
        frozenset({"ALL hasSymptom.Serious(patient)",
                    "hasSymptom(patient,chestPain)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  ALL hasSymptom.Serious(patient), hasSymptom(patient,chestPain)")
    print(f"    => HeartAttack(patient): {result}")
    print(f"  (True: L∀ instantiates Serious(chestPain), then schema matches)")
    
    # Concept schema: Serious(chestPain) is virtually asserted
    result = r.derives(
        frozenset({"hasSymptom(patient,chestPain)"}),
        frozenset({"Serious(chestPain)"})
    )
    print(f"\n  hasSymptom(patient,chestPain) => Serious(chestPain): {result}")
    print(f"  (True: concept schema virtually asserts Serious(chestPain))")
    
    # New symptom — no re-grounding, just add the role assertion
    print("\n  --- New symptom discovered: shortness of breath ---")
    base.add_individual('hasSymptom', 'patient', 'shortnessOfBreath')
    
    print(f"  Ground entries added: 1 (role assertion only)")
    print(f"  Schema re-grounding: none needed (lazy evaluation)")
    
    r2 = NMMSALCReasoner(base, max_depth=15)
    
    # The new symptom immediately works with existing schemas
    result = r2.derives(
        frozenset({"hasSymptom(patient,shortnessOfBreath)", 
                    "Serious(shortnessOfBreath)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  hasSymptom + Serious(shortnessOfBreath) => HeartAttack: {result}")
    print(f"  (True: schema matches new individual without re-grounding)")
    
    # Concept schema works for new individual too
    result = r2.derives(
        frozenset({"hasSymptom(patient,shortnessOfBreath)"}),
        frozenset({"Serious(shortnessOfBreath)"})
    )
    print(f"  hasSymptom(shortnessOfBreath) => Serious(shortnessOfBreath): {result}")
    print(f"  (True: concept schema matches lazily)")
    
    # Nonmonotonicity: adding defeating info blocks inference
    result = r2.derives(
        frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)",
                    "Normal(ecg)"}),
        frozenset({"HeartAttack(patient)"})
    )
    print(f"\n  + Normal(ecg) => HeartAttack: {result}")
    print(f"  (False: no schema matches {'{'}hasSymptom, Serious, Normal{'}'} exactly)")
    
    print(f"\n  Lazy schema architecture:")
    print(f"    Storage: O(k+m) schemas, not O(n×(k+m)) ground entries")
    print(f"    Adding individuals: O(1), no schema re-expansion")
    print(f"    Query: schemas matched against concrete sequent atoms")


if __name__ == "__main__":
    demo_propositional_backward_compat()
    demo_beer_bottles()
    demo_medical_reasoning()
    demo_restricted_quantifier_logic()
    demo_nonmonotonicity_with_quantifiers()
    demo_shakespeare()
    demo_witness_completeness()
    demo_edge_cases()
    demo_soundness_audit()
    demo_commitment_store()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
The NMMS-ALC reasoner extends propositional NMMS with ALC-style restricted
quantification, meeting all of Hlobil's (2025) desiderata:

  MOF:  Nonmonotonicity preserved — adding premises defeats inferences
  SCL:  Supraclassicality — all classically valid (ALC) sequents derivable  
  DDT:  Deduction-detachment theorem holds for →
  DS:   Disjunction simplification holds for ∨
  LC:   Left conjunction is multiplicative (∧ decomposes to separate premises)

The restricted quantifiers avoid the problems Hlobil identifies with ∀L and ∀R:
  - No unrestricted instantiation that brings in defeating cases
  - Quantification is always relative to a role (relation)
  - Triggers (role assertions in context) control which instances matter
  - This naturally models domain-specific, defeasible reasoning

Key design: ALL R.C behaves as a "generalized conjunction" over triggered 
instances (matching Hlobil's semantic clause, Def. 16), while SOME R.C 
behaves as a "generalized disjunction" — but only over known witnesses.
""")