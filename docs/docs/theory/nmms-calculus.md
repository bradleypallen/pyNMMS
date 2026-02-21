# The NMMS Calculus

This page describes the theoretical foundations of pyNMMS, following Hlobil & Brandom (2025), Chapter 3: "Introducing Logical Vocabulary."

## Overview

NMMS (Non-Monotonic Multi-Succedent) is a sequent calculus for codifying **open reason relations** — consequence relations where Monotonicity ([Weakening]) and Transitivity ([Mixed-Cut]) can fail.

## Material Base (Definition 1)

A material base B = <L_B, |~_B> consists of:

- An **atomic language** L_B
- A **base consequence relation** |~_B ⊆ P(L_B) x P(L_B)

satisfying **Containment**: Gamma ∩ Delta ≠ ∅ implies Gamma |~_B Delta.

The base encodes defeasible material inferences among atomic sentences as axioms.

## Logical Extension

The rules of NMMS extend |~_B to a consequence relation |~ over a logically extended language L (adding ~, ->, &, |). A sequent Gamma => Delta is derivable iff there is a proof tree whose leaves are all axioms (base sequents).

## Structural Rules (Absent)

NMMS **omits** two structural rules:

- **[Weakening]**: Gamma |~ Delta does NOT imply Gamma, A |~ Delta. Adding premises can defeat inferences.
- **[Mixed-Cut]**: Gamma |~ A, Delta and Gamma', A |~ Delta' does NOT imply Gamma, Gamma' |~ Delta, Delta'. Chaining good inferences can yield bad ones.

## Propositional Rules

All rules are Ketonen-style. Multi-premise rules include a third top sequent containing all active formulae from the other premises on the same sides. This compensates for the absence of structural contraction.

### Left Rules

**[L~]** Negation left:

```
    Gamma => Delta, A
    -----------------
    Gamma, ~A => Delta
```

**[L->]** Implication left (3 premises):

```
    Gamma => Delta, A     Gamma, B => Delta     Gamma, B => Delta, A
    -----------------------------------------------------------------
                      Gamma, A -> B => Delta
```

**[L&]** Conjunction left:

```
    Gamma, A, B => Delta
    --------------------
    Gamma, A & B => Delta
```

**[L|]** Disjunction left (3 premises):

```
    Gamma, A => Delta     Gamma, B => Delta     Gamma, A, B => Delta
    -----------------------------------------------------------------
                      Gamma, A | B => Delta
```

### Right Rules

**[R~]** Negation right:

```
    Gamma, A => Delta
    -----------------
    Gamma => Delta, ~A
```

**[R->]** Implication right:

```
    Gamma, A => Delta, B
    --------------------
    Gamma => Delta, A -> B
```

**[R&]** Conjunction right (3 premises):

```
    Gamma => Delta, A     Gamma => Delta, B     Gamma => Delta, A, B
    -----------------------------------------------------------------
                      Gamma => Delta, A & B
```

**[R|]** Disjunction right:

```
    Gamma => Delta, A, B
    --------------------
    Gamma => Delta, A | B
```

## Critical Properties

### Supraclassicality (Fact 2)

CL ⊆ |~ — all classically valid sequents are derivable when the base obeys Containment. The "narrowly logical part" (derivable from Containment alone) is exactly classical propositional logic.

### Conservative Extension (Fact 3 / Prop. 26)

If Gamma ∪ Delta ⊆ L_B, then Gamma |~ Delta iff Gamma |~_B Delta. Adding logical vocabulary does not change base-level reason relations.

### Invertibility (Prop. 27)

All NMMS rules are invertible — the bottom sequent is derivable iff all top sequents are derivable.

### Projection (Theorem 7)

Every sequent Gamma => Delta in the extended language uniquely decomposes into a set of base-vocabulary sequents (AtomicImp) such that Gamma => Delta is derivable iff AtomicImp ⊆ |~_B.

## Explicitation Conditions

These biconditionals show how logical vocabulary "makes explicit" reason relations:

- **DD** (Deduction-Detachment): Gamma |~ A -> B, Delta iff Gamma, A |~ B, Delta
- **II** (Incoherence-Incompatibility): Gamma |~ ~A, Delta iff Gamma, A |~ Delta
- **AA** (Antecedent-Adjunction): Gamma, A & B |~ Delta iff Gamma, A, B |~ Delta
- **SS** (Succedent-Summation): Gamma |~ A | B, Delta iff Gamma |~ A, B, Delta

## References

- Hlobil, U. & Brandom, R. B. (2025). *Reasons for Logic, Logic for Reasons*. Chapter 3: "Introducing Logical Vocabulary."
