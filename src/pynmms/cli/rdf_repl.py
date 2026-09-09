"""``pynmms rdf repl`` -- an interactive session as a position over a stored graph.

The session holds one :class:`~pynmms.rdf.position.Position` over the graph
as background; every command is a speech act on it (``tell``, ``deny``,
``withdraw``, ``commit``) or a question about it (``coherent``,
``challenges``, ``propose``, ``defend``, ``entitlement``, ``position``).
Commands are dispatched through :data:`COMMANDS`, a name -> handler table.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pynmms.cli.exitcodes import EXIT_ERROR, EXIT_SUCCESS
from pynmms.cli.output import emit_error
from pynmms.reasoner import NMMSReasoner

logger = logging.getLogger(__name__)

REPL_HELP = """The session is a position over the stored graph as background.
Commands:
  ask <query>              challenge the position: antecedent => consequent, or a consequent
  tell <t1>, <t2>, ...     assert triples into the position (not yet in the graph)
  deny <t1>, <t2>, ...     reject a graph (its triples jointly); blank nodes are existential
  withdraw <t1>, ...       take assertions back
  coherent                 is the position in bounds? names what fails and what would rescue it
  challenges               the probes an opponent would put to the position
  propose                  the curation report: in bounds?, refutation and rescue, probes,
                           commitments and preclusions, score; nothing is written
  defend                   a round of probes; if none refutes, assertions become defended
  entitlement              each commitment's ground: asserted, defended, inherited, derived
  position                 the position's commitments, denials, and history
  commit                   write the position's assertions to the graph (closure extended)
  load <file>              load another RDF file into the graph
  save [file]              commit, then write the graph (default: the first -g file)
  show                     graph size, regime, prefixes, position summary
  trace on|off             show proof traces
  help                     this help
  quit                     exit
