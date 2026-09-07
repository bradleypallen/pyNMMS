# Implication-Space Semantics for RDF

This page states the results of Allen, *Implication-Space Semantics for RDF*
(unpublished manuscript, 2026) that `pynmms.rdf` implements, and maps each to
the class or method that realises it. The propositional core is described in
[NMMS Calculus](nmms-calculus.md); the ontology extension, which the RDF layer
generalises, in [Ontology Extension](onto-extension.md).

Results are cited by the manuscript's LaTeX labels, in `monospace`, never by
number: the numbering changes between renderings of the text. Where a human
reader needs a handle, the label is paired with the result's name, as in
Theorem `thm:closure` (Closure regimes).

The paper's claim in one sentence: for every entailment regime given by Horn
rules over triples, the implication-space semantics of Hlobil and Brandom,
applied to the base the regime specifies, reproduces the regime's own
entailment relation exactly, inconsistency included. NMMS proof search over
that base is therefore a sound and complete procedure for regime entailment,
which the paper's discussion states as the expectation that motivates this
implementation, and the logical vocabulary NMMS adds gives RDF what it lacks:
negation, conditionals, and a notion of incoherence.

## 1. Triples as bearers

**`def:rdftriple`.** A generalized RDF triple is any element of
`(I ∪ B ∪ L)³`: IRIs, blank nodes, and literals may occur in every position.

**`def:triplebearers`.** Every ground triple `t = (s, p, o)` denotes the
bearer `T⟨[[s]], [[p]], [[o]]⟩` of one ternary property `T`. There is no
separate sort of properties: an IRI in predicate position is the same object
it is in subject position (`rem:bearermapping`).

*Implementation.* [`TripleAtom(s, p, o)`](../api/rdf-atoms.md) is that bearer.
It is a `str` subclass whose value is the canonical quoted-atom name
`<s p o>`, with IRIs written in full and literals escaped so that the name
contains no `<` or `>`. Two atoms are equal exactly when their triples are,
which is what makes a triple usable as an atom name throughout the
string-typed core: in an `AtomSet`, in a `MaterialBase` entry, in a proof
trace, and in a JSON file. The ontology extension's `C(x)` and `R(x, y)` are
the `rdf:type` fragment of this encoding; [`convert.py`](../api/rdf-convert.md)
performs the translation.

## 2. Regimes

**`def:entailmentregime`.** A rule is a pair `⟨A, c⟩` of a finite set of
triples `A` and a conclusion `c` that is a triple or ⊥. A regime `R` over a
vocabulary `V` is a set of rules that is *range-restricted* (every term of `c`
occurs in `A` or in `V`) and *uniform* under substitution of terms for terms.
`cl_R(X)` is the least superset of `X` closed under `R`; `X` is
`R`-inconsistent iff `⊥ ∈ cl_R(X)`; `G` `R`-entails `H` iff `G` is
`R`-inconsistent or `cl_R(G) \ {⊥}` simply entails `H`.

**`rem:regimeschemas`.** In practice `R` is the set of instances of finitely
many rule schemas, which is what makes membership decidable and uniformity
automatic. Side conditions of the form "is a literal" are admitted.

*Implementation.* [`Rule`](../api/rdf-rules.md) is a schema over variables
whose instances are the regime's rules; the constructor enforces range
restriction, and an optional `guard` carries a side condition. `conclusion is
None` is ⊥. `Regime(name, rules, axioms)` bundles schemas with the finite
axiomatic triples. `parse_rule` reads `?x a ex:Alive, ?x a ex:Dead -> false`.
Three regimes ship: `SIMPLE` (no rules), `RDFS` (rdf1, rdfs1, rdfD1, rdfs2 to
rdfs13 and the finite axiomatic triples of RDF 1.1 Semantics §9.2), and
`OWL2RL` (the rules of OWL 2 RL/RDF Tables 4 to 9, with the families over
`rdf:List` arguments implemented as `ProceduralRule`s; the datatype rules and
the axiomatic-only rules are omitted and named in `OWL2RL_OMITTED`).

## 3. Implication-space semantics

**`def:bearers`.** With `𝔹` the set of bearers, an implication space is
`𝕊 = 𝒫(𝔹) × 𝒫(𝔹)`; a frame `⟨𝔹, 𝕀⟩` fixes the good implications `𝕀 ⊆ 𝕊`.

