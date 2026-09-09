"""``pynmms repl`` subcommand — interactive REPL.

The REPL is a thin loop over the same parsing and processing functions as
``pynmms tell`` and ``pynmms ask`` (:func:`pynmms.cli.tell._process_tell_statement`,
:func:`pynmms.cli.ask._ask_one`), run with JSON output off.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.cli.ask import _ask_one
from pynmms.cli.schema_line import describe_schema, format_registration, register_schema_line
from pynmms.cli.tell import _process_tell_statement
from pynmms.onto.base import OntoMaterialBase
from pynmms.reasoner import NMMSReasoner
from pynmms.robustness import Robustness

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Commands:
  tell A |~ B              Add a consequence to the base
  tell A, B |~             Add incompatibility (empty consequent)
  tell |~ A                Add theorem (empty antecedent)
  tell atom A              Add an atom to the base
  tell atom A "desc"       Add an atom with annotation
  tell A |~ B unless C, D  Guarded consequence: survives additions except C, D
  tell A |~ B monotone     Monotone consequence: survives any addition
  ask A => B               Query derivability of a sequent
  show                     Display the current base
  trace on/off             Toggle proof trace display
  save <file>              Save base to a JSON file
  load <file>              Load base from a JSON file
  help                     Show this help
  quit                     Exit the REPL
"""

ONTO_HELP_TEXT = """\
Commands (ontology mode):
  tell A |~ B                         Add a consequence to the base
  tell A, B |~                        Add incompatibility (empty consequent)
  tell |~ A                           Add theorem (empty antecedent)
  tell atom Happy(alice)              Add an atom to the base
  tell atom Happy(alice) "desc"       Add an atom with annotation
  tell schema subClassOf Man Mortal   Register subClassOf schema
  tell schema subClassOf Bird Flies unless Penguin
                                      Guarded schema (defeater concepts)
  tell schema subClassOf Man Mortal monotone
                                      Monotone schema
  tell schema range hasChild Person   Register range schema
  tell schema domain hasChild Parent  Register domain schema
  tell schema subPropertyOf hasChild hasDescendant
                                      Register subPropertyOf schema
  tell schema disjointWith Man Woman  Register disjointWith schema
  tell schema disjointProperties hasChild hasParent
                                      Register disjointProperties schema
  tell schema jointCommitment ChestPain,ElevatedTroponin MI
                                      Register jointCommitment schema
  ask A => B                          Query derivability of a sequent
  show                                Display the current base
  show schemas                        Display registered schemas
  show individuals                    Display known individuals
  trace on/off                        Toggle proof trace display
  save <file>                         Save base to a JSON file
  load <file>                         Load base from a JSON file
  help                                Show this help
  quit                                Exit the REPL
"""


class _Session:
    """State of one REPL session: the base, its mode and the trace flag."""

    def __init__(self, base: MaterialBase, onto_mode: bool) -> None:
        self.base = base
        self.onto_mode = onto_mode
        self.base_cls: type[MaterialBase] = OntoMaterialBase if onto_mode else MaterialBase
        self.show_trace = False

    # Each handler prints its own output; ``handle`` returns False on ``quit``.

    def handle(self, line: str) -> bool:
        if line in ("quit", "exit"):
            return False
        if line == "help":
            print(ONTO_HELP_TEXT if self.onto_mode else HELP_TEXT)
        elif line == "show":
            self.show()
        elif self.onto_mode and line == "show schemas":
            self.show_schemas()
        elif self.onto_mode and line == "show individuals":
            self.show_individuals()
        elif line.startswith("trace "):
            self.trace(line[6:].strip().lower())
        elif line.startswith("save "):
            self.save(line[5:].strip())
        elif line.startswith("load "):
            self.load(line[5:].strip())
        elif self.onto_mode and line.startswith("tell schema "):
            self.tell_schema(line[len("tell "):])
        elif line.startswith("tell "):
            _process_tell_statement(line[5:], self.base, "", added_label="Added")
        elif line.startswith("ask "):
            _ask_one(line[4:], NMMSReasoner(self.base), trace=self.show_trace)
        else:
            print(f"Unknown command: {line!r}. Type 'help' for commands.")
        return True

    def show(self) -> None:
        data = self.base.to_dict()
        ann = data.get("annotations", {})
        print(f"Language ({len(data['language'])} atoms):")
        for atom in data["language"]:
            desc = ann.get(atom)
            if desc:
                print(f"  {atom} — {desc}")
            else:
                print(f"  {atom}")
        print(f"Consequences ({len(data['consequences'])}):")
        for entry in data["consequences"]:
            ant = set(entry["antecedent"])
            con = set(entry["consequent"])
            rob = Robustness.from_json(entry.get("robustness"))
            suffix = "" if rob.is_exact else f" [{rob}]"
            print(f"  {ant} |~ {con}{suffix}")

    def show_schemas(self) -> None:
        assert isinstance(self.base, OntoMaterialBase)
        schemas = self.base.onto_schemas
        print(f"Schemas ({len(schemas)}):")
        for e in schemas:
            desc = f"  {e.type}: {describe_schema(e.type, e.arg1, e.arg2)}"
            if not e.robustness.is_exact:
                desc += f" [{e.robustness}]"
            if e.annotation:
                desc += f" — {e.annotation}"
            print(desc)

    def show_individuals(self) -> None:
        assert isinstance(self.base, OntoMaterialBase)
        print(f"Individuals: {sorted(self.base.individuals)}")
        print(f"Concepts: {sorted(self.base.concepts)}")
        print(f"Roles: {sorted(self.base.roles)}")

    def trace(self, val: str) -> None:
        if val == "on":
            self.show_trace = True
            print("Trace: ON")
        elif val == "off":
            self.show_trace = False
            print("Trace: OFF")
        else:
            print("Usage: trace on/off")

    def save(self, filepath: str) -> None:
        try:
            self.base.to_file(filepath)
            print(f"Saved to {filepath}")
        except OSError as e:
            print(f"Error saving: {e}")

    def load(self, filepath: str) -> None:
        try:
            self.base = self.base_cls.from_file(filepath)
            print(f"Loaded from {filepath}")
        except (OSError, ValueError) as e:
            print(f"Error loading: {e}")

    def tell_schema(self, line: str) -> None:
        assert isinstance(self.base, OntoMaterialBase)
        try:
            stype, details, rob, ann = register_schema_line(self.base, line)
            print(format_registration(stype, details, rob, ann))
        except (IndexError, ValueError) as e:
            print(f"Error: {e}")


def run_repl(args: argparse.Namespace) -> int:
    """Execute the ``repl`` subcommand."""
    onto_mode: bool = args.onto
    base_cls: type[MaterialBase] = OntoMaterialBase if onto_mode else MaterialBase
    label = "ontology base" if onto_mode else "base"

    base: MaterialBase
    if args.base and Path(args.base).exists():
        base = base_cls.from_file(args.base)
        print(f"Loaded {label} from {args.base}")
    else:
        base = base_cls()
        if args.base:
            print(f"Base file {args.base} not found, starting with empty {label}.")
        else:
            print(f"Starting with empty {label}.")

    print("pyNMMS REPL (ontology mode). Type 'help' for commands.\n" if onto_mode
          else "pyNMMS REPL. Type 'help' for commands.\n")

    session = _Session(base, onto_mode)
    prompt = "pynmms[onto]> " if onto_mode else "pynmms> "

    try:
        while True:
            try:
                line = input(prompt).strip()
            except EOFError:
                print()
                break
            if line and not session.handle(line):
                break
    except KeyboardInterrupt:
        print("\nInterrupted.")

    return 0
