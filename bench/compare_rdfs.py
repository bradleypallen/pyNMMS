"""F0: NMMS proof search versus classical RDFS entailment over one persisted store.

One on-disk Oxigraph store, materialised under a regime, serves as both
reasoners. The classical answer to a ground triple (or to a pattern with
blank nodes as variables) is one SPARQL ``ASK`` against the closure graph,
which by ``thm:closure`` is regime entailment. The NMMS answer is proof
search over :class:`~pynmms.rdf.RegimeBase` on the same store. For queries
the closure can answer the two must agree (NMMS is a conservative extension
of its base) and the difference in latency is the cost of the sequent
machinery; for negations, conditionals, disjunctions, and material entries
the classical column is "not expressible" and the NMMS column is the
result.

Usage::

    python -m bench.compare_rdfs --store DIR --regime rdfs --queries FILE
        [--entries FILE] [--rules FILE] [--regime-name NAME] [--prefix ex=IRI ...] [--reps 20]
        [--out bench/results] [--no-write] [--label TEXT]

The query file has one query per line, ``antecedent => consequent`` or a
bare consequent, ``#`` comments, and an optional ``tag:`` prefix (``atomic``,
``pattern``, ``logical``, ``material``, ``position``); untagged lines are
classified by form. A ``position:`` query is a position over the store as
background (``include_graph="background"``): Γ is the antecedent alone and
the store supplies the closure. A line may end with a prediction,
``## r,n,i`` giving the expected classical, NMMS, and NMMS-with-entries
verdicts as ``1``, ``0``, or ``-`` (not applicable); the harness reports
predicted against observed and counts the mismatches, so that a run is a
test of the model rather than an exploration. The entries file holds
material entries in tell syntax,
``<s p o>, <s p o> |~ <s p o> unless <s p o> & <s p o>, <s p o>`` or
``... monotone``, over the same prefixes. Every query runs against the
plain regime base and, when entries are given, against the base with the
entries (the ``nmms+I`` column).

Records go to ``bench/results/`` like the other benchmarks; the cold
column is the first run of each query after the store was reopened, the
warm column a median over ``--reps`` runs with the extras-closure cache
cleared before each, so it measures the query and not the memo.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._util import Section, env_info, git_sha, timeit, write_record

logger = logging.getLogger("bench.compare_rdfs")

GROUPS = ("atomic", "pattern", "logical", "material", "position")
NA = "n/a"


@dataclass
class Query:
    tag: str
    text: str
    antecedent: list[str]
    consequent: list[str]
    expect: tuple[Any, Any, Any] | None = None

    @property
    def include_graph(self) -> bool | str:
        return "background" if self.tag == "position" else True


def _prefixes(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--prefix expects PFX=IRI, got {item!r}")
        pfx, iri = item.split("=", 1)
        out[pfx.strip()] = iri.strip()
    return out


def read_queries(path: Path) -> list[Query]:
    from pynmms.cli.rdf import _split_query

    out: list[Query] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        expect = None
        if "##" in line:
            line, _, pred = line.partition("##")
            line = line.strip()
            parts = [x.strip() for x in pred.split(",")]
            if len(parts) != 3:
                raise ValueError(f"prediction must be r,n,i: {raw!r}")
            expect = tuple({"1": True, "0": False, "-": NA}[x] for x in parts)
        tag = ""
        head, sep, rest = line.partition(":")
        if sep and head.strip() in GROUPS and not head.strip().startswith("<"):
            tag, line = head.strip(), rest.strip()
        ant, con = _split_query(line)
        out.append(Query(tag, line, ant, con, expect))
    return out


def classify(q: Query, resolver: Any) -> str:
    """The group of an untagged query, from its form."""
    from pynmms.rdf.atoms import PatternAtom, TripleAtom

    if q.tag:
        return q.tag
    if not q.antecedent and len(q.consequent) == 1:
        if TripleAtom.coerce(q.consequent[0], resolver) is not None:
            return "atomic"
        if PatternAtom.coerce(q.consequent[0], resolver) is not None:
            return "pattern"
    return "logical"


def classical_ask(q: Query, resolver: Any) -> str | None:
    """The SPARQL ``ASK`` that answers *q* classically, or ``None``."""
    from rdflib import BNode

    from pynmms.rdf.atoms import PatternAtom, TripleAtom

    if q.antecedent or len(q.consequent) != 1:
        return None
    atom = TripleAtom.coerce(q.consequent[0], resolver)
    if atom is not None:
        return f"ASK {{ {' '.join(n.n3() for n in atom.triple)} }}"
    pat = PatternAtom.coerce(q.consequent[0], resolver)
    if pat is None:
        return None

    def term(n: Any) -> str:
        return f"?b{n}" if isinstance(n, BNode) else n.n3()

    return "ASK { " + " . ".join(" ".join(term(n) for n in t) for t in pat.triples) + " }"


def read_entries(path: Path, base: Any) -> int:
    """Add the material entries of *path* to *base*; return how many."""
    from pynmms.rdf.entries import load_entries

    ground, patterns = load_entries(path, base)
    return ground + patterns


def run(args: argparse.Namespace) -> list[Section]:
    from rdflib import Graph

    from pynmms.rdf import RegimeBase
    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.rules import REGIMES, custom, parse_rules_text
    from pynmms.reasoner import NMMSReasoner

    prefixes = _prefixes(args.prefix)
    regime = REGIMES[args.regime]
    if args.rules:
        resolver = Resolver(Graph())
        for pfx, iri in prefixes.items():
            resolver.bind(pfx, iri)
        rules = parse_rules_text(Path(args.rules).read_text(), resolver)
        regime = custom(args.regime_name or f"{regime.name}+{Path(args.rules).name}", rules,
                        extends=regime)
    elif args.regime_name:
        regime = custom(args.regime_name, [], extends=regime)

    t0 = time.perf_counter()
    backend = OxigraphBackend(args.store, regime=regime, prefixes=prefixes, materialize=False)
    reopen_s = time.perf_counter() - t0
    if not backend.materialised:
        if not args.materialize:
            raise SystemExit(f"{args.store} is not materialised for regime {regime.name}; "
                             "pass --materialize to do it now (an hour at 10^7 triples)")
        backend.materialize()
    plain = RegimeBase(backend, regime=regime)
    with_entries: RegimeBase | None = None
    n_entries = 0
    if args.entries:
        with_entries = RegimeBase(backend, regime=regime)
        n_entries = read_entries(Path(args.entries), with_entries)
    queries = read_queries(Path(args.queries))
    reasoner = NMMSReasoner(plain, persistent_cache=False)
    reasoner_i = NMMSReasoner(with_entries, persistent_cache=False) if with_entries else None

    columns = ["query", "rdfs", "nmms", "nmms+I", "agree", "ask_ms", "nmms_cold_ms",
               "nmms_ms", "nodes", "round_trips", "expect", "ok"]
    tables = {g: Section(f"compare_rdfs:{g}", columns) for g in GROUPS}
    per_group: dict[str, list[list[Any]]] = {g: [] for g in GROUPS}

    for q in queries:
        group = classify(q, backend.resolver)
        ask = classical_ask(q, backend.resolver)
        rdfs: Any = NA
        ask_ms: Any = NA
        if ask is not None:
            rdfs = bool(backend.store.query(ask))
            ask_ms = timeit(lambda: backend.store.query(ask), args.reps)

        seq = plain.sequent(q.antecedent, q.consequent, include_graph=q.include_graph)
        plain.clear_caches()
        backend.round_trips = 0
        t0 = time.perf_counter()
        result = reasoner.derives_sequent(seq)
        cold_ms = (time.perf_counter() - t0) * 1000
        round_trips = backend.round_trips
        nmms = result.derivable
        nmms_ms = timeit(lambda: (plain.clear_caches(), reasoner.derives_sequent(seq)), args.reps)

        nmms_i: Any = NA
        if with_entries is not None and reasoner_i is not None:
            seq_i = with_entries.sequent(q.antecedent, q.consequent,
                                         include_graph=q.include_graph)
            with_entries.clear_caches()
            nmms_i = reasoner_i.derives_sequent(seq_i).derivable
        agree: Any = (rdfs == nmms) if rdfs is not NA else NA
        expect_s: Any = NA
        ok: Any = NA
        if q.expect is not None:
            expect_s = ",".join("-" if e is NA else ("1" if e else "0") for e in q.expect)
            ok = all(e is NA or e == got for e, got in zip(q.expect, (rdfs, nmms, nmms_i)))
        row = [q.text, rdfs, nmms, nmms_i, agree, ask_ms, cold_ms, nmms_ms, result.nodes,
               round_trips, expect_s, ok]
        tables[group].add(*row)
        per_group[group].append(row)
        if agree is False:
            logger.warning("DISAGREEMENT on %r: rdfs=%s nmms=%s", q.text, rdfs, nmms)
        if ok is False:
            logger.warning("PREDICTION FAILED on %r: expected %s, got %s/%s/%s",
                           q.text, expect_s, rdfs, nmms, nmms_i)

    summary = Section("compare_rdfs:summary",
                      ["group", "queries", "agree", "predicted", "ask_ms", "nmms_cold_ms",
                       "nmms_ms", "overhead_x"],
                      notes=f"store {args.store}; regime {regime.name}; {n_entries} material "
                            f"entries; reopen {reopen_s:.3f} s; reps {args.reps}")
    for g in GROUPS:
        rows = per_group[g]
        if not rows:
            continue
        agrees = [r[4] for r in rows if r[4] is not NA]
        oks = [r[11] for r in rows if r[11] is not NA]
        asks = [r[5] for r in rows if r[5] is not NA]
        colds = [r[6] for r in rows]
        warms = [r[7] for r in rows]
        ask_med = statistics.median(asks) if asks else NA
        warm_med = statistics.median(warms)
        summary.add(g, len(rows), f"{sum(agrees)}/{len(agrees)}" if agrees else NA,
                    f"{sum(oks)}/{len(oks)}" if oks else NA,
                    ask_med, statistics.median(colds), warm_med,
                    (warm_med / ask_med) if asks and ask_med else NA)
    session = Section("compare_rdfs:session", ["reopen_s", "asserted", "regime", "entries"])
    session.add(reopen_s, backend.size(), regime.name, n_entries)
    backend.close()
    return [t for t in tables.values() if t.rows] + [summary, session]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.compare_rdfs",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="persisted Oxigraph store directory")
    parser.add_argument("--regime", default="rdfs", choices=["simple", "rdfs", "owl2rl"])
    parser.add_argument("--rules", help="extra Horn rules, one per line")
    parser.add_argument("--regime-name", help="regime name recorded in the store, if it "
                        "differs from the CLI convention '<regime>+<rules file>'")
    parser.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI")
    parser.add_argument("--queries", required=True, type=Path, help="query file")
    parser.add_argument("--entries", type=Path, help="material entries in tell syntax")
    parser.add_argument("--reps", type=int, default=20, help="repetitions for warm medians")
    parser.add_argument("--materialize", action="store_true",
                        help="materialise the store if it is not (slow at scale)")
    parser.add_argument("--label", default="", help="free text recorded with the run")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    print(f"pyNMMS compare_rdfs  sha={git_sha()}  {env_info()}  label={args.label!r}\n")
    sections = run(args)
    for section in sections:
        print(section.render(), end="\n\n")
    if not args.no_write:
        path = write_record(sections, args.out, quick=False)
        print(f"record: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