**`def:roles`.** For `H ⊆ 𝕊`,
`RSR(H) = {⟨x, y⟩ | ∀⟨𝔊, 𝔇⟩ ∈ H : ⟨𝔊 ∪ x, 𝔇 ∪ y⟩ ∈ 𝕀}`: the additions to
premises and conclusions under which every implication in `H` survives. The
implicational role of `H` is the class of sets with the same RSR; adjunction,
symjunction, and power-symjunction are the operations on roles; contents are
pairs of roles.

*Implementation.* A material base entry's
[`Robustness`](../api/robustness.md) policy fixes a tractable fragment of its
RSR: `EXACT` is the empty range (only `⟨∅, ∅⟩`), `MONOTONE` is all of `𝕊`,
and `guarded(left, right, exclusions)` is `𝕊` minus every pair that meets a
singleton defeater in `left` or `right` and minus every pair containing an
exclusion `⟨x, y⟩`. Singleton defeaters and finite conjunctive exclusions
together describe the RSR complement up to finite additions, and the guard
costs a bounded number of membership tests regardless of `|Γ|`. Section 8
says how these entries are read relative to a regime.

**`def:contententailment`, `lem:reduction`, `prop:positional`.** Content
entailment `𝔊 ⊨ 𝔇` holds iff the adjunction of the positive roles of `𝔊`
with the negative roles of `𝔇` lies within `𝕀`; by `lem:reduction` this
depends only on generating sets, and by `prop:positional`, for bearer sets
`Γ, Δ`, it holds iff `⟨Γ, Δ⟩ ∈ 𝕀`.

*Implementation.* NMMS derivability of `Γ ⇒ Δ` computes the right-hand side
of `prop:positional`; `RDFBase.position` builds that sequent from sets of
accepted and rejected graphs (Section 4).

**`def:canonicalframe`, `rem:canonicalframe`.** `𝕀_C = {⟨Γ, Δ⟩ | Γ ∩ Δ ≠ ∅}`:
reasoning "off", a graph implies exactly the triples it contains.

*Implementation.* Containment is the first check in every `is_axiom`, and
the reasoner decides it before consulting any base
(`NMMSReasoner._is_axiom`).

## 4. Contents of graphs and blank nodes

**`def:graphcontents`.** `[[G]]` has positive role the adjunction of its
triples' positive roles and negative role the power symjunction of their
negative roles: a graph is read conjunctively (`rem:graphreading`), and in
succedent position it is the denial of its triples taken jointly.

**`def:existential`.** `[[H]]` is the power symjunction over the ground
instances `μ(H)` of `H` of their positive roles, and the adjunction of their
negative roles: the existential reading of blank nodes, instance by
instance. **`conv:finiteness`** and **`def:admissible`** fix the finite
vocabulary fragment `N` over which instances range.

**`lem:shapes`.** `[[A]]⁺` is generated by the pairs `⟨⋃_{ν∈x} 𝔅(ν(A)), ∅⟩`
and `[[A]]⁻` by the pairs `⟨∅, ⋃_μ S_μ⟩` for a non-empty `S_μ ⊆ 𝔅(μ(A))` at
every `μ`; for a ground graph these reduce to `⟨𝔅(A), ∅⟩` and `⟨∅, S⟩` for
every non-empty `S ⊆ 𝔅(A)`: denial of a graph severally and in every joint
combination.

**`lem:skolem`, `rem:skolem`.** Replacing blank nodes by fresh IRIs is sound
in the antecedent and unsound in the succedent, where a Skolemized node can
never be a witness.

**`lem:witnesschar`.** In the Herbrand model of a regime base, `G ⊨ H` iff
`G` is `R`-inconsistent or some instance mapping `μ` sends `H` into
`cl_R(G) \ {⊥}`. (`lem:witness` supplies the witness coordinate, and
`lem:uniform` the uniformity of closure, that its proof needs.)

