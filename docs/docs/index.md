# pyNMMS

**An automated reasoner for the Non-Monotonic Multi-Succedent (NMMS) propositional sequent calculus** from Hlobil & Brandom 2025, Ch. 3.

pyNMMS implements a proof search engine for the NMMS sequent calculus, which codifies *open reason relations* -- consequence relations where Monotonicity and Transitivity can fail.

## Why pyNMMS?

Traditional logics assume that adding premises never defeats an inference (Monotonicity) and that chaining good inferences always yields good inferences (Transitivity). But real-world reasoning is often **defeasible**: new information can override previous conclusions.

pyNMMS provides:

- A **material base** for encoding defeasible inferences among atomic sentences
- **Backward proof search** implementing all 8 propositional NMMS rules
- **Supraclassicality**: all classically valid sequents remain derivable
- A **Tell/Ask CLI** and **interactive REPL** for exploring reason relations
- Full **proof traces** for understanding derivations
- **Ontology extension** with schema-level macros for material inferential commitments and incompatibilities (subClassOf, range, domain, subPropertyOf, disjointWith, disjointProperties, jointCommitment)
- **Robustness policies** on every base entry and schema: `exact`, `monotone`, or `guarded` by named defeaters, so that relevant defeat (`Penguin` defeats `Bird |~ Flies`) is distinguished from arbitrary defeat
- **Reasoning over RDF** (`pip install "pyNMMS[rdf]"`): triples as atoms, entailment regimes (simple, RDFS, OWL 2 RL, custom rules) as bases specified by closure, the graph kept in a backend so query cost is independent of graph size, and negation over RDF via incoherence, following Allen, *Implication-Space Semantics for RDF*
- **Query cost independent of antecedent size**: proof nodes are persistent diffs over a shared base, sentences are parsed once, and the search is complete without a depth cap

## Quick Example

```python
from pynmms import MaterialBase, NMMSReasoner

base = MaterialBase(
    language={"A", "B", "C"},
    consequences={
        (frozenset({"A"}), frozenset({"B"})),  # A |~ B
        (frozenset({"B"}), frozenset({"C"})),  # B |~ C
    },
)
reasoner = NMMSReasoner(base)

reasoner.query(frozenset({"A"}), frozenset({"B"}))  # True (base consequence)
reasoner.query(frozenset({"A"}), frozenset({"C"}))  # False (nontransitive!)
reasoner.query(frozenset({"A", "C"}), frozenset({"B"}))  # False (nonmonotonic!)
reasoner.query(frozenset(), frozenset({"A | ~A"}))  # True (supraclassical)
```

## Installation

```bash
pip install pyNMMS
```
