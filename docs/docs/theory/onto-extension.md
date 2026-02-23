# The NMMS_Onto Extension: Schema-Level Macros for Material Inferential Commitments

## 1. Introduction

NMMS (Non-Monotonic Multi-Succedent) provides a proof-theoretic framework for codifying **open reason relations** -- consequence relations where Monotonicity ([Weakening]) and Transitivity ([Mixed-Cut]) can fail. Hlobil & Brandom (2025), Chapter 3 ("Introducing Logical Vocabulary"), develops the propositional fragment: a sequent calculus whose eight Ketonen-style rules extend an arbitrary material base B = <L_B, |~_B> to a full propositional consequence relation |~. The calculus enjoys Supraclassicality, Conservative Extension, Invertibility, and a Projection theorem reducing derivability to base-level axiom checking.

NMMS_Onto is an **ontology engineering extension** that enriches the material base with schema-level macros for expressing material inferential commitments and incompatibilities. The extension adds no new proof rules: the same eight propositional rules apply unchanged. Instead, six ontology schema types -- `subClassOf`, `range`, `domain`, `subPropertyOf`, `disjointWith`, `disjointProperties` -- are registered as schematic patterns that the material base evaluates lazily when checking whether a sequent is an axiom. Because the extension operates entirely at the level of the base, all of Hlobil's proofs for the propositional calculus are preserved without modification.

The vocabulary is borrowed from W3C RDFS and OWL for familiarity, but the semantics are those of NMMS: exact-match defeasibility, no weakening, no transitivity. These are not limitations to be worked around -- they are the defining features of the NMMS framework that make it suitable for modeling open reason relations.

The resulting system, NMMS_Onto, occupies a distinctive niche: it supports defeasible ontological reasoning (class hierarchies, role constraints, property hierarchies, concept and property incompatibilities) within a framework where adding premises can defeat inferences and chaining good inferences can yield bad ones -- precisely the features that distinguish NMMS from classical and monotonic nonclassical logics.

### 1.1 Discursive Context: Schemas in the Game of Giving and Asking for Reasons

The intended use of NMMS_Onto is modeling **ontological commitments** within a **game of giving and asking for reasons** (Brandom 1994). The six schema types capture common patterns of **classificatory discursive practice**: asserting that something falls under a concept (`subClassOf`), that a role relates two individuals (`range`, `domain`, `subPropertyOf`), and that certain commitments are materially incompatible (`disjointWith`, `disjointProperties`). These are not abstract formal specifications imposed from outside -- they codify the inferential commitments that competent practitioners undertake when they classify, relate, and distinguish things in a domain.

When coupled with a dialogue system like **Elenchus**, the schemas provide the **structured vocabulary layer** that lets the system recognize classificatory patterns in a respondent's natural language commitments and map them to material inferential commitments in the base. A respondent who asserts "Socrates is a man" undertakes a commitment that Elenchus can recognize as an instance of `Man(socrates)`, which then interacts with registered schemas (e.g., `subClassOf(Man, Mortal)`) to determine what further commitments the respondent is committed to and what commitments would be incompatible with what they have asserted.

This positions NMMS_Onto not as a standalone formal ontology specification language but as a component of a larger **inferentialist knowledge engineering practice** -- one where ontological structure is articulated through the material inferential commitments that practitioners recognize, rather than through model-theoretic stipulation of what exists.


## 2. Design Decision: Axiom Extensions, Not Proof Rules

The central architectural decision in NMMS_Onto is to extend the material base rather than the proof rules. To appreciate why this matters, it helps to recall the structure of NMMS proof trees.

An NMMS proof tree has two kinds of nodes:

- **Leaves (axioms)**: Sequents that hold by virtue of the base alone. These are checked by `is_axiom(Gamma, Delta)`, which succeeds if (a) Gamma and Delta overlap (Containment), or (b) the pair (Gamma, Delta) is explicitly in |~_B (exact match).

- **Internal nodes (rule applications)**: Sequents derived by applying one of the eight Ketonen-style propositional rules to reduce a complex sequent to simpler subgoals. The rules decompose logical connectives (~, ->, &, |) until only atomic sentences remain.

