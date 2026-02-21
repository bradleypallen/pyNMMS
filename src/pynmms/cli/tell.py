"""``pynmms tell`` subcommand — add atoms or consequences to a base."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pynmms.base import MaterialBase

logger = logging.getLogger(__name__)


def _parse_tell_statement(statement: str) -> tuple[str, frozenset[str] | None, frozenset[str] | None]:
    """Parse a tell statement.

    Returns:
        ("atom", None, None) for ``atom X``
        ("consequence", antecedent, consequent) for ``A, B |~ C, D``
    """
    statement = statement.strip()

    if statement.lower().startswith("atom "):
        return ("atom", frozenset({statement[5:].strip()}), None)

    if "|~" not in statement:
        raise ValueError(
            f"Invalid tell statement: {statement!r}. "
            f'Expected "atom X" or "A, B |~ C, D".'
        )

    parts = statement.split("|~", 1)
    antecedent_str = parts[0].strip()
    consequent_str = parts[1].strip()

    antecedent = frozenset(s.strip() for s in antecedent_str.split(",") if s.strip())
    consequent = frozenset(s.strip() for s in consequent_str.split(",") if s.strip())

    if not antecedent or not consequent:
        raise ValueError(
            f"Invalid consequence: {statement!r}. "
            f"Both antecedent and consequent must be non-empty."
        )

    return ("consequence", antecedent, consequent)


def run_tell(args: argparse.Namespace) -> int:
    """Execute the ``tell`` subcommand."""
    base_path = Path(args.base)

    # Load or create base
    if base_path.exists():
        base = MaterialBase.from_file(base_path)
    elif args.create:
        base = MaterialBase()
    else:
        print(f"Error: Base file {base_path} does not exist. Use --create to create it.",
              file=sys.stderr)
        return 1

    try:
        kind, antecedent, consequent = _parse_tell_statement(args.statement)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if kind == "atom":
        assert antecedent is not None
        atom = next(iter(antecedent))
        base.add_atom(atom)
        print(f"Added atom: {atom}")
    else:
        assert antecedent is not None and consequent is not None
        base.add_consequence(antecedent, consequent)
        print(f"Added consequence: {set(antecedent)} |~ {set(consequent)}")

    base.to_file(base_path)
    logger.info("Saved base to %s", base_path)
    return 0
