# Proof Search

## Using the Reasoner

```python
from pynmms import MaterialBase, NMMSReasoner

base = MaterialBase(
    language={"A", "B"},
    consequences={(frozenset({"A"}), frozenset({"B"}))},
)
reasoner = NMMSReasoner(base)
```

### `derives()` — Full Result

```python
result = reasoner.derives(frozenset({"A"}), frozenset({"B"}))
print(result.derivable)      # True
print(result.trace)          # ['AXIOM: A => B']
print(result.depth_reached)  # 0
print(result.cache_hits)     # 0
print(result.nodes)          # 1   distinct proof nodes examined
print(result.connectives)    # 0   connective occurrences in the query
print(result.depth_limited)  # False
```

`result.trace` is a list of strings formatted on access. The underlying
`result.entries` is a list of `TraceEntry` records (`kind`, `depth`,
`sequent`, `rule`, `principal`) for programmatic analysis; formatting a large
antecedent happens only when you ask for the text.

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

## Completeness and Depth

Every NMMS rule replaces one connective occurrence by premises with strictly
fewer connectives, so proof depth is bounded by `result.connectives` and a
sequent can never recur on its own search path. The search is therefore
complete, and `max_depth` is `None` by default.

You can still cap the search:

```python
reasoner = NMMSReasoner(base, max_depth=10)
```

If the cap is hit, that branch returns `False`, `result.depth_limited` is set,
and `derivable == False` is inconclusive. Failures that depended on a cut-off
branch are not memoized, so a truncated search never pollutes the cache.
The CLI prints a warning and reports `"depth_limited": true` in `--json` mode.

## Memoization

The reasoner memoizes subgoals within a query; `cache_hits` reports how many
times a cached result was reused. Proof nodes are keyed on parsed sentences
with the atomic part of each side held as a persistent `AtomSet` (a shared
base plus small diffs), so building, hashing, and comparing a node costs
O(number of atoms the rules moved), not O(|Γ|). Query cost is independent of
the size of the antecedent for atomic and shallow queries.

For many queries against a fixed base, keep the cache across calls:

```python
reasoner = NMMSReasoner(base, persistent_cache=True)
```

The cache is cleared automatically whenever `base.generation` changes, which
every mutation of the base (adding atoms, consequences, or ontology schemas)
increments.
