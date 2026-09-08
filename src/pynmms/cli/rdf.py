"""``pynmms rdf`` -- NMMS queries over an RDF graph.

    pynmms rdf ask  -g graph.ttl [--regime rdfs|owl2rl] [--rules r.txt] "<ex:a a ex:C>"
    pynmms rdf ask  --store http://localhost:7200/repositories/x --regime rdfs "..."
    pynmms rdf tell -g graph.ttl "<ex:tweety a ex:Bird>, <ex:tweety ex:name \\"Tweety\\"@en>"
    pynmms rdf repl -g graph.ttl --regime rdfs
    pynmms rdf position -g graph.ttl --regime rdfs --accept a.ttl --reject r1.ttl --reject r2.ttl

A query is ``antecedent => consequent`` or just a consequent; the stored graph
is always part of the antecedent. Atoms are quoted triples ``<s p o>`` with
prefixes taken from the graph (``a`` abbreviates ``rdf:type``). A consequent
may also be a pattern ``<{ _:b a ex:Bird . _:b ex:name "T" }>`` whose blank
nodes are existential.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pynmms.cli.exitcodes import EXIT_ERROR, EXIT_NOT_DERIVABLE, EXIT_SUCCESS
from pynmms.cli.output import ask_response, emit_error, emit_json
from pynmms.reasoner import NMMSReasoner
from pynmms.syntax import find_top_level, split_top_level

if TYPE_CHECKING:
    from pynmms.rdf.backends import GraphBackend
    from pynmms.rdf.base import RegimeBase
    from pynmms.rdf.rules import Regime

logger = logging.getLogger(__name__)

REGIME_CHOICES = ["simple", "rdfs", "owl2rl"]

_FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".xml": "xml", ".rdf": "xml",
            ".jsonld": "json-ld", ".trig": "trig", ".nq": "nquads"}

REPL_HELP = """The session is a position over the stored graph as background.
Commands:
  ask <query>              challenge the position: antecedent => consequent, or a consequent
  tell <t1>, <t2>, ...     assert triples into the position (not yet in the graph)
  deny <t1>, <t2>, ...     reject a graph (its triples jointly); blank nodes are existential
  withdraw <t1>, ...       take assertions back
  coherent                 is the position in bounds? names what fails and what would rescue it
  position                 the position's commitments, denials, and history
  commit                   write the position's assertions to the graph (closure extended)
  load <file>              load another RDF file into the graph
  save [file]              commit, then write the graph (default: the first -g file)
  show                     graph size, regime, prefixes, position summary
  trace on|off             show proof traces
  help                     this help
  quit                     exit
