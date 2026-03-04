# pyNMMS

[![PyPI](https://img.shields.io/pypi/v/pyNMMS)](https://pypi.org/project/pyNMMS/)
[![Python](https://img.shields.io/pypi/pyversions/pyNMMS)](https://pypi.org/project/pyNMMS/)
[![License](https://img.shields.io/pypi/l/pyNMMS)](https://github.com/bradleypallen/pyNMMS/blob/main/LICENSE)
[![CI](https://github.com/bradleypallen/pyNMMS/actions/workflows/ci.yml/badge.svg)](https://github.com/bradleypallen/pyNMMS/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://bradleypallen.github.io/pyNMMS/)

An automated reasoner for the Non-Monotonic Multi-Succedent (NMMS) sequent calculus from Hlobil & Brandom 2025, Ch. 3.

**[Documentation](https://bradleypallen.github.io/pyNMMS/)** | **[PyPI](https://pypi.org/project/pyNMMS/)** | **[GitHub](https://github.com/bradleypallen/pyNMMS)**

## Installation

```bash
pip install pyNMMS
```

For development:

```bash
git clone https://github.com/bradleypallen/pyNMMS.git
cd pyNMMS
pip install -e ".[dev]"
```

## Quick Start

```python
from pynmms import MaterialBase, NMMSReasoner

# Create a material base with defeasible inferences
base = MaterialBase(
    language={"A", "B", "C"},
    consequences={
        (frozenset({"A"}), frozenset({"B"})),  # A |~ B
        (frozenset({"B"}), frozenset({"C"})),  # B |~ C
    },
)

reasoner = NMMSReasoner(base)

# A derives B (base consequence)
result = reasoner.derives(frozenset({"A"}), frozenset({"B"}))
assert result.derivable  # True

# A does NOT derive C (nontransitivity — no [Mixed-Cut])
result = reasoner.derives(frozenset({"A"}), frozenset({"C"}))
assert not result.derivable  # False

# A, C does NOT derive B (nonmonotonicity — no [Weakening])
result = reasoner.derives(frozenset({"A", "C"}), frozenset({"B"}))
assert not result.derivable  # False

# Classical tautologies still hold (supraclassicality)
result = reasoner.derives(frozenset(), frozenset({"A | ~A"}))
assert result.derivable  # True
```

## CLI

```bash
# Create a base and add consequences
pynmms tell -b base.json --create "A |~ B"
pynmms tell -b base.json "B |~ C"

# Query derivability
pynmms ask -b base.json "A => B"        # DERIVABLE
pynmms ask -b base.json "A => C"        # NOT DERIVABLE
pynmms ask -b base.json "A, C => B"     # NOT DERIVABLE

# Interactive REPL (no quotes needed around commands)
pynmms repl -b base.json
# pynmms> ask A => B
# DERIVABLE
# pynmms> ask A => C
# NOT DERIVABLE
```

## Ontology Extension

The `pynmms.onto` subpackage extends propositional NMMS with ontology axiom schemas (subClassOf, range, domain, subPropertyOf, disjointWith, disjointProperties, jointCommitment), enabling ontology reasoning while preserving nonmonotonicity.

```python
from pynmms.onto import OntoMaterialBase
from pynmms.reasoner import NMMSReasoner

base = OntoMaterialBase(language={"Man(socrates)", "hasChild(alice,bob)"})

# Register ontology axiom schemas
base.register_subclass("Man", "Mortal")       # {Man(x)} |~ {Mortal(x)}
base.register_range("hasChild", "Person")     # {hasChild(x,y)} |~ {Person(y)}
base.register_domain("hasChild", "Parent")    # {hasChild(x,y)} |~ {Parent(x)}
base.register_disjoint("Mortal", "Immortal")  # {Mortal(x), Immortal(x)} |~

r = NMMSReasoner(base, max_depth=15)

r.query(frozenset({"Man(socrates)"}), frozenset({"Mortal(socrates)"}))  # True
r.query(frozenset({"hasChild(alice,bob)"}), frozenset({"Person(bob)"}))  # True

# Nonmonotonic — extra premises defeat ontology inferences
r.query(
    frozenset({"Man(socrates)", "Immortal(socrates)"}),
    frozenset({"Mortal(socrates)"}),
)  # False
```

```bash
# CLI with --onto flag
pynmms tell -b onto_base.json --create --onto "atom Man(socrates)"
pynmms tell -b onto_base.json --onto --batch schemas.txt  # batch with schema lines
pynmms ask -b onto_base.json --onto "Man(socrates) => Mortal(socrates)"
pynmms repl --onto
```

## Key Properties

- **Nonmonotonicity**: Adding premises can defeat inferences (no Weakening)
- **Nontransitivity**: Chaining good inferences can yield bad ones (no Mixed-Cut)
- **Supraclassicality**: All classically valid sequents are derivable
- **Conservative Extension**: Logical vocabulary doesn't change base-level relations
- **Explicitation Conditions**: DD, II, AA, SS biconditionals hold

## Implementation

### Proof search strategy

The reasoner uses root-first backward proof search with memoization and backtracking. This is related to but distinct from the deterministic proof-search procedure in Definition 20 of the Ch. 3 appendix. Definition 20 specifies a deterministic decomposition: find the first complex sentence (alphabetically, left side first), apply the corresponding rule, repeat until all leaves are atomic, then check axioms. Our implementation instead tries each complex sentence in sorted order with backtracking — if decomposing one sentence fails to produce a proof, it backtracks and tries the next. Both approaches are correct because all NMMS rules are invertible (Proposition 27): if a sequent is derivable, any order of rule application will find the proof. Our approach adds memoization and depth-limiting as practical safeguards.

- 8 Ketonen-style propositional rules with third top sequent (compensates for working with sets rather than multisets, per Proposition 21)
- Memoization keyed on `(frozenset, frozenset)` pairs; cycle detection via pre-marking entries as `False` before recursion
- Depth-limited (default 25) to guarantee termination
- Deterministic rule application order (sorted iteration) for reproducible results

### Design decisions

- Propositional core with ontology axiom schemas in `pynmms.onto` subpackage
- Sets (frozensets), not multisets — Contraction is built in (per Proposition 21)
- Sentences represented as strings, parsed on demand by a recursive descent parser producing frozen `Sentence` dataclass AST nodes
- Base consequences use exact syntactic match — no subset/superset matching, which is what enforces the no-Weakening property
- Containment (Γ ∩ Δ ≠ ∅) checked automatically as an axiom schema
- No runtime dependencies beyond the Python standard library

### Known limitations

- Depth limit can cause false negatives for deeply nested valid sequents
- No incremental/persistent cache between queries
- Multi-premise rules ([L→], [L∨], [R∧]) each generate 3 subgoals, giving worst-case exponential branching
- Flat proof trace only — no structured proof tree or proof certificates
- Formula strings re-parsed at each proof step (no pre-compilation)
- Does not implement NMMS\\ctr (contraction-free variant, Section 3.2.3), Monotonicity Box (□, Section 3.3.1), or classicality operator (⌈cl⌉, Section 3.3.2)

### Test suite

512 tests across 20 test files:

- **Propositional core (307 tests)**: Syntax parsing, MaterialBase construction/serialization, individual rule correctness, axiom derivability, structural properties (nonmonotonicity, nontransitivity, supraclassicality, DD/II/AA/SS), soundness audit, CLI integration, logging/tracing, Ch. 3 worked examples, Hypothesis property-based tests, cross-validation against ROLE.jl ground truth
- **Ontology extension (205 tests)**: Ontology sentence parsing, OntoMaterialBase construction/validation, seven ontology schema types (subClassOf, range, domain, subPropertyOf, disjointWith, disjointProperties, jointCommitment), nonmonotonicity and non-transitivity of schemas, lazy evaluation, NMMSReasoner integration, CommitmentStore, CLI `--onto` integration, JSON output/exit codes, batch mode, annotations, legacy equivalence, logging

## Theoretical Background

This implements the NMMS sequent calculus from:

- Hlobil, U., & Brandom, R. B. (2025). Reasons for logic, logic for reasons: Pragmatics, semantics, and conceptual roles. Routledge.

NMMS codifies *open reason relations* — consequence relations where Monotonicity and Transitivity can fail. The material base encodes defeasible material inferences among atomic sentences, and the Ketonen-style logical rules extend this to compound sentences while preserving nonmonotonicity.

## License

MIT
