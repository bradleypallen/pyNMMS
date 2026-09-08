"""The F0 harness: NMMS versus classical RDFS entailment over one persisted store."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("pyoxigraph")
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS

from bench.compare_rdfs import NA, main, run
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf.backends import OxigraphBackend

EX = Namespace("http://ex.org/")
QUERIES = Path(__file__).parent.parent / "bench" / "queries" / "synthetic_rdfs.txt"
ENTRIES = Path(__file__).parent.parent / "bench" / "queries" / "synthetic_entries.txt"


def _store(tmp_path: Path) -> Path:
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.C0, RDFS.subClassOf, EX.C1))
    g.add((EX.C1, RDFS.subClassOf, EX.C2))
    g.add((EX.p, RDFS.range, EX.C1))
    for i in range(5000):
        g.add((EX[f"i{i}"], RDF.type, EX.C0))
        g.add((EX[f"i{i}"], EX.p, EX[f"j{i}"]))
    rules = tmp_path / "rules.txt"
    rules.write_text("?x a ex:Alive, ?x a ex:Dead -> false\n")
    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.rules import custom, parse_rule

    regime = custom("rdfs+rules.txt", [parse_rule(rules.read_text().strip(), Resolver(g))],
                    extends=RDFS_REGIME)
    with OxigraphBackend(tmp_path / "store", regime=regime, prefixes={"ex": str(EX)}) as ox:
        ox.load_graph(g)
    return tmp_path


def _args(root: Path, **over) -> argparse.Namespace:
    base = dict(store=str(root / "store"), regime="rdfs", regime_name=None,
                rules=str(root / "rules.txt"),
                prefix=["ex=http://ex.org/"], queries=QUERIES, entries=ENTRIES, reps=2,
                materialize=False, label="test", out=root / "results", no_write=True)
    base.update(over)
    return argparse.Namespace(**base)


def test_atomic_and_pattern_rows_agree_and_material_rows_differ(tmp_path):
    root = _store(tmp_path)
    sections = {s.name: s for s in run(_args(root))}
    atomic = sections["compare_rdfs:atomic"].rows
    assert len(atomic) == 11
    assert all(r[4] is True for r in atomic), atomic
    assert all(r[1] == r[2] == r[3] for r in atomic)
    pattern = sections["compare_rdfs:pattern"].rows
    assert [r[1] for r in pattern] == [True, False, True]
    assert all(r[4] is True for r in pattern)
    logical = {r[0]: r for r in sections["compare_rdfs:logical"].rows}
    assert all(r[1] is NA and r[4] is NA for r in logical.values())
    assert logical["<ex:i0 a ex:Alive> => ~<ex:i0 a ex:Dead>"][2] is True
    assert logical["=> ~<ex:i0 a ex:Dead>"][2] is False
    assert logical["<ex:i0 a ex:C2> -> <ex:i0 a ex:Zed>"][2] is False
    assert logical["<ex:i0 a ex:Alive>, <ex:i0 a ex:Dead> =>"][2] is True
    material = {r[0]: r for r in sections["compare_rdfs:material"].rows}
    # The closure says no; the plain base says no; the entries say yes.
    assert material["<ex:i0 a ex:Flies>"][1:4] == [False, False, True]
    assert material["<ex:i0 a ex:Grounded> => <ex:i0 a ex:Flies>"][3] is False
    assert material["<ex:i1 a ex:Flies>"][3] is False
    assert material["<ex:i2 ex:q ex:z>"][1:4] == [False, False, True]
    assert material["<ex:i0 a ex:HasWings>"][3] is False
    summary = {r[0]: r for r in sections["compare_rdfs:summary"].rows}
    assert summary["atomic"][2] == "11/11"
    assert summary["material"][2] == "4/4"
    assert sections["compare_rdfs:session"].rows[0][3] == 4


def test_refuses_an_unmaterialised_store(tmp_path):
    root = _store(tmp_path)
    with pytest.raises(SystemExit):
        run(_args(root, regime="owl2rl"))


def test_main_writes_a_record(tmp_path, capsys):
    root = _store(tmp_path)
    rc = main(["--store", str(root / "store"), "--rules", str(root / "rules.txt"),
               "--prefix", "ex=http://ex.org/", "--queries", str(QUERIES),
               "--entries", str(ENTRIES), "--reps", "1", "--out", str(root / "results")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "compare_rdfs:summary" in out and "record:" in out
    assert list((root / "results").glob("*.json"))