Hlobil's Chapter 3 proofs -- Supraclassicality (Fact 2), Conservative Extension (Fact 3 / Prop. 26), Invertibility (Prop. 27), and the Projection Theorem (Theorem 7) -- are established for **any** material base satisfying the Containment axiom (Definition 1). The proofs make no assumptions about the internal structure of base-level axioms beyond Containment. This means that any extension of |~_B that preserves Containment automatically inherits all of these results.

NMMS_Onto exploits this observation. The six ontology schemas add new pairs to the base consequence relation |~_B. Each schema generates axioms of the form {s} |~ {t} (for inferential commitment schemas) or {s, t} |~ {} (for incompatibility schemas) where s and t are atomic sentences. Since the inferential commitment schemas produce pairs with disjoint singleton antecedent and consequent sets, and the incompatibility schemas produce pairs with empty consequent, none of these conflict with Containment (which only requires that overlapping pairs be included). The schemas therefore extend |~_B while preserving Containment, and all of Hlobil's metatheoretic results carry over without any additional proof work.

By contrast, introducing new **proof rules** -- for instance, unrestricted quantifier rules [forall-L], [forall-R], [exists-L], [exists-R] -- would modify the internal structure of proof trees. This would require:

1. Re-establishing Invertibility for the new rules.
2. Re-proving the Projection Theorem with a modified AtomicImp decomposition.
3. Verifying that Supraclassicality and Conservative Extension still hold with the expanded rule set.
4. Ensuring that the third-top-sequent pattern (which compensates for the absence of structural contraction) interacts correctly with the new rules.

None of this work is necessary for NMMS_Onto, because the proof rules are left unchanged. The ontology schemas are visible only to the axiom checker, not to the proof search engine.

**Implementation consequence**: In `pyNMMS`, the `NMMSReasoner` class from the propositional core works without modification with `OntoMaterialBase`. No subclassing of the reasoner is required. The only change is that `OntoMaterialBase.is_axiom()` adds a third axiom check (Ax3: ontology schema match) after the standard Ax1 (Containment) and Ax2 (explicit base consequence).


## 3. The NMMS_Onto Material Base

An NMMS_Onto material base B_Onto = <L_B, |~_B, S> extends the standard NMMS material base with a set S of ontology schemas that serve as macros for generating material inferential commitments and incompatibilities. The atomic language L_B is partitioned into two syntactic categories:

**ABox assertions** (ground facts about individuals):

- **Concept assertions**: `C(a)` -- individual `a` belongs to concept `C`. Examples: `Man(socrates)`, `Happy(alice)`, `HeartAttack(patient)`.
- **Role assertions**: `R(a,b)` -- individual `a` stands in role `R` to individual `b`. Examples: `hasChild(alice,bob)`, `hasSymptom(patient,chestPain)`.

**TBox schemas** (schema-level macros for material inferential commitments and incompatibilities):

The TBox consists of six ontology schema types. Each schema is evaluated lazily at query time -- not eagerly grounded over all known individuals. All schemas use **exact match** (no weakening), which is what preserves nonmonotonicity.

### 3.1 subClassOf(C, D)

**Schema**: For any individual x,

    {C(x)} |~_B {D(x)}

**Intended reading**: Being a C is a defeasible material inferential commitment to being a D.

**Example**: `subClassOf(Man, Mortal)` generates the axiom `{Man(socrates)} |~ {Mortal(socrates)}` for any individual `socrates`, without needing to enumerate all individuals in advance.

### 3.2 range(R, C)

**Schema**: For any individuals x, y,

    {R(x,y)} |~_B {C(y)}

**Intended reading**: Standing in role R to something carries a defeasible material inferential commitment that the second argument is a C.

**Example**: `range(hasChild, Person)` generates `{hasChild(alice,bob)} |~ {Person(bob)}` -- if alice has a child bob, then bob is (defeasibly) a Person.

### 3.3 domain(R, C)

**Schema**: For any individuals x, y,

    {R(x,y)} |~_B {C(x)}

**Intended reading**: Standing in role R to something carries a defeasible material inferential commitment that the first argument is a C.

**Example**: `domain(hasChild, Parent)` generates `{hasChild(alice,bob)} |~ {Parent(alice)}` -- if alice has a child, then alice is (defeasibly) a Parent.

