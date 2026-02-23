"""Tests for pynmms CLI --rq flag with tell, ask, and repl subcommands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from pynmms.cli.main import main


class TestRQTellCommand:
    def test_tell_rq_creates_base(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "--rq", "Happy(alice) |~ Good(alice)"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "Happy(alice)" in data["language"]
        assert "Good(alice)" in data["language"]
        assert len(data["consequences"]) == 1
        assert "schemas" in data

        Path(path).unlink()

    def test_tell_rq_atom(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "--rq", "atom hasChild(alice,bob)"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "hasChild(alice,bob)" in data["language"]
        assert "alice" in data["individuals"]
        assert "bob" in data["individuals"]
        assert "hasChild" in data["roles"]

        Path(path).unlink()

    def test_tell_rq_no_create_missing(self):
        result = main(["tell", "-b", "/nonexistent/rq_base.json", "--rq", "P(a) |~ Q(a)"])
        assert result == 1


class TestRQAskCommand:
    def test_ask_rq_derivable(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)", "Good(alice)"],
                "consequences": [{"antecedent": ["Happy(alice)"], "consequent": ["Good(alice)"]}],
                "individuals": ["alice"],
                "concepts": ["Happy", "Good"],
                "roles": [],
                "schemas": [],
            }, f)
            path = f.name

        result = main(["ask", "-b", path, "--rq", "Happy(alice) => Good(alice)"])
        assert result == 0

        Path(path).unlink()

    def test_ask_rq_not_derivable(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)"],
                "consequences": [],
                "individuals": ["alice"],
                "concepts": ["Happy"],
                "roles": [],
                "schemas": [],
            }, f)
            path = f.name

        result = main(["ask", "-b", path, "--rq", "Happy(alice) => Sad(alice)"])
        assert result == 2

        Path(path).unlink()

    def test_ask_rq_with_trace(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)"],
                "consequences": [],
                "individuals": ["alice"],
                "concepts": ["Happy"],
                "roles": [],
                "schemas": [],
            }, f)
            path = f.name

        result = main([
            "ask", "-b", path, "--rq", "--trace",
            "Happy(alice) => Happy(alice)",
        ])
        assert result == 0

        Path(path).unlink()


class TestRQReplCommand:
    def _run_repl(self, inputs, rq=True):
        """Run the REPL with the given inputs."""
        args = ["repl"]
        if rq:
            args.append("--rq")
        with patch("builtins.input", side_effect=inputs + ["quit"]):
            return main(args)

    def test_repl_rq_tell_and_ask(self):
        result = self._run_repl([
            "tell Happy(alice) |~ Good(alice)",
            "ask Happy(alice) => Good(alice)",
        ])
        assert result == 0

    def test_repl_rq_tell_atom(self):
        result = self._run_repl([
            "tell atom hasChild(alice,bob)",
            "show",
        ])
        assert result == 0

    def test_repl_rq_show_schemas(self):
        result = self._run_repl([
            "tell schema concept hasChild alice Happy",
            "show schemas",
        ])
        assert result == 0

    def test_repl_rq_show_individuals(self):
        result = self._run_repl([
            "tell atom Happy(alice)",
            "show individuals",
        ])
        assert result == 0

    def test_repl_rq_help(self):
        result = self._run_repl(["help"])
        assert result == 0

    def test_repl_rq_schema_inference(self):
        result = self._run_repl([
            "tell schema inference hasChild alice Smart Happy",
            "show schemas",
        ])
        assert result == 0

    def test_repl_rq_schema_with_annotation(self, capsys):
        result = self._run_repl([
            'tell schema concept hasChild alice Happy "All children are happy"',
            "show schemas",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "All children are happy" in out
