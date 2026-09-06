"""``pynmms repl`` subcommand — interactive REPL."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner
from pynmms.syntax import find_top_level, split_top_level

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Commands:
  tell A |~ B              Add a consequence to the base
  tell A, B |~             Add incompatibility (empty consequent)
  tell |~ A                Add theorem (empty antecedent)
  tell atom A              Add an atom to the base
  tell atom A "desc"       Add an atom with annotation
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


def _parse_repl_tell(
    statement: str,
) -> tuple[str, frozenset[str] | None, frozenset[str] | None, str | None]:
    """Parse a REPL tell statement (without the 'tell ' prefix).

    Returns (kind, antecedent, consequent, annotation).
    """
    from pynmms.cli.tell import _parse_atom_with_annotation

    statement = statement.strip()

    if statement.lower().startswith("atom "):
        atom, annotation = _parse_atom_with_annotation(statement[5:])
        return ("atom", frozenset({atom}), None, annotation)

    if "|~" not in statement:
        raise ValueError(f"Expected 'atom X' or 'A, B |~ C, D', got: {statement!r}")

    turnstiles = find_top_level(statement, "|~")
    if not turnstiles:
        raise ValueError(f"Expected 'atom X' or 'A, B |~ C, D', got: {statement!r}")
    antecedent = frozenset(split_top_level(statement[: turnstiles[0]], ","))
    consequent = frozenset(split_top_level(statement[turnstiles[0] + 2 :], ","))

    return ("consequence", antecedent, consequent, None)


def _parse_repl_ask(sequent_str: str) -> tuple[frozenset[str], frozenset[str]]:
    """Parse a REPL ask query (without the 'ask ' prefix)."""
    sequent_str = sequent_str.strip()

    if "=>" not in sequent_str:
        raise ValueError(f"Expected 'A, B => C, D', got: {sequent_str!r}")

    arrows = find_top_level(sequent_str, "=>")
    if not arrows:
        raise ValueError(f"Expected 'A, B => C, D', got: {sequent_str!r}")
    antecedent = frozenset(split_top_level(sequent_str[: arrows[0]], ","))
    consequent = frozenset(split_top_level(sequent_str[arrows[0] + 2 :], ","))

    return antecedent, consequent


def run_repl(args: argparse.Namespace) -> int:
    """Execute the ``repl`` subcommand."""
    onto_mode = getattr(args, "onto", False)

    if onto_mode:
        from pynmms.onto.base import OntoMaterialBase

        base: MaterialBase
        if args.base and Path(args.base).exists():
            base = OntoMaterialBase.from_file(args.base)
            print(f"Loaded ontology base from {args.base}")
        else:
            base = OntoMaterialBase()
            if args.base:
                print(f"Base file {args.base} not found, starting with empty ontology base.")
            else:
                print("Starting with empty ontology base.")

        print("pyNMMS REPL (ontology mode). Type 'help' for commands.\n")
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
                prompt = "pynmms[onto]> " if onto_mode else "pynmms> "
                line = input(prompt).strip()
            except EOFError:
                print()
                break

            if not line:
                continue

            if line in ("quit", "exit"):
                break

            if line == "help":
                print(ONTO_HELP_TEXT if onto_mode else HELP_TEXT)
                continue

            if line == "show":
                data = base.to_dict()
                ann = data.get("annotations", {})
                print(f"Language ({len(data['language'])} atoms):")
                for atom in data["language"]:
                    desc = ann.get(atom)
                    if desc:
                        print(f"  {atom} \u2014 {desc}")
                    else:
                        print(f"  {atom}")
                print(f"Consequences ({len(data['consequences'])}):")
                for entry in data["consequences"]:
                    ant = set(entry["antecedent"])
                    con = set(entry["consequent"])
                    print(f"  {ant} |~ {con}")
                continue

            if onto_mode and line == "show schemas":
                assert isinstance(base, OntoMaterialBase)  # type: ignore[unreachable]
                schemas = base.onto_schemas
                print(f"Schemas ({len(schemas)}):")
                for schema_type, arg1, arg2, annotation in schemas:
                    if schema_type == "subClassOf":
                        desc = f"  subClassOf: {{{arg1}(x)}} |~ {{{arg2}(x)}}"
                    elif schema_type == "range":
                        desc = f"  range: {{{arg1}(x,y)}} |~ {{{arg2}(y)}}"
                    elif schema_type == "domain":
                        desc = f"  domain: {{{arg1}(x,y)}} |~ {{{arg2}(x)}}"
                    elif schema_type == "subPropertyOf":
                        desc = f"  subPropertyOf: {{{arg1}(x,y)}} |~ {{{arg2}(x,y)}}"
                    elif schema_type == "disjointWith":
                        desc = f"  disjointWith: {{{arg1}(x), {arg2}(x)}} |~"
                    elif schema_type == "disjointProperties":
                        desc = (
                            f"  disjointProperties:"
                            f" {{{arg1}(x,y), {arg2}(x,y)}} |~"
                        )
                    elif schema_type == "jointCommitment":
                        concepts = arg1.split(",")
                        ant_display = ", ".join(f"{c}(x)" for c in concepts)
                        desc = (
                            f"  jointCommitment:"
                            f" {{{ant_display}}} |~ {{{arg2}(x)}}"
                        )
                    else:
                        desc = f"  {schema_type}: {arg1} -> {arg2}"
                    if annotation:
                        desc += f" \u2014 {annotation}"
                    print(desc)
                continue

            if onto_mode and line == "show individuals":
                assert isinstance(base, OntoMaterialBase)  # type: ignore[unreachable]
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
                    if onto_mode:
                        base = OntoMaterialBase.from_file(filepath)
                    else:
                        base = MaterialBase.from_file(filepath)
                    print(f"Loaded from {filepath}")
                except (OSError, ValueError) as e:
                    print(f"Error loading: {e}")
                continue

            # Schema commands (ontology mode only)
            if onto_mode and line.startswith("tell schema "):
                assert isinstance(base, OntoMaterialBase)  # type: ignore[unreachable]
                from pynmms.cli.tell import _extract_trailing_annotation

                rest = line[len("tell schema "):].strip()
                body, annotation = _extract_trailing_annotation(rest)
                parts = body.split()
                try:
                    if parts[0] == "subClassOf" and len(parts) == 3:
                        _, sub_concept, super_concept = parts
                        base.register_subclass(
                            sub_concept, super_concept, annotation=annotation
                        )
                        msg = (
                            f"Registered subClassOf schema:"
                            f" {{{sub_concept}(x)}} |~ {{{super_concept}(x)}}"
                        )
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "range" and len(parts) == 3:
                        _, role, concept = parts
                        base.register_range(role, concept, annotation=annotation)
                        msg = f"Registered range schema: {{{role}(x,y)}} |~ {{{concept}(y)}}"
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "domain" and len(parts) == 3:
                        _, role, concept = parts
                        base.register_domain(role, concept, annotation=annotation)
                        msg = f"Registered domain schema: {{{role}(x,y)}} |~ {{{concept}(x)}}"
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "subPropertyOf" and len(parts) == 3:
                        _, sub_role, super_role = parts
                        base.register_subproperty(
                            sub_role, super_role, annotation=annotation
                        )
                        msg = (
                            f"Registered subPropertyOf schema:"
                            f" {{{sub_role}(x,y)}} |~ {{{super_role}(x,y)}}"
                        )
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "disjointWith" and len(parts) == 3:
                        _, concept1, concept2 = parts
                        base.register_disjoint(
                            concept1, concept2, annotation=annotation
                        )
                        msg = (
                            f"Registered disjointWith schema:"
                            f" {{{concept1}(x), {concept2}(x)}} |~"
                        )
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "disjointProperties" and len(parts) == 3:
                        _, role1, role2 = parts
                        base.register_disjoint_properties(
                            role1, role2, annotation=annotation
                        )
                        msg = (
                            f"Registered disjointProperties schema:"
                            f" {{{role1}(x,y), {role2}(x,y)}} |~"
                        )
                        if annotation:
                            msg += f" \u2014 {annotation}"
                        print(msg)
                    elif parts[0] == "jointCommitment" and len(parts) == 3:
                        _, jc_ant_str, jc_con = parts
                        jc_concepts = jc_ant_str.split(",")
                        if len(jc_concepts) < 2:
                            print(
                                "Error: jointCommitment requires at least 2 "
                                "comma-separated antecedent concepts."
                            )
                        else:
                            base.register_joint_commitment(
                                jc_concepts, jc_con,
                                annotation=annotation,
                            )
                            ant_display = ", ".join(
                                f"{c}(x)" for c in jc_concepts
                            )
                            msg = (
                                f"Registered jointCommitment schema:"
                                f" {{{ant_display}}} |~ {{{jc_con}(x)}}"
                            )
                            if annotation:
                                msg += f" \u2014 {annotation}"
                            print(msg)
                    else:
                        print(
                            "Usage: tell schema subClassOf <sub> <super>\n"
                            "       tell schema range <role> <concept>\n"
                            "       tell schema domain <role> <concept>\n"
                            "       tell schema subPropertyOf <sub_role> <super_role>\n"
                            "       tell schema disjointWith <concept1> <concept2>\n"
                            "       tell schema disjointProperties <role1> <role2>\n"
                            "       tell schema jointCommitment <C1,C2,...> <D>"
                        )
                except (IndexError, ValueError) as e:
                    print(f"Error: {e}")
                continue

            if line.startswith("tell "):
                rest = line[5:]
                try:
                    kind, antecedent, consequent, annotation = _parse_repl_tell(rest)
                    if kind == "atom":
                        assert antecedent is not None
                        atom = next(iter(antecedent))
                        base.add_atom(atom)
                        if annotation:
                            base.annotate(atom, annotation)
                            print(f"Added atom: {atom} \u2014 {annotation}")
                        else:
                            print(f"Added atom: {atom}")
                    else:
                        tell_ant = antecedent if antecedent else frozenset[str]()
                        tell_con = consequent if consequent else frozenset[str]()
                        base.add_consequence(tell_ant, tell_con)
                        print(f"Added: {set(tell_ant)} |~ {set(tell_con)}")
                except ValueError as e:
                    print(f"Error: {e}")
                continue

            if line.startswith("ask "):
                rest = line[4:]
                try:
                    antecedent, consequent = _parse_repl_ask(rest)
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
