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

The `dev` extra installs pytest, pytest-cov, Hypothesis, ruff, and mypy. Without it the property-based test module is skipped. `make check` runs lint, type check, and tests.

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

## Reasoning over RDF

The `rdf` extra (`pip install "pyNMMS[rdf]"`) adds `pynmms.rdf`: NMMS over an RDF graph, following the implication-space semantics for RDF (Allen, unpublished manuscript). Triples are the atoms, an entailment regime (simple, RDFS, or OWL 2 RL, plus your own Horn rules) specifies the base by closure, and the NMMS connectives give negation and conditionals over the graph; blank nodes in a consequent are existential pattern atoms:

```bash
pynmms rdf ask -g birds.ttl --regime rdfs "<ex:tweety a ex:Thing>"
pynmms rdf ask -g birds.ttl --regime rdfs --rules rules.txt "<ex:tweety a ex:Alive> => ~<ex:tweety a ex:Dead>"
```

The `oxigraph` extra (`pip install "pyNMMS[oxigraph]"`) adds `OxigraphBackend`: an embedded [Oxigraph](https://github.com/oxigraph/oxigraph) store, in memory or on disk, that materialises the regime with its own SPARQL engine (several times faster than the in-process closure) and keeps the closure across sessions; `pynmms rdf ask --oxigraph DIR -g data.ttl --regime rdfs ...` loads once and later runs reopen the store.

The graph stays in a backend (in-memory rdflib or a SPARQL endpoint); the antecedent is a reference to it plus the few triples proof rules add, so per-query cost is independent of graph size. See the [RDF tutorial](https://bradleypallen.github.io/pyNMMS/tutorial/rdf-tutorial/).

## Robustness Policies

Every base consequence and ontology schema carries a robustness policy: `exact` (the default; any added premise defeats it), `monotone` (survives any addition), or `guarded` by named defeaters (survives any addition except a defeater). This is the range-of-subjunctive-robustness idea of Hlobil & Brandom (Ch. 5) restricted to singleton additions, and it separates relevant defeat from arbitrary defeat:

```bash
pynmms tell -b birds.json --create "Bird |~ Flies unless Penguin"
pynmms ask -b birds.json "Bird, Tall => Flies"      # DERIVABLE
pynmms ask -b birds.json "Bird, Penguin => Flies"   # NOT DERIVABLE
pynmms tell -b onto.json --create --onto --batch - <<< "schema subClassOf Bird Flies unless Penguin"
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

- `max_depth`, if set, can cause false negatives; the search is complete when it is left unset (the default), since depth is bounded by the query's connective count, and `ProofResult.depth_limited` reports when a cap was hit
- The persistent cache (`persistent_cache=True`) is invalidated wholesale on any base mutation; there is no incremental cache maintenance
- Multi-premise rules ([L→], [L∨], [R∧]) each generate 3 subgoals, giving worst-case exponential branching
- Flat proof trace (a list of `TraceEntry` records) — no proof tree or proof certificates
- MONOTONE/GUARDED `range`, `domain`, and incompatibility schemas must scan Γ for a role or partner atom (O(|Γ|) per check); `subClassOf`, `subPropertyOf`, `jointCommitment`, and all EXACT schemas are O(1) index lookups
- Does not implement NMMS\\ctr (contraction-free variant, Section 3.2.3), Monotonicity Box (□, Section 3.3.1), or classicality operator (⌈cl⌉, Section 3.3.2)

### Test suite

780 tests across 36 test files:

- **Propositional core (390 tests)**: Syntax parsing (including the strict atom grammar and quoted atoms), AtomSet/Sequent proof-node structures, robustness policies (exact/monotone/guarded) on base entries, MaterialBase construction/serialization, individual rule correctness, axiom derivability, structural properties (nonmonotonicity, nontransitivity, supraclassicality, DD/II/AA/SS), soundness audit, CLI integration, logging/tracing, Ch. 3 worked examples, Hypothesis property-based tests, cross-validation against ROLE.jl ground truth, differential testing of the rewritten reasoner against a frozen copy of v0.6.2 on random bases and sequents (propositional and ontology, all entries exact)
- **Ontology extension (225 tests)**: Ontology sentence parsing, OntoMaterialBase construction/validation, seven ontology schema types (subClassOf, range, domain, subPropertyOf, disjointWith, disjointProperties, jointCommitment), nonmonotonicity and non-transitivity of schemas, schema robustness policies and indexing, lazy evaluation, NMMSReasoner integration, CommitmentStore, CLI `--onto` integration, JSON output/exit codes, batch mode, annotations, legacy equivalence, logging
- **RDF extension (165 tests)**: TripleAtom canonical names and escaping, GraphView diffs and invalidation, closure engine (RDFS, OWL 2 RL, false-concluding rules), RegimeBase (closure entailment, extras closure, negation as incoherence, explosion), pattern atoms for blank-node consequents, Skolemization, agreement with owlrl on random RDFS and OWL 2 RL graphs including list constructs (`thm:closure` oracle), converters from the ontology extension, `pynmms rdf ask/tell/repl` CLI, a live test of the SPARQL backend against an in-process endpoint, and a Hypothesis oracle that the per-node extras closure equals a full closure of the graph plus extras under RDFS and OWL 2 RL, and the Oxigraph backend (closure materialised in the store by SPARQL rule updates, agreement with MemoryBackend and owlrl, incremental add, on-disk persistence, `--oxigraph` CLI), and the position API (a holder's assertions, denials, and withdrawals as speech acts over the store as background, with verdicts naming the entry responsible and the defeater that would rescue it)

### Benchmarks

`bench/` is a standard-library benchmark package. `make bench` (or `python -m bench`, `--quick` for reduced sizes) runs three sections and writes a JSON record with timestamp, git SHA, and environment to `bench/results/`:

- `antecedent_scaling` — query cost versus antecedent size |Γ|
- `schema_scaling` — axiom-check cost versus number of ontology schemas
- `query_complexity` — proof cost versus number of connectives in the query

The committed records are the regression baseline for reasoner and base changes.

## Theoretical Background

This implements the NMMS sequent calculus from:

- Hlobil, U., & Brandom, R. B. (2025). Reasons for logic, logic for reasons: Pragmatics, semantics, and conceptual roles. Routledge.
- Allen, B. P. (2026). Implication-space semantics for RDF. Unpublished manuscript. The semantics implemented by `pynmms.rdf`: triples as bearers, regime bases by closure, and the recovery theorems that the oracle tests check.

NMMS codifies *open reason relations* — consequence relations where Monotonicity and Transitivity can fail. The material base encodes defeasible material inferences among atomic sentences, and the Ketonen-style logical rules extend this to compound sentences while preserving nonmonotonicity. Robustness policies on base entries fix how far each material inference survives additions to its premises; an RDF entailment regime is the limiting monotone case, specified by closure.


## License

MIT
