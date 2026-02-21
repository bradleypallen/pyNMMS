"""Tests for pynmms CLI — tell, ask, and repl subcommands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pynmms.cli.main import main


class TestTellCommand:
    def test_tell_creates_base(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()  # ensure it doesn't exist

        result = main(["tell", "-b", path, "--create", "A |~ B"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "A" in data["language"]
        assert "B" in data["language"]
        assert len(data["consequences"]) == 1

        Path(path).unlink()

    def test_tell_appends_to_existing(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"language": ["A", "B"], "consequences": [
                {"antecedent": ["A"], "consequent": ["B"]}
            ]}, f)
            path = f.name

        result = main(["tell", "-b", path, "B |~ C"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert len(data["consequences"]) == 2

        Path(path).unlink()

    def test_tell_atom(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "atom X"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "X" in data["language"]

        Path(path).unlink()

    def test_tell_no_create_fails(self):
        result = main(["tell", "-b", "/tmp/nonexistent_pynmms_test.json", "A |~ B"])
        assert result == 1

    def test_tell_bad_syntax(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "just a sentence"])
        assert result == 1

        Path(path).unlink(missing_ok=True)


class TestAskCommand:
    @pytest.fixture
    def base_file(self):
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
        Path(path).unlink()

    def test_ask_derivable(self, base_file, capsys):
        result = main(["ask", "-b", base_file, "A => B"])
        assert result == 0
        captured = capsys.readouterr()
        assert "DERIVABLE" in captured.out

    def test_ask_not_derivable(self, base_file, capsys):
        result = main(["ask", "-b", base_file, "A => C"])
        assert result == 0
        captured = capsys.readouterr()
        assert "NOT DERIVABLE" in captured.out

    def test_ask_with_trace(self, base_file, capsys):
        result = main(["ask", "-b", base_file, "--trace", "A => B"])
        assert result == 0
        captured = capsys.readouterr()
        assert "DERIVABLE" in captured.out
        assert "Proof trace" in captured.out

    def test_ask_nonexistent_base(self, capsys):
        result = main(["ask", "-b", "/tmp/nonexistent_pynmms.json", "A => B"])
        assert result == 1

    def test_ask_bad_sequent(self, base_file, capsys):
        result = main(["ask", "-b", base_file, "not a sequent"])
        assert result == 1


class TestReplCommand:
    def test_repl_basic_session(self, capsys):
        """Test a basic REPL session with tell and ask."""
        inputs = [
            "tell atom A",
            "tell atom B",
            "tell A |~ B",
            "ask A => B",
            "show",
            "help",
            "quit",
        ]

        with patch("builtins.input", side_effect=inputs):
            result = main(["repl"])
        assert result == 0
        captured = capsys.readouterr()
        assert "DERIVABLE" in captured.out

    def test_repl_eof(self, capsys):
        """Test REPL exits on EOF."""
        with patch("builtins.input", side_effect=EOFError):
            result = main(["repl"])
        assert result == 0

    def test_repl_save_load(self, capsys):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        inputs = [
            "tell A |~ B",
            f"save {path}",
            "quit",
        ]

        with patch("builtins.input", side_effect=inputs):
            main(["repl"])

        # Now load in a new session
        inputs2 = [
            f"load {path}",
            "ask A => B",
            "quit",
        ]

        with patch("builtins.input", side_effect=inputs2):
            main(["repl"])

        captured = capsys.readouterr()
        assert "DERIVABLE" in captured.out

        Path(path).unlink(missing_ok=True)

    def test_repl_trace_toggle(self, capsys):
        inputs = [
            "tell A |~ B",
            "trace on",
            "ask A => B",
            "trace off",
            "quit",
        ]

        with patch("builtins.input", side_effect=inputs):
            main(["repl"])

        captured = capsys.readouterr()
        assert "Trace: ON" in captured.out
        assert "AXIOM" in captured.out  # trace output includes axiom

    def test_repl_unknown_command(self, capsys):
        inputs = ["foobar", "quit"]

        with patch("builtins.input", side_effect=inputs):
            main(["repl"])

        captured = capsys.readouterr()
        assert "Unknown command" in captured.out


class TestMainEntry:
    def test_no_command_shows_help(self, capsys):
        result = main([])
        assert result == 0

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
