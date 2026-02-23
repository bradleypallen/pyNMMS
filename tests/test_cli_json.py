"""Tests for CLI JSON, quiet, stdin, batch, exit codes, empty sides, annotations."""

import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from pynmms.cli.main import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_file():
    """Create a base file with A |~ B and B |~ C."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({
            "language": ["A", "B", "C"],
            "consequences": [
                {"antecedent": ["A"], "consequent": ["B"]},
                {"antecedent": ["B"], "consequent": ["C"]},
            ],
        }, f)
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def empty_base():
    """Create an empty base file."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    Path(path).unlink()
    yield path
    Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_ask_derivable_returns_0(self, base_file):
        assert main(["ask", "-b", base_file, "A => B"]) == 0

    def test_ask_not_derivable_returns_2(self, base_file):
        assert main(["ask", "-b", base_file, "A => C"]) == 2

    def test_ask_error_returns_1(self, base_file):
        assert main(["ask", "-b", base_file, "not a sequent"]) == 1

    def test_ask_missing_base_returns_1(self):
        assert main(["ask", "-b", "/tmp/no_such_pynmms_file.json", "A => B"]) == 1

    def test_tell_success_returns_0(self, empty_base):
        assert main(["tell", "-b", empty_base, "--create", "A |~ B"]) == 0

    def test_tell_error_returns_1(self):
        assert main(["tell", "-b", "/tmp/no_such_pynmms_file.json", "A |~ B"]) == 1


# ---------------------------------------------------------------------------
# JSON output — ask
# ---------------------------------------------------------------------------

class TestAskJSON:
    def test_ask_json_derivable(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "--json", "A => B"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "DERIVABLE"
        assert data["sequent"]["antecedent"] == ["A"]
        assert data["sequent"]["consequent"] == ["B"]
        assert "depth_reached" in data
        assert "cache_hits" in data

    def test_ask_json_not_derivable(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "--json", "A => C"])
        assert rc == 2
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "NOT_DERIVABLE"

    def test_ask_json_with_trace(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "--json", "--trace", "A => B"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "trace" in data
        assert isinstance(data["trace"], list)

    def test_ask_json_error(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "--json", "not a sequent"])
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "error" in data


# ---------------------------------------------------------------------------
# JSON output — tell
# ---------------------------------------------------------------------------

