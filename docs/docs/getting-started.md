# Getting Started

## Installation

```bash
pip install pyNMMS
```

For development:

```bash
git clone https://github.com/bradleyallen/nmms-reasoner.git
cd nmms-reasoner
pip install -e ".[dev]"
```

## Your First Material Base

A **material base** encodes defeasible material inferences among atomic sentences.

```python
from pynmms import MaterialBase, NMMSReasoner

# Create a base: "rain" defeasibly implies "wet ground"
base = MaterialBase(
    language={"rain", "wet_ground", "covered"},
    consequences={
        (frozenset({"rain"}), frozenset({"wet_ground"})),
    },
)
```

## Querying Derivability

```python
reasoner = NMMSReasoner(base)

# Does rain derive wet ground?
result = reasoner.derives(frozenset({"rain"}), frozenset({"wet_ground"}))
print(result.derivable)  # True

# Nonmonotonicity: adding "covered" defeats the inference
result = reasoner.derives(
    frozenset({"rain", "covered"}),
    frozenset({"wet_ground"})
)
print(result.derivable)  # False — no weakening!
```

## Using the CLI

```bash
# Create a base
pynmms tell -b mybase.json --create "rain |~ wet_ground"

# Query it
pynmms ask -b mybase.json "rain => wet_ground"        # DERIVABLE
pynmms ask -b mybase.json "rain, covered => wet_ground"  # NOT DERIVABLE

# Interactive REPL
pynmms repl -b mybase.json
```

## Next Steps

- [Key Concepts](tutorial/concepts.md) — understand material bases, nonmonotonicity, and sequents
- [Proof Search](tutorial/proof-search.md) — how the reasoner works and how to read traces
- [CLI Usage](tutorial/cli-usage.md) — full guide to the Tell/Ask CLI and REPL