*Implementation.* [`MemoryBackend`](../api/rdf-backends.md) Skolemizes blank
nodes on load, and [`RDFBase.sequent`](../api/rdf-base.md) Skolemizes blank
nodes in antecedent atoms, tracking polarity so that the left operand of an
implication and the operand of a negation count as antecedent position. A
consequent graph with blank nodes is a [`PatternAtom`](../api/rdf-atoms.md)
`<{ t1 . t2 }>`; its axiom check is the witness search of `lem:witnesschar`,
run by `match_patterns` over the backend's closure and the per-node extras. A
rejected ground graph in `RDFBase.position` becomes the conjunction of its
triples, so that the Ketonen `R∧` rule with its third premise performs the
joint denial of `lem:shapes`. A pattern atom is opaque to the logical rules
and is rejected in antecedent position.

## 5. Bases and models

**`def:fitness`.** A base over `N` has as lexicon the ground triples over `N`
and a relation satisfying Containment. The canonical base `𝔅_C` is
Containment alone. For a regime `R`, the base `𝔅_R` has `Γ ⊨ Δ` iff `Γ` is
`R`-inconsistent or `Δ ∩ cl_R(Γ) ≠ ∅`. `𝔅_R` is monotone in both
coordinates, closed under Cut, and explosive.

The remark that follows `def:fitness` is what motivated Phase 2 of this
project: a base that took the rule *instances* as its pairs without closing
would validate `{(a, type, C), (C, subClassOf, D)} ⊨ (a, type, D)` and not
its weakening by an unrelated triple. That relation corresponds to no
regime, and its failure of monotonicity is "by omission rather than by
defeat". The pre-0.7 ontology extension was exactly that base.

**`def:inducedframe`, `def:canonicalmodel`.** A base `𝔅` induces the frame
`𝕀_𝔅 = 𝕀_C ∪ {⟨𝔅(Γ), 𝔅(Δ)⟩ | Γ ⊨_𝔅 Δ}`; the Herbrand model `ℳ^RDF_𝔅`
interprets every name as itself and every ground triple as the role of its
own bearer.

*Implementation.* [`RDFBase`](../api/rdf-base.md) is a base over `N` with an
intensional lexicon (any well-formed triple is a sentence) and explicit
entries with robustness policies. [`RegimeBase`](../api/rdf-base.md) is `𝔅_R`,
with `cl_R(G)` materialised in the backend and the per-node extras closed in
process by [`ClosureEngine.extend`](../api/rdf-closure.md), a semi-naive step
whose cost is proportional to the extras and never to `|G|`. With material
entries added it becomes the base of Section 8.

## 6. Recovery

**`thm:recovery`** (Recovery). For graphs `G`, `H` over `N`, `G ⊨^{b_𝔅} H`
iff `G ⊨ H` in the Herbrand model of `𝔅`: the class of models fit for a base
adds nothing to the base beyond the clause for blank nodes.

**`prop:incoherence`** (Incoherence recovery). `[[G]] ⊨ ∅` iff `G` is
`R`-inconsistent: the consistency check an OWL 2 RL reasoner performs by
deriving `false` is the semantics' verdict that `[[G]]` is incoherent.

**`thm:closure`** (Closure regimes). For an entailment regime `R`,
`G ⊨^{b_R} H` iff `G` `R`-entails `H`. Read proof-theoretically, this is
soundness and completeness of implication-space semantics for every regime
of `def:entailmentregime`.

**`cor:simple`, `cor:rdfs`, `cor:owlrl`.** The empty regime recovers simple
entailment; the RDFS patterns recover RDFS entailment for RDFS-consistent
graphs; the OWL 2 RL/RDF rules recover OWL 2 RL entailment, inconsistency
included.

*Implementation and test.* The oracle tests in `tests/test_rdf.py` are
`thm:closure` as executable checks: for random small graphs, NMMS
derivability of `G ⇒ t` against `RegimeBase` with the `RDFS` or `OWL2RL`
regime is compared with membership of `t` in the closure computed
independently by owlrl, on every user-vocabulary triple, list constructs
included. Because NMMS is a conservative extension of its base on atomic
sequents (Chapter 3, Fact 3), this is evidence that the closure base equals
regime entailment on ground triples; it is not a proof.
`RegimeBase.is_inconsistent(extras)` is `prop:incoherence`, and an
inconsistent `Γ` is an axiom for every `Δ`, the explosion of `𝔅_R`.
`pynmms rdf ask ... "Γ =>"` with an empty consequent asks the incoherence
question from the command line.

## 7. What the semantics adds to RDF

