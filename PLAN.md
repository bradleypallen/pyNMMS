# pyNMMS: plan for v0.7 through v0.9

**Inputs.** Allen, "Implication-Space Semantics for RDF" (unpublished manuscript, 2026);
`pynmms-issues.md` (performance and API review against 0.6.1, 2026-08-29);
prototypes `nmms_scaling_bench.py` and `rsrlib.py`.
**Target.** Reason directly over RDF graphs, with rdflib as a component, on
foundations the paper supplies, and with a reasoner that scales to antecedents
of arbitrary size.

---

## 1. What the paper changes about the project

The onto extension was designed before the semantics existed. Four results in
the paper bear directly on the code.

**(a) The atomic bearers are ground triples, not concept/role assertions.**
`def:triplebearers` encodes every triple as one ternary property `T(s, p, o)`. The
onto extension's `C(x)` and `R(x,y)` are the special cases `T(x, rdf:type, C)`
and `T(x, R, y)`. Schema statements such as `subClassOf(C, D)` are themselves
triples `T(C, rdfs:subClassOf, D)` and belong in the *antecedent*, not at a
meta level. The RDF layer should therefore be the general case and the onto
extension a surface syntax over it.

**(b) A regime base is defined by closure, and it is monotone, cut-closed and
explosive.** `def:fitness`: `Γ |~_R Δ` iff Γ is R-inconsistent or
`Δ ∩ cl_R(Γ) ≠ ∅`. `thm:closure` and Corollaries 36 to 38 show this recovers
simple entailment, RDFS entailment and OWL 2 RL exactly, inconsistency
included (`prop:incoherence`). NMMS has no Cut, so chaining cannot be left to the
proof rules: a regime base must compute the closure inside `is_axiom`. The
paper explicitly conjectures (the discussion) that NMMS over `B_R` is a sound and
complete calculus for R-entailment. That is the theorem pyNMMS should
instantiate and test.

**(c) The current exact-match schema semantics "corresponds to no regime."**
The remark after `def:fitness`: a base that takes rule *instances* as its pairs without
closing validates `{(a,type,C), (C,subClassOf,D)} |~ (a,type,D)` but not its
weakening by an unrelated triple, and "its failure of monotonicity is by
omission rather than by defeat." This is issue 9 in the change notes, stated
formally. `def:roles` (range of subjunctive robustness, RSR) supplies the
right replacement: a base entry should carry the set of premise/conclusion
additions under which it survives. The `rsrlib.py` defeater set is the
antecedent-side complement of an RSR.

**(d) Blank nodes are asymmetric.** `lem:skolem` and `rem:skolem`: Skolemization is
sound in the antecedent and unsound in the succedent. `lem:witnesschar` gives the
succedent condition as a witness search: some instance mapping μ with
`μ(H) ⊆ cl_R(G) \ {⊥}`. That is a basic graph pattern match with blank nodes
as variables, which rdflib's SPARQL engine performs natively.

None of this touches the eight proof rules. Every change below lives in the
base (`is_axiom`) or in reasoner engineering. Hlobil's metatheory holds for
any base satisfying Containment, and every base proposed here does.

---

## 2. Issue triage

| # | Issue | Phase | Resolution |
|---|-------|-------|------------|
| 1 | `_try_left_rules` Θ(\|Γ\|²) | 1 | Subsumed by the parsed-sentence refactor; surgical fix first as a stopgap |
| 2 | `_fmt` built eagerly | 1 | Lazy trace: store frozensets, format on access; gate `logger.debug` on `isEnabledFor` |
| 3 | Re-parse Γ at every node | 1 | Reasoner operates on `Sentence` objects; atoms partitioned by type, never parsed |
| 4 | Malformed connectives become atoms | 0 | Strict atom grammar; quoted atom form for IRIs |
| 5 | Incompleteness invisible | 1 | `ProofResult.depth_limited`; document that the cycle guard cannot fire |
| 6 | Linear schema scan | 2 | Per-shape dict index maintained incrementally on `register_*` |
| 7 | Index must cover misses | 2 | No scan fallback; all seven schema types indexed |
| 8 | Cache discarded per query | 1 | Opt-in persistent cache keyed on a base generation counter |
| 9 | Every TELL destructive | 2 | Robustness policy per entry (EXACT / MONOTONE / GUARDED), grounded in RSR |
| 10 | No bench suite; dev extras | 0 | `bench/`; extras already declared, README wording only |

Note on issue 10: `[project.optional-dependencies] dev` already exists in
`pyproject.toml` and the README already says `pip install -e ".[dev]"`. The
remaining action is to make the Hypothesis test module skip cleanly when
`hypothesis` is absent.

Note on issue 5: every NMMS rule replaces one connective occurrence by strictly
smaller premises, so a sequent can never recur on its own search path and the
cycle guard is dead code in practice. Proof depth is bounded by the number of
connective occurrences in the query. The flag is still worth exposing, and the
docs should state the bound.

---

## 3. Phases

### Phase 0: hygiene and measurement (v0.6.2, small) — DONE 2026-09-06

Goal: a regression harness before touching the hot paths.

1. **`bench/` directory** with plain-stdlib scripts adapted from
   `nmms_scaling_bench.py`: antecedent-size scaling (hit / miss / defeated),
   schema-count scaling (hit / miss), query-complexity curve in k. Each run
   logs a JSON record (timestamp, git SHA, Python version, table) to
   `bench/results/` for post-run analysis. Add `python -m bench` entry and a
   `make bench` target. No thresholds in CI yet; the results log is the
   baseline.
2. **Strict atom grammar (issue 4).** `parse_sentence` rejects atom names
   containing whitespace or parentheses unless wrapped in a quoted form. Add
   the quoted form now so Phase 3 has it: `<...>` delimits an opaque atom
   whose content is taken verbatim. Audit `tests/` for atoms with spaces.
3. Hypothesis import guard; README note on extras.

Deliverable: baseline numbers checked in, 512 tests green, atom grammar tests.

### Phase 1: reasoner performance and observability (v0.7.0, medium) — DONE 2026-09-06

Implemented as `pynmms.sequent` (`AtomSet` with diffs, `Sequent`, `TraceEntry`) plus the reasoner rewrite. Measured: antecedent-size cost flat at ~5 µs from 501 to 8001 atoms (was 507 ms at 8001); tautology k=8 from 23 ms to 9 ms; underivable k=8 from 1.6 ms to 0.06 ms. The hashable-atom-payload generalisation of `Sentence` is deferred to Phase 3, where `TripleAtom` is its first consumer.

Goal: query cost independent of |Γ| for atomic and shallow queries.

1. **Stopgap fixes on day one** (issue 1, issue 2): `if parsed.type == ATOM:
   continue` before the set difference in both rule loops; gate every trace
   f-string. Measure against the Phase 0 baseline. Ship these even if the
   refactor below slips.
2. **Parsed-sentence representation (issue 3).** The reasoner's internal
   sequents become `frozenset[Sentence]`, with strings parsed exactly once at
   the API boundary (`derives`, CLI, base file load). `Sentence` gains an
   `ATOM` payload that is any hashable object, so a triple can be an atom
   without a string encoding. `MaterialBase.is_axiom` accepts both forms
   during the deprecation window; a `_Sequent` helper keeps the atomic and
   complex parts separate so the left-rule loop iterates only complex
   sentences and the axiom check receives atoms directly. The atomic part is
   typed against a small `AtomSet` protocol (membership, hash, iteration over
   a diff, `with_added`, `with_removed`) rather than `frozenset` directly, so
   Phase 3 can substitute a store-backed view without touching the rules.
   TELL updates the partition incrementally.