"""

#: Prefixes rdflib binds by default, left out of ``show``.
_STOCK_PREFIXES = ("brick", "csvw", "dc", "foaf", "odrl", "org", "prof", "prov", "qb",
                   "schema", "sh", "skos", "sosa", "ssn", "time", "vann", "void", "wgs",
                   "geo", "xml", "doap", "dcam", "dcat")


@dataclass
class ReplSession:
    """The state a REPL command acts on."""

    base: Any  # RegimeBase
    reasoner: NMMSReasoner
    position: Any  # Position
    mem: Any  # MemoryBackend or OxigraphBackend
    regime: Any  # Regime
    default_file: str | None
    show_trace: bool = False


Handler = Callable[[ReplSession, str], None]


def _help(s: ReplSession, _arg: str) -> None:
    print(REPL_HELP)


def _show(s: ReplSession, _arg: str) -> None:
    mem, position = s.mem, s.position
    print(f"Triples: {mem.size()}  closure: {mem.closure_size()}  regime: {s.regime}"
          f"{'  background INCONSISTENT' if mem.is_inconsistent() else ''}")
    print(f"Position: {len(position.accepted)} asserted, {len(position.rejected)} denied, "
          f"{len(position.log)} moves")
    nsm = mem.resolver.nsm
    for prefix, ns in (nsm.namespaces() if nsm is not None else []):
        if prefix and not prefix.startswith(_STOCK_PREFIXES):
            print(f"  @prefix {prefix}: <{ns}>")


def _trace(s: ReplSession, arg: str) -> None:
    s.show_trace = arg.strip() == "on"
    print(f"Trace: {'ON' if s.show_trace else 'OFF'}")


def _ask(s: ReplSession, arg: str) -> None:
    from pynmms.cli.rdf import _ask_one

    _ask_one(s.base, s.reasoner, arg, json_mode=False, quiet=False, trace=s.show_trace,
             position=s.position)


def _tell(s: ReplSession, arg: str) -> None:
    from pynmms.cli.rdf import _parse_triples

    try:
        before = len(s.position.accepted)
        s.position.assert_(*_parse_triples(s.base, arg))
        n = len(s.position.accepted) - before
        print(f"Added {n} triple(s) to the position; {len(s.position.accepted)} asserted")
    except ValueError as e:
        print(f"Error: {e}")


def _deny(s: ReplSession, arg: str) -> None:
    from pynmms.cli.rdf import _parse_triples

    try:
        s.position.deny(_parse_triples(s.base, arg))
        print(f"Denied; {len(s.position.rejected)} rejected graph(s)")
    except ValueError as e:
        print(f"Error: {e}")


def _withdraw(s: ReplSession, arg: str) -> None:
    from pynmms.cli.rdf import _parse_triples

    try:
        s.position.withdraw(*_parse_triples(s.base, arg))
        print(f"Withdrawn; {len(s.position.accepted)} asserted")
    except ValueError as e:
        print(f"Error: {e}")


def _coherent(s: ReplSession, _arg: str) -> None:
    v = s.position.coherent()
    if v:
        print("COHERENT")
    else:
        print(f"OUT OF BOUNDS: {v.reason}")
        if v.rescue:
            print("  would be rescued by: " + ", ".join(v.rescue))


def _challenges(s: ReplSession, _arg: str) -> None:
    cs = s.position.challenges()
    if not cs:
        print("No challenges: nothing in the base bears on this position.")
    for i, c in enumerate(cs, 1):
        print(f"  {i}. [{c.kind}] {c.question()}")


def _propose(s: ReplSession, _arg: str) -> None:
    print(s.position.propose().summary())


def _defend(s: ReplSession, _arg: str) -> None:
    rnd = s.position.defend()
    print(f"{'STOOD' if rnd.stood else 'REFUTED'}: {rnd.refutations} refutation(s), "
          f"{rnd.open} open probe(s); score {s.position.score()}")


def _entitlement(s: ReplSession, _arg: str) -> None:
    for a, g in s.position.grounds(derived=True).items():
        extra = " ".join(f"{k}={v}" for k, v in (("source", g.source),
                                                  ("evidence", g.evidence),
                                                  ("reference", g.reference),
                                                  ("via", g.via)) if v)
        print(f"  [{g.kind:9s}] {a}{' ' + extra if extra else ''}")
    print(f"  score {s.position.score()}")


def _position(s: ReplSession, _arg: str) -> None:
    position = s.position
    print(f"Holder: {position.holder or '-'}")
    for a in sorted(position.accepted):
        print(f"  + {a}")
    for r in position.rejected:
        print(f"  - {r}")
    for i, m in enumerate(position.log, 1):
        note = f" {m.note}" if m.note else ""
        print(f"  {i}. {m.kind} {', '.join(sorted(m.atoms))}{note}")


def _commit(s: ReplSession, _arg: str) -> None:
    n = s.position.commit()
    print(f"Committed {n} new triple(s); {s.mem.size()} in the graph")


def _load(s: ReplSession, arg: str) -> None:
    try:
        n = s.mem.load(arg.strip())
        print(f"Loaded {n} triple(s); {s.mem.size()} total")
    except (OSError, ValueError) as e:
        print(f"Error: {e}")


def _save(s: ReplSession, arg: str) -> None:
    from pynmms.cli.rdf import _FORMATS
    from pynmms.rdf.backends import MemoryBackend

    target = arg.strip() or s.default_file
    if not target:
        print("Error: no file given and none loaded")
        return
    if s.position.accepted:
        n = s.position.commit()
        print(f"Committed {n} new triple(s)")
    if isinstance(s.mem, MemoryBackend):
        fmt = _FORMATS.get(Path(target).suffix.lower(), "turtle")
        s.mem.graph.serialize(destination=target, format=fmt)
    else:
        s.mem.dump(target)
    print(f"Saved {s.mem.size()} triples to {target}")


#: Commands that take an argument: ``name <arg>`` (a space is required).
ARG_COMMANDS: dict[str, Handler] = {
    "trace": _trace,
    "ask": _ask,
    "tell": _tell,
    "deny": _deny,
    "withdraw": _withdraw,
    "load": _load,
}

#: Commands that take none: the line is the name.
BARE_COMMANDS: dict[str, Handler] = {
    "help": _help,
    "show": _show,
    "coherent": _coherent,
    "challenges": _challenges,
    "propose": _propose,
    "defend": _defend,
    "entitlement": _entitlement,
    "position": _position,
    "commit": _commit,
}

#: Commands whose argument is optional: ``name`` or ``name <arg>``.
OPTIONAL_ARG_COMMANDS: dict[str, Handler] = {
    "save": _save,
}

COMMANDS: dict[str, Handler] = {**ARG_COMMANDS, **BARE_COMMANDS, **OPTIONAL_ARG_COMMANDS}

QUIT = ("quit", "exit")


def dispatch(session: ReplSession, line: str) -> bool:
    """Run one line; return ``False`` when the session should end."""
    if line in QUIT:
        return False
    if line in BARE_COMMANDS:
        BARE_COMMANDS[line](session, "")
        return True
    for name, handler in ARG_COMMANDS.items():
        if line.startswith(name + " "):
            handler(session, line[len(name) + 1:])
            return True
    for name, handler in OPTIONAL_ARG_COMMANDS.items():
        if line.startswith(name):
            handler(session, line[len(name):])
            return True
    print("Unknown command. Type 'help'.")
    return True


def run_repl(args: argparse.Namespace) -> int:
    from pynmms.cli.rdf import _build_backend, _close, _install_extras
    from pynmms.rdf import RegimeBase

    try:
        backend, regime = _build_backend(args)
    except (OSError, ValueError, ImportError) as e:
        emit_error(str(e))
        return EXIT_ERROR
    from pynmms.rdf.position import Position

    mem: Any = backend  # MemoryBackend or OxigraphBackend
    base = RegimeBase(mem, regime=regime)
    _install_extras(base, args)
    session = ReplSession(
        base=base,
        reasoner=NMMSReasoner(base, persistent_cache=True),
        position=Position(base, holder="repl"),
        mem=mem,
        regime=regime,
        default_file=args.graph[0] if args.graph else None,
    )
    print(f"pyNMMS RDF REPL: {mem.size()} triples, regime {regime}; the session is a position "
          f"over them. Type 'help' for commands.\n")

    while True:
        try:
            line = input("rdf> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        logger.debug("rdf repl: %s", line)
        if not dispatch(session, line):
            break
    _close(mem)
    return EXIT_SUCCESS


__all__ = ["REPL_HELP", "COMMANDS", "ReplSession", "dispatch", "run_repl"]