The regimes occupy an austere corner of implication space: monotone,
single-succedent, closed under Cut, explosive. On them the substructural
machinery of NMMS is idle. The bilateral machinery is not: the
false-concluding rules a regime publishes are recovered as incoherent
positions (`prop:incoherence`), and the II condition of NMMS turns them into
negation.

```
Γ |~ ¬A   iff   Γ, A |~ ∅
```

So with a rule `?x a ex:Alive, ?x a ex:Dead -> false`, the query
`<ex:t a ex:Alive> => ~<ex:t a ex:Dead>` is derivable and `~<ex:t a ex:Dead>`
alone is not. RDF explicitly omits negation; `pynmms rdf` supplies it from the
incompatibilities practitioners already publish, with no change to the RDF
object language.

What the regimes leave out is the domain knowledge: the material inferences
and their defeat conditions that communities handle today through SHACL
shapes and `NOT EXISTS` idioms. That is where the base's material entries
with `guarded` robustness live, and where the substructural machinery does
its work. Section 8 says how the two layers are read together.

## 8. Proposal: the regime-relative material base `𝔅_{R,I}`

*This section is a proposal, intended for a second paper; it is not a result
of the manuscript. It is implemented in `RegimeBase` as of pyNMMS 0.10.1.*

**The problem.** Through pyNMMS 0.10.0 a `RegimeBase` was the union of two
bases: the closure base `𝔅_R` and a set `I` of material entries with
robustness policies, matched literally. A material entry fired only when
its antecedent was literally present in `Γ`, and a defeater defeated only
when it was literally present. So `Sparrow ⊑ Bird` in the regime and
`Bird ⊢ Flies unless Penguin` in `I` did not make a sparrow fly, and
`EmperorPenguin ⊑ Penguin` did not stop one. The two layers were one closure
apart.

**Definition (regime-relative material base).** Let `R` be a regime and `I`
a set of material entries `⟨A, D; E⟩` with antecedent `A`, consequent `D`,
and defeaters `E`, a set of sets of atoms (a singleton defeater is a
singleton set). A pair `⟨Γ, Δ⟩` is good in `𝔅_{R,I}` iff

1. `Γ` is `R`-inconsistent, or
2. `Δ ∩ cl_R(Γ) ≠ ∅` (the regime layer), or
3. some entry `⟨A, D; E⟩` has
    - `A ⊆ cl_R(Γ)`: the antecedent is derivable, not merely present;
    - no `e ∈ E` with `e ⊆ cl_R(Γ)`: no defeater is derivable;
    - `Δ ∩ cl_R(Γ ∪ D) ≠ ∅`: the consequent is elaborated by the regime.

Policies map onto clause 3: `monotone` is `E = ∅`; `guarded` is `E` as
given; `exact` adds `Γ ⊆ cl_R(A)`, an antecedent `R`-equivalent to `A`.

**Properties.** Containment holds through clause 2, since `Γ ⊆ cl_R(Γ)`, so
`𝔅_{R,I}` is a base in the sense of `def:fitness` and Chapter 3's metatheory
applies to NMMS over it. With `I` empty it is `𝔅_R`. There is still no Cut
between material entries: clause 3 uses one entry, so `Bird ⊢ Flies` and
`Flies ⊢ HasWings` do not make a bird have wings. Monotonicity fails exactly
at the material entries: adding `Penguin(tweety)` to a position that made
`tweety` fly stops it, and that is the point.

**Rationale.** The regime elaborates material inferences at all three
places, antecedent, defeaters, and consequent, and nowhere else; Cut stays
absent between material entries. The defeater check is what current
practice writes as `NOT EXISTS` in a SPARQL query: the query's positive
pattern is the antecedent read through the store's materialised closure, and
the `NOT EXISTS` block is `e ⊆ cl_R(Γ)`. The elaboration of the consequent
is the clause most open to debate, and `RegimeBase.elaborate_consequent`
switches it off so the two readings, `Δ ∩ cl_R(Γ ∪ D)` and `Δ ∩ D`, can be
compared on the same base. A store adapter needs exactly three operations
to serve clause 3, `ASK` for the antecedent, `NOT EXISTS` for the defeaters,
and `ASK` over the closure extended by `D` for the consequent, which is why
this definition precedes the adapter work.

