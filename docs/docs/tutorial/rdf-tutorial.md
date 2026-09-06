# Reasoning over RDF

`pynmms.rdf` runs NMMS proof search with an RDF graph as the antecedent. It
implements the implication-space semantics for RDF (Allen, *Implication-Space
Semantics for RDF*, TGDK): triples are the atomic bearers, an entailment regime
specifies a base by closure, and the NMMS connectives give you negation,
conditionals, and incoherence over that base. Install the extra first:

```bash
pip install "pyNMMS[rdf]"
```

## Atoms are triples

A triple is written as a *quoted atom* `<s p o>`. Prefixes come from the graph
you load, and `a` abbreviates `rdf:type`:

```
<ex:tweety a ex:Bird>
<ex:bob ex:hasChild ex:kim>
<ex:tweety ex:name "Tweety"@en>
```

Internally every atom is a `TripleAtom`, a `str` whose value is the canonical
name with full IRIs, so two names are equal exactly when the triples are.

## Command line

Given `birds.ttl`:

```turtle
@prefix ex: <http://ex.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Bird rdfs:subClassOf ex:Animal .
ex:Animal rdfs:subClassOf ex:Thing .
ex:hasChild rdfs:range ex:Person .
ex:tweety a ex:Bird .
```

```bash
# simple entailment: only what is asserted
pynmms rdf ask -g birds.ttl "<ex:tweety a ex:Bird>"            # DERIVABLE
pynmms rdf ask -g birds.ttl "<ex:tweety a ex:Thing>"           # NOT DERIVABLE

# RDFS entailment: the regime's closure is the base
pynmms rdf ask -g birds.ttl --regime rdfs "<ex:tweety a ex:Thing>"                    # DERIVABLE
pynmms rdf ask -g birds.ttl --regime rdfs "<ex:bob ex:hasChild ex:kim> => <ex:kim a ex:Person>"

# logical vocabulary over the graph
pynmms rdf ask -g birds.ttl --regime rdfs "<ex:x a ex:Bird> -> <ex:x a ex:Animal>"   # DERIVABLE
```

A query is `antecedent => consequent`; the graph is always part of the
antecedent. Without `=>` the whole query is the consequent. `--json`, `-q`,
`--trace`, `--batch`, and `--max-depth` work as for `pynmms ask`.

### Custom rules and incoherence

Rules are Horn clauses over triple patterns, one per line; a conclusion of
`false` makes the rule false-concluding (Definition 9 of the paper):

```
# rules.txt
?x a ex:Alive, ?x a ex:Dead -> false
?x ex:parentOf ?y -> ?y ex:childOf ?x
```

```bash
pynmms rdf ask -g birds.ttl --regime rdfs --rules rules.txt \
    "<ex:tweety a ex:Alive>, <ex:tweety a ex:Dead> =>"           # DERIVABLE: incoherent
pynmms rdf ask -g birds.ttl --regime rdfs --rules rules.txt \
    "<ex:tweety a ex:Alive> => ~<ex:tweety a ex:Dead>"           # DERIVABLE: negation as incoherence
pynmms rdf ask -g birds.ttl --regime rdfs --rules rules.txt \
    "~<ex:tweety a ex:Dead>"                                     # NOT DERIVABLE
```

The second query is the II condition at work: `Γ |~ ¬A` iff `Γ, A |~ ∅`. RDF
has no negation; the regime's incompatibilities plus the NMMS rules supply
one (Proposition 34 and Section 4 of the paper).

## Python API

```python
from rdflib import Graph
from pynmms import NMMSReasoner
from pynmms.rdf import RDFS, RegimeBase, Resolver, parse_rule
from pynmms.rdf.backends import MemoryBackend
from pynmms.rdf.rules import custom

g = Graph().parse("birds.ttl")
rule = parse_rule("?x a ex:Alive, ?x a ex:Dead -> false", Resolver(g))
regime = custom("rdfs+incompat", [rule], extends=RDFS)

backend = MemoryBackend(g, regime=regime)      # materialises cl_R(G) once
base = RegimeBase(backend)
reasoner = NMMSReasoner(base, persistent_cache=True)

seq = base.sequent(["<ex:tweety a ex:Alive>"], ["~<ex:tweety a ex:Dead>"])
print(reasoner.derives_sequent(seq).derivable)   # True
```

`base.sequent(antecedent, consequent)` builds `G, antecedent ⇒ consequent`
with `G` as a `GraphView`: a reference to the backend plus the few atoms the
proof rules add. Pass `include_graph=False` to reason over the listed
sentences alone.

Explicit material inferences with robustness policies work as in the
propositional core, with triple atoms as the sentences:

```python
from pynmms.rdf import TripleAtom
from pynmms.robustness import guarded

bird, flies, penguin = (TripleAtom.from_name(f"<ex:tweety a ex:{c}>", base.resolver)
                        for c in ("Bird", "Flies", "Penguin"))
base.add_consequence(frozenset({bird}), frozenset({flies}), robustness=guarded([penguin]))
```

## How the closure is split

The regime base checks `Γ |~ Δ` as "Γ is inconsistent or Δ meets `cl_R(Γ)`".
The backend holds `cl_R(G)` for the stored graph; the per-node extras (the
handful of triples a proof rule moved into Γ) are closed by an in-process
semi-naive step that fires only rules with a premise matching a new triple
and joins the rest against the store. Python work per node is proportional
to the extras, never to `|G|`.

## Backends

| Backend | Use | Closure |
|---------|-----|---------|
| `MemoryBackend(graph, regime=...)` | files, tests, development | computed in-process at load |
| `SPARQLBackend(url, regime=...)` | a running store | whatever the store materialises; pass `probe=` to verify |

Blank nodes in the loaded graph are Skolemized (sound in the antecedent,
Lemma 30 of the paper). Blank nodes in a *consequent* are not yet supported.

## Shipped regimes

- `SIMPLE`: no rules, so `Γ |~ Δ` is Containment (simple entailment, Corollary 36).
- `RDFS`: rdf1 and rdfs2 to rdfs13 with the finite RDFS axiomatic triples
  (Corollary 37). The literal-typing rules rdfs1 and rdfD1 are omitted.

`custom(name, rules, extends=RDFS)` adds your rules on top.