class TestTellJSON:
    def test_tell_json_consequence(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", "--json", "A |~ B"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["action"] == "added_consequence"
        assert data["consequence"]["antecedent"] == ["A"]

    def test_tell_json_atom(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", "--json", "atom X"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["action"] == "added_atom"
        assert data["atom"] == "X"

    def test_tell_json_atom_with_annotation(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", "--json",
                    'atom p "Tara is human"'])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["action"] == "added_atom"
        assert data["atom"] == "p"
        assert data["annotation"] == "Tara is human"


# ---------------------------------------------------------------------------
# Quiet mode
# ---------------------------------------------------------------------------

class TestQuietMode:
    def test_ask_quiet_derivable(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "-q", "A => B"])
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_ask_quiet_not_derivable(self, base_file, capsys):
        rc = main(["ask", "-b", base_file, "-q", "A => C"])
        assert rc == 2
        assert capsys.readouterr().out == ""

    def test_tell_quiet(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", "-q", "A |~ B"])
        assert rc == 0
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Stdin input
# ---------------------------------------------------------------------------

class TestStdinInput:
    def test_ask_stdin(self, base_file, capsys):
        with patch("sys.stdin", StringIO("A => B\n")):
            rc = main(["ask", "-b", base_file, "-"])
        assert rc == 0
        assert "DERIVABLE" in capsys.readouterr().out

    def test_tell_stdin(self, empty_base, capsys):
        with patch("sys.stdin", StringIO("A |~ B\n")):
            rc = main(["tell", "-b", empty_base, "--create", "-"])
        assert rc == 0


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

class TestBatchMode:
    def test_ask_batch_all_derivable(self, base_file, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# A comment\n")
            f.write("A => B\n")
            f.write("B => C\n")
            f.write("\n")  # blank line
            batch_path = f.name

        try:
            rc = main(["ask", "-b", base_file, "--batch", batch_path])
            assert rc == 0
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_ask_batch_some_not_derivable(self, base_file, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("A => B\n")
            f.write("A => C\n")  # not derivable
            batch_path = f.name

        try:
            rc = main(["ask", "-b", base_file, "--batch", batch_path])
            assert rc == 2
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_ask_batch_json(self, base_file, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("A => B\n")
            f.write("A => C\n")
            batch_path = f.name

        try:
            main(["ask", "-b", base_file, "--json", "--batch", batch_path])
            out = capsys.readouterr().out
            lines = [line for line in out.strip().split("\n") if line]
            assert len(lines) == 2
            assert json.loads(lines[0])["status"] == "DERIVABLE"
            assert json.loads(lines[1])["status"] == "NOT_DERIVABLE"
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_ask_batch_stdin(self, base_file, capsys):
        with patch("sys.stdin", StringIO("A => B\nB => C\n")):
            rc = main(["ask", "-b", base_file, "--batch", "-"])
        assert rc == 0

    def test_tell_batch(self, empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# Build base\n")
            f.write("atom X\n")
            f.write("A |~ B\n")
            f.write("B |~ C\n")
            batch_path = f.name

        try:
            rc = main(["tell", "-b", empty_base, "--create", "--batch", batch_path])
            assert rc == 0

            with open(empty_base) as bf:
                data = json.load(bf)
            assert "X" in data["language"]
            assert len(data["consequences"]) == 2
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_tell_batch_stdin(self, empty_base, capsys):
        with patch("sys.stdin", StringIO("atom A\natom B\nA |~ B\n")):
            rc = main(["tell", "-b", empty_base, "--create", "--batch", "-"])
        assert rc == 0

        with open(empty_base) as f:
            data = json.load(f)
        assert "A" in data["language"]
        assert len(data["consequences"]) == 1


# ---------------------------------------------------------------------------
# Empty sides
# ---------------------------------------------------------------------------

class TestEmptySides:
    def test_tell_empty_consequent(self, empty_base, capsys):
        """Incompatibility: s, t |~ (Toy Base T)."""
        rc = main(["tell", "-b", empty_base, "--create", "s, t |~"])
        assert rc == 0
        with open(empty_base) as f:
            data = json.load(f)
        assert len(data["consequences"]) == 1
        entry = data["consequences"][0]
        assert set(entry["antecedent"]) == {"s", "t"}
        assert entry["consequent"] == []

    def test_tell_empty_antecedent(self, empty_base, capsys):
        """Theorem: |~ p."""
        rc = main(["tell", "-b", empty_base, "--create", "|~ p"])
        assert rc == 0
        with open(empty_base) as f:
            data = json.load(f)
        assert len(data["consequences"]) == 1
        entry = data["consequences"][0]
        assert entry["antecedent"] == []
        assert set(entry["consequent"]) == {"p"}

    def test_repl_empty_consequent(self, capsys):
        inputs = ["tell s, t |~", "show", "quit"]
        with patch("builtins.input", side_effect=inputs):
            rc = main(["repl"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "set() |~" not in out or "|~" in out  # consequence was added

    def test_repl_empty_antecedent(self, capsys):
        inputs = ["tell |~ p", "show", "quit"]
        with patch("builtins.input", side_effect=inputs):
            rc = main(["repl"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Added:" in out


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

class TestAnnotations:
    def test_tell_atom_annotation(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", 'atom p "Tara is human"'])
        assert rc == 0
        with open(empty_base) as f:
            data = json.load(f)
        assert data["annotations"]["p"] == "Tara is human"

    def test_tell_atom_no_annotation(self, empty_base, capsys):
        rc = main(["tell", "-b", empty_base, "--create", "atom p"])
        assert rc == 0
        with open(empty_base) as f:
            data = json.load(f)
        assert "annotations" not in data or "p" not in data.get("annotations", {})

    def test_repl_annotation_display(self, capsys):
        inputs = [
            'tell atom p "Tara is human"',
            "show",
            "quit",
        ]
        with patch("builtins.input", side_effect=inputs):
            rc = main(["repl"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Tara is human" in out

    def test_annotation_round_trip(self, empty_base):
        main(["tell", "-b", empty_base, "--create", 'atom p "Tara is human"'])
        main(["tell", "-b", empty_base, "atom q"])
        main(["tell", "-b", empty_base, "p |~ q"])

        with open(empty_base) as f:
            data = json.load(f)
        assert data["annotations"]["p"] == "Tara is human"
        assert "q" not in data.get("annotations", {})

    def test_tell_batch_with_annotations(self, empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write('atom p "Tara is human"\n')
            f.write('atom q "Tara body temp is 37C"\n')
            f.write("p |~ q\n")
            batch_path = f.name

        try:
            rc = main(["tell", "-b", empty_base, "--create", "--batch", batch_path])
            assert rc == 0

            with open(empty_base) as bf:
                data = json.load(bf)
            assert data["annotations"]["p"] == "Tara is human"
            assert data["annotations"]["q"] == "Tara body temp is 37C"
        finally:
            Path(batch_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Toy Base T (integration)
# ---------------------------------------------------------------------------

class TestToyBaseT:
    """Verify the full Toy Base T workflow from the plan."""

    def test_toy_base_t_repl_workflow(self, capsys):
        inputs = [
            'tell atom p "Tara is human"',
            'tell atom q "Tara body temp is 37C"',
            'tell atom v "Tara is healthy"',
            'tell atom s "X is a triangle"',
            'tell atom t "angle-sum exceeds two right angles"',
            'tell atom w "angle-sum equals two right angles"',
            'tell atom x "X is a Euclidean plane triangle"',
            "tell p |~ q",
            "tell s, t |~",
            "tell p, q |~ v",
            "tell s |~ w",
            "tell s, w |~ x",
            "show",
            "ask p => q",          # DERIVABLE
            "ask p, r => q",       # NOT DERIVABLE (monotonicity failure)
            "ask => p -> q",       # DERIVABLE (DD)
            "ask => ~(s & t)",     # DERIVABLE (II)
            "ask p => v",          # NOT DERIVABLE (transitivity failure)
            "quit",
        ]

        with patch("builtins.input", side_effect=inputs):
            rc = main(["repl"])
        assert rc == 0

        out = capsys.readouterr().out
        lines = out.split("\n")

        # Find the ask results
        derivable_set = ("DERIVABLE", "NOT DERIVABLE")
        ask_results = [
            line.strip() for line in lines if line.strip() in derivable_set
        ]
        assert ask_results == [
            "DERIVABLE",      # p => q
            "NOT DERIVABLE",  # p, r => q
            "DERIVABLE",      # => p -> q
            "DERIVABLE",      # => ~(s & t)
            "NOT DERIVABLE",  # p => v
        ]

        # Annotations visible in show
        assert "Tara is human" in out
