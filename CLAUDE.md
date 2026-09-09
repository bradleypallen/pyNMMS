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

# Lint, typecheck, test (Makefile targets); CI (.github/workflows/ci.yml) runs the same on
# Python 3.12 and 3.13 with the dev and rdf extras, then builds the package
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

The core uses the Python 3.10+ standard library only (no runtime dependencies). The `rdf` extra adds rdflib and owlrl, the `oxigraph` extra adds pyoxigraph (`pip install -e ".[dev,rdf,oxigraph]"`). Dev dependencies: pytest, pytest-cov, hypothesis, ruff, mypy, rdflib-endpoint, uvicorn, pyshacl.

## Theoretical Foundation

### Citing the RDF semantics manuscript

`pynmms.rdf` implements Allen, *Implication-Space Semantics for RDF* (unpublished manuscript; cite no venue). Refer to its results **by LaTeX label, never by number**, in docs, docstrings, and commit messages: `def:triplebearers`, `def:entailmentregime`, `def:roles`, `def:contententailment`, `prop:positional`, `def:graphcontents`, `lem:shapes`, `def:fitness`, `def:inducedframe`, `thm:recovery`, `lem:witness`, `lem:skolem`, `rem:skolem`, `lem:uniform`, `lem:witnesschar`, `prop:incoherence`, `thm:closure`, `cor:simple`, `cor:rdfs`, `cor:owlrl`. The numbering differs between renderings and will change again. When a human reader needs a handle, pair label and name: "Theorem \ref{thm:closure} (Closure regimes)". Numbered references to Hlobil & Brandom 2025 Chapter 3 (Definition 1, Fact 2, Theorem 7, ...) are the book's and stay as they are.


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

   **`robustness.py`** — `Robustness(kind, left, right, exclusions)` with `EXACT`, `MONOTONE`, `guarded(left, right, exclusions)`; `left`/`right` are singleton defeaters, `exclusions` are conjunctive pairs ⟨x, y⟩ (defeat when x ⊆ Γ and y ⊆ Δ; singleton pairs fold into `left`/`right`); `allows()` implements the guard in O(defeaters); `split_robustness_clause()` parses the trailing `unless X & Y, Z` / `monotone` clause used by tell statements and schema lines. JSON: `unless.pairs`.

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

Implements Allen, "Implication-Space Semantics for RDF" (unpublished manuscript). Requires rdflib; owlrl is used only as a test oracle.

