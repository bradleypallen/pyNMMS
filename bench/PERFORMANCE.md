# pyNMMS performance characteristics

Measured 2026-09-06 on one core of an Apple Silicon laptop, CPython 3.11,
pyNMMS 0.9.2 plus the index and memo fixes recorded in the same commit as
this file. Absolute numbers are indicative; the shapes (flat, linear,
exponential in what) are the substantive claims. Synthetic data throughout:
a class chain `C0 ⊑ C1 ⊑ C2`, a property with a range, and *n* individuals
each with a type assertion, a property assertion, and a literal name. The
committed records in `bench/results/` come from `python -m bench`; the
workflow tables below come from an ad hoc script whose figures are quoted in
the section headings' commit.

The framing throughout: pyNMMS is a **proof-search reasoner over a material
base**, not a materialising triplestore. Where a classical RDFS or OWL 2 RL
reasoner has one operation (materialise the closure, then answer lookups),
pyNMMS has two layers with different costs: the regime closure of the stored
graph, which is exactly what a classical reasoner does and is measured the
same way, and NMMS proof search over that closure, which is what classical
systems do not offer and is measured per query in the number of connectives.

## 1. Knowledge-base size

| Metric | Value |
|---|---|
| Largest graph measured with the in-memory backend | 300,010 asserted triples, 1,100,234 after RDFS closure |
| Resident memory at that size | 1.65 GB (rdflib graph plus closure graph plus indexes); about 1.5 KB per closure triple |
| Largest OWL 2 RL closure measured | 90,010 asserted, 420,289 closed |
| Largest graph measured with the Oxigraph backend, on disk | 10,000,003 asserted, 40,000,166 after RDFS closure; 6.7 GB on disk after compaction (section 7) |
| Python-side cost of the antecedent | zero per query: the graph never enters a Python set (`GraphView` is a reference plus a diff) |
| Practical ceiling, in-memory backend | a few million closure triples, bounded by rdflib's memory use and the one-time closure |
| Practical ceiling, Oxigraph backend | disk; the 10⁷ import is a one-time hour, queries stay flat (section 7) |
| Practical ceiling, SPARQL backend | the store's; pyNMMS holds no copy of the graph |

For comparison, the in-memory backend sits where rdflib and owlrl sit: fine
to a million or so triples, not a store. The SPARQL backend is how larger
graphs are reached; its per-query costs are in section 4.

## 2. Knowledge-engineering workflow operations (in-memory backend)

RDFS regime plus one false-concluding incompatibility rule. Times in seconds
unless marked.

| Asserted triples | Parse Turtle | Serialise Turtle | RDFS closure | Closure size | CLI cold start (parse + closure + one ask) | RSS |
|---|---|---|---|---|---|---|
| 3,010 | 0.05 | 0.05 | 0.5 | 11,234 | 0.6 | 49 MB |
| 30,010 | 0.5 | 0.6 | 5.9 | 110,234 | 6.4 | 192 MB |
| 300,010 | 5.9 | 6.1 | 67.9 | 1,100,234 | 85.8 | 1,649 MB |

RDFS materialisation runs at roughly 5,000 to 6,500 asserted triples per
second (about 16,000 closure triples per second). OWL 2 RL, with about 90
rules including the list-walking procedural ones:

| Asserted triples | OWL 2 RL closure | Closure size | Rate (asserted/s) | TELL 2 triples, closure extended |
|---|---|---|---|---|
| 3,010 | 3.0 s | 14,289 | 1,000 | 4.9 ms |
| 30,010 | 41.6 s | 140,289 | 720 | 5.4 ms |
| 90,010 | 154 s | 420,289 | 585 | 5.6 ms |

(The 90,010 row and the TELL column were measured with another job sharing
the machine and are pessimistic by roughly a third.)

