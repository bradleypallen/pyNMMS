# Proof Search

## Using the Reasoner

```python
from pynmms import MaterialBase, NMMSReasoner

base = MaterialBase(
    language={"A", "B"},
    consequences={(frozenset({"A"}), frozenset({"B"}))},
)
reasoner = NMMSReasoner(base, max_depth=25)
```

### `derives()` — Full Result

```python
result = reasoner.derives(frozenset({"A"}), frozenset({"B"}))
print(result.derivable)      # True
print(result.trace)          # ['AXIOM: A => B']
print(result.depth_reached)  # 0
print(result.cache_hits)     # 0
```

### `query()` — Boolean Only

```python
reasoner.query(frozenset({"A"}), frozenset({"B"}))  # True
```

## Reading Proof Traces

The trace records every rule application and axiom closure:

```python
result = reasoner.derives(frozenset(), frozenset({"A -> B"}))
for line in result.trace:
    print(line)
```

Output:
```
[R→] on A -> B
  AXIOM: A => B
```

Trace entries include:
- `AXIOM: Gamma => Delta` — leaf of the proof tree (base axiom or containment)
- `[L¬] on ~A` — left negation rule applied
- `[L→] on A -> B` — left implication rule (3 premises)
- `[L∧] on A & B` — left conjunction rule
- `[L∨] on A | B` — left disjunction rule (3 premises, Ketonen pattern)
- `[R¬] on ~A` — right negation rule
- `[R→] on A -> B` — right implication rule
- `[R∧] on A & B` — right conjunction rule (3 premises, Ketonen pattern)
- `[R∨] on A | B` — right disjunction rule
- `FAIL: Gamma => Delta` — no rule could close this branch
- `DEPTH LIMIT` — maximum proof depth exceeded

## Depth Limit

The `max_depth` parameter (default 25) prevents infinite proof search:

```python
reasoner = NMMSReasoner(base, max_depth=10)
```

If the depth limit is reached, the proof search returns `False` for that branch.

## Memoization

The reasoner uses memoization to avoid re-proving identical subgoals. The `cache_hits` field in `ProofResult` reports how many times a cached result was reused.