### 3.4 subPropertyOf(R, S)

**Schema**: For any individuals x, y,

    {R(x,y)} |~_B {S(x,y)}

**Intended reading**: An R-assertion carries a defeasible material inferential commitment to the corresponding S-assertion.

**Example**: `subPropertyOf(hasChild, hasDescendant)` generates `{hasChild(alice,bob)} |~ {hasDescendant(alice,bob)}` -- if alice has child bob, then alice (defeasibly) has descendant bob.

### 3.5 disjointWith(C, D)

**Schema**: For any individual x,

    {C(x), D(x)} |~_B {}

**Intended reading**: Being a C and being a D are materially incompatible. This is an incompatibility commitment -- the empty consequent means the pair of premises is incoherent.

Incompatibility is foundational in Brandom's framework: it is prior to negation, not derived from it. The `disjointWith` schema directly encodes material incompatibility between concepts without routing through negation.

**Example**: `disjointWith(Alive, Dead)` generates `{Alive(socrates), Dead(socrates)} |~ {}` -- being alive and being dead are incompatible for any individual.

### 3.6 disjointProperties(R, S)

**Schema**: For any individuals x, y,

    {R(x,y), S(x,y)} |~_B {}

**Intended reading**: Standing in role R and role S to the same pair of individuals is materially incompatible.

**Example**: `disjointProperties(employs, isEmployedBy)` generates `{employs(alice,bob), isEmployedBy(alice,bob)} |~ {}` -- alice cannot both employ bob and be employed by bob.


## 4. Containment Preservation

**Claim**: If B = <L_B, |~_B> satisfies Containment, then the extended base B_Onto = <L_B, |~_B union S_ground> also satisfies Containment, where S_ground denotes the set of all ground instances of the registered ontology schemas.

**Proof sketch**: Containment requires that Gamma |~_B Delta whenever Gamma intersection Delta is nonempty. We must show two things:

1. **The original Containment pairs are preserved**: B_Onto extends |~_B, so all original pairs remain.

2. **The new schema pairs do not violate Containment**: Each inferential commitment schema adds pairs of the form ({s}, {t}) where s and t are distinct atomic sentences (e.g., s = `Man(socrates)` and t = `Mortal(socrates)` for a subClassOf schema). Since s != t, we have {s} intersection {t} = empty, so these pairs are in the region where Containment is silent. Each incompatibility schema adds pairs of the form ({s, t}, {}) where s and t are distinct atomic sentences. Since the consequent is empty, {s, t} intersection {} = empty, so again Containment is silent. Adding pairs where Containment is silent cannot violate the requirement that pairs with nonempty intersection are included.

More precisely, Containment states: for all Gamma, Delta in P(L_B), if Gamma intersection Delta != empty then Gamma |~_B Delta. The ontology schemas only add pairs where the intersection **is** empty. So the condition "if Gamma intersection Delta != empty then Gamma |~_B Delta" is unaffected: the "if" side is unchanged (no new Gamma, Delta with nonempty intersection are introduced that were not already covered), and the "then" side is only strengthened (more pairs are in |~_B, not fewer).

**Corollary**: Since B_Onto satisfies Containment, all of the following results from Hlobil & Brandom (2025), Ch. 3, hold for NMMS_Onto without modification:

- **Fact 2 (Supraclassicality)**: CL is a subset of |~. All classically valid sequents are derivable.
- **Fact 3 / Proposition 26 (Conservative Extension)**: If Gamma union Delta is a subset of L_B, then Gamma |~ Delta iff Gamma |~_B Delta. Logical vocabulary does not alter base-level reason relations.
- **Proposition 27 (Invertibility)**: All NMMS rules are invertible.
- **Theorem 7 (Projection)**: Every sequent in the logically extended language decomposes into a set of base-vocabulary sequents (AtomicImp) such that derivability reduces to checking AtomicImp against |~_B.


## 5. Key Properties

### 5.1 Defeasibility

All ontology schemas are **defeasible**: adding premises to the antecedent side of a derivable sequent can defeat the inference. This is because the `is_axiom` check uses exact match -- a schema `{C(x)} |~ {D(x)}` matches only when the antecedent is exactly `{C(x)}` and the consequent is exactly `{D(x)}`, with no additional sentences on either side.