3. **Lazy trace.** `ProofResult.trace` becomes a sequence of structured
   `TraceEntry(kind, gamma, delta, depth)` records with `__str__` doing the
   formatting; `str(entry)` reproduces today's text so CLI output and
   `test_logging.py` are unchanged. `logger.debug` calls use `%s` with the
   entry object so formatting only happens when DEBUG is enabled.
4. **Completeness flags (issue 5).** `ProofResult.depth_limited: bool` and
   `ProofResult.connectives: int`. Default `max_depth` becomes `None`
   (unbounded) since depth is bounded by the query; keep the parameter for
   callers who want a cap.
5. **Persistent cache (issue 8).** `MaterialBase.generation` increments on
   every mutation. `NMMSReasoner(base, persistent_cache=True)` keeps
   `_cache` across queries and clears it when the generation changes.
6. Benchmarks re-run and logged; target is the flat 10³ to 10⁶ curve in the
   change notes.

Deliverable: same 512 tests, new tests for trace structure, flags, cache
invalidation; bench results committed.

### Phase 2: base semantics (v0.7.0 with Phase 1, or v0.7.1; medium) — DONE 2026-09-06

Implemented as `pynmms.robustness` plus a per-shape schema index in `OntoMaterialBase` and robust-entry indexing in `MaterialBase`. CLI syntax is a trailing clause (`unless X, Y` / `monotone`) rather than a flag so it works in batch, stdin, and REPL alike. Default stays EXACT. Measured: schema hit/miss flat at ~6 µs from 10³ to 10⁵ schemas (was 2.2 / 4.4 ms at 10⁵); guarded and defeated queries flat at ~7 µs from 501 to 8001 antecedent atoms. Applied atoms are canonicalised (`R(a, b)` ≡ `R(a,b)`) so index membership tests are exact.

Goal: schema lookup in O(1), and defeat that is relevant rather than
arbitrary.

1. **Schema index (issues 6, 7).** Replace the scan in
   `_check_onto_schemas` with per-shape dictionaries:
   `sub[C] -> {D}`, `range[R] -> {C}`, `domain[R] -> {C}`,
   `subprop[R] -> {S}`, `disjoint: set[frozenset]`,
   `disjoint_props: set[frozenset]`, `joint[D] -> {frozenset(C1..Cn)}`.
   Maintained in `register_*` and rebuilt in `from_dict`. Misses are a
   dictionary miss, not a scan. `onto_schemas` stays a list for serialization
   and annotation lookup.
2. **Robustness policy (issue 9).** Every base entry, explicit consequence or
   schema, carries a `robustness` value:
   - `EXACT`: today's behavior, `(Γ, Δ) == (Γ₀, Δ₀)`.
   - `MONOTONE`: `Γ ⊇ Γ₀` and `Δ ⊇ Δ₀`. This is the regime-base reading.
   - `GUARDED(left, right)`: MONOTONE, unless `Γ ∩ left` or `Δ ∩ right` is
     non-empty. `left`/`right` are the defeater sets; this is RSR restricted
     to singleton additions, which is what `rsrlib.py` prototyped.

   Matching for MONOTONE and GUARDED entries is driven from the succedent side
   (index by each Δ atom, then check `Γ₀ ⊆ Γ` and the guard), so cost is
   O(|Δ| × candidates), not O(|Γ|). Containment is preserved by all three, so
   the reasoner is untouched.
3. **Default policy.** v0.7 keeps `EXACT` as the default so no existing base
   file or test changes meaning. The JSON format gains a `robustness` field
   written explicitly on every entry, so files are self-describing before the
   default flips. Recommended flip in v0.8: onto schemas default to
   `GUARDED` with an empty defeater set. The paper's line 317 argument is the
   justification; `onto-extension.md` Assumption 2 is revised accordingly.
4. **CLI and REPL syntax.** `tell --onto "subClassOf(Bird, Flies) unless
   Penguin, Dead"` registers a GUARDED schema; `tell "A, B |~ C" --monotone`
   for explicit entries. Batch and JSON output carry the field.
5. **Annotated logging** for every schema registration and every guard
   decision at DEBUG, including which defeater fired.

Deliverable: tests for each policy on each schema type, the
`{Bird}`/`{Bird,Tall}`/`{Bird,Penguin}` triple from the notes as a named
test, serialization round-trip with the new field, bench results for indexed
hit and miss.

### Phase 3: `pynmms.rdf` with rdflib (v0.8.0, large) — IN PROGRESS (slice 1 done 2026-09-06)

Slice 1 delivered: `TripleAtom` (a `str` subclass with the canonical `<s p o>`
name, which made the hashable-payload generalisation of `Sentence`
unnecessary), `GraphView`, `GraphBackend` protocol with `MemoryBackend` and
`SPARQLBackend`, `Rule`/`Regime`/`parse_rule` with `SIMPLE` and `RDFS`, the
semi-naive `ClosureEngine` (both full closure and per-node extras), `RDFBase`
and `RegimeBase`, `pynmms rdf ask`, the owlrl oracle test for `thm:closure`, and
`bench/rdf_scale.py`. Slice 2 (same day) added: `OWL2RL` regime (fixed-arity rules of Tables
4–9 with an owlrl oracle test; list-valued families and datatype rules
omitted and listed in `OWL2RL_OMITTED`), rule guards and rdfs1,
`PatternAtom` for blank-node consequents with polarity-aware Skolemization
of antecedent blank nodes, `pynmms rdf tell` and `pynmms rdf repl`,
`rdf/convert.py`, and `OxigraphBackend`. Still open: a live-endpoint test
for `SPARQLBackend`, the omitted OWL 2 RL rules, rdfD1.

Goal: `Γ ⇒ Δ` where Γ is an RDF graph and the base is a regime of
`def:entailmentregime`, at a scale set by the graph store rather than by Python. rdflib
and owlrl are an optional extra: `pip install pyNMMS[rdf]`. The propositional
core stays dependency-free.

Scale principle: the reasoner does Python work proportional to the query and
to the handful of atoms that logical decomposition adds or removes; the store
does work proportional to the data. Nothing the size of the graph is ever
materialized as a Python set, and closure is never computed in-process for
anything but the per-node extras.

1. **Triple atoms.** `TripleAtom(s, p, o)` as the `ATOM` payload, wrapping
   rdflib terms. String form for the CLI uses the quoted atom from Phase 0:
   `<ex:tweety a ex:Bird> -> ~<ex:tweety a ex:Dead>`, with prefixes resolved
   through the graph's namespace manager.
2. **Antecedent as a view plus a diff.** `GraphView(store, added, removed)`
   implements the Phase 1 `AtomSet` protocol: `store` is a reference to an
   external graph, `added` and `removed` are small frozensets of triple
   atoms. Membership is `t in added or (t in store and t not in removed)`,
   answered by the store. Hash and equality use only `(store.id, added,
   removed)`, so the memo key for a proof node is the diff and Δ, never the
   graph. Logical decomposition only ever moves a few atoms, so diffs stay
   small along every branch. The one-time Θ(|G|) load, hash, and partition
   costs from the change notes disappear entirely: G is never loaded.
