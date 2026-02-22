# Restricted Quantifier Extension

The `pynmms.rq` subpackage extends propositional NMMS with ALC-style restricted quantifiers (`ALL R.C`, `SOME R.C`), following the semantic framework of Hlobil (2025), "First-Order Implication-Space Semantics."

## Motivation

Standard unrestricted quantifier rules fail in nonmonotonic settings:

- **The `∀R` problem** (Inf-5/Inf-6): Unrestricted `∀R` overgeneralizes from specific instances. If Shakespeare authored great works, `∀R` concludes *everyone* is an important author — generalizing over the entire domain rather than just authors.

- **The `∀L` problem** (Inf-7/Inf-8): Unrestricted `∀L` smuggles in defeating information via universal instantiation. If all bottles in the fridge are empty, `∀L` instantiates over *all* domain objects, bringing in information that defeats defeasible inferences.

Restricted quantifiers (`ALL R.C`, `SOME R.C`) avoid both problems by quantifying only over **role successors** `{b | R(a,b)}` rather than the full domain. This keeps the domain of quantification local to explicit role assertions in the proof context.

## Syntax

```
Individual:              alice, bob, carol, ...
Concept assertion:       Human(alice)
Role assertion:          hasChild(alice,bob)
Universal restriction:   ALL hasChild.Happy(alice)
                         = "all children of alice are Happy"
Existential restriction: SOME hasChild.Doctor(alice)
                         = "some child of alice is a Doctor"
```

Propositional connectives (`~`, `&`, `|`, `->`) work as in the base calculus and can combine with quantified sentences:

```
ALL hasChild.Happy(alice) -> Happy(bob)
ALL hasChild.Happy(alice) | ~ALL hasChild.Happy(alice)
ALL hasChild.Happy(alice) & ALL hasChild.Smart(alice)
```

## The Four Quantifier Rules

### [L∀R.C] — Universal restriction on the left

```
Γ, ALL R.C(a) ⇒ Δ  ←  Γ, {C(b) | R(a,b) ∈ Γ} ⇒ Δ
```

**Adjunction interpretation** (OQ-1, option A): `ALL R.C(a)` as a premise behaves as a generalized conjunction over triggered instances. One subgoal adds all `C(b)` for known R-successors `b`.

**How it avoids the ∀L problem**: Instantiates only for triggered role successors present in `Γ`, not the full domain. No hidden Weakening — no information enters the proof that wasn't already explicitly present as a role assertion.

### [L∃R.C] — Existential restriction on the left

```
Γ, SOME R.C(a) ⇒ Δ  ←  for all nonempty subsets S of {C(b) | R(a,b) ∈ Γ}:
                          Γ, S ⇒ Δ
```

**Ketonen pattern**: All `2^k - 1` nonempty subsets of triggered instances must independently prove the conclusion. This is the restricted analogue of Hlobil's power-symjunction for generalized disjunction.

For binary `L∨` with `{A, B}`, this gives the familiar three top sequents: `{A}`, `{B}`, `{A,B}`. For `n` triggers, we need all `2^n - 1` nonempty subsets.

### [R∃R.C] — Existential restriction on the right

```
Γ ⇒ Δ, SOME R.C(a)
```

Two strategies:

1. **Known witnesses**: For each `b` with `R(a,b) ∈ Γ`, prove `Γ ⇒ Δ, C(b)`.
2. **Fresh canonical witness**: Try `_w_{R}_{C}_{a}` with concept-label blocking (experimental).

### [R∀R.C] — Universal restriction on the right

```
Γ ⇒ Δ, ALL R.C(a)  ←  Γ, R(a,b) ⇒ Δ, C(b)   (b fresh eigenvariable)
```

**How it avoids the ∀R problem**: The eigenvariable represents an arbitrary role successor, not an arbitrary domain element. We only need to show `C(b)` holds for an arbitrary R-successor of `a`, not for every object in the domain.

## Design Decisions

### OQ-1: Adjunction vs. Power-Symjunction for [L∀R.C]

Hlobil's semantic clause for `∀` uses **power-symjunction** (Def. 16), not adjunction. The current implementation uses **adjunction** (option A): one subgoal adding all triggered instances simultaneously.

Arguments for adjunction:

1. Matches propositional `[L∧]` pattern (1 subgoal = multiplicative)
2. Consistent with classical ALC tableau rules
3. Avoids exponential branching (already present in `[L∃R.C]`)
4. The restricted domain mitigates the `∀L` problem that motivated power-symjunction
5. All 10 legacy demo scenarios pass with this interpretation

This is documented as a design choice pending theoretical analysis.

### OQ-2: Blocking Soundness

!!! warning "Experimental"
    Concept-label subset blocking is an experimental conjecture adapted from classical ALC tableau procedures.

Fresh witness `b` is blocked if `concept_label(b) ⊆ concept_label(c)` for some existing individual `c`. This is conjectured to be sound for NMMS because nonmonotonicity arises from the material base (exact match), not from logical rules.

### OQ-3: Empty Trigger Handling

- `ALL R.C(a)` with no triggers: vacuously true as premise, treated as inert (falls through)
- `SOME R.C(a)` with no triggers: treated as inert (safe, potentially incomplete)

## Preserved Properties

All five constraints from the propositional calculus are preserved:

| Property | Description | Status |
|----------|-------------|--------|
| **MOF** | Nonmonotonicity — adding premises defeats inferences | Preserved |
| **SCL** | Supraclassicality — all classically valid sequents derivable | Preserved |
| **DDT** | Deduction-detachment theorem | Preserved |
| **DS** | Disjunction simplification (Ketonen pattern) | Preserved |
| **LC** | Left conjunction is multiplicative | Preserved (with adjunction, OQ-1) |

## Lazy Schema Evaluation

Quantified commitments are stored as **schemas** and evaluated lazily during `is_axiom` checks. No eager grounding over all known individuals.

- **Storage**: `O(k + m)` schemas, not `O(n × (k + m))` ground entries
- **Adding individuals**: `O(1)`, no schema re-expansion needed
- **Query time**: Schemas matched against concrete individuals in each sequent

## References

- Hlobil (2025), "First-Order Implication-Space Semantics," §2 (Inf-5/6/7/8) and §3 (power-symjunction, Proposition 20)
- Hlobil & Brandom (2025), Ch. 3, "Introducing Logical Vocabulary"
