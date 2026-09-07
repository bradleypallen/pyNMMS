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

