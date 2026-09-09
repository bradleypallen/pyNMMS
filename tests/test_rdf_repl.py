"""``pynmms rdf repl``: scripted sessions through the command table.

Each test feeds lines to ``builtins.input`` and reads what the session
prints; the graph is a sparrow under an RDFS regime with one ⊥ rule
(nothing is both a bird and a fish) and one guarded material entry
(birds fly unless penguins).
"""

# ruff: noqa: E402

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph

from pynmms.cli.main import main
from pynmms.cli.rdf_repl import (
    ARG_COMMANDS,
    BARE_COMMANDS,
    COMMANDS,
    OPTIONAL_ARG_COMMANDS,
    REPL_HELP,
)

TWEETY = "<ex:tweety a ex:Fish>"
KIM = "<ex:kim a ex:Fish>"
FLIES = "<ex:tweety a ex:Flies>"
BIRD = "http://ex.org/Bird"


@pytest.fixture
def store(tmp_path: Path) -> dict[str, Path]:
    g = tmp_path / "g.ttl"
    g.write_text(
        "@prefix ex: <http://ex.org/> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "ex:Sparrow rdfs:subClassOf ex:Bird .\n"
        "ex:tweety a ex:Sparrow .\n"
    )
    rules = tmp_path / "rules.txt"
    rules.write_text("?x a http://ex.org/Bird, ?x a http://ex.org/Fish -> false\n")
    entries = tmp_path / "entries.txt"
    entries.write_text("<ex:tweety a ex:Bird> |~ <ex:tweety a ex:Flies> unless "
                       "<ex:tweety a ex:Penguin>\n")
    return {"graph": g, "rules": rules, "entries": entries}


def run(store: dict[str, Path], capsys, *lines: str, quit_: bool = True) -> tuple[int, str]:
    """Run a session over *store* with *lines* (``quit`` appended unless told not to)."""
    script = list(lines) + (["quit"] if quit_ else [])
    with patch("builtins.input", side_effect=script):
        rc = main(["rdf", "repl", "-g", str(store["graph"]), "--regime", "rdfs",
                   "--rules", str(store["rules"]), "--entries", str(store["entries"])])
    return rc, capsys.readouterr().out


class TestCommandTable:
    def test_every_documented_command_has_a_handler(self):
        documented = {m.group(1) for m in re.finditer(r"^  (\w+)", REPL_HELP, re.M)}
        assert documented - {"quit"} == set(COMMANDS)

    def test_the_three_tables_partition_the_commands(self):
        assert set(ARG_COMMANDS).isdisjoint(BARE_COMMANDS)
        assert set(OPTIONAL_ARG_COMMANDS).isdisjoint(ARG_COMMANDS | BARE_COMMANDS)
        assert set(COMMANDS) == set(ARG_COMMANDS) | set(BARE_COMMANDS) | set(OPTIONAL_ARG_COMMANDS)


