# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Project

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest -v

# Run tests with coverage
pytest --cov=pynmms --cov-report=term-missing

# CLI usage
pynmms tell -b base.json --create "A |~ B"
pynmms tell -b base.json 'atom p "Tara is human"'
pynmms tell -b base.json "s, t |~"           # empty consequent (incompatibility)
pynmms tell -b base.json "|~ p"              # empty antecedent (theorem)
pynmms ask -b base.json "A => B"
pynmms ask -b base.json --json "A => B"      # JSON output
pynmms ask -b base.json -q "A => B"          # quiet (exit code only)
pynmms tell -b base.json --create --batch base.txt  # batch input
pynmms ask -b base.json --batch queries.txt          # batch queries
echo "A => B" | pynmms ask -b base.json -    # stdin input
pynmms repl
# REPL commands are unquoted (no shell quoting):
#   pynmms> ask A => B
#   pynmms> tell A |~ B

# CLI with ontology extension
pynmms tell -b onto_base.json --create --onto "atom Man(socrates)"
pynmms tell -b onto_base.json --onto --batch schemas.txt
pynmms ask -b onto_base.json --onto "Man(socrates) => Mortal(socrates)"
pynmms repl --onto
```

Uses Python 3.10+ standard library only (no runtime dependencies). Dev dependencies: pytest, pytest-cov, ruff, mypy.

## Theoretical Foundation

This implements the NMMS sequent calculus from Hlobil & Brandom 2025 (Ch. 3, "Introducing Logical Vocabulary"). The `pynmms` package implements propositional NMMS in the core and **ontology axiom schemas** (subClassOf, range, domain, subPropertyOf, disjointWith, disjointProperties, jointCommitment) in the `pynmms.onto` subpackage.

### The NMMS Framework

NMMS (Non-Monotonic Multi-Succedent) is a sequent calculus for codifying **open reason relations** — consequence relations where Monotonicity ([Weakening]) and Transitivity ([Mixed-Cut]) can fail. The key ideas:

- **Material Base** (Definition 1 in Ch. 3): An atomic language L_B plus a base consequence relation |~_B ⊆ P(L_B) × P(L_B) obeying Containment (Γ ∩ Δ ≠ ∅ implies Γ |~_B Δ). The base encodes defeasible material inferences among atomic sentences as axioms.

- **Logical Extension**: The rules of NMMS extend |~_B to a consequence relation |~ over a logically extended language L (adding ¬, →, ∧, ∨). A sequent Γ ⇒ Δ is derivable iff there is a proof tree whose leaves are all axioms (base sequents).

- **No structural rules**: NMMS omits [Weakening] and [Mixed-Cut]. This is what allows nonmonotonic and nontransitive material inferences. Failures of monotonicity mean adding premises can defeat inferences; failures of transitivity mean chaining good inferences can yield bad ones.

- **Ketonen-style rules with third top sequent**: The NMMS rules differ from standard Ketonen rules by having a third premise in multi-premise rules. The third top sequent contains all active formulae from the other premises on the same sides. This ensures that working with sets (where contraction is built in) doesn't affect derivability — it compensates for the absence of structural contraction while preserving idempotency.

### Critical Properties (from Ch. 3)

- **Supraclassicality** (Fact 2): CL ⊆ |~ — all classically valid sequents are derivable when the base obeys Containment. The "narrowly logical part" (derivable from Containment alone) is exactly classical propositional logic.
- **Conservative Extension** (Fact 3/Prop. 26): If Γ ∪ Δ ⊆ L_B, then Γ |~ Δ iff Γ |~_B Δ. Adding logical vocabulary does not change base-level reason relations.
- **Invertibility** (Prop. 27): All NMMS rules are invertible — the bottom sequent is derivable iff all top sequents are derivable.
- **Projection** (Theorem 7): Every sequent Γ ⇒ Δ in the extended language uniquely decomposes into a set of base-vocabulary sequents (AtomicImp) such that Γ ⇒ Δ is derivable iff AtomicImp ⊆ |~_B.

### Explicitation Conditions (the expressivist core)

These biconditionals are what make logical vocabulary "make explicit" reason relations:
- **DD** (Deduction-Detachment): Γ |~ A → B, Δ  iff  Γ, A |~ B, Δ
- **II** (Incoherence-Incompatibility): Γ |~ ¬A, Δ  iff  Γ, A |~ Δ
- **AA** (Antecedent-Adjunction): Γ, A ∧ B |~ Δ  iff  Γ, A, B |~ Δ
- **SS** (Succedent-Summation): Γ |~ A ∨ B, Δ  iff  Γ |~ A, B, Δ

## Architecture

### Propositional Core (`src/pynmms/`)

1. **`syntax.py`** — Recursive descent parser for propositional sentences: atoms, negation (~), conjunction (&), disjunction (|), implication (->). Returns frozen `Sentence` dataclass AST nodes. Operator precedence: `&` > `|` > `->`.

2. **`base.py`** — `MaterialBase` class implementing the material base B = <L_B, |~_B>. Stores atomic language, consequence relation, and optional atom annotations. Exact syntactic match (no weakening). JSON serialization via `to_file()`/`from_file()`.

3. **`reasoner.py`** — `NMMSReasoner` class with backward proof search implementing 8 Ketonen-style propositional rules (L¬, L→, L∧, L∨, R¬, R→, R∧, R∨). Returns `ProofResult` with derivability, trace, depth, and cache stats.

4. **`cli/`** — Tell/Ask CLI with REPL mode (`--onto` flag enables ontology mode):
   - `pynmms tell` — add atoms/consequences to a JSON base file; supports annotations, empty sides, `--json`, `-q`, `--batch`, stdin (`-`)
   - `pynmms ask` — query derivability with optional trace; semantic exit codes (0=derivable, 1=error, 2=not derivable), `--json`, `-q`, `--batch`, stdin (`-`)
   - `pynmms repl` — interactive session with tell/ask/show/save/load
   - `cli/exitcodes.py` — `EXIT_SUCCESS=0`, `EXIT_ERROR=1`, `EXIT_NOT_DERIVABLE=2`
   - `cli/output.py` — JSON response builders for structured output

### Ontology Extension (`src/pynmms/onto/`)

The `pynmms.onto` subpackage extends propositional NMMS with ontology axiom schemas — schema-level macros for material inferential commitments and incompatibilities. Instead of adding proof rules, it enriches the material base with seven unanchored axiom schema types that are evaluated lazily at query time.

1. **`onto/syntax.py`** — `OntoSentence` frozen dataclass (types: `ATOM_CONCEPT`, `ATOM_ROLE`). `parse_onto_sentence()` tries binary connectives first, then ontology patterns (role assertions, concept assertions). Bare propositional atoms are rejected.

2. **`onto/base.py`** — `OntoMaterialBase(MaterialBase)` adds vocabulary tracking (`_individuals`, `_concepts`, `_roles`) and seven ontology schema types:
   - **subClassOf(C, D)**: `{C(x)} |~ {D(x)}` for any individual x
   - **range(R, C)**: `{R(x,y)} |~ {C(y)}` for any x, y
   - **domain(R, C)**: `{R(x,y)} |~ {C(x)}` for any x, y
   - **subPropertyOf(R, S)**: `{R(x,y)} |~ {S(x,y)}` for any x, y
   - **disjointWith(C, D)**: `{C(x), D(x)} |~` for any individual x (material incompatibility)
   - **disjointProperties(R, S)**: `{R(x,y), S(x,y)} |~` for any x, y (material incompatibility)
   - **jointCommitment([C1,...,Cn], D)**: `{C1(x),...,Cn(x)} |~ {D(x)}` for any x (joint inferential commitment, min 2 antecedents)
   All use exact match (no weakening). `CommitmentStore` provides a higher-level API.

   **No separate reasoner** — the base `NMMSReasoner` works transparently with `OntoMaterialBase` because ontology schemas extend `is_axiom()`, not the proof rules.

### Key design properties preserved by the calculus:
- **MOF**: Nonmonotonicity — adding premises can defeat inferences (no [Weakening])
- **SCL**: Supraclassicality — all classically valid sequents derivable
- **DDT**: Deduction-detachment theorem (the DD condition above)
- **DS**: Disjunction simplification — the Ketonen third-sequent pattern for [L∨]
- **LC**: Left conjunction is multiplicative (Γ, A ∧ B ⇒ Δ requires Γ, A, B ⇒ Δ, not just Γ, A ⇒ Δ)

## Test Suite

512 tests across 20 test files:

**Propositional core (307 tests, 13 files):**
- `test_syntax.py` — parser unit tests
- `test_base.py` — MaterialBase construction, validation, axiom checks, serialization
- `test_reasoner_axioms.py` — axiom-level derivability (Demo 1 equivalence)
- `test_reasoner_rules.py` — individual rule correctness
- `test_reasoner_properties.py` — nontransitivity, nonmonotonicity, supraclassicality, DD/II/AA/SS
- `test_reasoner_properties_random_bases.py` — Hypothesis property-based tests against random bases
- `test_reasoner_soundness.py` — containment-leak soundness audit (Demo 9 equivalence)
- `test_chapter3_examples.py` — every worked example from Ch. 3
- `test_cross_validation_role.py` — cross-validation against ROLE.jl ground truth
- `test_cli.py` — CLI integration tests
- `test_cli_json.py` — JSON output, quiet mode, stdin, batch, exit codes, empty sides, annotations, Toy Base T integration
- `test_logging.py` — proof trace and logging output

**Ontology extension (205 tests, 7 files):**
- `test_onto_syntax.py` — ontology sentence parsing (concept/role assertions), atomicity checks
- `test_onto_base.py` — OntoMaterialBase construction, validation, ontology schemas, CommitmentStore
- `test_onto_schemas.py` — all 7 ontology schema types, nonmonotonicity, non-transitivity, lazy evaluation, NMMSReasoner integration
- `test_onto_cli.py` — `--onto` flag with tell/ask/repl
- `test_onto_cli_json.py` — ontology-specific tests for JSON output, exit codes, batch, annotations
- `test_onto_legacy_equivalence.py` — propositional backward compat, medical concept/role, ontology schema equivalence
- `test_onto_logging.py` — ontology schema registration logging, proof traces

## Logging

All modules use `logging.getLogger(__name__)` at DEBUG level. The `NMMSReasoner` produces proof traces both in `ProofResult.trace` and via the logging system for post-experimental run analysis and reporting.