- **`rdf/atoms.py`** — `TripleAtom(s, p, o)`: a `str` subclass whose value is the canonical quoted-atom name `<s p o>` (full IRIs, escaped literals, no `<`/`>` inside) carrying the three rdflib terms. `Resolver` expands `prefix:local` and `a`; unprefixed names must be absolute IRIs. Because it is a `str`, a triple flows through the string-typed core unchanged. `PatternAtom` is a succedent graph pattern `<{ t1 . t2 }>` whose blank nodes are existential (`lem:witnesschar` witness search); `skolemize_triple` replaces blank nodes by Skolem IRIs for antecedent position.
- **`rdf/view.py`** — `GraphView(backend, added, removed)`: Γ as a reference to the stored graph plus small diffs; implements the `AtomSetLike` protocol of `sequent.py`. Hash/equality use backend identity, generation, and the diffs only. Proof rules never remove atoms, so `removed` stays empty in practice.
- **`rdf/rules.py`** — `Var`, `Rule` (range-restricted Horn schema, conclusion `None` = ⊥, optional `guard` side condition), `Regime(name, rules, axioms)`, `parse_rule("?x a ex:A, ?x a ex:B -> false")`, shipped `SIMPLE`, `RDFS` (rdf1, rdfs1, rdfD1, rdfs2–13, finite axiomatic triples), and `OWL2RL` (RDFS plus the fixed-arity OWL 2 RL/RDF rules of Tables 4–9 plus the list-valued families as `ProceduralRule`s in `OWL2RL_LIST_RULES`: cls-int1/2, cls-uni, cls-oo, cax-adc, prp-spo2, prp-key, prp-adp, eq-diff2/3, scm-int, scm-uni; datatype and axiomatic-only rules omitted, listed in `OWL2RL_OMITTED`), `custom(..., extends=)`. A `ProceduralRule(name, triggers, fire)` is fired by the closure engine on triples whose predicate is in `triggers` (`None` = any) and walks lists via `rdf_list(head, lookup)`.
- **`rdf/values.py`** — guards over values: `parse_guard(text)` gives a `Guard` with `evaluate(bindings)` (Python) and `to_sparql()` (a `FILTER`), following SPARQL's kinds (typed numbers/dates by value, plain strings as strings, cross-kind comparisons false); functions `num`, `year` (first four characters, as `xsd:integer(SUBSTR(...))`), `str`, `lang`, `datatype`, `rank` over `declare_ordering`/`ordering name: a < b` lines, `isLiteral/isIRI/isBlank`. A rule carries it as `[...]` among its premises (`Rule.guard_expr`; `guard` becomes its evaluation); `parse_rules_text` reads a rules file with orderings; `sparql_rules.translatable` accepts guarded rules whose guard translates.
- **`rdf/closure.py`** — `ClosureEngine.close()` (full closure) and `.extend(extras, store_lookup, store_contains, store_join=None)` (semi-naive: fires only rules with a premise matching a new triple, joins the rest against the store). With `store_join`, each pattern-rule firing splits the remaining premises into in-process (`new`) and store positions, tries every subset, and hands the store positions to `backend.join()` as one query; `new` and the store are disjoint so nothing is derived twice. Cost ∝ extras, not |G|. `join_patterns` / `match_patterns` are the BGP join and witness search. `_TripleIndex` (used for `close()` and the per-node `new` set) has single and composite `(s,p)`/`(p,o)` indexes and picks the most selective; without the composite ones, premises with only the object bound (e.g. `?x owl:hasValue C`) scanned every triple with that object and made the class-restriction rules quadratic (found 2026-09-06 when OWL 2 RL closure of 3k triples took 17 s; now 3 s).
- **`rdf/base.py`** — `RDFBase(MaterialBase)`: intensional lexicon, explicit entries with robustness over `TripleAtom`s, `sequent(antecedent, consequent, include_graph=True)` builds `G, Γ ⇒ Δ` with a `GraphView`; `position(accept=[graphs], reject=[graphs])` builds the sequent for a position ⟨𝔊, 𝔇⟩ (`def:contententailment` / `prop:positional`): accepted graphs unioned and Skolemized per graph into Γ, each rejected ground graph a conjunction sentence in Δ (`lem:shapes` via `R∧`), rejected graphs with blank nodes as pattern atoms, none rejected = incoherence; atoms are canonicalised with polarity tracking so blank nodes are Skolemized exactly in antecedent position (left of `->` and under `~` flip polarity) and pattern atoms are rejected there. `RegimeBase`: the regime-relative material base B_{R,I}; `is_axiom` = (i) Γ R-inconsistent, (ii) Δ ∩ cl_R(Γ) ≠ ∅, (iii) a material entry read through the regime (antecedent derivable, no defeater derivable, consequent elaborated; `elaborate_consequent`), with cl_R(G) from the backend and the extras closed in-process (cached per extras set); pattern atoms in Δ are matched against closure ∪ extras. **Attribution** (`attribution = "position"`, default): a ⊥ or a material incompatibility counts only if the position's own added/derived triples take part; the store's contradictions are `background_inconsistent()`; `attribution = "global"` is the explosive B_R of `def:fitness`. `sequent(..., include_graph="background")` makes Γ the antecedent alone with the store as background (a `GraphView(background=True)`), for checking one record's coherence. Empty-consequent entries: exact yields Γ |~ ∅ only, monotone/guarded explode. `is_inconsistent(extras)` is `prop:incoherence` for the position.
- **`rdf/defeasible.py`** — material entries as patterns (workstream D): `DefeasibleRule(premises, conclusion|None, defeaters, robustness, guard_expr)` parsed from `A |~ D unless E1 ; E2 | monotone` with variables and `[guard]`s; `Matcher` unifies a Δ atom with a conclusion and joins the premises against the closure (store minus set-aside atoms plus the extras closure), checks defeaters for solutions, and anchors incompatibilities and elaborated conclusions on the position's own triples (attribution). `RegimeBase.add_rule`/`pattern_rules`; `_pattern_check` runs after ground entries; `Position.challenges()` probes from them; harness entry files accept pattern lines. `bench/defeasible_go.py`: GO's propagation as pattern entries defeated by `NOT`.
- **`rdf/dialogue.py`** — the Elenchus loop (step 6): `Dialogue(base, holder, positum, opponent)` holds `⟨[C : D], T, I⟩` (a `Position`, open `Tension`s as sequents over the holder's own atoms with source and rescue, accepted and contested tensions, `Proposal`s from contestation, a `Turn` transcript); moves `commit`/`deny`/`withdraw` (positum protected), `accept(id, retract=|refine=)` (an external tension joins the base as an exact entry), `contest(id, exception=)` (adds the exception as a defeater of the responsible ground or pattern entry), `propose_tension`; `ComputedOpponent` derives tensions from the base (denials entailed, incoherence with participants found by string match and single-atom withdrawal) and probes from `challenges()`; `status()` coherent/tensions open/aporia; `save`/`load` JSON; `play(script)` scripted respondent with predictions (questions `status?`, `tensions?`, `probes?`, `commits? <atoms>`, `precludes? <atoms>`). `bench/elenchus_session.py` runs a session file over a store.
- **`rdf/provenance.py`** — provenance as entitlement: `Ground(kind, source, evidence, reference, via)` with kinds asserted/defended/inherited/derived (`entitled` = defended or inherited); `RecordPattern(subject, predicate, object, evidence, reference)` says how annotation records carry a triple's evidence (`RegimeBase.provenance`); `provenance_of(base, triple)` reads the source graph (`backend.graphs_of`) and the record; `holder_graph`/`attribution_triple` for `commit` (holder's named graph + `prov:wasAttributedTo`). Backends: `OxigraphBackend.load_graph(g, source=)`, `add(triples, source=)`, `graphs_of(t)`; `MemoryBackend.graphs_of` is empty.
- **`rdf/position.py`** — `Position(base, holder)`: a holder's commitments as speech acts over the store as background (`assert_`, `deny`, `withdraw`, `commit`; `coherent()`, `commits_to()`, `precludes()` returning a `Verdict` with `reason` and `rescue` from `RegimeBase.last_reason`/`last_rescue`; an ordered `log` of `Move`s; `propose()` → `Report` (coherent verdict, challenges, commitments incl. derived, precluded atoms, defaults, rescue, score, trace, ms; `summary()`), the curation loop's step before `commit`; entitlement: `grounds(derived=)`, `defend()` → `Round(stood, refutations, open)` marking asserted commitments defended when no probe refutes, `score()`; `Position.of(..., source=graph)` reads one named graph's account; `commit()` with a holder writes to the holder's graph with PROV attribution; `challenges()` generates an opponent's probes as `Challenge(kind, asks, source, rescue)`: refutations, incompatibilities and ⊥ rules the position's own triples partly satisfy (asking for the rest, a pattern when variables stay free), and unacknowledged defaults; background-only antecedents yield no probe). A position speaks for the subjects it asserts about: their stored triples are set aside (`sequent(..., include_graph="background", aside=...)`, a `GraphView` with `removed` = the record) so one asserted date is coherent while the record read aloud with two (`Position.of(base, subject)`, following Skolem children) is not. The REPL is the first client; `bench/replay_dialogue.py` replays a scripted dialogue with predictions.
- **`rdf/backends/`** — `GraphBackend` protocol (`contains`, `triples`, `closure_contains`, `closure_triples`, `is_inconsistent`, `generation`, `resolver`); `MemoryBackend` (rdflib Graph, Skolemizes blank nodes on load, materialises the regime closure into a second graph, `add()` extends it incrementally); `SPARQLBackend(url, regime, probe, update_endpoint, prefixes)` (rdflib SPARQLStore over the default graph; closure = whatever the endpoint materialises; optional probe; `join()` = one `SELECT` per rule firing; `add()` = chunked `INSERT DATA` (`BULK_CHUNK` = 500) with one generation bump per call; `size()`, `contains()` and `join()` results are memoised per generation (`memo_limit`), since proof search repeats them and `intersects()` compares lengths first (a `COUNT(*)` per axiom check without the memo); logs round trips and latency; tested live in `tests/test_rdf_sparql.py` against an in-process rdflib-endpoint server, skipped if `rdflib-endpoint`/`uvicorn` are absent); `OxigraphBackend(path, regime, prefixes, materialize)` (embedded pyoxigraph store, in memory or on disk; asserted graph in `<urn:pynmms:asserted>`, `cl_R(G)` in the default graph; the closure is computed **in the store**: `sparql_rules.partition()` turns each guard-free pattern rule into `INSERT { c } WHERE { A FILTER NOT EXISTS { c } }` and ⊥ rules into `ASK`, run to a fixpoint, with guarded and procedural rules evaluated in process between rounds; `rdfs1`/`rdfD1` skipped (literal-subject conclusions are unstorable); `add()` extends via `ClosureEngine.extend` with the store as join partner; a `<urn:pynmms:meta>` graph records the regime so reopening a path skips materialisation; `load()` uses Oxigraph's parser, Skolemizes, and binds Turtle `@prefix` lines; `close()` releases the on-disk lock; an on-disk store materialises in a temporary in-memory store and bulk-loads the result (about 600 bytes of memory per closure triple) below `IN_MEMORY_LIMIT` = 2M asserted triples, and by rule updates directly on disk above it (RocksDB-write-bound, no memory cost); `in_memory=` overrides; 3 to 4x faster than the in-process closure, instant reopen).
- **`rdf/convert.py`** — `onto_to_graph(base)` (ABox + schema triples), `onto_to_rules(base)` (jointCommitment rules), `onto_to_defeasible(base, exact=)` (every schema with its policy as a `DefeasibleRule`; guarded defeater concepts as pattern defeaters on the matched individuals; exact schemas compiled as monotone or skipped), `install_onto(target, base)` (rules plus ground consequences with translated defeaters), `consequences_to_triples(base)`, `atom_to_triple`.
- **`rdf/entries.py`** — `load_entries(path_or_text, base)`: tell-syntax entry files, ground and pattern lines and `ordering name: a < b` lines for `rank` guards; used by the harness and the CLI `--entries` flag. Premises of a pattern entry are split by `defeasible._split_premises`, which ignores commas and `<` inside `[guards]` (a guard may contain `<=`).
- **`cli/rdf.py`** — `pynmms rdf ask` (`--entries FILE` and `--onto FILE`, repeatable, on ask/position/repl, load material entries and ontology-extension bases as pattern entries; `-g` repeatable or `--store`, or `--oxigraph DIR` to open/create a persistent Oxigraph store into which `-g` files are loaded once; `tell --oxigraph DIR --regime ...` extends the store's closure incrementally; `--regime simple|rdfs|owl2rl`, `--rules`, `--prefix PFX=IRI` repeatable, `--trace`, `--json`, `-q`, `--batch`, `--max-depth`), `pynmms rdf tell -g file [--prefix ...] "<s p o>, ..."` (rewrites the file in its format), `pynmms rdf repl -g file` (ask/tell/load/save/show/trace), `pynmms rdf position -g file --accept a.ttl --reject r.ttl` (exit 0 = out of bounds, 2 = in bounds). Unbound short prefixes (`ex:x` with no `ex` binding) are errors, not IRIs; only known URI schemes (`http`, `urn`, ...) or tokens containing `/` pass as absolute IRIs.
- Not yet: datatype rules, store-side closure push-down and native RDFox/GraphDB adapters (Phase 5; need a store to develop against).

### Key design properties preserved by the calculus:
- **MOF**: Nonmonotonicity — adding premises can defeat inferences (no [Weakening])
- **SCL**: Supraclassicality — all classically valid sequents derivable
- **DDT**: Deduction-detachment theorem (the DD condition above)
- **DS**: Disjunction simplification — the Ketonen third-sequent pattern for [L∨]
- **LC**: Left conjunction is multiplicative (Γ, A ∧ B ⇒ Δ requires Γ, A, B ⇒ Δ, not just Γ, A ⇒ Δ)

## Test Suite

808 tests across 38 test files:

**Propositional core (392 tests, 15 files):**
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
- `test_differential_v062.py` — Hypothesis differential test of the current reasoner and bases against a frozen v0.6.2 copy in `tests/legacy_v062/` (propositional, and ontology with EXACT schemas); the strongest check on the Phase 1/2 rewrite
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

**RDF extension (191 tests, 16 files):**
- `test_rdf.py` — TripleAtom/PatternAtom, GraphView, ClosureEngine, RegimeBase (RDFS and OWL 2 RL incl. list rules), Skolemization, owlrl oracles (`thm:closure`), converters, `pynmms rdf ask/tell/repl` CLI; skipped entirely if rdflib is absent
- `test_rdf_sparql.py` — SPARQLBackend against an in-process rdflib-endpoint server (membership, probe, extras closure, batched `join()` round-trip count, chunked `add()` via UPDATE); skipped if `rdflib-endpoint`/`uvicorn` are absent
- `test_rdf_extras_oracle.py` — Hypothesis oracle: `cl_R(G) ∪ extend(G, extras) == close(G ∪ extras)` (same ⊥ verdict) under RDFS and OWL 2 RL with an incompatibility rule and list constructs, batched and per-lookup; the check that the semi-naive extras step is right
- `test_rdf_material.py` — the regime-relative material base B_{R,I}: material entries read through the regime (antecedent derivable, no defeater derivable, consequent elaborated; `elaborate_consequent` flag), no material chaining, empty-I regression against `ClosureEngine.close` and owlrl, Containment, incompatibility entries (empty consequent) making Γ incoherent through the regime, attribution of incoherence to the position (store contradictions as inventory), positions over the store as background, exact incompatibilities only at Δ = ∅; runs over MemoryBackend and OxigraphBackend
- `test_rdf_oxigraph.py` — OxigraphBackend: rule translation (`sparql_rules.partition`), term round trips, closure in the store equal to MemoryBackend's on random RDFS and OWL 2 RL graphs (lists included), owlrl oracle, ⊥ rules, incremental `add()`, `join()`, on-disk reopen skips materialisation, Skolemization and prefix capture on `load()`, bounded round trips, `--oxigraph` CLI; skipped if pyoxigraph is absent
- `test_compare_rdfs.py` — the F0 harness on a small on-disk store: atomic and pattern rows agree with the closure, logical rows are marked not expressible, material rows differ only with entries, an unmaterialised store is refused, a record is written; skipped if pyoxigraph is absent
- `test_rdf_position.py` — the position API, predictions first (challenges: a ⊥ rule partly matched, an incompatibility partly satisfied with its rescue, an unacknowledged default, a set-aside record fact asked for, refutations first, a pattern probe), background licenses stored facts, assert/commits_to/precludes through the regime, deny as rejected graphs, verdicts naming the entry and the rescuing defeater, a position speaking for its subjects (the chalice: one date coherent, the record read aloud not), `Position.of` following Skolem children, withdraw and commit
- `test_replay_dialogue.py` — the dialogue replay script on a small store with predictions
- `test_rdf_values.py` — guards: SPARQL kinds, `year`, `lang`/`datatype`/`in`, `rank`, translation forms, rule parsing with guards, orderings in rules text, in-process and store closures agreeing on an anachronism rule, a guarded ⊥ rule
- `test_rdf_defeasible.py` — pattern entries, predictions first: parsing (alternatives, monotone, ⊥, guards, defeater variables), firing on derived antecedents and defeat through the regime, elaboration and no chaining, a value-guarded defeater, an incompatibility pattern attributed to the position, GO-style propagation defeated by a curated NOT, probes from pattern entries
- `test_onto_surface.py` — the ontology extension as surface syntax: every schema type to one pattern entry, exclusions as conjunctions, `install_onto` with translated ground defeaters, a differential test against NMMS_Onto's matcher on random bases (agreement up to the licensed explosion difference), the `--onto`/`--entries` CLI flags
- `test_rdf_entitlement.py` — provenance as entitlement, predictions first: asserted → defended → refuted standings and score, derived grounds from defaults, sources from named graphs (two catalogues as two positions, jointly incoherent, each standing alone), commit into the holder's graph with attribution, a record pattern giving evidence and reference and an evidence-keyed defeater
- `test_curation.py` — `Position.propose()` reports (coherent and incoherent, rescue, precluded, defaults, score, trace, nothing written) and the SHACL/SPARQL/NMMS harness on a small store agreeing, rescuing, and accepting a fix; skipped without pyshacl
- `test_rdf_dialogue.py` — the Elenchus loop, predictions first: a commitment completing an incompatibility raises a tension with the right participants, accept by retraction and by refinement of a denial, contest with an exception revising the base, an external tension accepted entering the base, positum protection and aporia, JSON round trip, a scripted respondent
- `test_pulmonary.py` — the pulmonary base from the CPE/ARDS placeholder benchmark and its vignette sessions, predictions first: the builder's entries (ladder defeaters, rank-guarded monotonicity ladders, contested overrides, insufficient bad verdicts as no entry, orderings loaded), the check of the base against its own verdicts (33/35 placeholder, 35/35 model panel), and the four vignettes' predictions holding on both bases
- `test_gaf_to_nt.py` — the GAF converter: relations, `NOT` qualifiers, labels, evidence records, the `--no-records` count, and that the propagation rules parse one per relation

## Benchmarks

`bench/` is a stdlib-only benchmark package (`python -m bench`, `make bench`). `python -m bench.compare_rdfs --store DIR --queries FILE [--entries FILE]` is the Phase 6 F0 harness: NMMS proof search against classical RDFS entailment (one SPARQL `ASK` on the closure, `thm:closure`) over one persisted Oxigraph store, grouped atomic / pattern / logical / material, with agreement, cold and warm latency, nodes, and round trips; query and entry files under `bench/queries/`; `python -m bench.curation_loop --store DIR --entries FILE --shapes FILE --target-class IRI [--fix ...]` runs the same records through pySHACL (record neighbourhood, SHACL-SPARQL shapes), the shapes' SPARQL natively, and NMMS `propose`, predicting agreement and measuring rescue, defaults, and a hypothetical fix (`bench/queries/am_shapes.ttl`, `am_curation_entries.txt`); a `position:` tag runs a query as a position over the store as background, and a trailing `## r,n,i` prediction is checked against the observed verdicts (write predictions before running). `python -m bench.gaf_to_nt GAF OUT.nt --rules RULES` converts a GO annotation file to N-Triples (gene product related to class by its qualifier, `NOT` as `go:not_<qualifier>`, per-annotation evidence records) and writes the annotation-propagation rules; `bench/queries/go_*.txt` are the F0 files for GO plus the human GAF; `bench/queries/am_*.txt` for the Amsterdam Museum graph (thesaurus propagation rules, attribution-by-default entries defeated by `creatorQualifier`, a posthumous-making incompatibility). `bench/pulmonary/` is the CPE/ARDS placeholder benchmark as a base: `build_base.py` writes `pulmonary_<source>.txt` (pattern entries with orderings, defeaters from the ladders, rank guards over the tiers, overrides for contested items) from `benchmark_v0.5.json` and the panel verdicts, and `session.py` plays the vignettes under `vignettes/` (Elenchus scripts with predictions, `## placeholder=x models=y` when the bases differ) over an in-memory store and, with `--check`, replays the items against the base. Not for clinical use. Sections: `antecedent_scaling` (query cost vs |Γ|), `schema_scaling` (axiom-check cost vs number of ontology schemas), `query_complexity` (proof cost vs connectives in the query). Every run writes a JSON record with timestamp, git SHA, and environment to `bench/results/`; those records are the regression baseline and are committed. Reasoner DEBUG logging is silenced during timing runs.

## Logging

All modules use `logging.getLogger(__name__)` at DEBUG level. The `NMMSReasoner` produces proof traces both in `ProofResult.trace` and via the logging system for post-experimental run analysis and reporting.
