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

# Lint, typecheck, test (Makefile targets)
make check

# Benchmarks (write a JSON record to bench/results/; --quick for reduced sizes)
make bench
python -m bench --quick --only antecedent_scaling --no-write

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

# RDF (requires the rdf extra): the graph is the antecedent
pynmms rdf ask -g graph.ttl --regime rdfs "<ex:tweety a ex:Thing>"
pynmms rdf ask -g graph.ttl --regime rdfs --rules rules.txt "<ex:x a ex:Alive> => ~<ex:x a ex:Dead>"
pynmms rdf ask --store http://localhost:7200/repositories/x --regime rdfs "..."
```

The core uses the Python 3.10+ standard library only (no runtime dependencies). The `rdf` extra adds rdflib and owlrl (`pip install -e ".[dev,rdf]"`). Dev dependencies: pytest, pytest-cov, hypothesis, ruff, mypy.

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

1. **`syntax.py`** — Recursive descent parser for propositional sentences: atoms, negation (~), conjunction (&), disjunction (|), implication (->). Returns frozen `Sentence` dataclass AST nodes. Operator precedence: `&` > `|` > `->`. Atoms follow a strict grammar: an identifier, an identifier applied to comma-separated identifiers (`C(a)`, `R(a,b)`), or a *quoted atom* `<...>` whose content is verbatim (brackets included in the name). Anything else in atom position raises `ValueError`. Exports depth-aware lexical helpers `find_top_level`, `split_top_level`, `is_fully_wrapped` that skip parentheses and quoted atoms; the onto parser and the CLI sequent splitters use them.

2. **`base.py`** — `MaterialBase` class implementing the material base B = <L_B, |~_B>. Stores atomic language, consequence relation, optional atom annotations, and a per-consequence robustness policy. EXACT entries are matched from a `(|Γ|,|Δ|)` size index; MONOTONE/GUARDED entries from a consequent-atom index with subset matching and a defeater guard. Atom names are canonicalised (whitespace inside `R(a, b)` removed). JSON serialization via `to_file()`/`from_file()`; every consequence is written with an explicit `robustness` field.

   **`robustness.py`** — `Robustness(kind, left, right)` with `EXACT`, `MONOTONE`, `guarded(left, right)`; `allows()` implements the guard; `split_robustness_clause()` parses the trailing `unless X, Y` / `monotone` clause used by tell statements and schema lines.

3. **`sequent.py`** — Proof-search data structures. `AtomSet` is a persistent set of atom names (shared base `frozenset` plus small added/removed diffs) with structural hash/equality, so derived proof nodes cost O(|diff|) rather than O(|Γ|). `Sequent` is a proof node with each side partitioned into an `AtomSet` and a `frozenset[Sentence]` of complex sentences; strings are parsed once at the API boundary (with a small cache keyed on the input frozenset). `TraceEntry` is a structured trace record formatted only on `str()`.

4. **`reasoner.py`** — `NMMSReasoner` class with backward proof search implementing 8 Ketonen-style propositional rules (L¬, L→, L∧, L∨, R¬, R→, R∧, R∨) over `Sequent` nodes; rules iterate only the complex part of a side and the base's `is_axiom` receives the atom part (any `collections.abc.Set[str]`). Returns `ProofResult` with derivability, `entries`/`trace`, `depth_reached`, `cache_hits`, `nodes`, `connectives`, and `depth_limited`. `max_depth` defaults to `None` (search is complete; depth is bounded by connective count); `persistent_cache=True` keeps the memo across queries and is invalidated by `MaterialBase.generation`.

5. **`cli/`** — Tell/Ask CLI with REPL mode (`--onto` flag enables ontology mode):
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
   Every schema is a `SchemaEntry(type, arg1, arg2, annotation, robustness)`. Schemas are indexed by consequent concept/role (or concept pair for incompatibilities), so hits and misses are O(candidates) regardless of schema count. EXACT schemas (default) match only the generated instance; GUARDED schemas take defeater *concept names*, instantiated on the individuals of the matched consequent. `CommitmentStore` provides a higher-level API. `cli/schema_line.py` parses and registers `schema ...` lines for both `tell` and the REPL.

   **No separate reasoner** — the base `NMMSReasoner` works transparently with `OntoMaterialBase` because ontology schemas extend `is_axiom()`, not the proof rules.

### RDF Extension (`src/pynmms/rdf/`, optional extra)

Implements Allen, "Implication-Space Semantics for RDF" (TGDK). Requires rdflib; owlrl is used only as a test oracle.

- **`rdf/atoms.py`** — `TripleAtom(s, p, o)`: a `str` subclass whose value is the canonical quoted-atom name `<s p o>` (full IRIs, escaped literals, no `<`/`>` inside) carrying the three rdflib terms. `Resolver` expands `prefix:local` and `a`; unprefixed names must be absolute IRIs. Because it is a `str`, a triple flows through the string-typed core unchanged. `PatternAtom` is a succedent graph pattern `<{ t1 . t2 }>` whose blank nodes are existential (Lemma 33 witness search); `skolemize_triple` replaces blank nodes by Skolem IRIs for antecedent position.
- **`rdf/view.py`** — `GraphView(backend, added, removed)`: Γ as a reference to the stored graph plus small diffs; implements the `AtomSetLike` protocol of `sequent.py`. Hash/equality use backend identity, generation, and the diffs only. Proof rules never remove atoms, so `removed` stays empty in practice.
- **`rdf/rules.py`** — `Var`, `Rule` (range-restricted Horn schema, conclusion `None` = ⊥, optional `guard` side condition), `Regime(name, rules, axioms)`, `parse_rule("?x a ex:A, ?x a ex:B -> false")`, shipped `SIMPLE`, `RDFS` (rdf1, rdfs1, rdfs2–13, finite axiomatic triples), and `OWL2RL` (RDFS plus the fixed-arity OWL 2 RL/RDF rules of Tables 4–9; list-valued rule families and datatype rules omitted, listed in `OWL2RL_OMITTED`), `custom(..., extends=)`.
- **`rdf/closure.py`** — `ClosureEngine.close()` (full closure) and `.extend(extras, store_lookup, store_contains)` (semi-naive: fires only rules with a premise matching a new triple, joins the rest against the store). Cost ∝ extras, not |G|. `match_patterns(patterns, lookup)` is the BGP witness search used for pattern atoms.
- **`rdf/base.py`** — `RDFBase(MaterialBase)`: intensional lexicon, explicit entries with robustness over `TripleAtom`s, `sequent(antecedent, consequent, include_graph=True)` builds `G, Γ ⇒ Δ` with a `GraphView`; atoms are canonicalised with polarity tracking so blank nodes are Skolemized exactly in antecedent position (left of `->` and under `~` flip polarity) and pattern atoms are rejected there. `RegimeBase`: `is_axiom` = Containment or explicit entry or (Γ R-inconsistent or Δ ∩ cl_R(Γ) ≠ ∅), with cl_R(G) from the backend and the extras closed in-process (cached per extras set); pattern atoms in Δ are matched against closure ∪ extras. `is_inconsistent(extras)` is Proposition 34.
- **`rdf/backends/`** — `GraphBackend` protocol (`contains`, `triples`, `closure_contains`, `closure_triples`, `is_inconsistent`, `generation`, `resolver`); `MemoryBackend` (rdflib Graph, Skolemizes blank nodes on load, materialises the regime closure into a second graph, `add()` extends it incrementally); `SPARQLBackend` (rdflib SPARQLStore; closure = whatever the endpoint materialises; optional probe; logs round trips and latency; untested against a live endpoint); `OxigraphBackend` (MemoryBackend over an `oxrdflib` store; needs the package).
- **`rdf/convert.py`** — `onto_to_graph(base)` (ABox + schema triples, with notes on policies RDF cannot express), `onto_to_rules(base)` (jointCommitment rules), `consequences_to_triples(base)`, `atom_to_triple`.
- **`cli/rdf.py`** — `pynmms rdf ask` (`-g` repeatable or `--store`, `--regime simple|rdfs|owl2rl`, `--rules`, `--trace`, `--json`, `-q`, `--batch`, `--max-depth`), `pynmms rdf tell -g file "<s p o>, ..."` (rewrites the file in its format), `pynmms rdf repl -g file` (ask/tell/load/save/show/trace).
- Not yet: list-valued OWL 2 RL rules, datatype rules, a live-endpoint test for `SPARQLBackend`, store-side closure push-down (Phase 5).

### Key design properties preserved by the calculus:
- **MOF**: Nonmonotonicity — adding premises can defeat inferences (no [Weakening])
- **SCL**: Supraclassicality — all classically valid sequents derivable
- **DDT**: Deduction-detachment theorem (the DD condition above)
- **DS**: Disjunction simplification — the Ketonen third-sequent pattern for [L∨]
- **LC**: Left conjunction is multiplicative (Γ, A ∧ B ⇒ Δ requires Γ, A, B ⇒ Δ, not just Γ, A ⇒ Δ)

## Test Suite

647 tests across 22 test files:

**Propositional core (381 tests, 14 files):**
- `test_syntax.py` — parser unit tests, strict atom grammar, quoted atoms, split helpers
- `test_sequent.py` — AtomSet persistence/normalisation, Sequent partitioning, TraceEntry formatting
- `test_robustness.py` — Robustness policies, clause parsing, robust entries in MaterialBase
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
- `test_logging.py` — proof trace and logging output, completeness flags, persistent cache

**Ontology extension (225 tests, 7 files):**
- `test_onto_syntax.py` — ontology sentence parsing (concept/role assertions), atomicity checks
- `test_onto_base.py` — OntoMaterialBase construction, validation, ontology schemas, CommitmentStore
- `test_onto_schemas.py` — all 7 ontology schema types, nonmonotonicity, non-transitivity, lazy evaluation, NMMSReasoner integration, robustness policies per schema type, schema index
- `test_onto_cli.py` — `--onto` flag with tell/ask/repl
- `test_onto_cli_json.py` — ontology-specific tests for JSON output, exit codes, batch, annotations
- `test_onto_legacy_equivalence.py` — propositional backward compat, medical concept/role, ontology schema equivalence
- `test_onto_logging.py` — ontology schema registration logging, proof traces

**RDF extension (41 tests, 1 file):**
- `test_rdf.py` — TripleAtom/PatternAtom, GraphView, ClosureEngine, RegimeBase (RDFS and OWL 2 RL), Skolemization, owlrl oracles (Theorem 35), converters, `pynmms rdf ask/tell/repl` CLI; skipped entirely if rdflib is absent

## Benchmarks

`bench/` is a stdlib-only benchmark package (`python -m bench`, `make bench`). Sections: `antecedent_scaling` (query cost vs |Γ|), `schema_scaling` (axiom-check cost vs number of ontology schemas), `query_complexity` (proof cost vs connectives in the query). Every run writes a JSON record with timestamp, git SHA, and environment to `bench/results/`; those records are the regression baseline and are committed. Reasoner DEBUG logging is silenced during timing runs.

## Logging

All modules use `logging.getLogger(__name__)` at DEBUG level. The `NMMSReasoner` produces proof traces both in `ProofResult.trace` and via the logging system for post-experimental run analysis and reporting.
