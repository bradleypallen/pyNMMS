"""The GAF-to-N-Triples converter used by the F0 evaluation on GO."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from bench.gaf_to_nt import RELATIONS, convert, propagation_rules  # noqa: E402


def _row(db_id: str, symbol: str, qualifier: str, go_id: str, ref: str, aspect: str) -> str:
    cols = ["UniProtKB", db_id, symbol, qualifier, go_id, ref, "IDA", "", aspect, "name",
            symbol, "protein", "taxon:9606", "20200101", "UniProt", "", ""]
    return "\t".join(cols)


GAF = "!gaf-version: 2.2\n" + "\n".join([
    _row("P04637", "TP53", "enables", "GO:0003677", "PMID:1", "F"),
    _row("P04637", "TP53", "located_in", "GO:0005634", "PMID:2|PMID:3", "C"),
    _row("A0A087X1C5", "CYP2D7", "NOT|enables", "GO:0070330", "PMID:4", "F"),
]) + "\n"


def test_convert_writes_relations_negations_and_records(tmp_path: Path):
    src = tmp_path / "x.gaf"
    src.write_text(GAF)
    dst = tmp_path / "x.nt"
    counts = convert(src, dst)
    assert counts == {"rows": 3, "gene_products": 2, "positive": 2, "negative": 1,
                      "triples": 3 + 2 * 2 + 3 * 5}
    from rdflib import Graph, Literal, URIRef

    g = Graph().parse(dst)
    tp53 = URIRef("http://identifiers.org/uniprotkb/P04637")
    go = "http://pynmms.dev/go/"
    assert (tp53, URIRef(go + "enables"),
            URIRef("http://purl.obolibrary.org/obo/GO_0003677")) in g
    assert (URIRef("http://identifiers.org/uniprotkb/A0A087X1C5"), URIRef(go + "not_enables"),
            URIRef("http://purl.obolibrary.org/obo/GO_0070330")) in g
    assert (tp53, URIRef("http://www.w3.org/2000/01/rdf-schema#label"), Literal("TP53")) in g
    refs = set(g.objects(None, URIRef(go + "reference")))
    assert Literal("PMID:2") in refs and Literal("PMID:3") not in refs


def test_no_records_keeps_only_annotation_triples(tmp_path: Path):
    src = tmp_path / "x.gaf"
    src.write_text(GAF)
    counts = convert(src, tmp_path / "x.nt", records=False)
    assert counts["triples"] == 3 + 2 * 2


def test_propagation_rules_parse_one_per_relation():
    from rdflib import Graph

    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.rules import parse_rule

    lines = [ln for ln in propagation_rules().splitlines() if ln and not ln.startswith("#")]
    assert len(lines) == len(RELATIONS)
    rules = [parse_rule(ln, Resolver(Graph())) for ln in lines]
    assert all(len(r.premises) == 2 and r.conclusion is not None for r in rules)
