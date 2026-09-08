"""The dialogue replay script over a small persisted store."""

# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("pyoxigraph")
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from bench.replay_dialogue import main
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf.backends import OxigraphBackend

EX = Namespace("http://ex.org/")


def test_replay_checks_predictions(tmp_path: Path, capsys):
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Sparrow, RDFS.subClassOf, EX.Bird))
    g.add((EX.chalice, EX.start, Literal("1780")))
    g.add((EX.chalice, EX.start, Literal("1632")))
    g.add((EX.tweety, RDF.type, EX.Sparrow))
    with OxigraphBackend(tmp_path / "store", regime=RDFS_REGIME, prefixes={"ex": str(EX)}) as ox:
        ox.load_graph(g)
    entries = tmp_path / "entries.txt"
    entries.write_text('<ex:chalice ex:start "1780">, <ex:chalice ex:start "1632"> |~ monotone\n')
    dialogue = tmp_path / "d.txt"
    dialogue.write_text("""holder me
read ex:chalice
coherent? ## 0
withdraw <ex:chalice ex:start "1632">
coherent? ## 1
assert <ex:polly a ex:Sparrow>
commits? <ex:polly a ex:Bird> ## 1
commits? <ex:tweety a ex:Bird> ## 1
precludes? <ex:polly a ex:Fish> ## 0
deny <ex:polly a ex:Bird>
coherent? ## 1
commit
""")
    rc = main(["--store", str(tmp_path / "store"), "--prefix", f"ex={EX}",
               "--dialogue", str(dialogue), "--entries", str(entries), "--no-write"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dialogue:summary" in out
    # The last coherence check is predicted in bounds but the denial of Bird is entailed:
    # a deliberate failed prediction, so the report must say 5/6.
    assert "5/6" in out
