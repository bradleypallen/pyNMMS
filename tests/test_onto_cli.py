"""Tests for pynmms CLI --onto flag with tell, ask, and repl subcommands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from pynmms.cli.main import main


class TestOntoTellCommand:
    def test_tell_onto_creates_base(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "--onto", "Happy(alice) |~ Good(alice)"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "Happy(alice)" in data["language"]
        assert "Good(alice)" in data["language"]
        assert len(data["consequences"]) == 1
        assert "onto_schemas" in data

        Path(path).unlink()

    def test_tell_onto_atom(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        result = main(["tell", "-b", path, "--create", "--onto", "atom hasChild(alice,bob)"])
        assert result == 0

        with open(path) as f:
            data = json.load(f)
        assert "hasChild(alice,bob)" in data["language"]
        assert "alice" in data["individuals"]
        assert "bob" in data["individuals"]
        assert "hasChild" in data["roles"]

        Path(path).unlink()

    def test_tell_onto_no_create_missing(self):
        result = main(["tell", "-b", "/nonexistent/onto_base.json", "--onto", "P(a) |~ Q(a)"])
        assert result == 1


class TestOntoAskCommand:
    def test_ask_onto_derivable(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)", "Good(alice)"],
                "consequences": [{"antecedent": ["Happy(alice)"], "consequent": ["Good(alice)"]}],
                "individuals": ["alice"],
                "concepts": ["Happy", "Good"],
                "roles": [],
                "onto_schemas": [],
            }, f)
            path = f.name

        result = main(["ask", "-b", path, "--onto", "Happy(alice) => Good(alice)"])
        assert result == 0

        Path(path).unlink()

    def test_ask_onto_not_derivable(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)"],
                "consequences": [],
                "individuals": ["alice"],
                "concepts": ["Happy"],
                "roles": [],
                "onto_schemas": [],
            }, f)
            path = f.name

        result = main(["ask", "-b", path, "--onto", "Happy(alice) => Sad(alice)"])
        assert result == 2

        Path(path).unlink()

    def test_ask_onto_with_trace(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({
                "language": ["Happy(alice)"],
                "consequences": [],
                "individuals": ["alice"],
                "concepts": ["Happy"],
                "roles": [],
                "onto_schemas": [],
            }, f)
            path = f.name

        result = main([
            "ask", "-b", path, "--onto", "--trace",
            "Happy(alice) => Happy(alice)",
        ])
        assert result == 0

        Path(path).unlink()


class TestOntoReplCommand:
    def _run_repl(self, inputs, onto=True):
        """Run the REPL with the given inputs."""
        args = ["repl"]
        if onto:
            args.append("--onto")
        with patch("builtins.input", side_effect=inputs + ["quit"]):
            return main(args)

    def test_repl_onto_tell_and_ask(self):
        result = self._run_repl([
            "tell Happy(alice) |~ Good(alice)",
            "ask Happy(alice) => Good(alice)",
        ])
        assert result == 0

    def test_repl_onto_tell_atom(self):
        result = self._run_repl([
            "tell atom hasChild(alice,bob)",
            "show",
        ])
        assert result == 0

    def test_repl_onto_show_schemas(self):
        result = self._run_repl([
            "tell schema subClassOf Man Mortal",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_show_individuals(self):
        result = self._run_repl([
            "tell atom Happy(alice)",
            "show individuals",
        ])
        assert result == 0

    def test_repl_onto_help(self):
        result = self._run_repl(["help"])
        assert result == 0

    def test_repl_onto_schema_range(self):
        result = self._run_repl([
            "tell schema range hasChild Person",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_schema_domain(self):
        result = self._run_repl([
            "tell schema domain hasChild Parent",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_schema_subproperty(self):
        result = self._run_repl([
            "tell schema subPropertyOf hasChild hasDescendant",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_schema_disjoint_with(self):
        result = self._run_repl([
            "tell atom Man(socrates)",
            "tell atom Woman(socrates)",
            "tell schema disjointWith Man Woman",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_schema_disjoint_properties(self):
        result = self._run_repl([
            "tell atom hasChild(alice,bob)",
            "tell atom hasParent(alice,bob)",
            "tell schema disjointProperties hasChild hasParent",
            "show schemas",
        ])
        assert result == 0

    def test_repl_onto_schema_disjoint_with_annotation(self, capsys):
        result = self._run_repl([
            'tell schema disjointWith Man Woman "Men and women are disjoint"',
            "show schemas",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Men and women are disjoint" in out

    def test_repl_onto_schema_with_annotation(self, capsys):
        result = self._run_repl([
            'tell schema subClassOf Man Mortal "All men are mortal"',
            "show schemas",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "All men are mortal" in out

    def test_repl_onto_schema_joint_commitment(self, capsys):
        result = self._run_repl([
            "tell schema jointCommitment ChestPain,ElevatedTroponin MI",
            "show schemas",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "jointCommitment" in out
        assert "ChestPain(x)" in out
        assert "MI(x)" in out

    def test_repl_onto_schema_joint_commitment_annotation(self, capsys):
        result = self._run_repl([
            'tell schema jointCommitment ChestPain,ElevatedTroponin MI "Joint MI rule"',
            "show schemas",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "Joint MI rule" in out


class TestRoleAssertionsInSequents:
    """Commas inside R(a,b) must not split the sequent (depth-aware splitting)."""

    def test_ask_role_assertion_with_range_schema(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        assert main(["tell", "-b", path, "--create", "--onto",
                     "atom hasChild(alice,bob)"]) == 0
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as bf:
            bf.write("schema range hasChild Person\n")
            batch_path = bf.name
        assert main(["tell", "-b", path, "--onto", "--batch", batch_path]) == 0
        Path(batch_path).unlink()
        assert main(["ask", "-b", path, "--onto",
                     "hasChild(alice,bob) => Person(bob)"]) == 0
        assert main(["ask", "-b", path, "--onto",
                     "hasChild(alice, bob) => Person(alice)"]) == 2

        Path(path).unlink()

    def test_tell_consequence_with_two_role_assertions(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()

        stmt = "hasChild(alice,bob), hasChild(bob,carol) |~ hasGrandchild(alice,carol)"
        assert main(["tell", "-b", path, "--create", "--onto", stmt]) == 0
        with open(path) as f:
            data = json.load(f)
        assert sorted(data["consequences"][0]["antecedent"]) == [
            "hasChild(alice,bob)", "hasChild(bob,carol)"
        ]

        Path(path).unlink()


class TestSchemaRobustnessClause:
    def test_guarded_schema_via_batch_and_ask(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        Path(path).unlink()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as bf:
            bf.write('schema subClassOf Bird Flies unless Penguin "birds fly"\n')
            bf.write("schema disjointWith Alive Dead monotone\n")
            batch_path = bf.name

        assert main(["tell", "-b", path, "--create", "--onto", "--batch", batch_path]) == 0
        with open(path) as f:
            data = json.load(f)
        assert data["onto_schemas"][0]["robustness"]["unless"]["antecedent"] == ["Penguin"]
        assert data["onto_schemas"][0]["annotation"] == "birds fly"
        assert data["onto_schemas"][1]["robustness"] == {"kind": "monotone"}

        assert main(["ask", "-b", path, "--onto", "Bird(a), Tall(a) => Flies(a)"]) == 0
        assert main(["ask", "-b", path, "--onto", "Bird(a), Penguin(a) => Flies(a)"]) == 2
        assert main(["ask", "-b", path, "--onto", "Alive(a), Dead(a), Tall(a) =>"]) == 0

        Path(path).unlink()
        Path(batch_path).unlink()

    def test_repl_schema_with_clause_and_show(self, capsys):
        inputs = iter([
            "tell schema subClassOf Bird Flies unless Penguin",
            "tell Bird(b) |~ Sings(b) monotone",
            "show schemas",
            "show",
            "quit",
        ])
        with patch("builtins.input", lambda _: next(inputs)):
            main(["repl", "--onto"])
        out = capsys.readouterr().out
        assert "Registered subClassOf schema: {Bird(x)} |~ {Flies(x)} [unless Penguin]" in out
        assert "subClassOf: {Bird(x)} |~ {Flies(x)} [unless Penguin]" in out
        assert "[monotone]" in out
