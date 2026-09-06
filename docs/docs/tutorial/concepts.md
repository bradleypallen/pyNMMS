# Key Concepts

## Material Bases

A **material base** B = <L_B, |~_B> consists of:

- **L_B**: An atomic language — a set of atomic sentence strings (e.g., `"rain"`, `"wet_ground"`)
- **|~_B**: A base consequence relation — a set of sequents (Gamma, Delta) where Gamma and Delta are sets of atomic sentences

The base encodes **defeasible material inferences**: reasoning patterns that hold in normal circumstances but can be overridden by additional information.

### Containment Axiom

Every material base automatically satisfies **Containment**: if Gamma and Delta share any element (Gamma ∩ Delta ≠ ∅), then Gamma |~_B Delta. This is the analogue of the identity axiom in classical logic.

### Exact Match (No Weakening)

By default a base consequence `Γ₀ |~ Δ₀` licenses only the sequent `Γ₀ ⇒ Δ₀` itself: there is no Weakening, so `{A, C} ⇒ B` is not an axiom just because `{A} |~ B` is. This is what makes the base nonmonotonic.

### Robustness Policies

Exact match is the narrowest point on a **range of subjunctive robustness** (Hlobil & Brandom 2025, Ch. 5): the additions to premises and conclusions under which an implication survives. Every entry and ontology schema carries a policy: `exact` (the default), `monotone` (survives any addition; the reading of an RDF entailment regime), or `guarded` by named defeaters (`Bird |~ Flies unless Penguin`: survives any addition except a defeater). Guarded entries distinguish *relevant* defeat from the arbitrary defeat of exact matching. Containment holds whatever the policy, so the NMMS metatheory is unchanged.

## Sequents

A **sequent** Gamma => Delta represents a reason relation: the sentences in Gamma (the antecedent) provide reason for at least one of the sentences in Delta (the succedent).

- **Multi-succedent**: Delta can contain multiple sentences. `Gamma => A, B` means "Gamma provides reason for A-or-B."
- **Empty antecedent**: `=> A` means A is unconditionally assertable.
- **Empty succedent**: `A => ` means A is incoherent (leads to nothing).

## Nonmonotonicity

In NMMS, **adding premises can defeat inferences**. If `{rain} |~ {wet_ground}` but the base has no consequence from `{rain, covered}`, then:

- `rain => wet_ground` is derivable
- `rain, covered => wet_ground` is **not** derivable

This models the everyday pattern: rain normally makes the ground wet, but if the ground is covered, the inference is defeated.

## Nontransitivity

NMMS also lacks **Mixed-Cut** (the structural rule for transitivity). Even if `A |~ B` and `B |~ C`, it does not follow that `A |~ C`. Each inference step must be independently justified by the base.

## Supraclassicality

Despite lacking Weakening and Mixed-Cut, NMMS is **supraclassical**: all classically valid sequents are derivable. The law of excluded middle (`=> A | ~A`), double negation elimination (`~~A => A`), and all classical tautologies hold.

## Explicitation Conditions

The logical connectives "make explicit" reason relations through these biconditionals:

- **DD** (Deduction-Detachment): `Gamma |~ A -> B, Delta` iff `Gamma, A |~ B, Delta`
- **II** (Incoherence-Incompatibility): `Gamma |~ ~A, Delta` iff `Gamma, A |~ Delta`
- **AA** (Antecedent-Adjunction): `Gamma, A & B |~ Delta` iff `Gamma, A, B |~ Delta`
- **SS** (Succedent-Summation): `Gamma |~ A | B, Delta` iff `Gamma |~ A, B, Delta`
