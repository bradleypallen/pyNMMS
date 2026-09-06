# Reasoning over RDF

`pynmms.rdf` runs NMMS proof search with an RDF graph as the antecedent. It
implements the implication-space semantics for RDF (Allen, *Implication-Space
Semantics for RDF*, unpublished manuscript): triples are the atomic bearers, an entailment regime
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
`--trace`, `--batch`, and `--max-depth` work as for `pynmms ask`. Use
`--regime owl2rl` for the OWL 2 RL/RDF rules (see below). Prefixes come from
the loaded files; declare any others with `--prefix ex=http://ex.org/`
(repeatable). A prefixed name whose prefix is not bound is an error rather
than a silently wrong IRI, which matters for a file that declares no prefixes
(an empty Turtle file, for instance) or for a SPARQL endpoint.

### Adding triples and an interactive session

```bash
pynmms rdf tell -g birds.ttl "<ex:kim a ex:Bird>, <ex:kim ex:name \"Kim\"@en>"
pynmms rdf repl -g birds.ttl --regime rdfs
rdf> ask <ex:kim a ex:Animal>
rdf> tell <ex:kim ex:hasChild ex:pip>
rdf> ask <ex:pip a ex:Person>
rdf> save
```

`tell` parses the file, adds the triples, and writes it back in the same
format. The REPL keeps the graph in memory (with its closure maintained
incrementally) until you `save`.

### Blank nodes in the consequent

A consequent may be a *pattern atom* whose blank nodes are existential
variables, written `<{ t1 . t2 . ... }>`:

```bash
pynmms rdf ask -g birds.ttl --regime rdfs '<{ _:b a ex:Bird . _:b ex:name "Tweety"@en }>'
```

This asks whether *some* individual is a Bird named Tweety, the witness
search of Lemma 33 in the paper. Blank nodes in an antecedent are Skolemized
(Lemma 30); a bare triple atom with a blank node in the consequent denotes
that specific node and is never entailed, so use the pattern form there. A
pattern atom is opaque to the logical rules: it can be combined with
connectives but not decomposed, and it cannot appear in antecedent position.

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

Defeaters can be conjunctive: `guarded(exclusions=[(frozenset({penguin, injured}), frozenset())])`
is defeated only when both atoms are present. On the command line that is
`unless <...> & <...>`.

Endpoints do not expose their prefix declarations, so give `SPARQLBackend`
the prefixes your queries use (`prefixes={"ex": "http://ex.org/"}`). A name
such as `ex:tweety` with no bound prefix is an error, not the IRI `ex:tweety`.

## How the closure is split

The regime base checks `Γ |~ Δ` as "Γ is inconsistent or Δ meets `cl_R(Γ)`".
The backend holds `cl_R(G)` for the stored graph; the per-node extras (the
handful of triples a proof rule moved into Γ) are closed by an in-process
semi-naive step that fires only rules with a premise matching a new triple
and joins the rest against the store. Python work per node is proportional
to the extras, never to `|G|`.

On a remote store the join is batched: for each rule firing, the premises
that must come from the store are sent as one `SELECT` through
`backend.join()`, so a firing costs one round trip rather than one per
premise per candidate. `RegimeBase.batched = False` restores per-lookup
firing, which is what procedural (list-walking) rules always use.

## Backends

| Backend | Use | Closure |
|---------|-----|---------|
| `MemoryBackend(graph, regime=...)` | files, tests, development | computed in-process at load |
| `SPARQLBackend(url, regime=..., prefixes={...}, update_endpoint=...)` | a running store | whatever the store materialises; pass `probe=` to verify; `add()` inserts in chunked `INSERT DATA` updates; `join()` batches rule premises into one query |
| `OxigraphBackend(path, regime=...)` | fast local store (needs `oxrdflib`) | computed in-process at load |

Blank nodes in the loaded graph are Skolemized (sound in the antecedent,
Lemma 30 of the paper); blank nodes in a consequent go in a pattern atom.

## Shipped regimes

- `SIMPLE`: no rules, so `Γ |~ Δ` is Containment (simple entailment, Corollary 36).
- `RDFS`: rdf1, rdfs1, rdfD1 (literal typing) and rdfs2 to rdfs13 with the
  finite RDFS axiomatic triples (Corollary 37).
- `OWL2RL`: RDFS plus the fixed-arity OWL 2 RL/RDF rules of Tables 4 to 9
  (Corollary 38): equality (`owl:sameAs`, `differentFrom`), property
  characteristics (functional, inverse-functional, irreflexive, symmetric,
  asymmetric, transitive, inverse, equivalent, disjoint), negative property
  assertions, class restrictions (someValuesFrom/allValuesFrom/hasValue,
  max-cardinality 0 and 1), class axioms (subClassOf, equivalentClass,
  disjointWith, complementOf, `owl:Nothing`), and the schema rules. The
  false-concluding rules among these are exactly the published
  incompatibilities Proposition 34 recovers. The rule families over
  `rdf:List` arguments (`intersectionOf`, `unionOf`, `oneOf`,
  `AllDisjointClasses`, `AllDisjointProperties`, property chains, `hasKey`,
  `AllDifferent`) are implemented procedurally. Not implemented: the datatype
  rules and the axiomatic-only rules `eq-ref`, `cls-thing`, `cls-nothing1`;
  `OWL2RL_OMITTED` lists them.

`custom(name, rules, extends=RDFS)` adds your rules on top.

## From the ontology extension

`onto_to_graph(base)` turns an `OntoMaterialBase` into an RDF graph: `C(x)`
becomes `x rdf:type C`, `R(x,y)` becomes `x R y`, and the schemas become
`rdfs:subClassOf`, `rdfs:range`, `rdfs:domain`, `rdfs:subPropertyOf`,
`owl:disjointWith`, and `owl:propertyDisjointWith` triples. `onto_to_rules`
returns a rule for each `jointCommitment`, and `consequences_to_triples`
carries the ground consequences over with their robustness policies. Schema
triples are read monotonically by a regime, so EXACT brittleness and GUARDED
defeaters on schemas are dropped in the conversion; the returned notes say
which, so you can add guarded entries on the `RDFBase` instead.