3. **`RDFBase`**: a general base over ground triples (`def:fitness`) with
   Containment and an intensional lexicon. The language is "any well-formed
   triple over N", so `add_atom` validation becomes a well-formedness check
   rather than set membership. Explicit entries and robustness policies from
   Phase 2 work unchanged, which is where domain knowledge and relevant defeat
   live (paper, Section 4). Guarded entries are indexed by succedent atom, so
   their cost is O(|Δ| × candidates) and independent of the store size; the
   guard `Γ ∩ defeaters` is |defeaters| membership calls against the view.
4. **`RegimeBase(RDFBase)`**: `is_axiom(Γ, Δ)` computes "Γ is R-inconsistent
   or `Δ ∩ cl_R(Γ) ≠ ∅`" for `Γ = G ∪ added \ removed`. Regimes: `SIMPLE`
   (R = ∅, no closure), `RDFS`, `OWL2RL`, and `Custom(rules)` for user Horn
   rules over triples with `⊥` conclusions. Closure is split in two:
   - **Closure of G lives in the store.** The backend is responsible for
     `cl_R(G)`, either because the store materializes the regime natively
     (RDFox, GraphDB, Stardog, or any SPARQL endpoint with an entailment
     regime configured) or because the backend ran owlrl once at load time
     (the in-memory rdflib backend). It is recomputed only when the base
     generation changes.
   - **Closure of the extras is an incremental semi-naive step in pyNMMS.**
     `added` is small, so the new consequences of `cl_R(G) ∪ added` are found
     by firing rule schemas whose premises mention at least one added triple,
     with the remaining premises answered by store membership or a bounded
     SPARQL pattern query. `removed` is handled conservatively: a regime base
     is monotone, so removing a premise can only lose consequences, and the
     step is rerun from `cl_R(G \ removed)` only when `removed` is non-empty
     and the query touches a consequence of a removed triple (rare; log it).
     `⊥` from either half marks Γ inconsistent. This engine is a few hundred
     lines over the RDFS and OWL 2 RL rule tables and is a Phase 3
     requirement, not a Phase 5 luxury: without it every proof node pays a
     full closure.
5. **Pluggable backend.** A `GraphBackend` protocol with `contains(t)`,
   `ask(pattern)`, `match(pattern, limit)`, `closure_contains(t)`,
   `is_inconsistent()`, `load(source)`, `skolemize()`, and `generation`.
   Backends shipped: `MemoryBackend` (rdflib in-memory plus owlrl; for
   development, tests, and the `thm:closure` oracle), `SPARQLBackend` (any
   endpoint via rdflib `SPARQLStore`; closure is whatever the endpoint's
   regime provides, declared at construction and checked by a probe query),
   and `OxigraphBackend` via `oxrdflib` for a fast local store without a
   regime, paired with the in-process closure engine. RDFox and GraphDB are
   reached through `SPARQLBackend`; native adapters are Phase 5. All backends
   log load counts, Skolemized blank node counts, closure size and time, and
   per-query round-trip counts and latency for post-run analysis.
6. **Blank nodes.** Antecedent graphs are Skolemized on load (rdflib
   `Graph.skolemize()`, sound by `lem:skolem`). A succedent graph with blank nodes
   is wrapped as a single `PatternAtom(H)` whose axiom check is the `lem:witnesschar`
   witness search, run as a SPARQL `ASK` through the backend with blank
   nodes as variables; on a store that materializes the regime this is one
   round trip regardless of |G|. A ground succedent graph is the conjunction of its
   triple atoms and goes through `R∧` as usual. `PatternAtom` is opaque to the
   logical rules; the paper's existential extension is out of scope.
7. **Incoherence.** `Γ ⇒ ∅` returns True iff the regime derives `⊥`
   (`prop:incoherence`). Verify how owlrl surfaces inconsistency for OWL 2 RL
   (`owl:Nothing` typing versus raised error) before relying on it. With `II`
   this gives `Γ ⇒ ¬t` iff `Γ ∪ {t}` is inconsistent: negation over RDF as
   incoherence, which is the paper's Section 4 payoff and should be the
   headline example in the docs.
8. **Converters.** `OntoMaterialBase.to_graph()` emits the ABox as
   `rdf:type` and role triples, schemas as `rdfs:subClassOf`, `rdfs:range`,
   `rdfs:domain`, `rdfs:subPropertyOf`, `owl:disjointWith`,
   `owl:propertyDisjointWith`, and joint commitments as an `owl:Restriction`
   or a custom rule, with annotations as `rdfs:comment`. `RDFBase.from_onto()`
   for the reverse. This makes the onto extension a surface syntax rather than
   a parallel implementation, without deleting it yet.
9. **CLI.** `pynmms rdf ask -g graph.ttl --regime rdfs "<...> -> <...>"`,
   `pynmms rdf tell` for adding triples or explicit entries, `--json`, `-q`,
   batch, and REPL `load graph.ttl`. `--store URL` selects `SPARQLBackend`,
   `--store oxigraph:PATH` selects `OxigraphBackend`; default is in-memory.
   Loading logs triple counts, Skolemized blank nodes, and closure size and
   time.
10. **Test oracle from the paper.** `thm:closure` makes rdflib plus owlrl a ground
   truth: for random small graphs G, H over a fixed vocabulary, NMMS
   derivability of `G ⇒ H` against `RegimeBase(RDFS)` must equal "owlrl
   closure of G contains an instance of H", and `G ⇒ ∅` must equal owlrl
   inconsistency. This is the same pattern as `test_cross_validation_role.py`
   and should be a Hypothesis test. `cor:simple` (simple entailment) gives a
   second oracle that needs no closure.
11. **Scale benchmark.** `bench/rdf_scale.py` generates synthetic graphs at
   10⁵, 10⁶, and 10⁷ triples with a fixed schema, loads them into each
   backend, and measures atomic, negated, and k = 4 queries. Acceptance:
   per-query cost flat across graph sizes on the store-backed backends, and
   Python-side memory independent of |G|. Results logged to
   `bench/results/` alongside the Phase 0 tables.

Deliverable: `src/pynmms/rdf/` (`atoms.py`, `view.py`, `base.py`,
`regime.py`, `closure.py`, `backends/`, `convert.py`, `cli.py`), tests
mirroring the onto layout plus backend-parametrized tests, docs tutorial.

Scale profile after Phase 3: Python work per proof node is O(|diff| + |Δ|)
plus a bounded number of store calls. Throughput is store round-trip bound,
in the low thousands of axiom checks per second per process against a
network endpoint and tens of thousands against a local Oxigraph, rather than
the ninety thousand of the in-memory case. Batch query workloads parallelize
across processes since the store is shared and the reasoner is stateless
apart from its cache.

### Phase 4: documentation and theory (v0.8.x, small to medium) — DONE 2026-09-06

`theory/rdf-semantics.md` written; `onto-extension.md` gained 8.4 (onto vocabulary as the `rdf:type` fragment), revised 8.2, Open Questions 1 and 5, and the new references; landing pages and README updated. Version bumped to 0.8.0.

1. New theory page `theory/rdf-semantics.md`: Definitions 9, 13, 19, 25, 26;
   `thm:recovery` and 35; `prop:incoherence`; each stated once and mapped to the class
   or method that implements it.
2. Revise `theory/onto-extension.md`: Assumption 2 (exact match) becomes a
   discussion of robustness policies; Open Question 1 (schema interaction)
   is answered for regime bases by closure and left open for guarded bases;
   Open Question 5 (scaling) cites the bench results; Section 8 cites the
   paper and states that the onto vocabulary is the `rdf:type` fragment of
   the triple encoding. Add the paper to Section 10.
