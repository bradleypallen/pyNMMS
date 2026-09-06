"""``pynmms rdf`` -- NMMS queries over an RDF graph.

    pynmms rdf ask -g graph.ttl [--regime rdfs] "<ex:a a ex:C> -> <ex:a a ex:D>"
    pynmms rdf ask -g graph.ttl --rules rules.txt "<ex:x a ex:Alive> => ~<ex:x a ex:Dead>"
    pynmms rdf ask --store http://localhost:7200/repositories/x --regime rdfs "..."

A query is ``antecedent => consequent`` or just a consequent; the stored graph
is always part of the antecedent. Atoms are quoted triples ``<s p o>`` with
prefixes taken from the graph (``a`` abbreviates ``rdf:type``).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pynmms.cli.exitcodes import EXIT_ERROR, EXIT_NOT_DERIVABLE, EXIT_SUCCESS
from pynmms.cli.output import ask_response, emit_error, emit_json
from pynmms.reasoner import NMMSReasoner
from pynmms.syntax import find_top_level, split_top_level

logger = logging.getLogger(__name__)


def add_rdf_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    rdf = subparsers.add_parser("rdf", help="Reason over an RDF graph (requires pyNMMS[rdf])")
    sub = rdf.add_subparsers(dest="rdf_command")
    ask = sub.add_parser("ask", help="Query derivability against a graph")
    src = ask.add_mutually_exclusive_group()
    src.add_argument("-g", "--graph", action="append", default=[],
                     help="RDF file to load (repeatable; format from extension)")
    src.add_argument("--store", help="SPARQL endpoint URL to use as the graph")
    ask.add_argument("--regime", choices=["simple", "rdfs"], default="simple",
                     help="Entailment regime (default: simple)")
    ask.add_argument("--rules", help="File of extra Horn rules, one per line "
                     "('?x ex:p ?y -> ?y ex:q ?x', '... -> false')")
    ask.add_argument("--no-skolemize", action="store_true",
                     help="Keep blank nodes as blank nodes (default: Skolemize on load)")
    ask.add_argument("--trace", action="store_true", help="Print the proof trace")
    ask.add_argument("--json", action="store_true", help="JSON output")
    ask.add_argument("-q", "--quiet", action="store_true", help="Exit code only")
    ask.add_argument("--batch", help="File of queries, one per line ('-' for stdin)")
    ask.add_argument("--max-depth", type=int, default=None, help="Cap proof depth")
    ask.add_argument("query", nargs="?", default=None,
                     help="'antecedent => consequent' or a consequent ('-' for stdin)")


def _split_query(text: str) -> tuple[list[str], list[str]]:
    arrows = find_top_level(text, "=>")
    if not arrows:
        return [], split_top_level(text, ",")
    i = arrows[0]
    return split_top_level(text[:i], ","), split_top_level(text[i + 2:], ",")


def run_rdf(args: argparse.Namespace) -> int:
    if getattr(args, "rdf_command", None) != "ask":
        emit_error("Usage: pynmms rdf ask ...", json_mode=False, quiet=False)
        return EXIT_ERROR
    json_mode, quiet, trace = args.json, args.quiet, args.trace
    try:
        from pynmms.rdf import RegimeBase
        from pynmms.rdf.backends import GraphBackend, MemoryBackend, SPARQLBackend
        from pynmms.rdf.rules import REGIMES, custom, parse_rule
    except ImportError as e:  # pragma: no cover - depends on environment
        emit_error(f"pynmms rdf requires the 'rdf' extra: pip install pyNMMS[rdf] ({e})",
                   json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    regime = REGIMES[args.regime]
    backend: GraphBackend
    try:
        if args.store:
            backend = SPARQLBackend(args.store, regime=regime)
        else:
            mem = MemoryBackend(skolemize=not args.no_skolemize)
            for path in args.graph:
                mem.load(path)
            backend = mem
        if args.rules:
            lines = Path(args.rules).read_text().splitlines()
            rules = [parse_rule(ln, backend.resolver) for ln in lines
                     if ln.strip() and not ln.strip().startswith("#")]
            regime = custom(f"{regime.name}+{Path(args.rules).name}", rules, extends=regime)
        if isinstance(backend, MemoryBackend) and (regime.rules or regime.axioms):
            # Materialise the closure once, after all graphs and rules are known.
            backend = MemoryBackend(backend.graph, regime=regime, skolemize=False)
    except (OSError, ValueError) as e:
        emit_error(str(e), json_mode=json_mode, quiet=quiet)
        return EXIT_ERROR

    base = RegimeBase(backend, regime=regime)
    reasoner = NMMSReasoner(base, max_depth=args.max_depth, persistent_cache=True)

    if args.batch is not None:
        text = sys.stdin.read() if args.batch == "-" else Path(args.batch).read_text()
        lines = text.splitlines()
        queries = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    else:
        if args.query is None:
            emit_error("No query provided.", json_mode=json_mode, quiet=quiet)
            return EXIT_ERROR
        queries = [sys.stdin.readline().strip() if args.query == "-" else args.query]

    worst = EXIT_SUCCESS
    for q in queries:
        rc = _ask_one(base, reasoner, q, json_mode=json_mode, quiet=quiet, trace=trace)
        worst = max(worst, rc) if rc != EXIT_ERROR else EXIT_ERROR
        if rc == EXIT_ERROR:
            break
    return worst


def _ask_one(base, reasoner, query: str, *, json_mode: bool, quiet: bool, trace: bool) -> int:  # type: ignore[no-untyped-def]
    ant, con = _split_query(query)
    try:
        seq = base.sequent(ant, con)
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
