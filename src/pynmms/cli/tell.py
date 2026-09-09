"""``pynmms tell`` subcommand — add atoms or consequences to a base."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.cli.exitcodes import EXIT_ERROR, EXIT_SUCCESS
from pynmms.cli.output import (
    emit_error,
    emit_json,
    tell_atom_response,
    tell_consequence_response,
    tell_schema_response,
)
from pynmms.cli.schema_line import (
    extract_trailing_annotation,
    format_registration,
    register_schema_line,
)
from pynmms.onto.base import OntoMaterialBase
from pynmms.robustness import EXACT, Robustness, split_robustness_clause
from pynmms.syntax import find_top_level, split_top_level

logger = logging.getLogger(__name__)

TellStatement = tuple[
    str, frozenset[str] | None, frozenset[str] | None, str | None, Robustness
]


def _parse_tell_statement(statement: str) -> TellStatement:
    """Parse a tell statement (shared by ``tell`` and the REPL).

    Returns ``(kind, antecedent, consequent, annotation, robustness)``:
        ("atom", frozenset({name}), None, annotation_or_None, EXACT)
            for ``atom X`` or ``atom X "desc"``
        ("consequence", antecedent, consequent, None, robustness)
            for ``A, B |~ C, D``, optionally followed by ``unless X, Y`` or
            ``monotone``
    """
    statement = statement.strip()

    if statement.lower().startswith("atom "):
        atom, annotation = extract_trailing_annotation(statement[5:].strip())
        return ("atom", frozenset({atom}), None, annotation, EXACT)

    statement, robustness = split_robustness_clause(statement)

    turnstiles = find_top_level(statement, "|~")
    if not turnstiles:
        raise ValueError(
            f"Invalid tell statement: {statement!r}. "
            f'Expected "atom X" or "A, B |~ C, D".'
        )
    antecedent_str = statement[: turnstiles[0]]
    consequent_str = statement[turnstiles[0] + 2 :]

    antecedent = frozenset(split_top_level(antecedent_str, ","))
    consequent = frozenset(split_top_level(consequent_str, ","))

    return ("consequence", antecedent, consequent, None, robustness)


def _process_tell_statement(
    statement: str,
    base: MaterialBase,
    base_path: Path | str,
    *,
    json_mode: bool = False,
    quiet: bool = False,
    added_label: str = "Added consequence",
) -> int:
    """Process a single tell statement. Returns exit code.

    *added_label* is the prefix of the human-readable confirmation for a new
    consequence (the REPL says ``Added:``).
    """
    try:
        kind, antecedent, consequent, annotation, robustness = _parse_tell_statement(statement)
    except ValueError as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    if kind == "atom":
        assert antecedent is not None
        atom = next(iter(antecedent))
        try:
            base.add_atom(atom)
        except ValueError as e:
            emit_error(str(e), json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        if annotation:
            base.annotate(atom, annotation)
        if json_mode:
            emit_json(tell_atom_response(atom, str(base_path), annotation))
        elif not quiet:
            if annotation:
                print(f"Added atom: {atom} — {annotation}")
            else:
                print(f"Added atom: {atom}")
    else:
        assert antecedent is not None or consequent is not None
        ant = antecedent if antecedent else frozenset()
        con = consequent if consequent else frozenset()
        try:
            base.add_consequence(ant, con, robustness=robustness)
        except ValueError as e:
            emit_error(str(e), json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        if json_mode:
            emit_json(tell_consequence_response(
                ant, con, str(base_path), robustness=robustness.to_json()))
        elif not quiet:
            suffix = "" if robustness.is_exact else f" [{robustness}]"
            print(f"{added_label}: {set(ant)} |~ {set(con)}{suffix}")

    return EXIT_SUCCESS


def read_batch_lines(
    batch_source: str, *, json_mode: bool = False, quiet: bool = False
) -> list[str] | None:
    """Read a batch file (or stdin for ``-``), dropping blank and ``#`` lines.

    Returns ``None`` after reporting the error if the file cannot be read.
    """
    if batch_source == "-":
        raw = sys.stdin.read().splitlines()
    else:
        try:
            with open(batch_source) as f:
                raw = f.read().splitlines()
        except OSError as e:
            emit_error(str(e), json_mode=json_mode, quiet=quiet)
            return None
    lines = [line.strip() for line in raw]
    return [line for line in lines if line and not line.startswith("#")]


def run_tell(args: argparse.Namespace) -> int:
    """Execute the ``tell`` subcommand."""
    base_path = Path(args.base)
    onto_mode: bool = args.onto
    json_mode: bool = args.json
    quiet: bool = args.quiet
    batch: str | None = args.batch
    base_cls: type[MaterialBase] = OntoMaterialBase if onto_mode else MaterialBase

    base: MaterialBase
    if base_path.exists():
        base = base_cls.from_file(base_path)
    elif args.create:
        base = base_cls()
    else:
        msg = f"Base file {base_path} does not exist. Use --create to create it."
        emit_error(msg, json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    # --- Batch mode ---
    if batch is not None:
        return _run_tell_batch(batch, base, base_path, onto_mode=onto_mode,
                               json_mode=json_mode, quiet=quiet)

    # --- Single statement ---
    statement = args.statement
    if statement is None:
        emit_error("No statement provided.", json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    if statement == "-":
        statement = sys.stdin.readline().rstrip("\n")

    rc = _process_tell_statement(statement, base, base_path,
                                 json_mode=json_mode, quiet=quiet)
    if rc == EXIT_SUCCESS:
        base.to_file(base_path)
        logger.info("Saved base to %s", base_path)
    return rc


def _run_tell_batch(
    batch_source: str,
    base: MaterialBase,
    base_path: Path,
    *,
    onto_mode: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
) -> int:
    """Process a batch file of tell statements."""
    lines = read_batch_lines(batch_source, json_mode=json_mode, quiet=quiet)
    if lines is None:
        return EXIT_ERROR

    had_error = False
    for line in lines:
        # Ontology schema lines
        if onto_mode and line.startswith("schema "):
            assert isinstance(base, OntoMaterialBase)
            rc = _process_onto_schema_line(line, base, base_path,
                                           json_mode=json_mode, quiet=quiet)
        else:
            rc = _process_tell_statement(line, base, base_path,
                                         json_mode=json_mode, quiet=quiet)
        if rc != EXIT_SUCCESS:
            had_error = True

    base.to_file(base_path)
    logger.info("Saved base to %s (batch)", base_path)
    return EXIT_ERROR if had_error else EXIT_SUCCESS


def _process_onto_schema_line(
    line: str,
    base: OntoMaterialBase,
    base_path: Path | str,
    *,
    json_mode: bool = False,
    quiet: bool = False,
) -> int:
    """Process an ontology schema line like ``schema subClassOf Man Mortal``."""
    try:
        schema_type, details, robustness, annotation = register_schema_line(base, line)
    except ValueError as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    if json_mode:
        emit_json(tell_schema_response(
            schema_type, details, str(base_path), annotation=annotation,
            robustness=robustness.to_json()))
    elif not quiet:
        print(format_registration(schema_type, details, robustness, annotation))
    return EXIT_SUCCESS