3. `docs/tutorial/rdf-tutorial.md` with the Tweety example end to end:
   load Turtle, ask RDFS entailment, ask incoherence, ask a negated triple,
   add a guarded material inference, watch it defeat.
4. README: RDF quickstart, updated test counts, `[rdf]` extra.

### Phase 5: later (v0.9+) — IN PROGRESS (slice 1 done 2026-09-06)

Slice 1: general RSR as conjunctive exclusion pairs (`guarded(exclusions=...)`, `unless X & Y` syntax, JSON `unless.pairs`, schema guards on the same individual; the guard is O(defeaters), so the general case indexes as cleanly as singletons); the list-valued OWL 2 RL rule families and rdfD1 as `ProceduralRule`s with an owlrl oracle over list constructs; `SPARQLBackend.add()` via SPARQL UPDATE, `prefixes=`, default-graph identifier, and a live test against an in-process rdflib-endpoint server; unbound short prefixes are now errors. Slice 2 (same day): batched store calls (`GraphBackend.join()`; `ClosureEngine.extend(store_join=)` splits each firing's remaining premises into in-process and store positions and sends the store positions as one query; round trips measured against the in-process endpoint) and bulk TELL (`SPARQLBackend.add()` in chunked `INSERT DATA` updates, one generation bump per call). Remaining: native RDFox/GraphDB adapters and closure push-down (need a store), reimplementing `OntoMaterialBase` over `RDFBase`, the first-order existential, `owl:sameAs` as substitution commitments.

- Native backend adapters for RDFox and GraphDB, pushing the extras-closure
  step down into the store's own rule engine (RDFox Datalog, GraphDB
  rulesets) so no rule firing happens in Python at all.
- Batched and asynchronous store calls: the proof search issues membership
  checks for a whole rule's premises in one round trip, and sibling branches
  of multi-premise rules run concurrently. (Slice 2 did the join batching;
  membership checks are still one round trip each, and nothing runs
  concurrently.)
- **Projection-then-bulk-check.** Today the search consults the base once
  per proof node, so over a store the latency of a query is one round trip
  per node, up to ~2.17^k of them for k connectives. Theorem 7 of Ch. 3
  (Projection) says every sequent decomposes uniquely into a set of atomic
  base sequents, AtomicImp, and is derivable iff AtomicImp ⊆ |~_B; by
  invertibility (Prop. 27) that decomposition never depends on the base.
  So reorganise `NMMSReasoner` for store-backed bases into two passes:
  (1) apply the logical rules only, in memory, producing the atomic leaves
  as a DAG with memo sharing (the same 2.17^k nodes, no store calls);
  (2) check every leaf against the base in one batched request: for a
  `RegimeBase` that is one closure step over the union of all leaves'
  extras and one `VALUES`-batched membership query for all leaf consequents,
  plus the indexed guarded-entry checks in memory. Latency becomes
  O(1) round trips per query instead of O(nodes); CPU cost is unchanged
  except that short-circuit pruning is lost (every leaf is computed even
  when an early failure would have ended the search), which only matters
  for deep queries. Keep the node-at-a-time search for in-memory backends
  and as the fallback; expose the choice as `NMMSReasoner(strategy=
  "projection")`. Tests: the projection pass must agree with the current
  search on random sequents (reuse the differential harness), and the
  round-trip count over the in-process endpoint must be constant in k.
  This is the change to make before any compiled-language rewrite: it
  turns the store-backed profile from latency-per-node into
  latency-per-query, which is what industrial use needs.
- Bulk TELL against a store-backed base: streaming inserts with a generation
  bump per batch rather than per triple, and a closure-maintenance hook so
  the store's materialization is kept current by the store, not by pyNMMS.
- General RSR beyond singleton defeaters: entries carrying arbitrary
  `⟨x, y⟩` exclusion pairs; whether this indexes cleanly is open. (Done in
  slice 1: it does, the guard is O(|exclusions|).)
- Reimplement `OntoMaterialBase` on top of `RDFBase` and retire the parallel
  schema matcher.
- The paper's existential extension for blank nodes in the succedent.
- `owl:sameAs` as symmetric substitution commitments (paper, `rem:identity`).

---

### Phase 6: the production-store target (v0.10 to v1.0, large)

**Target.** A reasoner that adds negation, conditionals, incoherence
checking, and defeasible material inference on top of a production
triplestore holding a full-size biomedical or heritage knowledge base, with
query latency in the tens of milliseconds and no size limit of its own.

Everything below is measured against that sentence. "Full-size" means the
published dataset, not a module: GO, HPO, or MONDO whole (about a million
triples each), a CIDOC-CRM collection export (10⁶ to 10⁷), a Wikidata class
slice (10⁶ to 10⁸). "Tens of milliseconds" means a cold query with up to
four connectives, p50 under 20 ms and p95 under 100 ms, over a LAN to a store
holding 10⁷ triples, with repeated queries served from memo at under 1 ms.
"No size limit of its own" means pyNMMS holds no copy of the graph and no
per-query cost grows with it, which Phases 1 to 3 already established and
which this phase must preserve under every new feature.

What is already in place: the calculus and its bases, the `GraphBackend`
protocol with in-memory, SPARQL, and (since v0.11.0) embedded Oxigraph
implementations, the semi-naive extras step with batched joins,
per-generation memos, robustness policies over ground triples read through
the regime, and oracle tests against ROLE.jl and owlrl. What follows is the
gap between that and the target, as eight workstreams.

**Development store: Oxigraph (decided 2026-09-07).** The first adapter is
an embedded Oxigraph store through `pyoxigraph`, not a GraphDB container:
no server, no licence, RocksDB on disk for the target sizes, and a Rust
SPARQL engine that runs the regime's rules itself. Measured on the
synthetic RDFS graph, the closure in the store is five times faster than the
in-process engine (24 s against 113 s for 600k asserted, 2.4M closed) and
matches it triple for triple; an `ASK`, an `ASK` with `NOT EXISTS`, and a
scratch-graph insert-ask-drop are 15 to 30 µs. Rule updates run directly
against an on-disk store are RocksDB-write-bound (127 s for the same
closure), so the backend materialises in memory and bulk-loads the result
(33 s on disk, all in); see `bench/PERFORMANCE.md` section 7. Oxigraph has no reasoner of
its own, so the rule translation of workstream C is what materialises the
regime; the hypothetical closure of A.3 is a scratch named graph rather
than a transaction. GraphDB and RDFox remain the adapters for a store
someone else operates.

#### A. Store adapters with four capabilities

The `GraphBackend` protocol grows four operations, each declared by a
capability flag so the reasoner can choose the fast path when it exists and
an emulation when it does not:

1. **Materialised regime with incremental maintenance.** The store owns
   `cl_R(G)` and keeps it current on insert. The adapter declares which
   regime the store's ruleset implements (GraphDB `rdfs`, `owl-horst`,
   `owl2-rl`; RDFox user Datalog) and probes it at construction.
2. **Batched membership.** `contains_many(triples) -> set` and
   `closure_contains_many` as one `VALUES` query, replacing the one-ASK-per-
   conclusion pattern that dominates the extras step's round trips today.