**Example**: With `subClassOf(Man, Mortal)`:

- `{Man(socrates)} |~ {Mortal(socrates)}` -- derivable (schema match).
- `{Man(socrates), Immortal(socrates)} |~ {Mortal(socrates)}` -- **not derivable**. The antecedent `{Man(socrates), Immortal(socrates)}` does not match the schema's singleton antecedent pattern.

This is not a bug but a feature: learning that Socrates is immortal defeats the defeasible inference that he is mortal. The exact-match semantics of the material base (inherited from Hlobil's framework) is what makes this possible without any explicit defeat mechanism or priority ordering.

### 5.2 Non-transitivity

Because NMMS lacks [Mixed-Cut], chaining two individually valid schema applications does not yield a valid inference. Schemas compose only when the intermediate step is explicitly recorded in the base as an axiom.

**Example**: With `subClassOf(Man, Mortal)` and `subClassOf(Mortal, Physical)`:

- `{Man(socrates)} |~ {Mortal(socrates)}` -- derivable (first schema).
- `{Mortal(socrates)} |~ {Physical(socrates)}` -- derivable (second schema).
- `{Man(socrates)} |~ {Physical(socrates)}` -- **not derivable**. There is no axiom matching `({Man(socrates)}, {Physical(socrates)})`, and backward proof search cannot chain the two schemas because the calculus lacks [Mixed-Cut].

Similarly, `subPropertyOf(hasChild, hasDescendant)` and `subPropertyOf(hasDescendant, hasRelative)` do not jointly entail `{hasChild(alice,bob)} |~ {hasRelative(alice,bob)}`.

This distinguishes NMMS_Onto from systems where `subClassOf` is transitive. In NMMS_Onto, if one wants the transitive closure, one must explicitly register each link: `subClassOf(Man, Mortal)`, `subClassOf(Man, Physical)`, and `subClassOf(Mortal, Physical)` as separate schemas. This is by design -- some subclass chains should compose, and others should not, depending on the domain.

### 5.3 Incompatibility as Foundational

The `disjointWith` and `disjointProperties` schemas encode **material incompatibility** directly, without routing through negation. In Brandom's inferentialist framework, incompatibility is prior to negation: two commitments are incompatible when holding both leads to incoherence (empty consequent). Negation is then understood in terms of incompatibility, not the other way around.

**Example**: With `disjointWith(Alive, Dead)`:

- `{Alive(socrates), Dead(socrates)} |~ {}` -- the pair is incoherent (schema match).
- This incompatibility is **defeasible**: `{Alive(socrates), Dead(socrates), Zombie(socrates)} |~ {}` is **not** an axiom. The extra premise `Zombie(socrates)` defeats the incompatibility, because the antecedent no longer exactly matches the schema pattern.

This models a natural reasoning pattern: being alive and being dead are ordinarily incompatible, but in certain contexts (zombies, theological resurrection) the incompatibility may not hold.

### 5.4 Lazy Evaluation

Ontology schemas are stored as abstract patterns and evaluated lazily during `is_axiom` checks. This means:

- **Storage**: O(k) schemas, where k is the number of registered schemas. Not O(n * k) ground entries, where n is the number of known individuals.
- **Adding individuals**: O(1). When a new individual enters the language (e.g., `Man(plato)` is added), no schema re-expansion or re-grounding is needed. The schema `subClassOf(Man, Mortal)` will automatically match `{Man(plato)} |~ {Mortal(plato)}` at query time.
- **Query time**: Each `is_axiom` call iterates over the registered schemas and attempts pattern matching against the concrete antecedent and consequent. For singleton pairs (the only ones inferential commitment schemas generate), this is O(k) per axiom check.

This lazy evaluation strategy avoids the combinatorial explosion that would arise from eagerly grounding all schemas over all known individuals, especially in bases with many individuals and many schemas.

### 5.5 Deduction-Detachment Theorem (DDT)

The DDT -- Gamma |~ A -> B, Delta iff Gamma, A |~ B, Delta -- is a property of the proof rules ([R->] and [L->]), not of the base. Since NMMS_Onto does not modify the proof rules, DDT holds automatically.

**Example**: With `subClassOf(Man, Mortal)`:

- `{Man(socrates)} |~ {Mortal(socrates)}` is derivable (schema match).
- Therefore, by DDT, `{} |~ {Man(socrates) -> Mortal(socrates)}` is also derivable.

The backward proof proceeds: [R->] decomposes `{} => {Man(socrates) -> Mortal(socrates)}` into `{Man(socrates)} => {Mortal(socrates)}`, which is an axiom via the subClassOf schema. This means that NMMS_Onto can express ontology schema relationships as object-language implications -- the logical vocabulary "makes explicit" the defeasible material inferences encoded in the schemas.


## 6. Schemas as Macros: No New Reasoning Capabilities

It is important to emphasize that NMMS_Onto schemas add **no new reasoning capabilities** to the NMMS framework. They are macros -- convenient shorthand for generating families of ordinary base axioms. Everything that can be expressed with a schema could equally be expressed by manually adding the corresponding ground axioms to the base.

The value of schemas is purely ergonomic:

- **Conciseness**: A single `subClassOf(Man, Mortal)` schema replaces potentially many ground axioms `{Man(socrates)} |~ {Mortal(socrates)}`, `{Man(plato)} |~ {Mortal(plato)}`, etc.
- **Open-endedness**: Schemas apply to individuals not yet known at registration time. When a new individual appears in the language, the schema automatically generates the corresponding axiom without explicit registration.
- **Ontological vocabulary**: The schema names (`subClassOf`, `range`, `domain`, `subPropertyOf`, `disjointWith`, `disjointProperties`) provide a familiar vocabulary for expressing common patterns of material inferential commitment and incompatibility.

But the underlying reasoning mechanism is unchanged: the same eight Ketonen-style propositional rules, the same backward proof search, the same axiom checking. The schemas simply expand the set of pairs that count as axioms.


## 7. What NMMS_Onto Does NOT Include

To be explicit about the boundaries of the extension:

- **No unrestricted quantifiers**: NMMS_Onto does not add universal or existential quantifier rules (forall-L, forall-R, exists-L, exists-R). Hlobil identifies fundamental problems with unrestricted quantification in nonmonotonic settings: unrestricted forall-R overgeneralizes from specific instances, and unrestricted forall-L smuggles in defeating information via universal instantiation. NMMS_Onto avoids these problems entirely by working at the schema level rather than adding quantifier proof rules.

- **No ALL/SOME proof rules**: Unlike ALC-style restricted quantifier extensions, NMMS_Onto does not include proof rules for restricted universal (`ALL R.C`) or restricted existential (`SOME R.C`) expressions. These would require new internal proof tree nodes, revalidation of Invertibility and Projection, and careful treatment of the third-top-sequent pattern. The ontology schema approach achieves useful ontological reasoning without this complexity.

- **No transitive closure**: `subClassOf` and `subPropertyOf` are not transitively closed. Each link must be explicitly registered. This is a consequence of the absence of [Mixed-Cut] and is a deliberate design feature of the NMMS framework.

- **No concept intersection, union, or complement**: NMMS_Onto does not support complex concept expressions such as `C AND D`, `C OR D`, or `NOT C`. The propositional connectives (~, &, |, ->) are available in the proof rules and can combine atomic sentences, but there is no mechanism for constructing complex concepts from simpler ones within the ontology schema language itself.

- **No cardinality restrictions or nominals**: Features such as `MIN n R.C`, `MAX n R.C`, `EXACTLY n R.C`, or `{a}` (nominals) from expressive DLs (SHOIN, SROIQ) are not included.

- **No role characteristics**: NMMS_Onto does not support role transitivity, symmetry, reflexivity, inverseness, functionality, or role chains as built-in features. If `R` should be symmetric, both `{R(a,b)} |~ {R(b,a)}` and `{R(b,a)} |~ {R(a,b)}` must be registered as explicit ground consequences or handled through additional schemas.


## 8. Assumptions and Open Questions

### Assumptions

1. **Containment suffices**: The Containment axiom (Definition 1 in Ch. 3) is the only structural requirement on the material base. We assume that Hlobil's proofs depend on no other properties of |~_B beyond Containment and the specific form of the proof rules. This assumption is supported by the text of Ch. 3, which states the results for "any material base satisfying Containment."

2. **Exact match is the right notion of defeasibility**: The schemas use singleton antecedent and singleton consequent (for inferential commitment schemas) or pair antecedent and empty consequent (for incompatibility schemas) with no weakening. This means that *any* additional premise defeats the inference or incompatibility. In practice, one might want finer-grained defeat: `{Man(socrates), Greek(socrates)} |~ {Mortal(socrates)}` might be desired even though the schema only directly generates the singleton-antecedent form. Users can accommodate this by adding explicit ground consequences for the desired multi-premise patterns.

3. **Propositional connectives are sufficient for logical structure**: The claim is that the six ontology schemas, combined with propositional connectives via the eight proof rules, provide adequate expressive power for a useful fragment of ontological reasoning. This is an empirical claim that depends on the intended applications.

### Open Questions

1. **Schema interaction principles**: Should there be systematic rules for how schemas interact? For instance, should `subClassOf(C, D)` and `domain(R, C)` jointly entail anything about `R` and `D`? In classical ontology languages, they do (via monotonic closure). In NMMS_Onto, they do not, by design. But are there principled middle grounds -- forms of controlled interaction that preserve the nonmonotonic character while recovering some useful entailments?

2. **Retraction semantics**: The `CommitmentStore` supports retracting schemas by source label. What are the formal properties of retraction? Does retracting a schema correspond to a well-defined operation on the consequence relation? How does retraction interact with cached proof results?

3. **NMMS and KLM as different normative projects**: The defeasible description logic literature (Casini & Straccia 2010, Giordano et al. 2013) works with preferential and rational consequence relations from the KLM framework. NMMS and KLM are asking **different questions**. KLM asks what a rational agent should believe by default -- it models defeasible inference through preferential models and rational closure, where exceptions are handled by minimizing abnormality. NMMS asks what an agent is **committed to** given specific reasons -- it codifies material inferential commitments, not default beliefs. The two frameworks operate at different levels of the normative landscape: KLM at the level of idealized rational belief revision, NMMS at the level of discursive practice and the commitments one undertakes in making assertions. The interesting question is not embedding one framework in the other but understanding what each makes explicit about reasoning practice.

4. **Adequacy as a question about discursive practice, not model correspondence**: In an inferentialist framework, **the proof theory is the semantics** -- meaning is constituted by inferential role, not by correspondence to model-theoretic structures. The question of completeness relative to a model-theoretic semantics presupposes that meaning is fixed by models, which is precisely what inferentialism rejects. The more appropriate question for NMMS_Onto is whether the six schema types adequately capture the material inferential commitments that competent practitioners would recognize as constitutive of ontological vocabulary -- whether `subClassOf`, `range`, `domain`, `subPropertyOf`, `disjointWith`, and `disjointProperties` suffice for the classificatory discursive practices one encounters in knowledge engineering. This is an empirical question about discursive practice, not a mathematical question about model correspondence.

5. **Scaling properties**: The lazy evaluation strategy avoids combinatorial explosion in schema grounding, but the proof search itself has exponential worst-case complexity (due to the multi-premise Ketonen rules for [L->], [L|], [R&]). How does the addition of ontology schemas affect proof search performance in practice? Are there heuristics for ordering schema checks to improve average-case behavior?


## 9. References

- Brandom, R. B. (1994). *Making It Explicit: Reasoning, Representing, and Discursive Commitment*. Harvard University Press.

- Hlobil, U. & Brandom, R. B. (2025). *Reasons for Logic, Logic for Reasons*. Chapter 3: "Introducing Logical Vocabulary."

- Casini, G. & Straccia, U. (2010). Rational Closure for Defeasible Description Logics. In *Proceedings of the 12th European Conference on Logics in Artificial Intelligence (JELIA)*, pp. 77--90. Springer.

- Giordano, L., Gliozzi, V., Olivetti, N., & Pozzato, G. L. (2013). A Non-Monotonic Description Logic for Reasoning About Typicality. *Artificial Intelligence*, 195, 165--202.
