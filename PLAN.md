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
Definition 19 encodes every triple as one ternary property `T(s, p, o)`. The
onto extension's `C(x)` and `R(x,y)` are the special cases `T(x, rdf:type, C)`
and `T(x, R, y)`. Schema statements such as `subClassOf(C, D)` are themselves
triples `T(C, rdfs:subClassOf, D)` and belong in the *antecedent*, not at a
meta level. The RDF layer should therefore be the general case and the onto
extension a surface syntax over it.

**(b) A regime base is defined by closure, and it is monotone, cut-closed and
explosive.** Definition 25: `Γ |~_R Δ` iff Γ is R-inconsistent or
`Δ ∩ cl_R(Γ) ≠ ∅`. Theorem 35 and Corollaries 36 to 38 show this recovers
simple entailment, RDFS entailment and OWL 2 RL exactly, inconsistency
included (Proposition 34). NMMS has no Cut, so chaining cannot be left to the
proof rules: a regime base must compute the closure inside `is_axiom`. The
paper explicitly conjectures (line 452) that NMMS over `B_R` is a sound and
complete calculus for R-entailment. That is the theorem pyNMMS should
instantiate and test.

**(c) The current exact-match schema semantics "corresponds to no regime."**
Lines 317 to 323: a base that takes rule *instances* as its pairs without
closing validates `{(a,type,C), (C,subClassOf,D)} |~ (a,type,D)` but not its
weakening by an unrelated triple, and "its failure of monotonicity is by
omission rather than by defeat." This is issue 9 in the change notes, stated
formally. Definition 13 (range of subjunctive robustness, RSR) supplies the
right replacement: a base entry should carry the set of premise/conclusion
additions under which it survives. The `rsrlib.py` defeater set is the
antecedent-side complement of an RSR.

**(d) Blank nodes are asymmetric.** Lemma 30 and Remark 31: Skolemization is
sound in the antecedent and unsound in the succedent. Lemma 33 gives the
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
and `RegimeBase`, `pynmms rdf ask`, the owlrl oracle test for Theorem 35, and
`bench/rdf_scale.py`. Slice 2 (same day) added: `OWL2RL` regime (fixed-arity rules of Tables
4–9 with an owlrl oracle test; list-valued families and datatype rules
omitted and listed in `OWL2RL_OMITTED`), rule guards and rdfs1,
`PatternAtom` for blank-node consequents with polarity-aware Skolemization
of antecedent blank nodes, `pynmms rdf tell` and `pynmms rdf repl`,
`rdf/convert.py`, and `OxigraphBackend`. Still open: a live-endpoint test
for `SPARQLBackend`, the omitted OWL 2 RL rules, rdfD1.

Goal: `Γ ⇒ Δ` where Γ is an RDF graph and the base is a regime of
Definition 9, at a scale set by the graph store rather than by Python. rdflib
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
3. **`RDFBase`**: a general base over ground triples (Definition 25) with
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
   development, tests, and the Theorem 35 oracle), `SPARQLBackend` (any
   endpoint via rdflib `SPARQLStore`; closure is whatever the endpoint's
   regime provides, declared at construction and checked by a probe query),
   and `OxigraphBackend` via `oxrdflib` for a fast local store without a
   regime, paired with the in-process closure engine. RDFox and GraphDB are
   reached through `SPARQLBackend`; native adapters are Phase 5. All backends
   log load counts, Skolemized blank node counts, closure size and time, and
   per-query round-trip counts and latency for post-run analysis.
6. **Blank nodes.** Antecedent graphs are Skolemized on load (rdflib
   `Graph.skolemize()`, sound by Lemma 30). A succedent graph with blank nodes
   is wrapped as a single `PatternAtom(H)` whose axiom check is the Lemma 33
   witness search, run as a SPARQL `ASK` through the backend with blank
   nodes as variables; on a store that materializes the regime this is one
   round trip regardless of |G|. A ground succedent graph is the conjunction of its
   triple atoms and goes through `R∧` as usual. `PatternAtom` is opaque to the
   logical rules; the paper's existential extension is out of scope.
7. **Incoherence.** `Γ ⇒ ∅` returns True iff the regime derives `⊥`
   (Proposition 34). Verify how owlrl surfaces inconsistency for OWL 2 RL
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
10. **Test oracle from the paper.** Theorem 35 makes rdflib plus owlrl a ground
   truth: for random small graphs G, H over a fixed vocabulary, NMMS
   derivability of `G ⇒ H` against `RegimeBase(RDFS)` must equal "owlrl
   closure of G contains an instance of H", and `G ⇒ ∅` must equal owlrl
   inconsistency. This is the same pattern as `test_cross_validation_role.py`
   and should be a Hypothesis test. Corollary 36 (simple entailment) gives a
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
   Theorem 28 and 35; Proposition 34; each stated once and mapped to the class
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
  of multi-premise rules run concurrently.
- Bulk TELL against a store-backed base: streaming inserts with a generation
  bump per batch rather than per triple, and a closure-maintenance hook so
  the store's materialization is kept current by the store, not by pyNMMS.
- General RSR beyond singleton defeaters: entries carrying arbitrary
  `⟨x, y⟩` exclusion pairs; whether this indexes cleanly is open. (Done in
  slice 1: it does, the guard is O(|exclusions|).)
- Reimplement `OntoMaterialBase` on top of `RDFBase` and retire the parallel
  schema matcher.
- The paper's existential extension for blank nodes in the succedent.
- `owl:sameAs` as symmetric substitution commitments (paper, Remark 11).

---

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
   the Theorem 35 oracle; the store for closure of G at scale; a small
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
  for random small `added` sets; the Theorem 35 oracle covers this if the
  Hypothesis test drives queries with connectives, not only atomic ones.
- **Endpoint regime mismatch.** A `SPARQLBackend` declared as RDFS against a
  store that does not materialize RDFS silently underreports entailments.
  The construction-time probe query (a known subclass inference) turns this
  into a loud error.
- **owlrl inconsistency reporting** must be checked before Proposition 34 is
  wired to it.
- **Atom grammar tightening** may break user base files with spaces in atom
  names. Ship a `pynmms migrate` check that reports offending atoms.
- **Test suite growth.** Phase 3 adds a second cross-validation family. Keep
  Hypothesis example counts modest so the suite stays under 30 seconds.