3. **Hypothetical closure.** `closure_of(extras) -> (derived, bottom)` as a
   transaction: add the extras, let the store reason incrementally, read
   the derived triples and the incoherence marker, roll back. RDFox supports
   this over its REST transactions. GraphDB exposes RDF4J transactions;
   whether inferred statements are visible inside an uncommitted
   transaction must be probed, and if not the adapter falls back to the
   in-process `ClosureEngine.extend` against the store's closure.
4. **Explanation.** `explain(triple) -> premises` from the store's proof
   API (RDFox `EXPLAIN`, GraphDB's explain plugin), used for traces now and
   for the SMT-style learning later.

Delivered first (v0.11.0): `backends/oxigraph.py`, an embedded store with
capabilities 1 (the regime materialised by SPARQL rule updates, incremental
`add()`, persistence with a recorded regime) and the D0 operations at
microsecond cost; `sparql_rules.py` is the rule translation of workstream C
for pattern rules. Still to do for Oxigraph: capability 3 as a scratch
named graph, and capability 2 (`VALUES`-batched membership), which matters
less in process than over HTTP.

Deliverables for the network stores: `backends/graphdb.py` and `backends/rdfox.py` (REST clients
with auth, timeouts, retries, and per-call stats), `--store graphdb://host/
repo` and `rdfox://host/datastore` in the CLI, and Docker-based integration
tests. GraphDB Free runs in a container and can be a CI service; RDFox needs
a licence (an academic one is available) and its tests are skipped without
it. Build against GraphDB first because the test infrastructure is free,
and against RDFox first for hypothetical closure, which is the capability
that makes negation and conditional queries one round trip.

#### B. Latency: one or two round trips per query

- **Projection-then-bulk-check** (Phase 5 item): apply the logical rules in
  memory to produce the atomic leaves as a memo DAG, then check all leaves
  in one batched call: one hypothetical-closure transaction over the union
  of the leaves' extras (or one in-process extend), one `contains_many` for
  all leaf consequents, and the guarded-entry checks in memory. Selectable
  as `NMMSReasoner(strategy="projection")`; the node-at-a-time search stays
  as the in-memory default.
- **Asynchronous store calls** for the node-at-a-time strategy so sibling
  branches overlap their round trips; a thread-safe memo.
- **Warm-start**: persist the per-generation memo keyed by the store's
  generation token across sessions, so a research session does not pay
  cold costs after every restart.

Acceptance: round trips per query constant in the number of connectives
(measured with the in-process endpoint), and the p50/p95 targets above on
the LUBM benchmark in section F.

#### C. Regimes and rules that live in the store

- A translation from our `Rule` format to RDFox Datalog and to GraphDB
  `.pie` rulesets, so custom rules, including false-concluding ones, run in
  the store. ⊥ becomes a designated triple (`pynmms:incoherent`) that the
  store derives and pyNMMS reads as inconsistency; `prop:incoherence` is then
  one `ASK`.
- Literal comparisons (dates, quantities) in store rules, using the store's
  built-ins; the same rules run in-process through `Rule.guard` predicates
  so the two paths can be cross-checked on samples.
- A regime descriptor per store ruleset, so that when hypothetical closure
  is emulated in process, the in-process rules match what the store
  materialises. Oracle: closure of random extras store-side versus
  in-process must agree (the extras-oracle test, pointed at a store).

#### D. Defeasible material inference over triple patterns

**D0. Material entries through the store (`B_{R,I}` clause 3).** Since
v0.10.1 a `RegimeBase` reads its ground material entries `⟨A, D; E⟩`
through the regime: the antecedent must lie in `cl_R(Γ)`, no defeater may,
and the consequent is elaborated as `Δ ∩ cl_R(Γ ∪ D)` (theory page,
Section 8). In memory that is three lookups against the per-query closure
and one semi-naive extension by `D`. Over `SPARQLBackend` the same clause
is unimplemented in store terms: today the closure of the extras is pulled
into process rule by rule, and every entry check is a further sequence of
round trips. The store path for clause 3 is, per candidate entry:

1. **Antecedent**: `A ⊆ cl_R(Γ)`, one `ASK` over the store's materialised
   closure with the extras added as `VALUES` or, with capability A.3, read
   from the hypothetical-closure transaction. Entries are indexed by
   consequent atom, so only entries whose `D` meets `Δ` (or, with
   elaboration, whose `D` could reach `Δ` through the regime) are
   candidates; the second set is bounded by the store's own
   `closure_contains_many` over `D`.
2. **Defeaters**: `∀ e ∈ E : e ⊄ cl_R(Γ)`, one `ASK` with `FILTER NOT
   EXISTS` per entry (all defeaters in one query as a `UNION` inside the
   `NOT EXISTS`), which is exactly the idiom current practice writes by
   hand.
3. **Consequent**: `Δ ∩ cl_R(Γ ∪ D) ≠ ∅`, one hypothetical-closure call
   (A.3) over `extras ∪ D`, or in emulation one in-process `extend` by `D`
   against the store; with `elaborate_consequent=False` this is `Δ ∩ D`
   and costs nothing.

So one entry costs two `ASK`s plus one closure extension with capability
A.3, and the whole material check for a leaf is batchable with the leaf's
own membership checks in strategy B. Without A.3 the consequent clause is
the expensive one, and `elaborate_consequent=False` is the documented
fallback for stores that cannot reason in a transaction. Deliverables:
`SPARQLBackend.material_check(entries, extras, delta)` (or the three
primitives `ask_all`, `ask_none`, `closure_of`) behind a capability flag,
`RegimeBase` routing clause 3 through it when present, the material-base
tests of `tests/test_rdf_material.py` run against the in-process endpoint
with a round-trip budget asserted, and a row in `bench/PERFORMANCE.md`
section 4 for a guarded entry with one and with three defeaters. This is
the ground-entry case of the pattern rules below and should land first,
since the rule matcher reduces to it once variables are bound.

The remaining item is the pattern generalisation. Today material entries
are ground triples and the schema-level defeasible inferences exist only
in the ontology extension's string atoms. A heritage or biomedical base
needs defeasible *rules* over patterns:

    ?x a ex:Bird -> ?x a ex:Flies unless ?x a ex:Penguin, ?x ex:injured true

`DefeasibleRule(premises, conclusion, robustness)` on `RDFBase`, indexed by
conclusion predicate. Matching a leaf `P ⇒ N`: unify a consequent atom with
the conclusion, bind the variables, require the premises in Γ (one join
against store plus extras), require every defeater pattern to have no match
(one join each, expecting empty), apply EXACT/MONOTONE/GUARDED semantics as
for ground entries. This is the "reimplement `OntoMaterialBase` over
`RDFBase`" item done properly: the ontology extension becomes a surface
syntax compiling to `DefeasibleRule`s over `rdf:type` triples, and its
parallel matcher can be retired once the differential test confirms
agreement. Conjunctive exclusions carry over as multi-pattern defeaters.
Store round trips: two to three per candidate rule per leaf, batched with
the leaf checks in strategy B, and the same three store operations as D0
once the variables are bound.

#### E. Data-model gaps that real datasets hit first

- **Named graphs and provenance.** Adapter-level scoping: a backend bound
  to a set of graphs (`FROM`/`GRAPH` clauses), so a query can be restricted
  to a source or an evidence level. `TripleAtom` stays a triple; a
  `graphs=` argument on the backend and on `sequent()` selects the scope.
- **Datatypes.** rdfD1 typing exists; comparisons come from workstream C.
  The remaining OWL 2 RL datatype rules stay omitted unless a dataset
  needs them.
- **Wikidata's model.** No RDFS: a custom regime for `wdt:P31`/`wdt:P279`
  and part-of transitivity; a compiler from `P2302` property-constraint
  statements to false-concluding rules with the listed exceptions as
  defeaters. Truthy statements first; statement nodes only for constraints
  that need qualifiers.

#### F. Evaluation on real data, with oracles

- **F0. NMMS versus RDFS over one persisted materialisation** (harness, synthetic, GO + human GAF, and Amsterdam Museum runs DONE 2026-09-07; see `bench/PERFORMANCE.md` sections 8 to 10: total agreement, 394 of 1,383 curated `NOT` annotations contradicted by the RDFS closure, 335 of them in the asserted data itself; the Amsterdam Museum run models attribution qualifiers as defeaters and posthumous making as an incompatibility; it showed that an incompatibility the store already satisfies explodes the base under the global reading, which led to position attribution (`RegimeBase.attribution`) and positions over the store as background (`include_graph="background"`), delivered the same day; OWL 2 RL over GO and the pattern form of entries remain). The first
  evaluation needs no external store: an on-disk Oxigraph store holding a
  graph and its RDFS closure serves as both reasoners. The classical RDFS
  answer to a ground triple is one `ASK` against the closure graph
  (`thm:closure`, ter Horst); the NMMS answer is proof search over
  `RegimeBase` on the same store. The harness, `bench/compare_rdfs.py`,
  takes a store directory and a query file and writes one record per
  query to `bench/results/`:
    1. *Atomic hits and misses*: the raw `ASK` latency, the NMMS verdict
       and latency, and agreement, which must be total (NMMS is a
       conservative extension of its base). This is `thm:closure` checked
       at 10⁷ triples, beyond owlrl's reach, and the measured overhead of
       the sequent machinery over a lookup.
    2. *Negation, conditional, disjunctive, and pattern-atom queries*:
       NMMS verdict, latency, nodes, round trips; the RDFS column is marked
       "not expressible", since the closure alone answers none of them.
    3. *Material entries*: a base file of guarded entries over the same
       vocabulary (`Bird ⊢ Flies unless Penguin`), the NMMS verdict for
       instances that the closure makes birds, penguins, or both, and
       again "not expressible" for RDFS.
    4. *Session amortisation*: reopen time and the first ten queries cold
       (RocksDB block cache empty) against warm, so the cost of a new
       session over a persisted store is on record.
  The closure itself is our translation of the RDFS rules, so agreement
  between the store-side closure and the Python engine is a self-check;
  for independent evidence at scale the same N-Triples file goes through
  GraphDB's `rdfs` ruleset or Jena's RDFS reasoner and the two closures
  are diffed triple for triple (owlrl remains the oracle at small sizes).
  Synthetic data first, using the 10⁷ store of 2026-09-07. The real
  dataset for F0 is the **Gene Ontology with the human GAF annotations**:
  `go.owl` (about 1.5M triples; real subclass chains, the three root
  branches declared disjoint, restriction axioms full of blank nodes for
  the Skolemizer to work on) plus the human gene-association file
  converted to triples by a short GAF-to-RDF script in `bench/` (each
  annotation a gene product typed by a GO class, with evidence code and
  reference kept as annotation triples). The GAF's `NOT` qualifier is the
  reason for the choice: curators publish explicit negative assertions,
  which are the incompatibilities `prop:incoherence` recovers, so "is this
  gene product annotated to a function it is also annotated NOT to have,
  after closure" is a query a biologist recognises and the closure can
  answer only with NMMS. The `NOT` annotations become false-concluding
  rules or rejected graphs in a position; the `contributes_to` and
  `colocalizes_with` qualifiers become guarded material entries. Under
  RDFS first, then OWL 2 RL, where the `owl:someValuesFrom` axioms show
  what the regime leaves behind. The closure of a few million annotation
  triples under GO's depth may pass 10⁷, so the on-disk materialisation
  path and its timing are part of the record.
- **LUBM** at scales 10, 100, and 1,000 (about 1.3M, 13M, 130M triples) in
  GraphDB and RDFox, for latency distributions per query class (atomic,
  negation, conditional, pattern, four-connective) and throughput in
  queries per second, single-threaded and with async. This is the benchmark
  classical reasoners publish on, so the numbers are comparable.
- **HPO with HPOA** under OWL 2 RL in the store, after GO in F0:
  absent-versus-present phenotype conflicts (`NOT` annotations again),
  frequency and onset modifiers as defeasibility. Oracle: owlrl on a
  sample of query results.
- **A CIDOC-CRM export or a Wikidata slice**: incoherence versus the
  dataset's own validation reports (Wikidata constraint-violation reports;
  a SHACL shapes graph run by the store, whose violation report is an
  oracle for the incoherence check); defeat by exceptions and ranks.
