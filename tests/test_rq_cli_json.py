"""RQ-specific tests for JSON output and exit codes."""

import json
import tempfile
from pathlib import Path

import pytest

from pynmms.cli.main import main


@pytest.fixture
def rq_base_file():
    """Create an RQ base file with Happy(alice) |~ Good(alice)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({
            "language": ["Happy(alice)", "Good(alice)"],
            "consequences": [
                {"antecedent": ["Happy(alice)"], "consequent": ["Good(alice)"]}
            ],
            "individuals": ["alice"],
            "concepts": ["Good", "Happy"],
            "roles": [],
            "schemas": [],
        }, f)
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def rq_empty_base():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    Path(path).unlink()
    yield path
    Path(path).unlink(missing_ok=True)


class TestRQExitCodes:
    def test_ask_rq_derivable_returns_0(self, rq_base_file):
        rc = main(["ask", "-b", rq_base_file, "--rq", "Happy(alice) => Good(alice)"])
        assert rc == 0

    def test_ask_rq_not_derivable_returns_2(self, rq_base_file):
        rc = main(["ask", "-b", rq_base_file, "--rq", "Happy(alice) => Sad(alice)"])
        assert rc == 2


class TestRQAskJSON:
    def test_ask_rq_json_derivable(self, rq_base_file, capsys):
        rc = main(["ask", "-b", rq_base_file, "--rq", "--json",
                    "Happy(alice) => Good(alice)"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "DERIVABLE"

    def test_ask_rq_json_not_derivable(self, rq_base_file, capsys):
        rc = main(["ask", "-b", rq_base_file, "--rq", "--json",
                    "Happy(alice) => Sad(alice)"])
        assert rc == 2
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "NOT_DERIVABLE"


class TestRQTellJSON:
    def test_tell_rq_json_atom(self, rq_empty_base, capsys):
        rc = main(["tell", "-b", rq_empty_base, "--create", "--rq", "--json",
                    "atom hasChild(alice,bob)"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["action"] == "added_atom"
        assert data["atom"] == "hasChild(alice,bob)"

    def test_tell_rq_json_consequence(self, rq_empty_base, capsys):
        rc = main(["tell", "-b", rq_empty_base, "--create", "--rq", "--json",
                    "Happy(alice) |~ Good(alice)"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["action"] == "added_consequence"


class TestRQBatch:
    def test_tell_rq_batch(self, rq_empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write('atom Happy(alice) "Alice is happy"\n')
            f.write("atom hasChild(alice,bob)\n")
            f.write("Happy(alice) |~ Good(alice)\n")
            f.write("schema concept hasChild alice Happy\n")
            f.write("schema inference hasChild alice Serious HeartAttack\n")
            batch_path = f.name

        try:
            rc = main(["tell", "-b", rq_empty_base, "--create", "--rq",
                        "--batch", batch_path])
            assert rc == 0

            with open(rq_empty_base) as bf:
                data = json.load(bf)
            assert "Happy(alice)" in data["language"]
            assert "hasChild(alice,bob)" in data["language"]
            assert len(data["consequences"]) == 1
            assert len(data["schemas"]) == 2
            assert data["annotations"]["Happy(alice)"] == "Alice is happy"
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_tell_rq_batch_json(self, rq_empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("atom Happy(alice)\n")
            f.write("Happy(alice) |~ Good(alice)\n")
            batch_path = f.name

        try:
            rc = main(["tell", "-b", rq_empty_base, "--create", "--rq",
                        "--json", "--batch", batch_path])
            assert rc == 0
            out = capsys.readouterr().out
            lines = [line for line in out.strip().split("\n") if line]
            assert len(lines) == 2
            assert json.loads(lines[0])["action"] == "added_atom"
            assert json.loads(lines[1])["action"] == "added_consequence"
        finally:
            Path(batch_path).unlink(missing_ok=True)


class TestRQAnnotations:
    def test_rq_annotation_round_trip(self, rq_empty_base):
        main(["tell", "-b", rq_empty_base, "--create", "--rq",
              'atom Happy(alice) "Alice is happy"'])

        with open(rq_empty_base) as f:
            data = json.load(f)
        assert data["annotations"]["Happy(alice)"] == "Alice is happy"

        # Load and re-save to verify round-trip
        from pynmms.rq.base import RQMaterialBase
        base = RQMaterialBase.from_file(rq_empty_base)
        assert base.annotations["Happy(alice)"] == "Alice is happy"


class TestRQSchemaAnnotations:
    def test_concept_schema_annotation_json(self, rq_empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("atom hasChild(alice,bob)\n")
            f.write('schema concept hasChild alice Happy "All children of alice are happy"\n')
            batch_path = f.name

        try:
            rc = main([
                "tell", "-b", rq_empty_base, "--create", "--rq", "--json",
                "--batch", batch_path,
            ])
            assert rc == 0
            out = capsys.readouterr().out
            lines = [line for line in out.strip().split("\n") if line]
            schema_line = json.loads(lines[1])
            assert schema_line["action"] == "registered_concept_schema"
            assert schema_line["annotation"] == "All children of alice are happy"

            # Verify annotation in serialized file
            with open(rq_empty_base) as bf:
                data = json.load(bf)
            assert len(data["schemas"]) == 1
            assert data["schemas"][0]["annotation"] == "All children of alice are happy"
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_inference_schema_annotation_json(self, rq_empty_base, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("atom hasChild(alice,bob)\n")
            f.write('schema inference hasChild alice Serious HeartAttack '
                    '"Serious children risk heart attacks"\n')
            batch_path = f.name

        try:
            rc = main([
                "tell", "-b", rq_empty_base, "--create", "--rq", "--json",
                "--batch", batch_path,
            ])
            assert rc == 0
            out = capsys.readouterr().out
            lines = [line for line in out.strip().split("\n") if line]
            schema_line = json.loads(lines[1])
            assert schema_line["action"] == "registered_inference_schema"
            assert schema_line["annotation"] == "Serious children risk heart attacks"

            with open(rq_empty_base) as bf:
                data = json.load(bf)
            assert data["schemas"][0]["annotation"] == "Serious children risk heart attacks"
        finally:
            Path(batch_path).unlink(missing_ok=True)

    def test_schema_annotation_round_trip(self, rq_empty_base):
        """Save with annotation, load, verify annotation preserved."""
        from pynmms.rq.base import RQMaterialBase

        base = RQMaterialBase(language={"hasChild(alice,bob)"})
        base.register_concept_schema(
            "hasChild", "alice", "Happy",
            annotation="All children of alice are happy",
        )
        base.to_file(rq_empty_base)

        restored = RQMaterialBase.from_file(rq_empty_base)
        assert len(restored._inference_schemas) == 1
        assert restored.schema_annotations == ["All children of alice are happy"]

    def test_schema_without_annotation_omits_field(self, rq_empty_base):
        """Schema without annotation should not have 'annotation' key in JSON."""
        from pynmms.rq.base import RQMaterialBase

        base = RQMaterialBase(language={"hasChild(alice,bob)"})
        base.register_concept_schema("hasChild", "alice", "Happy")
        base.to_file(rq_empty_base)

        with open(rq_empty_base) as f:
            data = json.load(f)
        assert "annotation" not in data["schemas"][0]
