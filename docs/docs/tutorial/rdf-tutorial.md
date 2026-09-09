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
search of `lem:witnesschar` in the paper. Blank nodes in an antecedent are Skolemized
(`lem:skolem`); a bare triple atom with a blank node in the consequent denotes
that specific node and is never entailed, so use the pattern form there. A
pattern atom is opaque to the logical rules: it can be combined with
connectives but not decomposed, and it cannot appear in antecedent position.

### Custom rules and incoherence

Rules are Horn clauses over triple patterns, one per line; a conclusion of
`false` makes the rule false-concluding (`def:entailmentregime` of the paper):

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
one (`prop:incoherence` and the paper's discussion).

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

A third form, `include_graph="background"`, makes Γ the listed triples
alone while the store still supplies the closure: a position over a
background. This is how one record of a large graph is checked for
coherence. Incoherence is attributed to the position that derives it, so a
contradiction elsewhere in the store does not make every query explode;
`RegimeBase.background_inconsistent()` reports the store's own, and
`RegimeBase.attribution = "global"` restores the explosive regime base of
the paper.

Explicit material inferences with robustness policies work as in the
propositional core, with triple atoms as the sentences:

```python
from pynmms.rdf import TripleAtom
from pynmms.robustness import guarded

bird, flies, penguin = (TripleAtom.from_name(f"<ex:tweety a ex:{c}>", base.resolver)
                        for c in ("Bird", "Flies", "Penguin"))
base.add_consequence(frozenset({bird}), frozenset({flies}), robustness=guarded([penguin]))
```

Since 0.10.1 a `RegimeBase` reads material entries *through the regime*: the
antecedent must be derivable (not merely present), no defeater may be
derivable, and the consequent is elaborated by the regime's closure. With
`Sparrow ⊑ Bird` in the graph the entry above makes a sparrow fly, and with
`EmperorPenguin ⊑ Penguin` it stops an emperor penguin. Material entries do
not chain with one another. See the theory page, Section 8.

Defeaters can be conjunctive: `guarded(exclusions=[(frozenset({penguin, injured}), frozenset())])`
is defeated only when both atoms are present. On the command line that is
`unless <...> & <...>`.

Endpoints do not expose their prefix declarations, so give `SPARQLBackend`
the prefixes your queries use (`prefixes={"ex": "http://ex.org/"}`). A name
such as `ex:tweety` with no bound prefix is an error, not the IRI `ex:tweety`.

## Positions: accepted graphs and rejected graphs

The paper's basic object (`def:contententailment`, `prop:positional`) is a *position* ⟨𝔊, 𝔇⟩: a set of graphs accepted
and a set of graphs rejected. The position is out of bounds when the
accepted graphs entail one of the rejected ones, and that is a sequent:
the accepted graphs are read conjunctively and unioned into the antecedent
(blank nodes Skolemized per graph), and each rejected ground graph becomes
the conjunction of its triples in the succedent, which is what the Ketonen
`R∧` rule with its third premise checks "severally and in every joint
combination" (`lem:shapes`). A rejected graph with blank nodes becomes a pattern
atom. Several rejected graphs are alternatives. With nothing rejected, the
question is whether the accepted graphs are incoherent.

```bash
pynmms rdf position -g birds.ttl --regime rdfs --reject claims.ttl
pynmms rdf position -g birds.ttl --rules rules.txt --accept observation.ttl
pynmms rdf position -g birds.ttl --regime rdfs --accept a.ttl --reject r1.ttl --reject r2.ttl --json
```

Exit code 0 means out of bounds, 2 means in bounds. From Python:

```python
seq = base.position(accept=[graph_or_path_or_triples], reject=[another_graph])
reasoner.derives_sequent(seq).derivable   # True: the position is out of bounds
```

Under a monotone regime a rejected ground graph is entailed iff each of its
triples is in the closure; under exact or guarded entries the conjunction
form is what keeps the joint combinations honest, which is why
`position()` expands ground graphs rather than using a pattern atom.

## Values in rules

A rule may carry a guard over the values it binds, in square brackets among
the premises:

```
?x am:maker ?m, ?m rdf:value ?p, ?p am:deathDateEnd ?d, ?x am:productionDateStart ?s,
    [year(?s) > year(?d)] -> ?x am:anachronisticMaker ?p
?a go:evidence ?e, [rank(strength, ?e) >= rank(strength, "IDA")] -> ?a go:strongEvidence "yes"
ordering strength: IEA < ISS < IBA < IMP < IDA
```

Comparisons (`< <= > >= = !=`), `in (...)`, `&& || !`, and the functions
`num`, `year`, `str`, `lang`, `datatype`, `rank`, `isLiteral`, `isIRI`,
`isBlank`. The guard is evaluated two ways that agree: as a SPARQL `FILTER`
when the store materialises the closure, and in Python when the
in-process closure runs. Semantics follow SPARQL: typed numbers and dates
compare as values, plain strings as strings (`num` reads a plain string as
a number, `year` takes the first four characters as a year), and a
comparison across kinds is false. `ordering name: a < b < c` in a rules
file declares an ordering for `rank`. A guard is not uniform under
substitution, so a guarded rule is an admitted exception to
`def:entailmentregime`; see the theory page.

## Material entries as patterns

A material entry may have variables, and its defeaters may be patterns
with their own variables and value guards:

```
?x am:maker ?m, ?m rdf:value ?p |~ ?x am:madeBy ?p unless ?m am:creatorQualifier "naar"
?g go:involved_in ?c, ?c rdfs:subClassOf ?d |~ ?g go:involved_in ?d unless ?g go:not_involved_in ?d
?x am:maker ?m, ?m rdf:value ?p, ?p am:deathDateEnd ?d, ?x am:productionDateStart ?s,
    [year(?s) > year(?d)] |~ false unless ?x am:posthumousImpression "yes"
?x a ex:Bird |~ ?x a ex:HasWings monotone
```

`parse_defeasible_rule(text, resolver)` gives a `DefeasibleRule`, and
`RegimeBase.add_rule` installs it. It fires for a substitution when its
premises join against the closure (guards included), no defeater has a
solution, and its conclusion, elaborated by the regime, meets Δ; `false`
concludes an incompatibility, counted against a position only when the
position's own triples take part. Alternatives are separated by `;`.
Entries do not chain. The harness entry files accept these lines beside
ground ones, and `Position.challenges()` generates probes from them.

### Entry files and the ontology extension as surface syntax

`--entries FILE` on `ask`, `position`, and `repl` loads material entries in
tell syntax, ground or pattern (`pynmms.rdf.entries.load_entries` in
Python). `--onto FILE` loads an ontology-extension base and installs its
schemas as pattern entries and its consequences as ground entries
(`pynmms.rdf.convert.install_onto`): `subClassOf(C, D)` becomes
`?x a C |~ ?x a D`, `range`, `domain`, and `subPropertyOf` the corresponding
role entries, `disjointWith` and `disjointProperties` incompatibilities,
`jointCommitment` a multi-premise entry, and a guarded schema's defeater
concepts become defeaters on the individuals of the match. The seven
schema types are therefore a surface syntax for pattern entries over
`rdf:type` and role triples, with one difference from NMMS_Onto's own
matcher: an exact schema, defeated by any addition, has no pattern
counterpart and is compiled as monotone; and a monotone or guarded
incompatibility explodes within the position, where NMMS_Onto's does not.

## Positions as speech acts

A position is what a holder has said. `Position` keeps the atoms asserted,
the graphs denied, and the order of the moves, and checks them over the
store as background; it speaks for the subjects it asserts about, so their
stored records are set aside while it is checked, and reading a record
aloud is `Position.of`:

```python
from pynmms.rdf import Position

pos = Position(base, holder="curator")
pos.assert_("<am:proxy-52227 am:etchedBy am:p-10974>")
v = pos.coherent()            # Verdict: bool(v), v.reason, v.rescue
pos.commits_to("<am:proxy-52227 am:objectName am:t-11421>")
pos.precludes("<am:proxy-52227 am:madeBy am:p-10974>")
pos.deny([(s, p, o)])         # a rejected graph, its triples jointly
pos.withdraw("<...>")
pos.commit()                  # TELL: the assertions become background

record = Position.of(base, "am:proxy-31227")   # the stored record as a position
```

`challenges()` generates the probes an opponent would put to the position
from the base: incompatibilities and ⊥ rules its commitments partly
satisfy, asking for the rest, and defaults it is committed to but has not
acknowledged, each with the defeaters that would answer it. That is the
opponent's side of the game of Section 9.1 of the ontology extension
page, and the REPL's `challenges` command prints them as questions.

`coherent()` asks whether ⟨accepted, rejected⟩ is in bounds
(`def:contententailment`): out of bounds iff the accepted graphs entail a
rejected one, or, with nothing rejected, iff they are incoherent. A failed
verdict names the entry or rule responsible and the defeaters that would
rescue it. The REPL is a client: `tell` asserts into the session's
position, `ask` challenges it, `deny`, `withdraw`, `coherent`, `position`,
and `commit` are the other moves, and `save` commits before writing.
`python -m bench.replay_dialogue` replays a scripted dialogue with
predictions against a persisted store.

## Provenance as entitlement

A position keeps two scores. What it is committed to is what it asserted
plus what follows; what it is entitled to is the subset it has standing
for. `Position.grounds()` says why each commitment is held:

- `asserted`: the holder said it and has not defended it;
- `defended`: the holder said it and `defend()`, a round of the opponent's
  probes, found no refutation;
- `inherited`: read aloud from the store by `Position.of`, with the named
  graph it came from and, through `RegimeBase.provenance = RecordPattern(...)`,
  the evidence and reference of the annotation record that carries it;
- `derived` (with `grounds(derived=True)`): a default the base commits the
  holder to, via its entry.

`score()` counts committed, entitled, and open. `Position.of(base, s,
source=graph)` reads one named graph's account of a subject, so two
catalogues become two positions that can be checked alone and together.
`commit()` with a holder writes the assertions into the holder's own named
graph, attributed with `prov:wasAttributedTo`, so the store becomes a
ledger of who committed to what, and later readers inherit from the
holder. A defeater can read evidence strength, since annotation records
are patterns and evidence codes an ordering:

```
?g go:involved_in ?c, ?c rdfs:subClassOf ?d |~ ?g go:involved_in ?d
    unless ?g go:not_involved_in ?d
    ; ?r go:gene_product ?g, ?r go:class ?c, ?r go:evidence ?e, [rank(strength, ?e) < rank(strength, "IMP")]
```

The REPL's `defend` and `entitlement` commands and the replay script's
`defend`, `entitled?`, and `score?` moves expose the same score.

## The curation loop

`Position.propose()` assesses a position as a proposal and writes nothing:
whether it is in bounds with the refutation and the rescue, the opponent's
probes, its commitments (asserted, inherited, and the defaults it is
committed to), what it is precluded from accepting, its entitlement score,
and the proof trace. The loop is propose, take the rescue or edit, propose
again, commit. The REPL's `propose` command prints the report's summary
and the replay script's `propose?` move records it.

`python -m bench.curation_loop` runs the same records through SHACL
(pySHACL over each record's neighbourhood, with SHACL-SPARQL constraints),
the shapes' own SPARQL run natively on the store, and NMMS `propose` on the
record read aloud, with the constraints stated once as shapes and once as
pattern incompatibilities whose defeaters are the shapes' `NOT EXISTS`
clauses. The three must agree on what is flagged; what only the third
column has is the rescue, the defaults, and a hypothetical fix accepted
without writing.

## The Elenchus loop

`Dialogue` holds the dialectical state `⟨[C : D], T, I⟩` of Allen's
Elenchus protocol over a store: the position, the open tensions (sequents
`Γ |~ Δ` over the holder's own atoms that the opponent claims incoherent,
with the rescue that would answer each), and the material implications
from accepted tensions. The respondent's moves are `commit`, `deny`,
`withdraw`, `accept(tension, retract=... | refine=(old, new))`, and
`contest(tension, exception=...)`; a positum given at construction cannot
be withdrawn. The opponent is computed from the base, so every tension it
raises is one the base licenses: accepting one endorses the base, and
contesting one with an exception revises it, adding the exception as a
defeater of the responsible entry. A tension may also come from outside,
`propose_tension`, an oracle or a colleague; accepted, it enters the base
as a material implication. `status()` is `coherent`, `tensions open`, or
`aporia` (out of bounds, every tension's own atoms in the positum, no
rescue left). `save` and `load` persist the state as JSON, and
`commit_to_store` writes the commitments that held. `play(script)` runs a
scripted respondent with predictions, and `python -m
bench.elenchus_session` does so over a persisted store.

A base need not come from a catalogue. `bench/pulmonary/` reads a
clinical inference benchmark (35 defeasible inferences from findings to a
diagnosis, with placeholder verdicts; not for clinical use) as pattern
entries, good items as defaults defeated by the additions the bad items
of their ladder make, contested items rescued by an explicit override,
ordered tiers under `rank` guards, and plays vignette sessions over it:

```text
holder respondent
positum <pul:v1 pul:has pul:ad>, <pul:v1 pul:bi "bi_mod">, <pul:v1 pul:cv "cv_struct">
commits? <pul:v1 pul:dx pul:cpe> ## True
commit <pul:v1 pul:dx pul:cpe>
commit <pul:v1 pul:bnp "bnp_lo">
status? ## tensions open
accept 1 retract <pul:v1 pul:dx pul:cpe>
precludes? <pul:v1 pul:dx pul:cpe> ## True
```

```bash
python -m bench.pulmonary.session --check --base placeholder
```

`--check` replays the benchmark's items against the base built from
them, which says where a panel's verdicts are inconsistent with one
another under a defeasible reading.

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
| `OxigraphBackend(path, regime=...)` | an embedded store, in memory or on disk (needs `pyoxigraph`, the `oxigraph` extra) | computed *inside the store*: the regime's pattern rules run as SPARQL updates to a fixpoint; kept on disk across sessions |

Blank nodes in the loaded graph are Skolemized (sound in the antecedent,
`lem:skolem`); blank nodes in a consequent go in a pattern atom.

### Oxigraph: the closure in the store

`OxigraphBackend` keeps the asserted graph and `cl_R(G)` in an embedded
[Oxigraph](https://github.com/oxigraph/oxigraph) store and materialises the
regime with the store's own SPARQL engine, several times faster than the
in-process closure and with microsecond membership and join queries. An
on-disk store records which regime it holds, so reopening it skips the
closure altogether. On the command line, `--oxigraph DIR` opens or creates
such a store; `-g` files are loaded into it once, and later runs need only
the directory:

```bash
pynmms rdf ask --oxigraph ./kb -g ontology.ttl -g data.ttl --regime rdfs "<ex:tweety a ex:Bird>"
pynmms rdf ask --oxigraph ./kb --regime rdfs --prefix ex=http://ex.org/ "<ex:tweety a ex:Bird>"
pynmms rdf tell --oxigraph ./kb --regime rdfs --prefix ex=http://ex.org/ "<ex:polly a ex:Sparrow>"
```

`tell` extends the closure incrementally and persists it. An on-disk store
below two million asserted triples computes the closure in a temporary
in-memory store and bulk-loads the result, which costs about 600 bytes of
memory per closure triple; above that it runs the rule updates directly on
disk, slower but with no memory cost (`in_memory=` overrides the choice).
In Python:

```python
from pynmms.rdf import RDFS, RegimeBase
from pynmms.rdf.backends import OxigraphBackend

with OxigraphBackend("./kb", regime=RDFS, prefixes={"ex": "http://ex.org/"}) as backend:
    backend.load("ontology.ttl", materialize=False)
    backend.load("data.ttl")            # materialises once, in the store
    base = RegimeBase(backend)
```

Rules with a Python guard or a procedural body (the OWL 2 RL list rules)
run in process against the store between rounds, so every shipped regime
works. Two RDFS rules, `rdfs1` and `rdfD1`, conclude generalized triples
with a literal subject that a SPARQL store cannot hold; the backend skips
them, and literal typing is therefore absent from the store's closure.

## Shipped regimes

- `SIMPLE`: no rules, so `Γ |~ Δ` is Containment (simple entailment, `cor:simple`).
- `RDFS`: rdf1, rdfs1, rdfD1 (literal typing) and rdfs2 to rdfs13 with the
  finite RDFS axiomatic triples (`cor:rdfs`).
- `OWL2RL`: RDFS plus the fixed-arity OWL 2 RL/RDF rules of Tables 4 to 9
  (`cor:owlrl`): equality (`owl:sameAs`, `differentFrom`), property
  characteristics (functional, inverse-functional, irreflexive, symmetric,
  asymmetric, transitive, inverse, equivalent, disjoint), negative property
  assertions, class restrictions (someValuesFrom/allValuesFrom/hasValue,
  max-cardinality 0 and 1), class axioms (subClassOf, equivalentClass,
  disjointWith, complementOf, `owl:Nothing`), and the schema rules. The
  false-concluding rules among these are exactly the published
  incompatibilities `prop:incoherence` recovers. The rule families over
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
