# pyNMMS

**Non-Monotonic Multi-Succedent sequent calculus** — propositional NMMS from Hlobil & Brandom 2025, Ch. 3.

pyNMMS implements a proof search engine for the NMMS sequent calculus, which codifies *open reason relations* — consequence relations where Monotonicity and Transitivity can fail.

## Why pyNMMS?

Traditional logics assume that adding premises never defeats an inference (Monotonicity) and that chaining good inferences always yields good inferences (Transitivity). But real-world reasoning is often **defeasible**: new information can override previous conclusions.

pyNMMS provides:

- A **material base** for encoding defeasible inferences among atomic sentences
- **Backward proof search** implementing all 8 propositional NMMS rules
- **Supraclassicality**: all classically valid sequents remain derivable
- A **Tell/Ask CLI** and **interactive REPL** for exploring reason relations
- Full **proof traces** for understanding derivations

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
