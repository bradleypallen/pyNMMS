# Material Bases

## Creating a Base

### Via Python API

```python
from pynmms import MaterialBase

# From constructor
base = MaterialBase(
    language={"A", "B", "C"},
    consequences={
        (frozenset({"A"}), frozenset({"B"})),
        (frozenset({"B"}), frozenset({"C"})),
    },
)

# Incrementally
base = MaterialBase()
base.add_atom("A")
base.add_atom("B")
base.add_consequence(frozenset({"A"}), frozenset({"B"}))
```

### Via CLI

```bash
pynmms tell -b mybase.json --create "atom A"
pynmms tell -b mybase.json "atom B"
pynmms tell -b mybase.json "A |~ B"
```

## Checking Axioms

The `is_axiom` method checks whether a sequent is an axiom of the base:

```python
base.is_axiom(frozenset({"A"}), frozenset({"A"}))  # True (Containment)
base.is_axiom(frozenset({"A"}), frozenset({"B"}))  # True (base consequence)
base.is_axiom(frozenset({"A", "X"}), frozenset({"B"}))  # False (no weakening)
```

## Serialization

Bases can be saved to and loaded from JSON:

```python
# Save
base.to_file("mybase.json")

# Load
base = MaterialBase.from_file("mybase.json")

# Dict round-trip
data = base.to_dict()
base = MaterialBase.from_dict(data)
```

### JSON Format

```json
{
  "language": ["A", "B", "C"],
  "consequences": [
    {"antecedent": ["A"], "consequent": ["B"]},
    {"antecedent": ["B"], "consequent": ["C"]}
  ]
}
```

## Validation

The base enforces that all sentences are atomic:

```python
# This raises ValueError:
MaterialBase(language={"~A"})  # Negation is not atomic
MaterialBase(consequences={(frozenset({"A -> B"}), frozenset({"C"}))})  # Implication is not atomic
```
