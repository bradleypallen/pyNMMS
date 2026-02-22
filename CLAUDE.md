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
pynmms ask -b base.json "A => B"
pynmms repl

# CLI with restricted quantifiers
pynmms tell -b rq_base.json --create --rq "atom hasChild(alice,bob)"
pynmms ask -b rq_base.json --rq "ALL hasChild.Doctor(alice), hasChild(alice,bob) => ParentOfDoctor(alice)"
pynmms repl --rq
```

Uses Python 3.10+ standard library only (no runtime dependencies). Dev dependencies: pytest, pytest-cov, ruff, mypy.

## Theoretical Foundation

This implements the NMMS sequent calculus from Hlobil & Brandom 2025 (Ch. 3, "Introducing Logical Vocabulary"). The `pynmms` package implements propositional NMMS in the core and **restricted quantifiers** (`ALL R.C`, `SOME R.C`) in the `pynmms.rq` subpackage.

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

2. **`base.py`** — `MaterialBase` class implementing the material base B = <L_B, |~_B>. Stores atomic language and consequence relation. Exact syntactic match (no weakening). JSON serialization via `to_file()`/`from_file()`.

3. **`reasoner.py`** — `NMMSReasoner` class with backward proof search implementing 8 Ketonen-style propositional rules (L¬, L→, L∧, L∨, R¬, R→, R∧, R∨). Returns `ProofResult` with derivability, trace, depth, and cache stats.

4. **`cli/`** — Tell/Ask CLI with REPL mode (`--rq` flag enables restricted quantifier mode):
   - `pynmms tell` — add atoms/consequences to a JSON base file
   - `pynmms ask` — query derivability with optional trace
   - `pynmms repl` — interactive session with tell/ask/show/save/load

### Restricted Quantifiers (`src/pynmms/rq/`)

The `pynmms.rq` subpackage extends propositional NMMS with ALC-style restricted quantifiers (`ALL R.C`, `SOME R.C`), avoiding the problems Hlobil (2025) identifies with unrestricted ∀/∃ in nonmonotonic settings.

1. **`rq/syntax.py`** — `RQSentence` frozen dataclass (types: `ATOM_CONCEPT`, `ATOM_ROLE`, `ALL_RESTRICT`, `SOME_RESTRICT`). `parse_rq_sentence()` tries binary connectives first, then RQ patterns, then falls through to propositional atoms. Helpers: `find_role_triggers`, `collect_individuals`, `fresh_individual`, `concept_label`, `find_blocking_individual`.

2. **`rq/base.py`** — `RQMaterialBase(MaterialBase)` adds vocabulary tracking (`_individuals`, `_concepts`, `_roles`), inference schemas (lazy evaluation), and Ax3 (exact-match schema axiom). `CommitmentStore` provides a higher-level API for managing assertions and schemas, compiling to an `RQMaterialBase`.

3. **`rq/reasoner.py`** — `NMMSRQReasoner(NMMSReasoner)` overrides `_try_left_rules()` and `_try_right_rules()` to handle both propositional and RQ sentence types in a single pass. Four quantifier rules:
   - **[L∀R.C]**: Adjunction — 1 subgoal with all triggered concept instances (like [L∧])
   - **[L∃R.C]**: Ketonen pattern — all 2^k−1 nonempty subsets of triggered instances (like [L∨])
   - **[R∃R.C]**: Known witnesses + fresh canonical witness with concept-label blocking (experimental)
   - **[R∀R.C]**: Eigenvariable — fresh `_e_{R}_{C}_{a}` for arbitrary role successor (like [R∧])

### Key design properties preserved by the calculus:
- **MOF**: Nonmonotonicity — adding premises can defeat inferences (no [Weakening])
- **SCL**: Supraclassicality — all classically valid sequents derivable
- **DDT**: Deduction-detachment theorem (the DD condition above)
- **DS**: Disjunction simplification — the Ketonen third-sequent pattern for [L∨]
- **LC**: Left conjunction is multiplicative (Γ, A ∧ B ⇒ Δ requires Γ, A, B ⇒ Δ, not just Γ, A ⇒ Δ)

## Test Suite

554 tests across 20 test files:

**Propositional core (273 tests, 12 files):**
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
- `test_logging.py` — proof trace and logging output

**Restricted quantifiers (281 tests, 8 files):**
- `test_rq_syntax.py` — RQ sentence parsing, helpers, atomicity checks
- `test_rq_base.py` — RQMaterialBase construction, validation, schemas, CommitmentStore
- `test_rq_reasoner_rules.py` — individual rule correctness for all 4 quantifier rules + propositional backward compat
- `test_rq_reasoner_properties.py` — MOF, nontransitivity, SCL, DDT, II, AA, SS with quantifiers
- `test_rq_reasoner_soundness.py` — containment-leak probes for all RQ rules
- `test_rq_schemas.py` — concept/inference schemas, lazy evaluation, CommitmentStore integration
- `test_rq_cli.py` — `--rq` flag with tell/ask/repl
- `test_rq_legacy_equivalence.py` — RQ demo scenario equivalence (all 10 original demo scenarios)
- `test_rq_logging.py` — RQ rule names in traces, blocking warnings

## Logging

All modules use `logging.getLogger(__name__)` at DEBUG level. The `NMMSReasoner` and `NMMSRQReasoner` produce proof traces both in `ProofResult.trace` and via the logging system for post-experimental run analysis and reporting. The RQ reasoner logs quantifier rule applications (e.g., `[L∀R.C]`, `[R∃R.C]`) and blocking events with `warnings.warn()` on first use.
