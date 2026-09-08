"""Convert a GO annotation file (GAF 2.x) to N-Triples for the F0 evaluation.

Each annotation row becomes a gene product related to a GO class by its
qualifier, kept as a relation rather than ``rdf:type`` (a protein is not an
instance of a biological process; it *enables*, *is involved in*, or *is
located in* one):

    <gp> go:enables <GO_0003677> .

The ``NOT`` qualifier, the curators' explicit negative assertion, becomes
the relation ``go:not_<qualifier>``; it is data, and what the regime and
the reasoner do with it is the experiment. Every annotation also gets a
record with its evidence code and reference, so that later work can weigh
evidence, and every gene product gets a label and a type::

    <ann> go:gene_product <gp> ; go:relation go:enables ; go:class <GO_..> ;
          go:evidence "IDA" ; go:reference "PMID:123" .
    <gp> rdfs:label "TP53" ; a go:GeneProduct .

Gene products are ``http://identifiers.org/<db>/<id>``; GO classes are the
OBO IRIs used by ``go.owl``; relations live under ``http://pynmms.dev/go/``.

Usage::

    python -m bench.gaf_to_nt goa_human.gaf.gz goa_human.nt [--no-records]
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
from pathlib import Path

logger = logging.getLogger("bench.gaf_to_nt")

GO = "http://pynmms.dev/go/"
OBO = "http://purl.obolibrary.org/obo/"
RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"

#: GAF 2.2 relation qualifiers (the non-NOT part of column 4).
RELATIONS = (
    "enables", "involved_in", "located_in", "part_of", "is_active_in", "contributes_to",
    "colocalizes_with", "acts_upstream_of", "acts_upstream_of_or_within",
    "acts_upstream_of_positive_effect", "acts_upstream_of_negative_effect",
    "acts_upstream_of_or_within_positive_effect", "acts_upstream_of_or_within_negative_effect",
)

#: GAF 2.1 files have no relation; the aspect column gives the default one.
ASPECT_DEFAULT = {"F": "enables", "P": "involved_in", "C": "located_in"}


def _lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def convert(src: Path, dst: Path, *, records: bool = True) -> dict[str, int]:
    """Write the N-Triples; return counts (rows, gene products, positive, negative)."""
    opener = gzip.open if src.suffix == ".gz" else open
    seen_gp: set[str] = set()
    counts = {"rows": 0, "gene_products": 0, "positive": 0, "negative": 0, "triples": 0}
    n_ann = 0
    with opener(src, "rt", encoding="utf-8") as fh, open(dst, "w", encoding="utf-8") as out:
        def emit(s: str, p: str, o: str) -> None:
            out.write(f"{s} {p} {o} .\n")
            counts["triples"] += 1

        for line in fh:
            if line.startswith("!"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 15:
                continue
            db, obj_id, symbol, qualifier, go_id, ref, evidence, _with, aspect = cols[:9]
            counts["rows"] += 1
            gp = f"<http://identifiers.org/{db.lower()}/{obj_id}>"
            cls = f"<{OBO}{go_id.replace(':', '_')}>"
            quals = [q for q in qualifier.split("|") if q]
            negative = "NOT" in quals
            rel = next((q for q in quals if q in RELATIONS), None) or ASPECT_DEFAULT.get(
                aspect, "annotated_to")
            pred = f"<{GO}{'not_' if negative else ''}{rel}>"
            emit(gp, pred, cls)
            counts["negative" if negative else "positive"] += 1
            if gp not in seen_gp:
                seen_gp.add(gp)
                emit(gp, RDF_TYPE, f"<{GO}GeneProduct>")
                emit(gp, RDFS_LABEL, _lit(symbol))
            if records:
                n_ann += 1
                ann = f"<urn:pynmms:go:annotation:{n_ann}>"
                emit(ann, f"<{GO}gene_product>", gp)
                emit(ann, f"<{GO}relation>", pred)
                emit(ann, f"<{GO}class>", cls)
                emit(ann, f"<{GO}evidence>", _lit(evidence))
                emit(ann, f"<{GO}reference>", _lit(ref.split("|")[0]))
    counts["gene_products"] = len(seen_gp)
    logger.info("%s -> %s: %s", src, dst, counts)
    return counts


def propagation_rules() -> str:
    """Rules propagating annotations up ``rdfs:subClassOf``, one per relation.

    GO's own tooling propagates positive annotations to superclasses; a
    ``NOT`` annotation does not propagate up (it would propagate *down*,
    which these rules leave alone).
    """
    lines = ["# Annotation propagation: a gene product related to a class is related to",
             "# its superclasses. Written for pynmms rdf --rules; prefixes bound by the CLI."]
    for rel in RELATIONS:
        lines.append(f"?g {GO}{rel} ?c, ?c rdfs:subClassOf ?d -> ?g {GO}{rel} ?d")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.gaf_to_nt",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gaf", type=Path, help="GAF file, optionally gzipped")
    parser.add_argument("out", type=Path, help="N-Triples output")
    parser.add_argument("--no-records", action="store_true",
                        help="omit the per-annotation evidence records")
    parser.add_argument("--rules", type=Path,
                        help="also write the propagation rules to this file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    counts = convert(args.gaf, args.out, records=not args.no_records)
    if args.rules:
        args.rules.write_text(propagation_rules())
    print(counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