*Implementation.* `RegimeBase.is_axiom` implements the three clauses, with
`cl_R(Γ)` computed once per query and `cl_R(Γ ∪ D)` as its semi-naive
extension by `D`. `tests/test_rdf_material.py` holds the eight cases of the
specification: the sparrow that flies, the emperor penguin that does not,
the irrelevant premise that changes nothing, the consequent elaborated only
with the flag on, the absence of material chaining, the empty-`I` regression
against the closure base and owlrl on five hundred random cases, Containment
on random pairs with entries present, and the documented nonmonotonicity.

## 9. Where the implementation stops short

- **The first-order existential.** A pattern atom is the witness search of
  `lem:witnesschar`, not the `∃` of Hlobil's first-order extension. It cannot
  be decomposed by the logical rules and cannot occur in antecedent
  position.
- **`owl:sameAs`.** `rem:identity` defers identity as substitution. It runs
  only monotonically here, through the OWL 2 RL equality rules.
- **RDF 1.2 triple terms**, which the paper defers.
- **The datatype rules of OWL 2 RL** and the axiomatic-only rules; `cor:owlrl`
  holds for the implemented fragment, and the oracle test covers only that.
- **Closure at scale.** The in-memory backend computes `cl_R(G)` in process,
  which is linear in `|G|` and paid once at load. Beyond a few hundred
  thousand triples the closure belongs in the store.

## 10. Status against the paper's objectives

A snapshot as of pyNMMS 0.10.1.

### 10.1 The paper's results, now executable

| Statement | Implementation |
|---|---|
| `def:triplebearers` | `TripleAtom` |
| `def:entailmentregime`, `rem:regimeschemas` | `Rule`, `Regime`, `parse_rule`; `SIMPLE`, `RDFS`, `OWL2RL`; ⊥ rules |
| `def:fitness` (`𝔅_R`) | `RegimeBase` |
| `def:contententailment`, `prop:positional` | `RDFBase.position` and `pynmms rdf position` |
| `def:graphcontents`, `lem:shapes` | rejected graphs as conjunctions under `R∧` |
| `lem:skolem`, `rem:skolem` | polarity-aware Skolemization |
| `lem:witnesschar` | `PatternAtom` and the witness search |
| `prop:incoherence` | `is_inconsistent`, empty-consequent queries, explosion |
| `thm:closure`, `cor:rdfs`, `cor:owlrl` | oracle tests against owlrl on random RDFS and OWL 2 RL graphs |

The oracle tests exercise `thm:closure`'s base-level content on the
implemented fragment. They are evidence for ground graphs, not a proof.

### 10.2 What the paper points toward, now running

The introduction's motivation was a semantics able to handle negation and
default reasoning, and the discussion claims that a regime's
false-concluding rules become incoherent positions while the substructural
machinery works on the domain knowledge the regimes leave out.

- Negation over RDF from published incompatibilities through the II
  condition, at about 50 µs in memory.
- A home for that domain knowledge as material entries whose robustness
  policies are fragments of `def:roles`'s RSR, read relative to the regime
  by Section 8's `𝔅_{R,I}`.
- Positions as pairs of sets of graphs (`prop:positional`), checked for
  being out of bounds.

### 10.3 What remains open, from the paper's own list

The first-order existential in place of the witness search; `rem:identity`;
RDF 1.2; the datatype rules; the comparison with SHACL that the discussion
invites, planned as a Phase 6 evaluation; and any evaluation on real data.
Every number so far is synthetic.

## References

- Bradley P. Allen. *Implication-Space Semantics for RDF*. Unpublished
  manuscript, 2026.
- Ulf Hlobil and Robert B. Brandom. *Reasons for Logic, Logic for Reasons:
  Pragmatics, Semantics, and Conceptual Roles*. Routledge, 2025.
- Ulf Hlobil. First-order implication-space semantics. *Journal of
  Philosophical Logic*, 55(3):529–554, 2026.
- Patrick J. Hayes and Peter F. Patel-Schneider. *RDF 1.1 Semantics*. W3C
  Recommendation, 2014.
- Boris Motik et al. *OWL 2 Web Ontology Language Profiles* (second edition).
  W3C Recommendation, 2012.
- Herman J. ter Horst. Completeness, decidability and complexity of entailment
  for RDF Schema and a semantic extension involving the OWL vocabulary.
  *Journal of Web Semantics*, 3(2–3):79–115, 2005.