class TestSession:
    def test_banner_help_and_quit(self, store, capsys):
        rc, out = run(store, capsys, "help")
        assert rc == 0
        assert "pyNMMS RDF REPL: 2 triples, regime rdfs+rules.txt" in out
        assert REPL_HELP in out

    def test_quit_ends_the_session_before_later_lines(self, store, capsys):
        # "help" after "quit" must never be read (side_effect would supply it)
        rc, out = run(store, capsys, "quit", "help", quit_=False)
        assert rc == 0
        assert "Commands:" not in out

    def test_exit_and_eof_end_the_session(self, store, capsys):
        assert run(store, capsys, "exit", quit_=False)[0] == 0
        with patch("builtins.input", side_effect=EOFError):
            assert main(["rdf", "repl", "-g", str(store["graph"])]) == 0

    def test_unknown_command(self, store, capsys):
        _, out = run(store, capsys, "bogus", "trace", "ask", "coherent now")
        assert out.count("Unknown command. Type 'help'.") == 4

    def test_blank_lines_are_skipped(self, store, capsys):
        _, out = run(store, capsys, "", "   ", "coherent")
        assert "Unknown command" not in out and "COHERENT" in out

    def test_tell_then_coherent(self, store, capsys):
        _, out = run(store, capsys, "coherent", f"tell {TWEETY}", "coherent")
        assert out.index("COHERENT") < out.index("Added 1 triple(s) to the position; 1 asserted")
        assert "OUT OF BOUNDS: ⊥ from the regime rdfs+rules.txt" in out

    def test_withdraw_restores_coherence(self, store, capsys):
        _, out = run(store, capsys, f"tell {TWEETY}", f"withdraw {TWEETY}", "coherent")
        assert "Withdrawn; 0 asserted" in out
        assert out.rstrip().endswith("COHERENT")

    def test_deny_names_the_entry_and_its_rescue(self, store, capsys):
        _, out = run(store, capsys, f"deny {FLIES}", "coherent")
        assert "Denied; 1 rejected graph(s)" in out
        assert "OUT OF BOUNDS: entry " in out and "http://ex.org/Flies> [guarded]" in out
        assert "would be rescued by: <http://ex.org/tweety" in out and "Penguin>" in out

    def test_tell_error_is_reported_not_raised(self, store, capsys):
        rc, out = run(store, capsys, "tell nonsense", "deny nonsense", "withdraw nonsense")
        assert rc == 0
        assert out.count("Error: 'nonsense' is not a triple atom <s p o>") == 3

    def test_challenges(self, store, capsys):
        _, out = run(store, capsys, f"tell {KIM}", "challenges")
        assert "1. [incoherence] Do you also accept <http://ex.org/kim" in out
        assert f"{BIRD}>? Then " in out and "puts you out of bounds." in out

    def test_challenges_when_nothing_bears(self, tmp_path, capsys):
        g = tmp_path / "plain.ttl"
        g.write_text("@prefix ex: <http://ex.org/> .\nex:a ex:p ex:b .\n")
        with patch("builtins.input", side_effect=["challenges", "quit"]):
            assert main(["rdf", "repl", "-g", str(g)]) == 0
        out = capsys.readouterr().out
        assert "No challenges: nothing in the base bears on this position." in out

    def test_propose_reports_without_writing(self, store, capsys):
        _, out = run(store, capsys, f"tell {TWEETY}", "propose", "show")
        assert "out of bounds" in out.lower()
        assert "Triples: 2 " in out  # nothing committed
        assert len(Graph().parse(str(store["graph"]))) == 2

    def test_position_lists_commitments_denials_and_moves(self, store, capsys):
        _, out = run(store, capsys, f"tell {KIM}", f"deny {FLIES}", "position")
        assert "Holder: repl" in out
        assert "  + <http://ex.org/kim http://www.w3.org/1999/02/22-rdf-syntax-ns#type " \
               "http://ex.org/Fish>" in out
        assert "  - " in out
        assert "  1. assert <http://ex.org/kim" in out and "  2. deny " in out

    def test_entitlement_and_defend(self, store, capsys):
        _, out = run(store, capsys, f"tell {KIM}", "entitlement", "defend", "entitlement")
        assert "  [asserted ] <http://ex.org/kim" in out
        assert "  score {'committed': 1, 'entitled': 0, 'open': 1}" in out
        assert re.search(r"^(STOOD|REFUTED): \d+ refutation\(s\), \d+ open probe\(s\); score ",
                         out, re.M)

    def test_show_trace_and_ask(self, store, capsys):
        _, out = run(store, capsys, "show", "trace on", "ask <ex:tweety a ex:Bird>",
                     "trace off", "ask <ex:tweety a ex:Fish>")
        assert "Triples: 2  closure: " in out and "regime: rdfs+rules.txt" in out
        assert "Position: 0 asserted, 0 denied, 0 moves" in out
        assert "  @prefix ex: <http://ex.org/>" in out
        assert "Trace: ON" in out and "Trace: OFF" in out
        assert "DERIVABLE\n\nProof trace:" in out and "AXIOM:" in out
        assert out.rstrip().endswith("NOT DERIVABLE")

    def test_commit_save_and_load(self, store, capsys, tmp_path):
        out_file = tmp_path / "out.ttl"
        more = tmp_path / "more.ttl"
        more.write_text("@prefix ex: <http://ex.org/> .\nex:x ex:p ex:y .\n")
        _, out = run(store, capsys, f"tell {KIM}", "commit", f"load {more}",
                     "tell <ex:z a ex:Fish>", f"save {out_file}", "load /nonexistent.ttl")
        # the holder's first commit also writes its PROV attribution triple
        assert "Committed 1 new triple(s); 4 in the graph" in out
        assert "Loaded 1 triple(s); 5 total" in out
        assert "Committed 1 new triple(s)\nSaved 6 triples to " in out
        assert len(Graph().parse(str(out_file))) == 6
        assert "Error: " in out.splitlines()[-1]

    def test_save_defaults_to_the_first_graph_file(self, store, capsys):
        _, out = run(store, capsys, f"tell {KIM}", "save")
        assert f"Saved 4 triples to {store['graph']}" in out  # kim plus the attribution
        assert len(Graph().parse(str(store["graph"]))) == 4

    def test_save_without_a_file(self, tmp_path, capsys):
        pytest.importorskip("pyoxigraph")
        with patch("builtins.input", side_effect=["save", "quit"]):
            assert main(["rdf", "repl", "--oxigraph", str(tmp_path / "ox")]) == 0
        assert "Error: no file given and none loaded" in capsys.readouterr().out
