# Restricted Quantifiers Tutorial

This tutorial shows how to use the `pynmms.rq` subpackage for reasoning with restricted quantifiers.

## Building an RQ Material Base

```python
from pynmms.rq import RQMaterialBase

# Create a base with concept and role assertions
base = RQMaterialBase(
    language={
        "hasChild(alice,bob)", "hasChild(alice,carol)",
        "Happy(bob)", "Doctor(carol)",
    },
    consequences={
        (frozenset({"hasChild(alice,bob)", "Doctor(bob)"}),
         frozenset({"ParentOfDoctor(alice)"})),
        (frozenset({"hasChild(alice,carol)", "Doctor(carol)"}),
         frozenset({"ParentOfDoctor(alice)"})),
    },
)
```

## Querying with Quantifiers

```python
from pynmms.rq import NMMSRQReasoner

r = NMMSRQReasoner(base, max_depth=20)

# ALL hasChild.Doctor(alice) with trigger bob => ParentOfDoctor(alice)
r.query(
    frozenset({"ALL hasChild.Doctor(alice)", "hasChild(alice,bob)"}),
    frozenset({"ParentOfDoctor(alice)"}),
)  # True

# SOME hasChild.Doctor(alice) with known witness carol
r.query(
    frozenset({"hasChild(alice,carol)", "Doctor(carol)"}),
    frozenset({"SOME hasChild.Doctor(alice)"}),
)  # True
```

## Nonmonotonicity with Quantifiers

```python
base = RQMaterialBase(
    consequences={
        (frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
         frozenset({"ParentHappy(alice)"})),
    },
)
r = NMMSRQReasoner(base, max_depth=15)

# Good inference
r.query(
    frozenset({"hasChild(alice,bob)", "Happy(bob)"}),
    frozenset({"ParentHappy(alice)"}),
)  # True

# Defeated by ALL hasChild.Grumpy — adds Grumpy(bob) to premises
r.query(
    frozenset({
        "hasChild(alice,bob)", "Happy(bob)",
        "ALL hasChild.Grumpy(alice)",
    }),
    frozenset({"ParentHappy(alice)"}),
)  # False
```

## Using Schemas

```python
from pynmms.rq import RQMaterialBase, NMMSRQReasoner

base = RQMaterialBase(language={"hasSymptom(patient,chestPain)"})

# Register a concept schema (lazy — no eager grounding)
base.register_concept_schema("hasSymptom", "patient", "Serious")

# Register an inference schema
base.register_inference_schema(
    "hasSymptom", "patient", "Serious",
    {"HeartAttack(patient)"},
)

r = NMMSRQReasoner(base, max_depth=15)

# Schema fires lazily
r.query(
    frozenset({"hasSymptom(patient,chestPain)", "Serious(chestPain)"}),
    frozenset({"HeartAttack(patient)"}),
)  # True

# Add new individual — schema works without re-grounding
base.add_individual("hasSymptom", "patient", "headache")
r2 = NMMSRQReasoner(base, max_depth=15)
r2.query(
    frozenset({"hasSymptom(patient,headache)", "Serious(headache)"}),
    frozenset({"HeartAttack(patient)"}),
)  # True
```

## Using the CommitmentStore

```python
from pynmms.rq import CommitmentStore, NMMSRQReasoner

cs = CommitmentStore()
cs.add_assertion("hasSymptom(patient,chestPain)")
cs.commit_universal(
    "serious symptoms",
    "hasSymptom", "patient",
    "Serious", "HeartAttack",
)

base = cs.compile()
r = NMMSRQReasoner(base, max_depth=15)
```

## CLI Usage with `--rq`

```bash
# Add RQ atoms
pynmms tell -b rq_base.json --create --rq "atom hasChild(alice,bob)"
pynmms tell -b rq_base.json --rq "hasChild(alice,bob), Doctor(bob) |~ ParentOfDoctor(alice)"

# Query
pynmms ask -b rq_base.json --rq "ALL hasChild.Doctor(alice), hasChild(alice,bob) => ParentOfDoctor(alice)"
pynmms ask -b rq_base.json --rq --trace "hasChild(alice,bob), Doctor(bob) => SOME hasChild.Doctor(alice)"

# Interactive REPL
pynmms repl --rq
```

### RQ REPL commands

```
pynmms[rq]> tell atom hasChild(alice,bob)
pynmms[rq]> tell Happy(alice) |~ Good(alice)
pynmms[rq]> tell schema concept hasChild alice Happy
pynmms[rq]> tell schema inference hasChild alice Serious HeartAttack
pynmms[rq]> ask ALL hasChild.Happy(alice), hasChild(alice,bob) => Happy(bob)
pynmms[rq]> show schemas
pynmms[rq]> show individuals
```