- Every evaluation logs per-query latency, round trips, nodes, and depth to
  `bench/results/` as the existing records do.

#### G. Operations and tooling

Connection configuration in a file, authentication for both stores, read-
only mode, timeouts and retries with logging, thread-safe memos, and a
`pynmms rdf` session that can be pointed at a store with one flag. The CLI
and REPL stay research-grade; a service wrapper is out of scope for this
phase and would be a thin layer over `RegimeBase` when wanted.

#### H. Positions as speech acts: the position API — DONE 2026-09-07 (`pynmms.rdf.position`, REPL client, `bench/replay_dialogue.py`, `bench/queries/am_dialogue.txt`)

The real-data runs of 2026-09-07 (F0 on GO and on the Amsterdam Museum)
settled what a position is. It is not a region of the graph; it is what
someone has said. The stored graph is the sediment of past speech acts
whose speakers are gone, so it is the *background*, what a conversation
takes for granted, and no one is committed to a record until they read it
aloud. Treating the whole store as one enormous move by nobody is what
made one contradictory record incoherent for every query; the
`attribution` and `include_graph="background"` changes of that day are the
first half of the correction, and this workstream is the second.

The primitive is the accumulating position of a session:

    pos = Position(base, holder="curator@museum")      # empty, over the store as background
    pos.assert_("<am:proxy-52227 am:etchedBy am:p-10974>")
    pos.deny(graph)                                     # a rejected graph (def:contententailment)
    pos.coherent()          -> bool, with the entry or ⊥ rule that fails and the defeater that would rescue it
    pos.commits_to(query)   -> derivability of a sequent over the position (ask as challenge)
    pos.precludes(query)    -> Γ, A ⇒ ∅: what the position is incompatible with
    pos.withdraw(atom)      # positions have a history, not just a set
    pos.commit()            # write the accepted graph to the store (TELL), closure extended
    Position.of(base, subject, holder=...)              # read a record aloud: its concise description as Γ

- `Position` holds a holder, the accepted atoms, the rejected graphs, and
  an ordered log of assertions, denials, and withdrawals; the base reads
  its current state as a sequent over the background
  (`include_graph="background"`). Human scale is the normal scale: tens of
  triples, so the millisecond hypothetical rows of F0 are the ordinary
  cost and the 10⁷ store matters only as background.
- Coherence and preclusion reports name the entry or rule responsible and
  the defeater that would answer it, in the shape a SHACL user recognises
  (one report per position), so the comparison with validation is like for
  like.
