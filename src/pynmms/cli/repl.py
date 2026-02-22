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

RQ_HELP_TEXT = """\
Commands (RQ mode):
  tell A |~ B                   Add a consequence to the base
  tell atom Happy(alice)        Add an atom to the base
  tell schema concept hasChild alice Happy
                                Register concept schema: hasChild(alice,x) |~ Happy(x)
  tell schema inference hasChild alice Serious HeartAttack
                                Register inference schema
  ask A => B                    Query derivability of a sequent
  show                          Display the current base
  show schemas                  Display registered schemas
  show individuals              Display known individuals
  trace on/off                  Toggle proof trace display
  save <file>                   Save base to a JSON file
  load <file>                   Load base from a JSON file
  help                          Show this help
  quit                          Exit the REPL
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
    rq_mode = getattr(args, "rq", False)

    if rq_mode:
        from pynmms.rq.base import RQMaterialBase
        from pynmms.rq.reasoner import NMMSRQReasoner

        base: MaterialBase
        if args.base and Path(args.base).exists():
            base = RQMaterialBase.from_file(args.base)
            print(f"Loaded RQ base from {args.base}")
        else:
            base = RQMaterialBase()
            if args.base:
                print(f"Base file {args.base} not found, starting with empty RQ base.")
            else:
                print("Starting with empty RQ base.")

        print("pyNMMS REPL (RQ mode). Type 'help' for commands.\n")
    else:
        if args.base and Path(args.base).exists():
            base = MaterialBase.from_file(args.base)
            print(f"Loaded base from {args.base}")
        else:
            base = MaterialBase()
            if args.base:
                print(f"Base file {args.base} not found, starting with empty base.")
            else:
                print("Starting with empty base.")

        print("pyNMMS REPL. Type 'help' for commands.\n")

    show_trace = False

    try:
        while True:
            try:
                prompt = "pynmms[rq]> " if rq_mode else "pynmms> "
                line = input(prompt).strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            if line in ("quit", "exit"):
                break

            if line == "help":
                print(RQ_HELP_TEXT if rq_mode else HELP_TEXT)
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

            if rq_mode and line == "show schemas":
                assert isinstance(base, RQMaterialBase)  # type: ignore[unreachable]
                schemas = base._inference_schemas
                print(f"Schemas ({len(schemas)}):")
                for s_role, s_subject, s_premise, s_concl in schemas:
                    if s_premise:
                        print(f"  {s_role}({s_subject}, x), {s_premise}(x) |~ {s_concl}")
                    else:
                        print(f"  {s_role}({s_subject}, x) |~ {s_concl}")
                continue

            if rq_mode and line == "show individuals":
                assert isinstance(base, RQMaterialBase)  # type: ignore[unreachable]
                print(f"Individuals: {sorted(base.individuals)}")
                print(f"Concepts: {sorted(base.concepts)}")
                print(f"Roles: {sorted(base.roles)}")
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
                    if rq_mode:
                        base = RQMaterialBase.from_file(filepath)
                    else:
                        base = MaterialBase.from_file(filepath)
                    print(f"Loaded from {filepath}")
                except (OSError, ValueError) as e:
                    print(f"Error loading: {e}")
                continue

            # Schema commands (RQ mode only)
            if rq_mode and line.startswith("tell schema "):
                assert isinstance(base, RQMaterialBase)  # type: ignore[unreachable]
                rest = line[len("tell schema "):].strip()
                parts = rest.split()
                try:
                    if parts[0] == "concept" and len(parts) == 4:
                        _, role, subject, concept = parts
                        base.register_concept_schema(role, subject, concept)
                        print(f"Registered concept schema: {role}({subject}, x) |~ {concept}(x)")
                    elif parts[0] == "inference" and len(parts) == 5:
                        _, role, subject, premise, concl_name = parts
                        from pynmms.rq.syntax import make_concept_assertion
                        base.register_inference_schema(
                            role, subject, premise,
                            {make_concept_assertion(concl_name, "__OBJ__")},
                        )
                        print(
                            f"Registered inference schema: "
                            f"{role}({subject}, x), {premise}(x) |~ {concl_name}(x)"
                        )
                    else:
                        print(
                            "Usage: tell schema concept <role> <subject> <concept>\n"
                            "       tell schema inference <role> <subject> <premise> <conclusion>"
                        )
                except (IndexError, ValueError) as e:
                    print(f"Error: {e}")
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
                    r: NMMSReasoner
                    if rq_mode:
                        r = NMMSRQReasoner(base, max_depth=25)
                    else:
                        r = NMMSReasoner(base, max_depth=25)
                    result = r.derives(antecedent, consequent)

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
