"""Defeasible propagation on GO: the curators' NOT as defeaters (workstream D on real data).

Over a store materialised under plain RDFS (no propagation), the thirteen
annotation-propagation rules become pattern entries, one per qualifier::

    ?g go:r ?c, ?c rdfs:subClassOf ?d |~ ?g go:r ?d unless ?g go:not_r ?d

and the position API reads each gene product with a NOT annotation aloud
and asks whether it is committed to the class the curators denied.
Predictions, written before the run against the counts of section 9 of
PERFORMANCE.md: of the 1,383 NOT annotations, the 335 whose class is also
asserted positively for the same gene product stay committed (the data
itself contradicts, and no default can retract an assertion), and the
rest, the 59 that propagation reached and the 989 it did not, are not
committed to. A sample of propagations with no NOT must still fire.

Usage::

    python -m bench.defeasible_go --store DIR [--sample N] [--evidence IMP]
        [--out DIR] [--no-write]

With ``--evidence CODE`` the propagation entries also yield to weak evidence:
``unless ?r go:gene_product ?g, ?r go:class ?c, ?r go:evidence ?e,
[rank(strength, ?e) < rank(strength, "CODE")]`` over the annotation records,
with the GO evidence codes ordered from computational to experimental. The
prediction for the sample is then the number of sampled propagations whose
annotation carries evidence at or above the threshold, counted by SPARQL.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path

from ._util import Section, env_info, git_sha, write_record

logger = logging.getLogger("bench.defeasible_go")

GO = "http://pynmms.dev/go/"
#: GO evidence codes, weakest first (computational, then curated non-experimental, then
#: experimental), for ``rank(strength, ?e)``.
STRENGTH = ("IEA", "ISS", "ISO", "ISA", "ISM", "IGC", "IBA", "IBD", "IKR", "IRD", "RCA", "TAS",
            "NAS", "IC", "ND", "HTP", "HDA", "HMP", "HGI", "HEP", "IGI", "IPI", "IMP", "IDA",
            "EXP")
RELATIONS = ("enables", "involved_in", "located_in", "part_of", "is_active_in",
             "contributes_to", "colocalizes_with", "acts_upstream_of",
             "acts_upstream_of_or_within", "acts_upstream_of_positive_effect",
             "acts_upstream_of_negative_effect", "acts_upstream_of_or_within_positive_effect",
             "acts_upstream_of_or_within_negative_effect")


def run(args: argparse.Namespace) -> list[Section]:
    from rdflib import URIRef

    from pynmms.rdf import RDFS as RDFS_REGIME
    from pynmms.rdf import Position, RegimeBase, TripleAtom
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.defeasible import parse_defeasible_rule

    backend = OxigraphBackend(args.store, regime=RDFS_REGIME, materialize=False,
                              prefixes={"go": GO, "rdfs": "http://www.w3.org/2000/01/rdf-schema#"})
    if not backend.materialised:
        raise SystemExit(f"{args.store} is not materialised under rdfs")
    from pynmms.rdf.provenance import RecordPattern
    from pynmms.rdf.values import declare_ordering

    base = RegimeBase(backend, regime=RDFS_REGIME)
    base.provenance = RecordPattern(URIRef(GO + "gene_product"), URIRef(GO + "relation"),
                                    URIRef(GO + "class"), URIRef(GO + "evidence"),
                                    URIRef(GO + "reference"))
    declare_ordering("strength", list(STRENGTH))
    weak = ""
    if args.evidence:
        weak = (f" ; ?r go:gene_product ?g, ?r go:class ?c, ?r go:evidence ?e, "
                f'[rank(strength, ?e) < rank(strength, "{args.evidence}")]')
    for r in RELATIONS:
        base.add_rule(parse_defeasible_rule(
            f"?g go:{r} ?c, ?c rdfs:subClassOf ?d |~ ?g go:{r} ?d unless ?g go:not_{r} ?d{weak}",
            base.resolver, name=f"propagate-{r}"))
    store = backend.store
    P = {"go": GO}

    # Every NOT annotation, with whether the same triple is asserted positively.
    nots: list[tuple[URIRef, str, URIRef, bool]] = []
    for r in RELATIONS:
        q = (f"SELECT ?g ?c (EXISTS {{ ?g <{GO}{r}> ?c }} AS ?asserted) "
             f"WHERE {{ ?g <{GO}not_{r}> ?c }}")
        for row in store.query(q, prefixes=P):
            nots.append((URIRef(row["g"].value), r, URIRef(row["c"].value),
                         str(row["asserted"].value) == "true"))
    logger.info("%d NOT annotations, %d asserted positively as well", len(nots),
                sum(1 for n in nots if n[3]))

    per_rel = Section("defeasible_go:not", ["relation", "NOT", "asserted_too", "committed",
                                             "committed_asserted", "committed_other",
                                             "ms_per_position"])
    totals = {"NOT": 0, "asserted": 0, "committed": 0, "committed_asserted": 0, "other": 0}
    for r in RELATIONS:
        rows = [n for n in nots if n[1] == r]
        if not rows:
            continue
        t0 = time.perf_counter()
        committed = committed_asserted = 0
        for g, _, c, asserted in rows:
            pos = Position.of(base, g, holder="curators")
            v = pos.commits_to(TripleAtom(g, URIRef(GO + r), c))
            if v:
                committed += 1
                if asserted:
                    committed_asserted += 1
                else:
                    logger.warning("committed without assertion: %s %s %s (%s)", g, r, c, v.reason)
        ms = (time.perf_counter() - t0) * 1000 / len(rows)
        asserted_n = sum(1 for n in rows if n[3])
        per_rel.add(r, len(rows), asserted_n, committed, committed_asserted,
                    committed - committed_asserted, round(ms, 1))
        totals["NOT"] += len(rows)
        totals["asserted"] += asserted_n
        totals["committed"] += committed
        totals["committed_asserted"] += committed_asserted
        totals["other"] += committed - committed_asserted

    # Propagations with no NOT: the default must fire. Sample (g, r, c, d) with c ⊑ d asserted.
    rnd = random.Random(7)
    sample_rows: list[tuple[URIRef, str, URIRef, URIRef]] = []
    for r in RELATIONS[:4]:
        q = (f"SELECT ?g ?c ?d WHERE {{ ?g <{GO}{r}> ?c . "
             f"?c <http://www.w3.org/2000/01/rdf-schema#subClassOf> ?d . FILTER(?c != ?d) "
             f"FILTER NOT EXISTS {{ ?g <{GO}not_{r}> ?d }} }} LIMIT 20000")
        rows = [(URIRef(x["g"].value), r, URIRef(x["c"].value), URIRef(x["d"].value))
                for x in store.query(q, prefixes=P)]
        sample_rows.extend(rnd.sample(rows, min(len(rows), args.sample // 4)))
    predicted_fired = len(sample_rows)
    if args.evidence:
        # Predicted by SPARQL. g is committed to (g, r, d) iff the triple is asserted
        # (the regime clause, which no entry retracts), or the entry fires: SOME class
        # c' with g r c', c' ⊑ d, c' ≠ d, and no record of (g, c') with evidence below
        # the threshold. Two earlier versions of this predictor were wrong (run of
        # 2026-09-08): the first looked only at the sampled c (96 predicted, 206 fired),
        # the second forgot that an asserted target is committed by the regime and that
        # the closure's subClassOf is reflexive (161 predicted, 206 fired).
        threshold = STRENGTH.index(args.evidence)
        weak_codes = ", ".join(f'"{e}"' for e in STRENGTH[:threshold])
        predicted_fired = 0
        for g, r, c, d in sample_rows:
            q = (f"ASK {{ {{ <{g}> <{GO}{r}> <{d}> }} UNION {{ "
                 f"?c2 <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{d}> . "
                 f"<{g}> <{GO}{r}> ?c2 . FILTER(?c2 != <{d}>) "
                 f"FILTER NOT EXISTS {{ ?rec <{GO}gene_product> <{g}> ; "
                 f"<{GO}class> ?c2 ; <{GO}evidence> ?e FILTER(?e IN ({weak_codes})) }} }} }}")
            if bool(store.query(q)):
                predicted_fired += 1
    fired = 0
    t0 = time.perf_counter()
    inherited_with_evidence = 0
    for g, r, c, d in sample_rows:
        pos = Position.of(base, g)
        if pos.commits_to(TripleAtom(g, URIRef(GO + r), d)):
            fired += 1
        ground = pos.grounds().get(str(TripleAtom(g, URIRef(GO + r), c)))
        if ground is not None and ground.evidence:
            inherited_with_evidence += 1
    ms = (time.perf_counter() - t0) * 1000 / max(1, len(sample_rows))
    evidence_note = f" + evidence below {args.evidence} as defeater" if args.evidence else ""
    summary = Section("defeasible_go:summary",
                      ["NOT", "asserted_too", "committed", "committed_asserted",
                       "committed_other", "sample_propagations", "predicted_fired", "fired",
                       "inherited_with_evidence", "ms_per_position"],
                      notes=f"store {args.store}; rdfs + 13 pattern entries"
                            f"{evidence_note}; predictions: committed == asserted_too, "
                            f"committed_other == 0, fired == predicted_fired")
    summary.add(totals["NOT"], totals["asserted"], totals["committed"],
                totals["committed_asserted"], totals["other"], len(sample_rows),
                predicted_fired, fired, inherited_with_evidence, round(ms, 1))
    backend.close()
    return [per_rel, summary]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.defeasible_go",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True)
    parser.add_argument("--sample", type=int, default=400)
    parser.add_argument("--evidence", default="", metavar="CODE",
                        help="also defeat propagation when the annotation's evidence is "
                             "below CODE")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    print(f"pyNMMS defeasible_go  sha={git_sha()}  {env_info()}\n")
    sections = run(args)
    for s in sections:
        print(s.render(), end="\n\n")
    if not args.no_write:
        print(f"record: {write_record(sections, args.out, quick=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
