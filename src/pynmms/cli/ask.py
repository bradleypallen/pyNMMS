"""``pynmms ask`` subcommand — query derivability of a sequent."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.cli.exitcodes import EXIT_ERROR, EXIT_NOT_DERIVABLE, EXIT_SUCCESS
from pynmms.cli.output import ask_response, emit_error, emit_json
from pynmms.reasoner import NMMSReasoner
from pynmms.syntax import find_top_level, split_top_level

logger = logging.getLogger(__name__)


def _parse_sequent(sequent_str: str) -> tuple[frozenset[str], frozenset[str]]:
    """Parse a sequent string like ``A, B => C, D``.

    Returns (antecedent, consequent) as frozensets of sentence strings.
    """
    sequent_str = sequent_str.strip()

    if "=>" not in sequent_str:
        raise ValueError(
            f"Invalid sequent: {sequent_str!r}. Expected 'A, B => C, D'."
        )

    arrows = find_top_level(sequent_str, "=>")
    if not arrows:
        raise ValueError(
            f"Invalid sequent: {sequent_str!r}. Expected 'A, B => C, D'."
        )
    ant_str = sequent_str[: arrows[0]]
    con_str = sequent_str[arrows[0] + 2 :]

    antecedent = frozenset(split_top_level(ant_str, ","))
    consequent = frozenset(split_top_level(con_str, ","))

    return antecedent, consequent


def _ask_one(
    sequent_str: str,
    reasoner: NMMSReasoner,
    *,
    trace: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
) -> int:
    """Query a single sequent. Returns exit code."""
    try:
        antecedent, consequent = _parse_sequent(sequent_str)
    except ValueError as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    try:
        result = reasoner.derives(antecedent, consequent)
    except ValueError as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    if json_mode:
        resp = ask_response(
            derivable=result.derivable,
            antecedent=antecedent,
            consequent=consequent,
            depth_reached=result.depth_reached,
            cache_hits=result.cache_hits,
            trace=result.trace if trace else None,
            depth_limited=result.depth_limited,
        )
        emit_json(resp)
    elif not quiet:
        if result.derivable:
            print("DERIVABLE")
        else:
            print("NOT DERIVABLE")
            if result.depth_limited:
                print("(search gave up at --max-depth; the sequent may still be derivable)")

        if trace:
            print("\nProof trace:")
            for line in result.trace:
                print(f"  {line}")
            print(f"\nDepth reached: {result.depth_reached}")
            print(f"Cache hits: {result.cache_hits}")

    logger.info(
        "Query %s => %s: %s (depth %d)",
        set(antecedent), set(consequent),
        "DERIVABLE" if result.derivable else "NOT DERIVABLE",
        result.depth_reached,
    )

    return EXIT_SUCCESS if result.derivable else EXIT_NOT_DERIVABLE


def run_ask(args: argparse.Namespace) -> int:
    """Execute the ``ask`` subcommand."""
    base_path = Path(args.base)
    onto_mode = getattr(args, "onto", False)
    json_mode = getattr(args, "json", False)
    quiet = getattr(args, "quiet", False)
    batch = getattr(args, "batch", None)
    trace = getattr(args, "trace", False)

    if not base_path.exists():
        msg = f"Base file {base_path} does not exist."
        emit_error(msg, json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    base: MaterialBase
    reasoner: NMMSReasoner

    if onto_mode:
        from pynmms.onto.base import OntoMaterialBase

        base = OntoMaterialBase.from_file(base_path)
        reasoner = NMMSReasoner(base, max_depth=args.max_depth)
    else:
        base = MaterialBase.from_file(base_path)
        reasoner = NMMSReasoner(base, max_depth=args.max_depth)

    # --- Batch mode ---
    if batch is not None:
        return _run_ask_batch(batch, reasoner, trace=trace,
                              json_mode=json_mode, quiet=quiet)

    # --- Single sequent ---
    sequent_str = args.sequent
    if sequent_str is None:
        emit_error("No sequent provided.", json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    if sequent_str == "-":
        sequent_str = sys.stdin.readline().rstrip("\n")

    return _ask_one(sequent_str, reasoner, trace=trace,
                    json_mode=json_mode, quiet=quiet)


def _run_ask_batch(
    batch_source: str,
    reasoner: NMMSReasoner,
    *,
    trace: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
) -> int:
    """Process a batch file of sequents."""
    if batch_source == "-":
        lines = sys.stdin.read().splitlines()
    else:
        try:
            with open(batch_source) as f:
                lines = f.read().splitlines()
        except OSError as e:
            emit_error(str(e), json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR

    any_not_derivable = False
    any_error = False

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        rc = _ask_one(line, reasoner, trace=trace,
                      json_mode=json_mode, quiet=quiet)
        if rc == EXIT_ERROR:
            any_error = True
        elif rc == EXIT_NOT_DERIVABLE:
            any_not_derivable = True

    if any_error:
        return EXIT_ERROR
    if any_not_derivable:
        return EXIT_NOT_DERIVABLE
    return EXIT_SUCCESS
