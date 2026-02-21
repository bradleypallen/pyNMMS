"""``pynmms repl`` subcommand — interactive REPL."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Commands:
  tell A |~ B         Add a consequence to the base
  tell atom A         Add an atom to the base
  ask A => B          Query derivability of a sequent
  show                Display the current base
  trace on/off        Toggle proof trace display
  save <file>         Save base to a JSON file
  load <file>         Load base from a JSON file
  help                Show this help
  quit                Exit the REPL
"""


def _parse_repl_tell(statement: str) -> tuple[str, frozenset[str] | None, frozenset[str] | None]:
    """Parse a REPL tell statement (without the 'tell ' prefix)."""
    statement = statement.strip()

    if statement.lower().startswith("atom "):
        return ("atom", frozenset({statement[5:].strip()}), None)

    if "|~" not in statement:
        raise ValueError(f"Expected 'atom X' or 'A, B |~ C, D', got: {statement!r}")

    parts = statement.split("|~", 1)
    antecedent = frozenset(s.strip() for s in parts[0].strip().split(",") if s.strip())
    consequent = frozenset(s.strip() for s in parts[1].strip().split(",") if s.strip())

    if not antecedent or not consequent:
        raise ValueError("Both antecedent and consequent must be non-empty.")

    return ("consequence", antecedent, consequent)


def _parse_repl_ask(sequent_str: str) -> tuple[frozenset[str], frozenset[str]]:
    """Parse a REPL ask query (without the 'ask ' prefix)."""
    sequent_str = sequent_str.strip()

    if "=>" not in sequent_str:
        raise ValueError(f"Expected 'A, B => C, D', got: {sequent_str!r}")

    parts = sequent_str.split("=>", 1)
    antecedent = frozenset(s.strip() for s in parts[0].strip().split(",") if s.strip())
    consequent = frozenset(s.strip() for s in parts[1].strip().split(",") if s.strip())

    return antecedent, consequent


def run_repl(args: argparse.Namespace) -> int:
    """Execute the ``repl`` subcommand."""
    base: MaterialBase

    if args.base and Path(args.base).exists():
        base = MaterialBase.from_file(args.base)
        print(f"Loaded base from {args.base}")
    else:
        base = MaterialBase()
        if args.base:
            print(f"Base file {args.base} not found, starting with empty base.")
        else:
            print("Starting with empty base.")

    show_trace = False

    print("pyNMMS REPL. Type 'help' for commands.\n")

    try:
        while True:
            try:
                line = input("pynmms> ").strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            if line in ("quit", "exit"):
                break

            if line == "help":
                print(HELP_TEXT)
                continue

            if line == "show":
                data = base.to_dict()
                print(f"Language ({len(data['language'])} atoms):")
                for atom in data["language"]:
                    print(f"  {atom}")
                print(f"Consequences ({len(data['consequences'])}):")
                for entry in data["consequences"]:
                    print(f"  {set(entry['antecedent'])} |~ {set(entry['consequent'])}")
                continue

            if line.startswith("trace "):
                val = line[6:].strip().lower()
                if val == "on":
                    show_trace = True
                    print("Trace: ON")
                elif val == "off":
                    show_trace = False
                    print("Trace: OFF")
                else:
                    print("Usage: trace on/off")
                continue

            if line.startswith("save "):
                filepath = line[5:].strip()
                try:
                    base.to_file(filepath)
                    print(f"Saved to {filepath}")
                except OSError as e:
                    print(f"Error saving: {e}")
                continue

            if line.startswith("load "):
                filepath = line[5:].strip()
                try:
                    base = MaterialBase.from_file(filepath)
                    print(f"Loaded from {filepath}")
                except (OSError, ValueError) as e:
                    print(f"Error loading: {e}")
                continue

            if line.startswith("tell "):
                rest = line[5:]
                try:
                    kind, antecedent, consequent = _parse_repl_tell(rest)
                    if kind == "atom":
                        assert antecedent is not None
                        atom = next(iter(antecedent))
                        base.add_atom(atom)
                        print(f"Added atom: {atom}")
                    else:
                        assert antecedent is not None and consequent is not None
                        base.add_consequence(antecedent, consequent)
                        print(f"Added: {set(antecedent)} |~ {set(consequent)}")
                except ValueError as e:
                    print(f"Error: {e}")
                continue

            if line.startswith("ask "):
                rest = line[4:]
                try:
                    antecedent, consequent = _parse_repl_ask(rest)
                    reasoner = NMMSReasoner(base, max_depth=25)
                    result = reasoner.derives(antecedent, consequent)

                    if result.derivable:
                        print("DERIVABLE")
                    else:
                        print("NOT DERIVABLE")

                    if show_trace:
                        for tline in result.trace:
                            print(f"  {tline}")
                        print(f"  Depth: {result.depth_reached}, Cache hits: {result.cache_hits}")
                except ValueError as e:
                    print(f"Error: {e}")
                continue

            print(f"Unknown command: {line!r}. Type 'help' for commands.")

    except KeyboardInterrupt:
        print("\nInterrupted.")

    return 0