Both closures are linear in the graph after the composite-index fix (before
it, OWL 2 RL was quadratic: 17 s at 3,010 triples and not finishing at
30,010). For calibration against classical engines: these rates are in the
range of pure-Python rule engines such as owlrl and two to three orders of
magnitude below native materialisers (RDFox, GraphDB, Jena's RETE engine
report tens of thousands to millions of triples per second). That gap is the
in-process backend's cost, not the calculus's: a store that materialises its
own regime removes this step entirely, which is what the SPARQL backend
assumes.

The CLI cold start is dominated by materialisation; a session (REPL, or a
long-lived `RegimeBase`) pays it once.

The committed record `bench/results/20260907T001308Z-*.json` (`python -m
bench --only rdf_scale`) agrees: RDFS load of 20,003 / 100,003 / 200,003
triples in 3.6 / 18.9 / 51.6 s, atomic, negation, and four-connective
queries at 0.03 to 0.2 ms across all three sizes.

## 3. Interactive ASK and TELL (in-memory backend)

Per-operation medians after warm-up, with the graph as antecedent. Query
cost does not grow with the graph.

| Asserted triples | TELL 2 triples, closure extended incrementally | ASK atomic (closure hit) | ASK miss | ASK negation via incoherence | ASK with 4 connectives | ASK pattern atom (blank node, 2 triples) | ASK with 100 extra antecedent triples closed per node |
|---|---|---|---|---|---|---|---|
| 3,010 | 0.45 ms | 39 µs | 28 µs | 54 µs | 117 µs | 158 µs | 33 ms |
| 30,010 | 0.49 ms | 28 µs | 25 µs | 52 µs | 123 µs | 141 µs | 36 ms |
| 300,010 | 0.73 ms | 41 µs | 37 µs | 84 µs | 187 µs | 149 µs | 48 ms |

