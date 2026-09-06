# Implication-Space Semantics for RDF

This page states the results of Allen, *Implication-Space Semantics for RDF*
(Transactions on Graph Data and Knowledge, 2026) that `pynmms.rdf` implements,
and maps each to the class or method that realises it. Numbering follows the
paper. The propositional core is described in [NMMS Calculus](nmms-calculus.md);
the ontology extension, which the RDF layer generalises, in
[Ontology Extension](onto-extension.md).

The paper's claim in one sentence: for every entailment regime given by Horn
rules over triples, the implication-space semantics of Hlobil and Brandom,
applied to the base the regime specifies, reproduces the regime's own
entailment relation exactly, inconsistency included. NMMS proof search over
that base is therefore a sound and complete procedure for regime entailment
(the paper's closing conjecture, line 452), and the logical vocabulary NMMS
adds gives RDF what it lacks: negation, conditionals, and a notion of
incoherence.

## 1. Triples as bearers

**Definition 1 (RDF triple).** A generalized RDF triple is any element of
`(I ∪ B ∪ L)³`: IRIs, blank nodes, and literals may occur in every position.

**Definition 19 (RDF triples as bearers).** Every ground triple `t = (s, p, o)`
denotes the bearer `T⟨[[s]], [[p]], [[o]]⟩` of one ternary property `T`. There
is no separate sort of properties: an IRI in predicate position is the same
object it is in subject position.

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

**Definition 9 (entailment regime).** A rule is a pair `⟨A, c⟩` of a finite set
of triples `A` and a conclusion `c` that is a triple or ⊥. A regime `R` over a
vocabulary `V` is a set of rules that is *range-restricted* (every term of `c`
occurs in `A` or in `V`) and *uniform* under substitution of terms for terms.
`cl_R(X)` is the least superset of `X` closed under `R`; `X` is
`R`-inconsistent iff `⊥ ∈ cl_R(X)`; `G` `R`-entails `H` iff `G` is
`R`-inconsistent or `cl_R(G) \ {⊥}` simply entails `H`.

**Remark 10.** In practice `R` is the set of instances of finitely many rule
schemas, which is what makes membership decidable and uniformity automatic.
Side conditions of the form "is a literal" are admitted.

*Implementation.* [`Rule`](../api/rdf-rules.md) is a schema over variables
whose instances are the regime's rules; the constructor enforces range
restriction, and an optional `guard` carries a side condition. `conclusion is
None` is ⊥. `Regime(name, rules, axioms)` bundles schemas with the finite
axiomatic triples. `parse_rule` reads `?x a ex:Alive, ?x a ex:Dead -> false`.
Three regimes ship: `SIMPLE` (no rules), `RDFS` (rdf1, rdfs1, rdfs2 to rdfs13
and the finite axiomatic triples of RDF 1.1 Semantics §9.2), and `OWL2RL` (the
fixed-arity rules of OWL 2 RL/RDF Tables 4 to 9; the list-valued families and
datatype rules are omitted and named in `OWL2RL_OMITTED`).

## 3. Implication-space semantics

**Definition 12 (bearers, implication space, frame).** With `𝔹` the set of
bearers, an implication space is `𝕊 = 𝒫(𝔹) × 𝒫(𝔹)`; a frame `⟨𝔹, 𝕀⟩` fixes
the good implications `𝕀 ⊆ 𝕊`.

**Definition 13 (range of subjunctive robustness).** For `H ⊆ 𝕊`,
`RSR(H) = {⟨x, y⟩ | ∀⟨𝔊, 𝔇⟩ ∈ H : ⟨𝔊 ∪ x, 𝔇 ∪ y⟩ ∈ 𝕀}`: the additions to
premises and conclusions under which every implication in `H` survives. The
implicational role of `H` is `ℛ(H) = {x ⊆ 𝕊 | RSR(H) = RSR(x)}`.

*Implementation.* A material base entry's
[`Robustness`](../api/robustness.md) policy fixes a tractable fragment of its
RSR: `EXACT` is the empty range (only `⟨∅, ∅⟩`), `MONOTONE` is all of `𝕊`,
and `guarded(left, right)` is `𝕊` minus every pair that meets a defeater. The
defeater sets are RSR complements restricted to singleton additions. This is
the answer to the change notes' issue 9: with `EXACT` only, "every TELL is
destructive"; with `guarded`, `Bird |~ Flies` survives `Tall` and is defeated
by `Penguin`.

**Definition 17 (canonical frame).** `𝕀_C = {⟨Γ, Δ⟩ | Γ ∩ Δ ≠ ∅}`: reasoning
"off", a graph implies exactly the triples it contains.

*Implementation.* Containment is the first check in every `is_axiom`, and
the reasoner decides it before consulting any base
(`NMMSReasoner._is_axiom`).

## 4. Contents of graphs and blank nodes

**Definition 21 (content of a ground graph).** `[[G]]` has positive role the
adjunction of its triples' positive roles and negative role the power
symjunction of their negative roles: a graph is read conjunctively.
`[[G]]⁺` is generated by the single pair `⟨𝔅(G), ∅⟩`.

**Definition 22 (graphs with blank nodes).** `[[H]]` is the power symjunction
over the ground instances `μ(H)` of `H` of their positive roles, and the
adjunction of their negative roles: the existential reading of blank nodes,
instance by instance.

**Lemma 30 (Skolemization) and Remark 31.** Replacing blank nodes by fresh
IRIs is sound in the antecedent and unsound in the succedent, where a
Skolemized node can never be a witness.

**Lemma 33 (witness characterization).** In the Herbrand model of a regime
base, `G |~ H` iff `G` is `R`-inconsistent or some instance mapping `μ` sends
`H` into `cl_R(G) \ {⊥}`.

*Implementation.* [`MemoryBackend`](../api/rdf-backends.md) Skolemizes blank
nodes on load, and [`RDFBase.sequent`](../api/rdf-base.md) Skolemizes blank
nodes in antecedent atoms, tracking polarity so that the left operand of an
implication and the operand of a negation count as antecedent position. A
consequent graph with blank nodes is a [`PatternAtom`](../api/rdf-atoms.md)
`<{ t1 . t2 }>`; its axiom check is the witness search of Lemma 33, run by
`match_patterns` over the backend's closure and the per-node extras. A
pattern atom is opaque to the logical rules and is rejected in antecedent
position.

## 5. Bases and models

**Definition 25 (base; model fitness).** A base over `N` has as lexicon the
ground triples over `N` and a relation satisfying Containment. The canonical
base `𝔅_C` is Containment alone. For a regime `R`, the base `𝔅_R` has
`Γ |~ Δ` iff `Γ` is `R`-inconsistent or `Δ ∩ cl_R(Γ) ≠ ∅`. `𝔅_R` is monotone
in both coordinates, closed under Cut, and explosive.

The paper's note at lines 317 to 323 is what motivated Phase 2: a base that
took the rule *instances* as its pairs without closing would validate
`{(a, type, C), (C, subClassOf, D)} |~ (a, type, D)` and not its weakening by
an unrelated triple. That relation corresponds to no regime, and its failure
of monotonicity is "by omission rather than by defeat". The pre-0.7 ontology
extension was exactly that base.

**Definition 26 (induced frame) and Definition 27 (Herbrand model).** A base
`𝔅` induces the frame `𝕀_𝔅 = 𝕀_C ∪ {⟨𝔅(Γ), 𝔅(Δ)⟩ | Γ |~_𝔅 Δ}`; the Herbrand
model `ℳ^RDF_𝔅` interprets every name as itself and every ground triple as the
role of its own bearer.

*Implementation.* [`RDFBase`](../api/rdf-base.md) is a base over `N` with an
intensional lexicon (any well-formed triple is a sentence) and explicit
entries with robustness policies. [`RegimeBase`](../api/rdf-base.md) is
`𝔅_R`. Its `is_axiom` is Containment, then explicit entries, then the regime
clause: `Γ` inconsistent, or some atom of `Δ` in `cl_R(Γ)`. With `Γ` a
[`GraphView`](../api/rdf-view.md) over the backend, `cl_R(Γ)` is the backend's
materialised `cl_R(G)` extended by the per-node extras, closed in process by
[`ClosureEngine.extend`](../api/rdf-closure.md). The step is semi-naive: it
fires only rules with a premise matching a new triple and joins the remaining
premises against the store, so its cost is proportional to the extras and
never to `|G|`.

## 6. Recovery

**Theorem 28 (recovery).** For graphs `G`, `H` over `N`, `G |~^{b_𝔅} H` iff
`G |~ H` in the Herbrand model of `𝔅`: the class of models fit for a base adds
nothing to the base beyond the clause for blank nodes.

**Proposition 34 (incoherence recovery).** `[[G]] |~ ∅` iff `G` is
`R`-inconsistent: the consistency check an OWL 2 RL reasoner performs by
deriving `false` is the semantics' verdict that `[[G]]` is incoherent.

**Theorem 35 (closure regimes).** For an entailment regime `R`, `G |~^{b_R} H`
iff `G` `R`-entails `H`. Read proof-theoretically, this is soundness and
completeness of implication-space semantics for every regime of Definition 9.

**Corollaries 36 to 38.** The empty regime recovers simple entailment; the
RDFS patterns recover RDFS entailment for RDFS-consistent graphs; the OWL 2
RL/RDF rules recover OWL 2 RL entailment, inconsistency included.

*Implementation and test.* The oracle tests in `tests/test_rdf.py` are
Theorem 35 as executable checks: for random small graphs, NMMS derivability of
`G ⇒ t` against `RegimeBase` with the `RDFS` or `OWL2RL` regime is compared
with membership of `t` in the closure computed independently by owlrl, on
every user-vocabulary triple. `RegimeBase.is_inconsistent(extras)` is
Proposition 34, and an inconsistent `Γ` is an axiom for every `Δ`, which is
the explosion of `𝔅_R`. `pynmms rdf ask ... "Γ =>"` with an empty consequent
asks the incoherence question from the command line.

## 7. What the semantics adds to RDF

The regimes occupy an austere corner of implication space: monotone,
single-succedent, closed under Cut, explosive. On them the substructural
machinery of NMMS is idle. The bilateral machinery is not: the
false-concluding rules a regime publishes are recovered as incoherent
positions, and the II condition of NMMS turns them into negation.

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
shapes and `NOT EXISTS` idioms. That is where the base's explicit entries
with `guarded` robustness live, and where the substructural machinery does
its work. The two sit side by side in one `RegimeBase`: the regime part is
monotone and store-resident, the material part is defeasible and indexed by
consequent, and both satisfy Containment, so the metatheory of Chapter 3
applies to the whole.

## 8. Where the implementation stops short

- **Rule families over lists.** The OWL 2 RL rules whose premises range over
  an `rdf:List` of arbitrary length (`intersectionOf`, `unionOf`, `oneOf`,
  `AllDisjointClasses`, property chains, `hasKey`, `AllDifferent`) are rule
  *families* indexed by list length and are not one schema each. They are
  omitted, as are the datatype rules, which need the datatype value spaces.
  Corollary 38 holds for the implemented fragment, and the oracle test covers
  only that fragment.
- **rdfD1.** Datatype-specific literal typing is omitted; rdfs1 is included.
- **The existential of first-order implication-space semantics.** A pattern
  atom is the witness search of Lemma 33, not the `∃` of Hlobil's first-order
  extension. It cannot be decomposed by the logical rules and cannot occur in
  antecedent position.
- **Closure at scale.** The in-memory backend computes `cl_R(G)` in process,
  which is linear in `|G|` and paid once at load. For graphs beyond a few
  hundred thousand triples the closure belongs in the store; the SPARQL
  backend expects the endpoint to materialise its declared regime and checks
  it with a probe query. Push-down of the extras step into the store's own
  rule engine is future work.

## References

- Bradley P. Allen. *Implication-Space Semantics for RDF*. Transactions on
  Graph Data and Knowledge, 2026.
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