- `Position.of(subject)` is the special case of reading a stored record
  aloud: its triples become the position's commitments and are set aside
  from the background for that check, which is what makes one date
  coherent and two dates incoherent for the chalice.
- The REPL is the first client: `tell` accumulates into the session's
  position rather than the graph, `ask` challenges it, `show` reports its
  commitments and preclusions, `commit` writes it. The harness gains a
  `position` section that replays a scripted dialogue with predictions.
- First dialogue to replay: the museum's attribution history ("oude
  toeschrijving", "voorheen toegeschreven aan", "naar") as successive
  positions over the collection, and a curator's `NOT` annotation on GO as
  a denial against the propagated closure.

This is the coupling to dialogue (Elenchus) the ontology extension was
written for, stated as data: the base's entries are the rules of the
game, the background is the common ground, and positions are the moves.

#### The six steps from here to the vision

`docs/docs/theory/onto-extension.md`, Section 9, states the vision:
knowledge engineering as the engineering of the space of implications a
graph lives in, with the graph as a record of commitments. What has to be
true for that to be a practice rather than an argument, in the order each
unblocks the next:

1. **Positions as speech acts** (H above; the small design decision that
   everything else depends on). A week, with the REPL client.
2. **Material entries as patterns** (D). Every entry worth writing on real
   data was an instance of a rule with variables and defeaters. Test set:
   the 394 contradicted `NOT` annotations and the 137 posthumous makings;
   oracle: the defeasible reading recovers every curated exception and
   keeps every uncontradicted default. Two weeks.
3. **Values in rules and defeaters** (C) — rules DONE 2026-09-08
   (`pynmms.rdf.values`: guards as `[...]` among premises, evaluated as
   `FILTER` in the store and in Python, cross-checked; `year`, `num`,
   `lang`, `datatype`, `rank` over declared orderings). Defeaters with value
   conditions wait for pattern entries (step 2), since ground entries know
   their values when written. Settles what `def:entailmentregime` admits
   beyond uniform rules: flagged on the theory page, to be stated in the
   second paper.
4. **Provenance as entitlement.** Named graphs and PROV as the modelling
   convention; a triple carries its source, defeaters can name sources and
   evidence levels, a position is a holder's commitments. Two catalogues
   become two positions. A week.
5. **The curation loop.** `propose`: submit a record or edit as a position
   and get back what it commits to, what it is precluded from, which
   defeater would rescue an incoherence, and a trace, before anything is
   written. Measured on the museum and GO with predictions written first,
   against SHACL and SPARQL on the same store. A week.
6. **Scorekeeping and dialogue.** Positions per participant, commitments and
   preclusions tracked as assertions accumulate, challenges as incoherence
   queries. `Position.challenges()` (DONE 2026-09-08) generates the
   opponent's probes from the base: refutations, incompatibilities and ⊥
   rules the position partly satisfies, unacknowledged defaults, each with
   its rescue. What remains is the turn structure, explicit entitlement,
   and a termination rule: the Elenchus work, its own project once 1, 4,
   and 5 exist.

Alongside: the second paper (outline below), since the implementation is
now ahead of the text in exactly the places where negation and
defeasibility became usable; and the discipline the runs taught, every
experiment with its expectations recorded before it runs (`## r,n,i` in
the harness) and compared with the usual tooling on the same store.

#### The second paper: what the semantics has to add to catch up

The first paper proves `thm:recovery` and `thm:closure` for the closure
base `𝔅_R`. Everything that made negation and defeasibility usable on
real data (2026-09-07) is outside its text: the regime-relative material
base, positions over a background, attribution. Each item below is fixed
by what the code does and has tests stating the expected behaviour
(`tests/test_rdf_material.py`, `tests/test_rdf_position.py`), so the
definitions can be written from them. Labels follow the first paper's
convention and are cited by label.

1. **`def:materialbase`, the regime-relative material base `𝔅_{R,I}`.**
   Entries `⟨A, D; E⟩` and the three clauses as implemented: Γ
   R-inconsistent, or Δ meets `cl_R(Γ)`, or an entry with `A ⊆ cl_R(Γ)`,
   no `e ∈ E` with `e ⊆ cl_R(Γ)`, and Δ meeting `cl_R(Γ ∪ D)`; the
   policies exact, monotone, guarded; the empty-consequent case with the
   succedent policy deciding explosion. To prove: it is a base in the
   sense of `def:fitness`; with `I` empty it is `𝔅_R`; and the defeater
   test picks out a fragment of the range of subjunctive robustness of
   `def:roles`, so a guarded entry is an implication with a specified RSR
   and not an ad hoc rule. (Theory page, Section 8, is the draft.)
2. **`def:background` and `def:positionover`, a position over a
   background.** A background `B` and a position `P`, the base evaluated on
   `cl_R(B ∪ P)` with `P` alone as the commitments. The organising
   definition; short.
3. **`prop:attribution`.** A ⊥, or an incompatibility's antecedent, counts
   against `P` only if its derivation uses a triple of `P` not already in
   `cl_R(B)`. Define the `P`-dependent part of a closure and show the
   semi-naive extras step (`ClosureEngine.extend`) computes it. Corollary:
   the empty position over an R-inconsistent background is coherent, and
   the background's ⊥ is inventory (`background_inconsistent()`).
4. **`thm:recoverybg` and `thm:closurebg`, the theorems restated relative
   to a background.** On the positive part, `P` over `B` entails `H` iff
   `B ∪ P` R-entails `H` with ⊥ removed from `cl_R(B)`; on incoherence, `P`
   is out of bounds iff its own contribution derives ⊥. A paraconsistent
   reading of the background; its own proof, not a corollary.
5. **`lem:readaloud`, speaking for one's subjects.** Reading a record
   `rec(s)` aloud is the position `P = rec(s)` over `B \ rec(s)`. The
   positive closure is unchanged, `cl_R((B \ rec) ∪ rec) = cl_R(B)`, so
   reading aloud is conservative on what follows and changes only who is
   answerable for it (one date coherent, two dates not).