A classical reasoner's equivalent of "ASK atomic" is a lookup in the
materialised closure, also microseconds. The rows a classical reasoner has
no counterpart for are negation (`Γ, A ⇒ ~B`, answered as incoherence of
`Γ, A, B` under the regime's false-concluding rules), the conditional and
disjunctive queries, and the extras column, which is the cost of NMMS
proof rules moving triples into the antecedent and the regime closure being
extended for them in process: about 0.3 to 0.5 ms per extra triple under
RDFS.

Interactive TELL is sub-millisecond because the closure is extended
semi-naively from the new triples rather than recomputed; a classical
materialiser's incremental maintenance is the same idea.

## 4. Interactive ASK and TELL over a SPARQL endpoint

An in-process rdflib-endpoint server on localhost holding a 6,000-triple
RDFS-materialised graph. "Cold" is the first query on a fresh backend;
"warm" is the same query repeated, served from the per-generation memo of
memberships and joins. Round trips are HTTP requests.

| Operation | Cold | Round trips | Warm | Round trips |
|---|---|---|---|---|
| ASK atomic (closure hit) | 34 ms | 1 | ~0 | 0 |
| ASK miss | 142 ms | 2 | ~0 | 0 |
| ASK negation via incoherence (1 extra triple closed) | 298 ms | 68 | 1.3 ms | 0 |
| ASK with 4 connectives | 6.6 ms | 3 | 0.2 ms | 0 |
| ASK pattern atom (blank node) | 129 ms | 2 | 0.1 ms | 0 |
| ASK with 10 extra antecedent triples | 521 ms | 249 | 4.7 ms | 0 |
| TELL 1 triple (`INSERT DATA`) | 7 ms | 1 | 5 ms | 1 |
| TELL 500 triples (one `INSERT DATA`) | 644 ms | 1 | 609 ms | 1 |

Round trips, not computation, are the cost: about 2 ms each on localhost,
and whatever the network adds elsewhere. The extras closure is the expensive
path, roughly 25 to 70 round trips per extra triple under RDFS, because
each rule firing joins against the store and each conclusion is checked for
membership. The batched join reduced this from one lookup per premise per
candidate; the remaining reductions (a `VALUES`-batched membership check,
push-down of the extras step into the store's own rule engine) are Phase 5
work. Any TELL invalidates the memo, so a mixed ASK/TELL session sees cold
costs after each TELL.

## 5. What the propositional reasoner costs, independent of the base

From the committed records. Antecedent size and schema count are flat after
Phases 1 and 2:

| Case | Cost |
|---|---|
| Atomic query, 501 to 8,001 antecedent atoms, exact, guarded, or defeated entry | 5 to 10 µs, flat |
| Schema hit or miss, 1,000 to 100,000 registered schemas | 6 µs, flat |
| Tautology with *k* connectives, empty base (whole tree explored) | 0.02 ms (k=1) to 9.4 ms (k=8); about 2.17^k nodes |
| Underivable query with *k* connectives, 10,000 schemas | 0.014 ms (k=1) to 0.066 ms (k=8) |

The exponential in *k* is the decision problem (NMMS derivability is
co-NP-hard) and no indexing touches it. Sub-second queries run out around
k = 13. Realistic knowledge-engineering queries are atomic or have a handful
of connectives.

## 6. How to read this against a classical RDFS/DL reasoner

- **Materialisation throughput**: measure ours by the closure rates in
  section 2. In-process, pyNMMS is a Python rule engine and performs like
  one. Against a materialising store, pyNMMS does not materialise at all.
- **Query latency**: for the queries a classical reasoner can answer
  (membership in the closure), we are lookup-speed in memory and one round
  trip over SPARQL. For the queries it cannot (negation, conditionals,
  incoherence, defeasible material inference), cost is microseconds in
  memory plus the exponential in the query's connective count, and round
  trips over SPARQL proportional to the antecedent triples the proof rules
  introduce.
- **Scale**: the calculus adds no per-query dependence on graph size. The
  ceiling is the backend's: rdflib's for the in-memory backend, the store's
  otherwise.
- **What is not measured**: DL tableau-style consistency checking over
  expressive ontologies (pyNMMS has no counterpart; its regimes are Horn),
  graphs beyond 300,000 asserted triples in memory, any network store other
  than a localhost endpoint, and concurrent clients.

## 7. Oxigraph backend: the closure in the store

Measured 2026-09-07 on the same synthetic graph (RDFS plus one
incompatibility rule), with an **on-disk** Oxigraph store through
`OxigraphBackend`. "Load + close" is Oxigraph's own parse of the N-Triples
file, the Skolemization scan, and the regime materialised by SPARQL rule
updates in a temporary in-memory store, then bulk-loaded into the disk
store; "close (py)" is `MemoryBackend`'s in-process closure of the same
graph, measured in the same run. Query columns are medians after warm-up;
the negation and extras queries clear the per-query closure cache first,
so they pay the store round trips every time.

| Individuals | Load + close, on disk | Close (py) | Closure | ASK hit | ASK miss | ASK negation (1 extra closed) | ASK 4 connectives | TELL 2 triples | ASK 100 extras | Reopen from disk |
|---|---|---|---|---|---|---|---|---|---|---|
| 30,000 | 2.9 s | 10.9 s | 240,254 | 30 µs | 23 µs | 2.0 ms | 110 µs | 1.4 ms | 67 ms | 0.01 s |
| 300,000 | 32.7 s | 113 s | 2,400,254 | 24 µs | 23 µs | 2.0 ms | 113 µs | 1.7 ms | 68 ms | 0.01 s |
| 5,000,000 (10⁷ asserted) | 56 min, direct on disk | not run | 40,000,166 | 38 µs | 32 µs | 2.3 ms | 123 µs | 4.3 ms | 89 ms | 0.01 to 0.04 s |

The 10⁷ row (2026-09-07, 24 GB machine) took the direct-on-disk path,
since a scratch in-memory store costs about 600 bytes per closure triple
and 40 million closure triples would have needed the whole machine. Its
56 minutes break down as 52 s for Oxigraph to parse the 0.8 GB N-Triples
file, 4.3 min to copy the asserted graph into the closure graph (a
`DROP`/`ADD` inside the store), and 51 min for three rounds of the fifteen
rule updates against RocksDB, of which the last round derives nothing and
is pure `NOT EXISTS` reads. Resident memory peaked at 9.5 GB during
materialisation (RocksDB memtables and block cache; the process ran at 2 to
3.4 GB most of the time) and the store directory peaked at 15 GB before
compaction brought it to 6.7 GB. The Python engine was not run at this size:
it would need about 60 GB for the closure in rdflib. The reopen measured
inside the run, 40 s, was RocksDB recovering its write-ahead log right
after the write session; three further reopens took 0.01 to 0.04 s, with
the first lookup under a millisecond. `COUNT(*)` over the 40-million-triple
closure takes 8 s, so `closure_size()` is not an interactive operation at
this scale, though the fixpoint's per-round count is negligible against
the rounds.

Four things to read off this. First, membership and connective queries are
lookup-speed and flat from 24 thousand to 40 million closure triples, and
the store holds the closure across sessions: reopening is instantaneous,
where the in-memory backend re-parses and re-closes for about two minutes
at 2.4 million and could not hold 40 million at all. A 10⁷-triple RDFS
knowledge base is therefore a one-time hour of import followed by
interactive sessions that start in milliseconds, which is the Phase 6
target on the query side. Second, below two million asserted triples
materialisation runs in a temporary in-memory store and is three to four
times faster than the Python engine, and the closure matched it triple for
triple at every size where both ran. Running the rule updates directly
against the on-disk store took 127 s at 300,000 individuals, slower than
Python, because RocksDB writes dominate, which is why the backend chooses
the path by size. Third, the direct-on-disk hour at 10⁷ is mostly
avoidable: the 4-minute copy can be replaced by loading the file into both
graphs, the final read-only round by a semi-naive delta, and the write
cost by materialising in memory in partitions or by an Oxigraph server
with more memory; none of this is calculus work. Fourth, the negation and
extras queries cost more than in memory (2.3 ms against 54 µs, 89 ms
against 36 ms) because the extras closure still runs in process and calls
the store once per rule firing; each call is about 20 µs, so the cost is
round trips into Rust rather than Python work, and the scratch-graph
hypothetical closure planned for workstream A.3 removes them. `TELL` rose
from 1.7 ms to 4.3 ms at 10⁷, the only column that moved, since each
insert now lands in a much larger RocksDB tree.

## 8. F0: NMMS against classical RDFS entailment over one persisted store

`python -m bench.compare_rdfs` (2026-09-07; records
`bench/results/20260907T2233*` and `*T2235*`) on the 10⁷ store of section 7,
with the query file `bench/queries/synthetic_rdfs.txt` (31 queries) and the
four material entries of `synthetic_entries.txt`. The classical column is a
SPARQL `ASK` against the closure graph, which by `thm:closure` is RDFS
entailment; the NMMS column is proof search over `RegimeBase` on the same
store, with the extras-closure cache cleared before every run. Medians over
20 runs after one cold run; the cold column is that first run after
reopening the store.

| Group | Queries | Agreement | Classical `ASK` | NMMS cold | NMMS warm | Store calls per query |
|---|---|---|---|---|---|---|
| atomic (ground triple) | 11 | 11/11 | 20 µs | 29 µs | 14 µs | 1 to 2 |
| pattern (blank nodes as witnesses) | 3 | 3/3 | 27 µs, and one at 2.8 s | 0.7 ms | 66 µs | 1 |
| logical (negation, conditional, disjunction, incoherence) | 11 | not expressible | — | 1.1 ms | 1.1 ms | 3 to 89 |
| material (guarded and monotone entries) | 6 | 4/4 on the atomic-form rows | 19 µs | 58 µs | 14 µs | 2 |

Reopening the store took 21 ms.

What the table says. Where the closure can answer, NMMS agrees on every
query, which is `thm:closure` exercised at 40 million closure triples, and
costs no more than the lookup: the warm NMMS figure is below the `ASK`
because the reasoner reads the store through its quad index while the
`ASK` pays a SPARQL parse. The cold figures are the RocksDB block cache
filling, not the calculus. The logical group is what the closure cannot
express at all: the negation `Γ, A ⇒ ¬B` costs about a millisecond and up
to 89 store calls, because the one extra triple it moves into the
antecedent is closed in process with a store call per rule firing; the
conditionals and disjunctions over triples already in the closure cost
tens of microseconds and a handful of calls. The material rows are the
regime-relative base at work on a store this size: `i0 a Flies` is false
for the closure and for the plain base and true with the entry, the
derived antecedent `i2 a C2` fires its entry, `Grounded` defeats, and
`Flies` does not chain to `HasWings`.

The one slow row is instructive. The pattern `_:x a C2 . _:x p j7` took
2.8 s as a classical `ASK` because Oxigraph evaluates a basic graph pattern
left to right and has no statistics planner, so it scanned every instance
of `C2` before touching the selective triple; the reverse order takes
0.4 ms. The first run of the harness paid the same 2.8 s on the NMMS side,
since the witness search hands the whole pattern to the store. Both
SPARQL-speaking backends now order a join's patterns by selectivity
(`sparql_rules.order_bgp`: most bound terms first, `rdf:type` scans last),
which brought the NMMS figure to 66 µs; the classical column is left as the
user wrote it.

## 9. F0 on real data: the Gene Ontology with the human GAF

Run 2026-09-07 (record `bench/results/20260908T022824Z-*`). Data: `go.owl`
from current.geneontology.org (1,445,043 triples after Oxigraph's RDF/XML
parse, of which 862,029 carried blank nodes and were Skolemized) and
`goa_human.gaf.gz` (906,445 annotation rows for 38,924 gene products,
1,501 of them `NOT`), converted by `bench/gaf_to_nt.py` to 4,965,853
distinct triples: each annotation a gene product related to a GO class by
its qualifier (`go:enables`, `go:involved_in`, ... and `go:not_<qualifier>`
for the curators' negative assertions), plus a record per annotation with
evidence code and reference. Regime: RDFS plus thirteen annotation
propagation rules, one per qualifier, `?g go:r ?c, ?c rdfs:subClassOf ?d
-> ?g go:r ?d`, which is what GO's own tooling does for positive
annotations.

**Import.** 6,410,896 asserted triples closed to 10,571,108 in five rounds
of 27 store-side rules, 26 minutes on the direct-on-disk path (57 s of
parsing before it, peak resident memory 8.6 GB, store 5.4 GB on disk after
compaction). Reopening the store takes 10 ms.

**The harness** (`bench/queries/go_rdfs.txt`, `go_entries.txt`, 39 queries,
5 material entries):

| Group | Queries | Agreement | Classical `ASK` | NMMS cold | NMMS warm | Store calls |
|---|---|---|---|---|---|---|
| atomic | 18 | 18/18 | 21 µs | 21 µs | 14 µs | 1 to 2 |
| pattern | 5 | 5/5 | 28 µs to 4.1 ms | 0.8 ms | 0.2 ms | 1 |
| logical | 8 | not expressible | — | 56 µs | 34 µs; 1.2 to 2.1 ms with new triples in the antecedent | 1 to 80 |
| material | 8 | 2/2 on atomic-form rows | 21 µs | 20 µs | 14 µs | 1 to 58 |

The atomic rows include propagation at work on real depth: TP53 `enables`
DNA binding (asserted), nucleic acid binding, binding, and the
molecular-function root (all derived), and BRCA1 likewise; the misses are
a wrong qualifier for a right class and an unknown protein. The pattern
rows walk the hierarchy and the annotation records (TP53's DNA binding
with IDA evidence exists, with NAS evidence does not); the two record
queries cost 3 to 4 ms in both columns, which is the store joining about
a thousand annotation records for TP53. The logical rows with a fresh
protein `Q_new` in the antecedent show the extras closure propagating a
new annotation up the hierarchy in process, at one to two milliseconds
and up to 80 store calls.

**What the curators' NOT annotations say.** The store was materialised
without a false-concluding rule, so that queries would not explode; the
incompatibility `?g go:r ?c, ?g go:not_r ?c -> false` was then evaluated
by SPARQL over the closure, per qualifier:

| Qualifier | NOT annotations | Contradicted by the closure | Of which already in the asserted data |
|---|---|---|---|
| enables | 537 | 179 | 151 |
| involved_in | 591 | 144 | 114 |
| located_in | 201 | 62 | 61 |
| part_of | 21 | 8 | 8 |
| other five | 33 | 1 | 1 |
| total | 1,383 | 394 | 335 |

So 394 of the 1,383 negative assertions in the human GAF are contradicted
by the positive closure, and 335 of those are contradicted by the asserted
data itself: the GAF carries both `enables` and `NOT enables` for the same
protein and class, each with its own evidence and reference (CYP2D7 and
aromatase activity, both IDA, is one). The remaining 59 arise only through
propagation, where a positive annotation to a subclass reaches the class
the curator denied, which is the case GO's documentation says `NOT` exists
for. A classical RDFS reasoner materialises all 394 without comment. Under
`prop:incoherence` each is an incoherent position, and had the rule been
in the regime the whole store would be R-inconsistent and NMMS would
derive everything, which is the correct verdict of a monotone logic and a
useless one for a working biologist. That is the case for the defeasible
reading: the material rows show it in ground form. WDR91 is annotated
`involved_in` regulation of protein catabolic process and `NOT involved_in`
ubiquitin-dependent protein catabolic process; the entry that would infer
the latter by default is defeated by the `NOT` annotation read through
the regime, while the sibling entry without a `NOT` fires. The pattern
generalisation of that entry, `?g involved_in ?c ⊢ ?g involved_in ?d
unless ?g not_involved_in ?d`, is workstream D, and the 394 contradictions
are its test set.

**Against the Phase 6 target.** A real biomedical knowledge base of 10⁷
closure triples, imported once in half an hour, then queried
interactively in microseconds for what the closure knows and in
milliseconds for what it does not, with the reasoner and the classical
answer agreeing wherever both exist. What is not yet there: OWL 2 RL over
GO (the `owl:someValuesFrom` axioms, the disjoint roots), the pattern
form of material entries, and the import hour on disk.

## 10. F0 on heritage data: the Amsterdam Museum

Run 2026-09-07 (record `bench/results/20260908T032844Z-*`). Data: the
Amsterdam Museum linked data of de Boer et al. (2012) as preserved in the
"AM" benchmark graph (`am.tgz` from data.dgl.ai): 5,988,321 triples
describing 73,447 objects as Europeana Data Model proxies, with makers,
roles and attribution qualifiers, production and location date ranges,
and 28,047 SKOS concepts for object names, techniques, places, and
subjects linked by 7,487 `skos:broader` triples. The benchmark's target
property and the material relation are stripped. Half the triples have
blank-node subjects; they were Skolemized textually before loading.
Regime: RDFS plus `skos:broader` transitivity and one propagation rule
per thesaurus-valued property (`?x am:objectName ?c, ?c skos:broader ?d
-> ?x am:objectName ?d`, likewise technique, production place, current
location, association subject, content motif, content subject).

**Import.** Below the two-million threshold in spirit but not in count,
so `in_memory=True` was passed: 5,988,321 asserted triples closed to
8,042,439 in five rounds of 22 store-side rules in 2.2 minutes in a
temporary in-memory store, 2.9 minutes with the bulk load to disk, peak
resident memory 9.0 GB, store 2.8 GB. Reopen 10 ms. Against the 26
minutes of the GO import on the direct-on-disk path, that is the case for
raising the threshold when memory allows.

**The harness** (`bench/queries/am_rdfs.txt`, `am_entries.txt`, 39 queries,
6 material entries):

| Group | Queries | Agreement | Classical `ASK` | NMMS cold | NMMS warm | Store calls |
|---|---|---|---|---|---|---|
| atomic | 15 | 15/15 | 18 µs | 20 µs | 8 µs | 1 to 2 |
| pattern | 6 | 6/6 | 31 µs | 0.1 ms | 86 µs | 1 |
| logical | 8 | not expressible | — | 1.3 ms | 1.3 ms; 2.5 to 8.5 ms with new triples in the antecedent | 2 to 309 |
| material | 10 | 4/4 on atomic-form rows | 18 µs | 24 µs | 13 µs | 0 to 73 |

Thesaurus propagation works at object level: an ear clip's object name
climbs two `skos:broader` steps, a technique climbs one, and the wrong
property on the right concept is a miss. The hypothetical rows are the
expensive ones here, since a new object name or a new `broader` link
propagates through the transitive closure in process, at 100 to 309
store calls.

**Attribution and anachronism.** The museum records makers as blank
nodes carrying a person, a role, and sometimes a qualifier; 1,255 maker
records are qualified, 3,860 of them "naar" (after) and a few hundred
"toegeschreven aan" (attributed to), "kopie naar", "oude toeschrijving".
Matching production dates against makers' death dates finds 137 objects
made after their maker died, only 3 of whose maker records carry a
qualifier; the rest are posthumous editions, impressions after a
designer's drawing, or the anachronisms they appear to be. The material
rows model this in ground form for two etchings:

- `Pedemontium Florentissimum` (1725) has Gerard de Lairesse (died 1711)
  as designer and another person as etcher, neither qualified. The
  default "a maker record names who made it, unless qualified" fires for
  both, and a monotone entry turns the designer's making credit into a
  design credit.
- The 1727 etching after Jan Luyken (died 1712) has Luyken twice: as
  draughtsman with the qualifier "naar", where the default is defeated,
  and as etcher without one, where it fires. The incompatibility "etched
  by someone dead before it was made, unless a posthumous impression"
  then makes the position with the etching credit incoherent (`⇒` with
  an empty consequent is derivable, and so, by explosion within the
  position, is anything), and adding the posthumous-impression triple
  defeats it.

**The explosion, again.** The chalice `proxy-31227` carries two production
starts, 1780 and 1632, from two conflated records; 104 objects have a
start after their end and 234 have two different starts. An
incompatibility entry over the chalice's two asserted triples was tried
first. Because both are in the stored graph, the graph itself is
materially incoherent under that entry, and the run returned true for
all 39 queries, `⇒` included. The entry was removed and the conflict
kept as a query, which is coherent without it. Same lesson as GO from
the other direction: an incompatibility whose antecedent the store
already satisfies belongs in a position over the object, not in the
base, and the base needs the locality that positions give.

This run exposed two gaps, both fixed the same day. `RegimeBase` had no
clause for an entry with an empty consequent, so material
incompatibilities never fired through the regime; they now make Γ
incoherent when the antecedent is derivable and no defeater is, with the
entry's succedent policy deciding whether that explodes (`exact` yields
`Γ |~ ∅` alone). And the explosion above was the regime base's global
reading applied to a store that is itself contradictory. Incoherence is
now attributed to the position: a ⊥, or an incompatibility's antecedent,
counts only when the position's own triples take part in deriving it, the
store's contradictions are `background_inconsistent()`, and a query can be
run as a position over the store as background (`position:` in the query
file, `include_graph="background"` in the API), so that one record's
coherence is checked without blaming every other record.

**The re-run with predictions** (record `20260908T045223Z-*`, the chalice
entry restored, six `position:` rows with verdicts written before
running). Predictions were the harness's new `## r,n,i` suffix. Five of
six held: the chalice record as a position is incoherent with the entry
and coherent without it, the incoherence explodes within the position
(monotone entry), the ear clip's name climbs the thesaurus from a record
over the background, a stored fact follows from the empty position, and
the etching record with the etcher credit is incoherent. Meanwhile the
plain rows are unchanged: `⇒` over the whole store stays coherent with the
chalice entry present. The one failed prediction is instructive. A
position committing to the 1780 start alone was predicted coherent and
observed incoherent, because the background holds the 1632 start and
attribution by derivation blames a position for every incompatibility its
own commitments take part in. That is the principle working as stated,
and a prediction made on a looser reading of it; the query file records
both.

**A curator's session** (2026-09-07, `bench/replay_dialogue.py` with
`bench/queries/am_dialogue.txt`; records `20260908T052512Z-*` and
`*T052639Z-*`). The position API (`pynmms.rdf.position`) replayed a
scripted session over the same store: read the Luyken etching's record
aloud (78 triples, 10 ms), check it is in bounds, ask what it commits the
curator to, assert the etcher credit and watch the position go out of
bounds with the anachronism named and "posthumous impression" offered as
the rescue, assert the rescue, withdraw it, withdraw the credit, deny the
making credit (in bounds) and then deny the propagated object name (out of
bounds), then read the chalice aloud (189 triples), find it out of bounds,
withdraw one date, and find it in bounds while still committed to the
rest of its record. Fourteen questions, each answered in 2.5 to 10 ms
over the six-million-triple background. The first run held twelve of
fourteen predictions; both failures were one wrong guess about the data
(a thesaurus term that is not a broader term of the record's object
name), corrected in the file and noted there; the second run held all
fourteen. This is the locality the chalice needed, done the way the
speech-act reading says: the position speaks for the subjects it asserts
about, so their stored record is set aside while it is checked, and one
asserted date is coherent where the record read aloud with two is not.

**The opponent's probes** (2026-09-08, `Position.challenges()`, the same
dialogue with three `challenges?` moves and predicted counts). After the
etching's record is read aloud the opponent generates two probes in 5 ms:
a default to acknowledge, "you are committed to the etcher credit by the
unqualified etcher record", and an incompatibility, "do you also accept
the etcher credit? then the anachronism puts you out of bounds, unless a
posthumous impression"; the "naar" record's default is defeated and
yields nothing. Once the credit is asserted the only probe is the
refutation. After the chalice is read aloud and one date withdrawn, the
one probe asks whether the curator also accepts the record's other date.
All seventeen predictions held. This is the Elenchus loop with the
opponent generated from the base rather than scripted: the respondent's
moves are the dialogue file, the opponent's questions are computed.

**Values in rules** (2026-09-08, `pynmms.rdf.values`). The anachronism that
section 10 found with a hand-written SPARQL query became a rule of the
regime, `?x am:maker ?m, ?m rdf:value ?p, ?p am:deathDateEnd ?d, ?x
am:productionDateStart ?s, [year(?s) > year(?d)] -> ?x am:anachronisticMaker
?p` (`bench/queries/am_values.txt`), with a marker triple rather than ⊥
so the store stays coherent. Materialised in the store, the guard ran as a
SPARQL `FILTER` alongside the twenty-two pattern rules (2.3 minutes in
memory, closure 8,044,092 triples) and produced 1,650 marker triples,
exactly the count of the independent SPARQL query with the same year
semantics over the asserted data. The in-process evaluator agrees with
the store on the unit graphs (`tests/test_rdf_values.py`). The 137 of
section 10 were the objects whose dates were bare four-digit years on
both sides; with the first four characters of any date read as a year,
1,556 objects have a maker who died before they were made, most of them
posthumous editions and impressions, which is the population the
attribution defeaters of the position API are for.
