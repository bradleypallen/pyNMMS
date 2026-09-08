"""The curation loop against SHACL and SPARQL on one store (PLAN.md step 5).

The same records go through three checks:

* **SHACL**: each record's neighbourhood (three hops) is extracted from the
  store into an rdflib graph and validated by pySHACL against a shapes file
  whose constraints are SHACL-SPARQL (``sh:sparql``), with the record as
  the only focus node (a related object in the neighbourhood is not the
  record's fault); the report says whether it conforms.
* **SPARQL**: the shapes' own ``sh:select`` queries run natively on the
  store with ``$this`` bound to the record, which is what a SHACL-SPARQL
  engine does without the extraction.
* **NMMS**: the record is read aloud as a position over the store as
  background and :meth:`~pynmms.rdf.position.Position.propose` is asked;
  the entries file holds the same constraints as pattern incompatibilities,
  with their defeaters, so the closed-world ``NOT EXISTS`` clauses of the
  shapes and the defeaters of the entries say the same thing two ways.

The three must agree on which records are flagged; that is the prediction.
What only the third column has is then measured: a rescue named for each
flagged record, the defaults the record commits its holder to, and a
hypothetical fix, ``--fix ATOM`` asserted into the position and the
proposal repeated, accepted without anything being written.

Usage::

    python -m bench.curation_loop --store DIR --entries FILE --shapes FILE
        --target-class IRI [--clean-sample N] [--fix "<p o>"] [--regime rdfs]
        [--rules FILE] [--regime-name NAME] [--prefix ex=IRI ...] [--label TEXT]
        [--out DIR] [--no-write]

``--fix`` gives a predicate and object; the record's subject is prepended.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any

from ._util import Section, env_info, git_sha, write_record

logger = logging.getLogger("bench.curation_loop")

SH = "http://www.w3.org/ns/shacl#"


def _neighbourhood(backend: Any, subject: Any, hops: int = 3) -> Any:
    """The record's triples and those of the nodes it points at, to *hops*.

    Three hops: the record, its maker records, and the persons they name
    (whose death dates the anachronism check needs). The first run of this
    harness (2026-09-08) used two and pySHACL could not see the death dates,
    so the SHACL column missed 1,049 records the other two flagged; a
    harness bug, not a disagreement.
    """
    from rdflib import BNode, Graph, URIRef

    g = Graph()
    seen: set[Any] = set()
    frontier = [subject]
    for _ in range(hops):
        next_frontier: list[Any] = []
        for node in frontier:
            if node in seen:
                continue
            seen.add(node)
            for t in backend.triples((node, None, None)):
                g.add(t)
                if isinstance(t[2], (URIRef, BNode)):
                    next_frontier.append(t[2])
        frontier = next_frontier
    return g


def _shape_queries(shapes_path: Path) -> list[tuple[str, str]]:
    """(message, select) for every sh:sparql constraint in the shapes file."""
    from rdflib import Graph, URIRef

    g = Graph().parse(shapes_path)
    out = []
    for _, _, c in g.triples((None, URIRef(SH + "sparql"), None)):
        sel = g.value(c, URIRef(SH + "select"))
        msg = g.value(c, URIRef(SH + "message"))
        if sel is not None:
            out.append((str(msg) if msg else "constraint", str(sel)))
    return out


def run(args: argparse.Namespace) -> list[Section]:
    import pyshacl
    from rdflib import Graph, URIRef

    from pynmms.rdf import Position, RegimeBase
    from pynmms.rdf.atoms import Resolver, TripleAtom
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.entries import load_entries
    from pynmms.rdf.rules import REGIMES, custom, parse_rules_text

    prefixes: dict[str, str] = {}
    for item in args.prefix:
        pfx, iri = item.split("=", 1)
        prefixes[pfx.strip()] = iri.strip()
    regime = REGIMES[args.regime]
    if args.rules:
        resolver = Resolver(Graph())
        for pfx, iri in prefixes.items():
            resolver.bind(pfx, iri)
        regime = custom(args.regime_name or f"{regime.name}+{Path(args.rules).name}",
                        parse_rules_text(Path(args.rules).read_text(), resolver), extends=regime)
    elif args.regime_name:
        regime = custom(args.regime_name, [], extends=regime)
    backend = OxigraphBackend(args.store, regime=regime, prefixes=prefixes, materialize=False)
    if not backend.materialised:
        raise SystemExit(f"{args.store} is not materialised for regime {regime.name}")
    base = RegimeBase(backend, regime=regime)
    load_entries(Path(args.entries), base)
    shapes = Graph().parse(args.shapes)
    queries = _shape_queries(Path(args.shapes))
    store = backend.store
    target = URIRef(args.target_class)

    # Records: every target-class instance a shape query flags, plus a clean sample.
    flagged_by_sparql: dict[URIRef, list[str]] = {}
    for msg, sel in queries:
        q = sel.replace("$this", "?this")
        q = "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> " + q
        for row in store.query(q):
            s = URIRef(row["this"].value)
            flagged_by_sparql.setdefault(s, []).append(msg)
    all_targets = [URIRef(r["s"].value) for r in store.query(
        f"SELECT ?s WHERE {{ ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{target}> }}")]
    rnd = random.Random(11)
    clean = [s for s in all_targets if s not in flagged_by_sparql]
    records = sorted(flagged_by_sparql) + rnd.sample(clean, min(args.clean_sample, len(clean)))
    logger.info("%d target instances, %d flagged by the shapes' SPARQL, %d records checked",
                len(all_targets), len(flagged_by_sparql), len(records))

    fix_p = fix_o = None
    if args.fix:
        atom = TripleAtom.coerce(f"<{args.fix.strip('<>')}>".replace("<", "<urn:x ", 1),
                                 base.resolver)
        if atom is None:
            raise SystemExit(f"--fix must be '<predicate object>': {args.fix!r}")
        fix_p, fix_o = atom.p, atom.o

    rows = Section("curation:records", ["record", "sparql", "shacl", "nmms", "agree", "rescue",
                                        "defaults", "fixed", "ms_shacl", "ms_nmms"])
    agree = flagged = rescued = fixed = fix_tried = 0
    ms_shacl: list[float] = []
    ms_nmms: list[float] = []
    for s in records:
        sparql_flag = s in flagged_by_sparql
        t0 = time.perf_counter()
        sub = _neighbourhood(backend, s)
        conforms, _, _ = pyshacl.validate(sub, shacl_graph=shapes, advanced=True,
                                          inference="none", focus_nodes=[s])
        ms_shacl.append((time.perf_counter() - t0) * 1000)
        shacl_flag = not conforms
        t0 = time.perf_counter()
        pos = Position.of(base, s, holder="curator")
        rep = pos.propose()
        ms_nmms.append((time.perf_counter() - t0) * 1000)
        nmms_flag = not rep.coherent
        ok = sparql_flag == shacl_flag == nmms_flag
        agree += ok
        flagged += nmms_flag
        rescue_n = len(rep.rescue)
        rescued += 1 if (nmms_flag and rescue_n) else 0
        fixed_flag: Any = "-"
        if nmms_flag and fix_p is not None:
            fix_tried += 1
            pos.assert_(TripleAtom(s, fix_p, fix_o))
            fixed_flag = bool(pos.propose().coherent)
            fixed += fixed_flag
        rows.add(str(s).split("/")[-1], sparql_flag, shacl_flag, nmms_flag, ok, rescue_n,
                 len(rep.defaults), fixed_flag, round(ms_shacl[-1], 1), round(ms_nmms[-1], 1))
        if not ok:
            logger.warning("DISAGREEMENT on %s: sparql=%s shacl=%s nmms=%s (%s)", s,
                           sparql_flag, shacl_flag, nmms_flag, rep.coherent.reason)
    import statistics

    summary = Section("curation:summary", ["records", "agree", "flagged", "rescued", "fixed",
                                           "ms_shacl", "ms_nmms"],
                      notes=f"store {args.store}; shapes {Path(args.shapes).name}; entries "
                            f"{Path(args.entries).name}; prediction: the three columns agree on "
                            f"every record, every flagged record has a rescue, the fix restores "
                            f"coherence; {len(all_targets)} instances of the target class, "
                            f"{len(flagged_by_sparql)} flagged store-wide")
    summary.add(len(records), f"agree {agree}/{len(records)}", f"flagged {flagged}",
                f"rescued {rescued}/{flagged}", f"fixed {fixed}/{fix_tried}",
                round(statistics.median(ms_shacl), 1) if ms_shacl else 0,
                round(statistics.median(ms_nmms), 1) if ms_nmms else 0)
    backend.close()
    return [rows, summary]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.curation_loop",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True)
    parser.add_argument("--regime", default="rdfs", choices=["simple", "rdfs", "owl2rl"])
    parser.add_argument("--rules")
    parser.add_argument("--regime-name")
    parser.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI")
    parser.add_argument("--entries", required=True)
    parser.add_argument("--shapes", required=True)
    parser.add_argument("--target-class", required=True)
    parser.add_argument("--clean-sample", type=int, default=100)
    parser.add_argument("--fix", default="", help="'<predicate object>' asserted as the fix")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    logging.getLogger("pyshacl").setLevel(logging.WARNING)
    print(f"pyNMMS curation_loop  sha={git_sha()}  {env_info()}  label={args.label!r}\n")
    sections = run(args)
    print(sections[-1].render(), end="\n\n")
    if not args.no_write:
        print(f"record: {write_record(sections, args.out, quick=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