"""


def add_rdf_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    rdf = subparsers.add_parser("rdf", help="Reason over an RDF graph (requires pyNMMS[rdf])")
    sub = rdf.add_subparsers(dest="rdf_command")

    def common(p: argparse.ArgumentParser, *, store: bool = True) -> None:
        src = p.add_mutually_exclusive_group()
        src.add_argument("-g", "--graph", action="append", default=[],
                         help="RDF file to load (repeatable; format from extension)")
        if store:
            src.add_argument("--store", help="SPARQL endpoint URL to use as the graph")
        p.add_argument("--oxigraph", metavar="DIR",
                       help="Open or create an on-disk Oxigraph store (requires pyoxigraph); "
                            "-g files are loaded into it and the regime closure is kept "
                            "in the store across runs")
        p.add_argument("--regime", choices=REGIME_CHOICES, default="simple",
                       help="Entailment regime (default: simple)")
        p.add_argument("--rules", help="File of extra Horn rules, one per line "
                       "('?x ex:p ?y -> ?y ex:q ?x', '... -> false')")
        p.add_argument("--no-skolemize", action="store_true",
                       help="Keep blank nodes as blank nodes (default: Skolemize on load)")
        p.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI",
                       help="Bind a prefix for queries (repeatable), e.g. ex=http://ex.org/")

    ask = sub.add_parser("ask", help="Query derivability against a graph")
    common(ask)
    ask.add_argument("--trace", action="store_true", help="Print the proof trace")
    ask.add_argument("--json", action="store_true", help="JSON output")
    ask.add_argument("-q", "--quiet", action="store_true", help="Exit code only")
    ask.add_argument("--batch", help="File of queries, one per line ('-' for stdin)")
    ask.add_argument("--max-depth", type=int, default=None, help="Cap proof depth")
    ask.add_argument("query", nargs="?", default=None,
                     help="'antecedent => consequent' or a consequent ('-' for stdin)")

    tell = sub.add_parser("tell", help="Add triples to a graph file or an Oxigraph store")
    tell.add_argument("-g", "--graph", help="RDF file to update (created if absent)")
    tell.add_argument("--oxigraph", metavar="DIR",
                      help="Oxigraph store to update instead of a file; its closure is "
                           "extended incrementally")
    tell.add_argument("--regime", choices=REGIME_CHOICES, default="simple",
                      help="Entailment regime of the store (with --oxigraph)")
    tell.add_argument("--rules", help="File of extra Horn rules (with --oxigraph)")
    tell.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI",
                      help="Bind a prefix (repeatable), e.g. ex=http://ex.org/")
    tell.add_argument("--json", action="store_true", help="JSON output")
    tell.add_argument("-q", "--quiet", action="store_true", help="Exit code only")
    tell.add_argument("--batch", help="File of triple lists, one per line ('-' for stdin)")
    tell.add_argument("triples", nargs="?", default=None,
                      help="Comma-separated triple atoms <s p o> ('-' for stdin)")

    repl = sub.add_parser("repl", help="Interactive session over a graph")
    common(repl, store=False)

    pos = sub.add_parser(
        "position",
        help="Is a position (accepted graphs, rejected graphs) out of bounds?",
        description="The stored graph and every --accept file are accepted; each --reject "
        "file is a graph denied as a whole. Exit 0 if the position is out of bounds "
        "(the accepted graphs entail one of the rejected ones, or are incoherent when "
        "nothing is rejected), 2 if it is in bounds.",
    )
    common(pos)
    pos.add_argument("--accept", action="append", default=[], metavar="FILE",
                     help="RDF file whose graph is accepted (repeatable)")
    pos.add_argument("--reject", action="append", default=[], metavar="FILE",
                     help="RDF file whose graph is rejected (repeatable)")
    pos.add_argument("--trace", action="store_true", help="Print the proof trace")
    pos.add_argument("--json", action="store_true", help="JSON output")
    pos.add_argument("-q", "--quiet", action="store_true", help="Exit code only")
    pos.add_argument("--max-depth", type=int, default=None, help="Cap proof depth")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _split_query(text: str) -> tuple[list[str], list[str]]:
    arrows = find_top_level(text, "=>")
    if not arrows:
        return [], split_top_level(text, ",")
    i = arrows[0]
    return split_top_level(text[:i], ","), split_top_level(text[i + 2:], ",")


def _load_rules(path: str, resolver: object) -> list:  # type: ignore[type-arg]
    from pynmms.rdf.rules import parse_rule

    lines = Path(path).read_text().splitlines()
    return [parse_rule(ln, resolver) for ln in lines  # type: ignore[arg-type]
            if ln.strip() and not ln.strip().startswith("#")]


def _prefixes(args: argparse.Namespace) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in getattr(args, "prefix", None) or []:
        if "=" not in item:
            raise ValueError(f"--prefix expects PFX=IRI, got {item!r}")
        pfx, iri = item.split("=", 1)
        out[pfx.strip()] = iri.strip()
    return out


def _bind_prefixes(backend: GraphBackend, prefixes: dict[str, str]) -> None:
    for pfx, iri in prefixes.items():
        backend.resolver.bind(pfx, iri)


def _build_backend(args: argparse.Namespace) -> tuple[GraphBackend, Regime]:
    from pynmms.rdf.backends import MemoryBackend, SPARQLBackend
    from pynmms.rdf.rules import REGIMES, custom

    regime = REGIMES[args.regime]
    prefixes = _prefixes(args)
    backend: GraphBackend
    if getattr(args, "oxigraph", None):
        if getattr(args, "store", None):
            raise ValueError("--oxigraph and --store are mutually exclusive")
        backend = _build_oxigraph(args, regime, prefixes)
        return backend, args.regime_obj
    if getattr(args, "store", None):
        backend = SPARQLBackend(args.store, regime=regime, prefixes=prefixes)
    else:
        mem = MemoryBackend(skolemize=not args.no_skolemize)
        for path in args.graph:
            mem.load(path)
        for pfx, iri in prefixes.items():
            mem.graph.namespace_manager.bind(pfx, iri, replace=True)
        backend = mem
    if args.rules:
        rules = _load_rules(args.rules, backend.resolver)
        regime = custom(f"{regime.name}+{Path(args.rules).name}", rules, extends=regime)
    if isinstance(backend, MemoryBackend) and (regime.rules or regime.axioms):
        # Materialise the closure once, after all graphs and rules are known.
        backend = MemoryBackend(backend.graph, regime=regime, skolemize=False)
    _bind_prefixes(backend, prefixes)
    return backend, regime


def _build_oxigraph(
    args: argparse.Namespace, regime: Regime, prefixes: dict[str, str]
) -> GraphBackend:
    """An Oxigraph store, materialised once after every -g file is loaded."""
    from rdflib import Graph

    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.rules import custom

    if getattr(args, "rules", None):
        resolver = Resolver(Graph())
        for pfx, iri in prefixes.items():
            resolver.bind(pfx, iri)
        rules = _load_rules(args.rules, resolver)
        regime = custom(f"{regime.name}+{Path(args.rules).name}", rules, extends=regime)
    graphs = getattr(args, "graph", None) or []
    backend = OxigraphBackend(args.oxigraph, regime=regime, prefixes=prefixes,
                              skolemize=not getattr(args, "no_skolemize", False),
                              materialize=not graphs)
    for path in graphs:
        backend.load(path, materialize=False)
    if graphs:
        backend.materialize()
    args.regime_obj = regime
    return backend


def _close(backend: object) -> None:
    close = getattr(backend, "close", None)
    if callable(close):
        close()


def _parse_triples(base: RegimeBase, text: str) -> list:  # type: ignore[type-arg]
    from pynmms.rdf.atoms import TripleAtom

    out = []
    for name in split_top_level(text, ","):
        t = TripleAtom.coerce(name, base.resolver)
        if t is None:
            raise ValueError(f"{name!r} is not a triple atom <s p o>")
        out.append(t.triple)
    return out


def _ask_one(base: RegimeBase, reasoner: NMMSReasoner, query: str, *,
             json_mode: bool, quiet: bool, trace: bool, position: Any = None) -> int:
    ant, con = _split_query(query)
    try:
        seq = position.sequent(ant, con) if position is not None else base.sequent(ant, con)
        result = reasoner.derives_sequent(seq)
    except ValueError as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    if json_mode:
        resp = ask_response(
            derivable=result.derivable,
            antecedent=frozenset(ant),
            consequent=frozenset(con),
            depth_reached=result.depth_reached,
            cache_hits=result.cache_hits,
            trace=result.trace if trace else None,
            depth_limited=result.depth_limited,
        )
        resp["regime"] = str(base.regime)
        resp["graph_triples"] = base.backend.size()
        emit_json(resp)
    elif not quiet:
        print("DERIVABLE" if result.derivable else "NOT DERIVABLE")
        if trace:
            print("\nProof trace:")
            for line in result.trace:
                print(f"  {line}")
            print(f"\nNodes: {result.nodes}  Depth: {result.depth_reached}  "
                  f"Cache hits: {result.cache_hits}")
    logger.info("rdf query %r: %s (nodes %d)", query,
                "DERIVABLE" if result.derivable else "NOT DERIVABLE", result.nodes)
    return EXIT_SUCCESS if result.derivable else EXIT_NOT_DERIVABLE


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------


def run_rdf(args: argparse.Namespace) -> int:
    cmd = getattr(args, "rdf_command", None)
    try:
        import pynmms.rdf  # noqa: F401
    except ImportError as e:  # pragma: no cover - depends on environment
        emit_error(f"pynmms rdf requires the 'rdf' extra: pip install pyNMMS[rdf] ({e})")
        return EXIT_ERROR
    if cmd == "ask":
        return _run_ask(args)
    if cmd == "tell":
        return _run_tell(args)
    if cmd == "repl":
        return _run_repl(args)
    if cmd == "position":
        return _run_position(args)
    emit_error("Usage: pynmms rdf {ask,tell,repl,position} ...")
    return EXIT_ERROR


def _run_position(args: argparse.Namespace) -> int:
    from pynmms.rdf import RegimeBase

    json_mode, quiet, trace = args.json, args.quiet, args.trace
    try:
        backend, regime = _build_backend(args)
        base = RegimeBase(backend, regime=regime)
        seq = base.position(accept=args.accept, reject=args.reject)
    except (OSError, ValueError) as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    reasoner = NMMSReasoner(base, max_depth=args.max_depth, persistent_cache=True)
    result = reasoner.derives_sequent(seq)
    verdict = "OUT OF BOUNDS" if result.derivable else "IN BOUNDS"
    if json_mode:
        emit_json({
            "status": verdict.replace(" ", "_"),
            "accepted": list(args.accept),
            "rejected": list(args.reject),
            "graph_triples": base.backend.size(),
            "regime": str(base.regime),
            "depth_reached": result.depth_reached,
            "cache_hits": result.cache_hits,
            "depth_limited": result.depth_limited,
            **({"trace": result.trace} if trace else {}),
        })
    elif not quiet:
        what = ("the accepted graphs are incoherent" if not args.reject else
                "the accepted graphs entail a rejected one")
        print(f"{verdict}" + (f" ({what})" if result.derivable else ""))
        if trace:
            print("\nProof trace:")
            for line in result.trace:
                print(f"  {line}")
    logger.info("rdf position accept=%s reject=%s: %s (nodes %d)",
                args.accept, args.reject, verdict, result.nodes)
    _close(backend)
    return EXIT_SUCCESS if result.derivable else EXIT_NOT_DERIVABLE


def _run_ask(args: argparse.Namespace) -> int:
    from pynmms.rdf import RegimeBase

    json_mode, quiet, trace = args.json, args.quiet, args.trace
    try:
        backend, regime = _build_backend(args)
    except (OSError, ValueError, ImportError) as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    base = RegimeBase(backend, regime=regime)
    reasoner = NMMSReasoner(base, max_depth=args.max_depth, persistent_cache=True)

    if args.batch is not None:
        text = sys.stdin.read() if args.batch == "-" else Path(args.batch).read_text()
        queries = [ln.strip() for ln in text.splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
    else:
        if args.query is None:
            emit_error("No query provided.", json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        queries = [sys.stdin.readline().strip() if args.query == "-" else args.query]

    worst = EXIT_SUCCESS
    for q in queries:
        rc = _ask_one(base, reasoner, q, json_mode=json_mode, quiet=quiet, trace=trace)
        if rc == EXIT_ERROR:
            _close(backend)
            return EXIT_ERROR
        worst = max(worst, rc)
    _close(backend)
    return worst


def _run_tell(args: argparse.Namespace) -> int:
    from pynmms.rdf import RegimeBase
    from pynmms.rdf.backends import MemoryBackend
    from pynmms.rdf.rules import REGIMES

    json_mode, quiet = args.json, args.quiet
    if not args.graph and not args.oxigraph:
        emit_error("tell needs -g FILE or --oxigraph DIR", json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    backend: Any
    try:
        if args.oxigraph:
            args.graph = []
            backend = _build_oxigraph(args, REGIMES[args.regime], _prefixes(args))
            path = Path(args.oxigraph)
            fmt = None
        else:
            path = Path(args.graph)
            fmt = _FORMATS.get(path.suffix.lower(), "turtle")
            backend = MemoryBackend(skolemize=False)
            if path.exists():
                backend.load(path, format=fmt)
            for pfx, iri in _prefixes(args).items():
                backend.graph.namespace_manager.bind(pfx, iri, replace=True)
    except (OSError, ValueError, ImportError) as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR
    base = RegimeBase(backend)

    if args.batch is not None:
        text = sys.stdin.read() if args.batch == "-" else Path(args.batch).read_text()
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    else:
        if args.triples is None:
            emit_error("No triples provided.", json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        lines = [sys.stdin.readline().strip() if args.triples == "-" else args.triples]

    added_total = 0
    for line in lines:
        try:
            triples = _parse_triples(base, line)
        except ValueError as e:
            emit_error(str(e), json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        added_total += backend.add(triples)
    if fmt is not None:
        backend.graph.serialize(destination=str(path), format=fmt)
    logger.info("rdf tell: %d triples added to %s (%d total)", added_total, path, backend.size())
    if json_mode:
        emit_json({"action": "added_triples", "added": added_total,
                   "graph_triples": backend.size(), "graph_file": str(path)})
    elif not quiet:
        print(f"Added {added_total} triple(s); {backend.size()} in {path}")
    _close(backend)
    return EXIT_SUCCESS


def _run_repl(args: argparse.Namespace) -> int:
    from pynmms.rdf import RegimeBase
    from pynmms.rdf.backends import MemoryBackend

    try:
        backend, regime = _build_backend(args)
    except (OSError, ValueError, ImportError) as e:
        emit_error(str(e))
        return EXIT_ERROR
    from pynmms.rdf.position import Position

    mem: Any = backend  # MemoryBackend or OxigraphBackend
    base = RegimeBase(mem, regime=regime)
    reasoner = NMMSReasoner(base, persistent_cache=True)
    position = Position(base, holder="repl")
    default_file = args.graph[0] if args.graph else None
    show_trace = False
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
        if line in ("quit", "exit"):
            break
        if line == "help":
            print(REPL_HELP)
        elif line == "show":
            print(f"Triples: {mem.size()}  closure: {mem.closure_size()}  regime: {regime}"
                  f"{'  background INCONSISTENT' if mem.is_inconsistent() else ''}")
            print(f"Position: {len(position.accepted)} asserted, {len(position.rejected)} denied, "
                  f"{len(position.log)} moves")
            nsm = mem.resolver.nsm
            for prefix, ns in (nsm.namespaces() if nsm is not None else []):
                if prefix and not prefix.startswith(("brick", "csvw", "dc", "foaf", "odrl", "org",
                                                     "prof", "prov", "qb", "schema", "sh", "skos",
                                                     "sosa", "ssn", "time", "vann", "void", "wgs",
                                                     "geo", "xml", "doap", "dcam", "dcat")):
                    print(f"  @prefix {prefix}: <{ns}>")
        elif line.startswith("trace "):
            show_trace = line[6:].strip() == "on"
            print(f"Trace: {'ON' if show_trace else 'OFF'}")
        elif line.startswith("ask "):
            _ask_one(base, reasoner, line[4:], json_mode=False, quiet=False, trace=show_trace,
                     position=position)
        elif line.startswith("tell "):
            try:
                before = len(position.accepted)
                position.assert_(*_parse_triples(base, line[5:]))
                n = len(position.accepted) - before
                print(f"Added {n} triple(s) to the position; {len(position.accepted)} asserted")
            except ValueError as e:
                print(f"Error: {e}")
        elif line.startswith("deny "):
            try:
                position.deny(_parse_triples(base, line[5:]))
                print(f"Denied; {len(position.rejected)} rejected graph(s)")
            except ValueError as e:
                print(f"Error: {e}")
        elif line.startswith("withdraw "):
            try:
                position.withdraw(*_parse_triples(base, line[9:]))
                print(f"Withdrawn; {len(position.accepted)} asserted")
            except ValueError as e:
                print(f"Error: {e}")
        elif line == "coherent":
            v = position.coherent()
            if v:
                print("COHERENT")
            else:
                print(f"OUT OF BOUNDS: {v.reason}")
                if v.rescue:
                    print("  would be rescued by: " + ", ".join(v.rescue))
        elif line == "position":
            print(f"Holder: {position.holder or '-'}")
            for a in sorted(position.accepted):
                print(f"  + {a}")
            for r in position.rejected:
                print(f"  - {r}")
            for i, m in enumerate(position.log, 1):
                note = f" {m.note}" if m.note else ""
                print(f"  {i}. {m.kind} {', '.join(sorted(m.atoms))}{note}")
        elif line == "commit":
            n = position.commit()
            print(f"Committed {n} new triple(s); {mem.size()} in the graph")
        elif line.startswith("load "):
            try:
                n = mem.load(line[5:].strip())
                print(f"Loaded {n} triple(s); {mem.size()} total")
            except (OSError, ValueError) as e:
                print(f"Error: {e}")
        elif line.startswith("save"):
            target = line[4:].strip() or default_file
            if not target:
                print("Error: no file given and none loaded")
                continue
            if position.accepted:
                n = position.commit()
                print(f"Committed {n} new triple(s)")
            if isinstance(mem, MemoryBackend):
                fmt = _FORMATS.get(Path(target).suffix.lower(), "turtle")
                mem.graph.serialize(destination=target, format=fmt)
            else:
                mem.dump(target)
            print(f"Saved {mem.size()} triples to {target}")
        else:
            print("Unknown command. Type 'help'.")
    _close(mem)
    return EXIT_SUCCESS