6. **The evidence.** The F0 methodology (predictions before runs;
   agreement with the store's own answers as the oracle) and the three
   results: total agreement at 4×10⁷ closure triples; 394 of 1,383
   curated `NOT` annotations contradicted by the RDFS closure, 335 in the
   asserted data; the museum session of fourteen probes at milliseconds
   each (`bench/PERFORMANCE.md` sections 8 to 10).

Two revisions to the first paper's `sec:discussion`: the query-side
defeat idioms are no longer outside the semantics, since `𝔅_{R,I}` brings
the `NOT EXISTS` test inside as a claim in the base at the price of a
closed-world defeater check over a finite closure, and the section should
say so; and SHACL's focus node and the position over a background are the
same locality reached from opposite directions. `def:entailmentregime`'s
uniformity will need a stated exception once value guards exist (step 3
above), since a date comparison is not closed under substitution; flag it
now, state it with the values work.

Kept out of the paper until the code has them: patterns as bearers
(workstream D) and the pragmatics of verdicts and rescues, which are the
game (`onto-extension.md`, Section 9.1) rather than the semantics.

#### Sequencing and releases

| Release | Content | Depends on |
|---|---|---|
| v0.11 | A (Oxigraph adapter: closure in the store via C's rule translation, on-disk persistence, `--oxigraph`), D0 over Oxigraph | pyoxigraph — DONE 2026-09-07 |
| v0.12 | F0 on synthetic, GO, and the Amsterdam Museum (DONE 2026-09-07); position attribution and positions over the store as background (DONE 2026-09-07); H (the position API, REPL as client, dialogue replay in the harness); C (values in rules and defeaters) | v0.11 |
| v0.13 | D (defeasible rules over patterns; onto layer as surface syntax), tested on the 394 `NOT` contradictions and the 137 posthumous makings | v0.12 |
| v0.14 | provenance as entitlement (step 4), the curation loop `propose` (step 5) compared with SHACL and SPARQL on the same store; B (projection strategy, async, warm-start), A.3 hypothetical closure as a scratch graph | v0.13 |
| v0.15 | A (GraphDB and RDFox adapters, batched membership, Docker tests), E (graph scoping), F LUBM latency numbers | a GraphDB container; RDFox licence |
| v1.0 | scorekeeping and dialogue (step 6, with Elenchus), HPO/HPOA and Wikidata evaluations, Wikidata constraint compiler, API freeze, docs | all of the above |

Rough effort with one developer and Claude: H one week, C one, D two,
steps 4 and 5 one each, B one to two, the remaining A adapters two, E one,
G one; about three months end to end. The real-data evaluations have
already changed the plan once, on 2026-09-07, by putting positions ahead
of every store adapter.

#### Acceptance criteria for the target

- A GO or HPO release, or a heritage export of at least 10⁶ triples, loaded
  into GraphDB or RDFox with its regime materialised by the store, and
  pyNMMS holding none of it.
- Cold queries with up to four connectives at p50 under 20 ms and p95 under
  100 ms over a LAN at 10⁷ triples; repeated queries under 1 ms.
- Negation, conditional, incoherence, material-entry (`B_{R,I}`), and
  defeasible-rule queries all answered through the store path, with
  traces, and cross-checked against the in-process path on samples.
- The extras-oracle and differential tests passing against the store
  adapters as well as in memory.
- Round trips per query independent of the number of connectives.

#### Decisions needed

1. **Which store first.** Recommendation: GraphDB Free for the adapter,
   protocol, and CI, then RDFox for hypothetical closure once a licence is
   in hand. If a licence arrives early, reverse them: RDFox gives the full
   target sooner.
2. **Docker in CI.** GraphDB as a GitHub Actions service container adds a
   minute per run and about a gigabyte of image pulls. Recommendation:
   yes, on a separate job so the core suite stays fast.
3. **Fate of the ontology extension.** Workstream D makes it a surface
   syntax over `RDFBase`. Recommendation: keep its API and CLI unchanged,
   route the implementation through `DefeasibleRule`, and retire the string
   matcher only after the differential test says the two agree.
4. **Named graphs.** Adapter-level scoping (recommended) versus a quad atom
   type. Scoping covers provenance filtering without touching the calculus;
   a quad atom would be needed only to reason *about* provenance.

#### Risks specific to this phase

- **Hypothetical closure semantics in GraphDB** may not be available inside
  a transaction; the fallback is emulation, which keeps the extras step in
  Python and costs round trips. Probe early.
- **Rule translation fidelity.** Store rule languages differ in built-ins
  and in how they treat literals; the in-process versus store-side closure
  oracle must run on every dataset before its numbers are believed.
- **Memo growth.** Per-generation memos are unbounded within a generation;
  the `memo_limit` needs a real eviction policy under sustained use.
- **Network variance.** The latency targets assume a LAN; over a WAN the
  projection strategy is the only thing that keeps queries interactive.
- **Licensing.** RDFox is commercial; the academic licence covers research
  use but not distribution, so the RDFox adapter must remain optional.

## 4. Sequencing and dependencies

```
Phase 0  ──▶  Phase 1  ──▶  Phase 2  ──▶  Phase 3  ──▶  Phase 4
bench,        parsed          index,        rdflib,       docs
grammar       sentences,      robustness    regimes
              trace, flags
```

- Phase 2's index assumes Phase 1's parsed atoms (no re-parse in
  `is_axiom`). It can be built on strings if Phase 1 slips, at a small cost.
- Phase 3 requires Phase 0's quoted atom syntax, Phase 1's hashable atom
  payloads and `AtomSet` protocol (the store-backed `GraphView` implements
  it), and Phase 2's robustness policies (a regime base is the all-MONOTONE,
  closed case).
- Phase 1 stopgaps (items 1 and 2) are independent of everything and should
  be the first commit.

Release mapping: v0.6.2 = Phase 0; v0.7.0 = Phases 1 and 2; v0.8.0 = Phase 3
with Phase 4 docs; v0.8.1 flips the schema default to GUARDED.

---

## 5. Decisions needed

1. **Refactor or patch (Phase 1).** Recommendation: do the parsed-sentence
   refactor. The surgical fixes remove the quadratic term but leave a full
   parse of Γ per node, and the RDF layer needs non-string atoms anyway.
2. **Default robustness for onto schemas.** Recommendation: keep EXACT in
   v0.7 with the field written explicitly, flip to GUARDED in v0.8.1. The
   alternative (flip immediately) changes the meaning of every existing base
   file.
3. **Closure engine.** Recommendation: owlrl for the in-memory backend and
   the `thm:closure` oracle; the store for closure of G at scale; a small
   in-process semi-naive engine for the per-node extras in Phase 3. The
   earlier version of this plan deferred the engine to Phase 5. That would
   have left every proof node paying a full owlrl closure, which caps the
   design at around a million triples. The engine is a few hundred lines
   and is on the critical path.
6. **Which store to target first.** Recommendation: `SPARQLBackend` against
   a GraphDB or RDFox instance with RDFS materialization enabled, because it
   proves the round-trip-bound profile on real data with no adapter work.
   Oxigraph second, as the fast local option for users without a server.
4. **Fate of the onto extension.** Recommendation: keep it through v0.8 with
   converters both ways, reimplement over `RDFBase` in v0.9. Elenchus is
   coupled to the schema API and should not have to change twice.
5. **Multi-succedent over RDF.** `Δ` as a set of triple atoms is the natural
   NMMS reading (disjunction of triples), which has no RDF counterpart.
   Recommendation: support it, document it as strictly more expressive than
   R-entailment, and make the single-succedent case the tutorial path.

---

## 6. Risks

- **Store round-trip latency.** With closure delegated to the store, every
  axiom check is one or more network calls. A query with k connectives
  visits up to ~2.17^k nodes, so at k = 8 that is a few thousand calls, or
  seconds against a remote endpoint. Mitigation: the persistent cache from
  Phase 1, local Oxigraph for latency-sensitive workloads, and the Phase 5
  batching work. Atomic and shallow queries, which dominate real workloads,
  are a handful of calls.
- **Extras-closure correctness.** The semi-naive step over `added` must
  agree with a full closure. Test it against owlrl on the in-memory backend
  for random small `added` sets; the `thm:closure` oracle covers this if the
  Hypothesis test drives queries with connectives, not only atomic ones.
- **Endpoint regime mismatch.** A `SPARQLBackend` declared as RDFS against a
  store that does not materialize RDFS silently underreports entailments.
  The construction-time probe query (a known subclass inference) turns this
  into a loud error.
- **owlrl inconsistency reporting** must be checked before `prop:incoherence` is
  wired to it.
- **Atom grammar tightening** may break user base files with spaces in atom
  names. Ship a `pynmms migrate` check that reports offending atoms.
- **Test suite growth.** Phase 3 adds a second cross-validation family. Keep
  Hypothesis example counts modest so the suite stays under 30 seconds.
