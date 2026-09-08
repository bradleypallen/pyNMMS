"""Replay a scripted dialogue as a position over a persisted store, with predictions.

A dialogue file has one move per line::

    holder curator@museum
    assert <s p o>, <s p o>
    deny <s p o>, <s p o>              # a rejected graph, its triples jointly
    withdraw <s p o>
    read <subject>                      # Position.of: read a stored record aloud
    coherent? ## 1                      # predicted verdict: 1 in bounds, 0 out of bounds
    commits? <query> ## 0               # predicted derivability of accepted, ant => con
    precludes? <s p o> ## 1             # predicted incompatibility
    commit
    # comments and blank lines are ignored

Each question is answered by :class:`pynmms.rdf.position.Position`, timed,
and compared with its prediction; the reason and the rescuing defeaters of
a failed coherence check are recorded. A record goes to ``bench/results/``.

Usage::

    python -m bench.replay_dialogue --store DIR --regime rdfs --dialogue FILE
        [--entries FILE] [--rules FILE] [--regime-name NAME] [--prefix ex=IRI ...]
        [--out DIR] [--no-write] [--label TEXT]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

from ._util import Section, env_info, git_sha, write_record
from .compare_rdfs import NA, _prefixes, read_entries

logger = logging.getLogger("bench.replay_dialogue")


def _split(text: str) -> list[str]:
    from pynmms.syntax import split_top_level

    return [x.strip() for x in split_top_level(text, ",") if x.strip()]


def replay(args: argparse.Namespace) -> list[Section]:
    from rdflib import Graph

    from pynmms.cli.rdf import _split_query
    from pynmms.rdf import RegimeBase
    from pynmms.rdf.atoms import Resolver, TripleAtom
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.position import Position
    from pynmms.rdf.rules import REGIMES, custom, parse_rule

    prefixes = _prefixes(args.prefix)
    regime = REGIMES[args.regime]
    if args.rules:
        resolver = Resolver(Graph())
        for pfx, iri in prefixes.items():
            resolver.bind(pfx, iri)
        rules = [parse_rule(ln, resolver) for ln in Path(args.rules).read_text().splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        regime = custom(args.regime_name or f"{regime.name}+{Path(args.rules).name}", rules,
                        extends=regime)
    elif args.regime_name:
        regime = custom(args.regime_name, [], extends=regime)
    backend = OxigraphBackend(args.store, regime=regime, prefixes=prefixes, materialize=False)
    if not backend.materialised:
        raise SystemExit(f"{args.store} is not materialised for regime {regime.name}")
    base = RegimeBase(backend, regime=regime)
    n_entries = read_entries(Path(args.entries), base) if args.entries else 0
    position = Position(base)

    moves = Section("dialogue:moves", ["#", "move", "text", "answer", "expect", "ok", "ms",
                                       "reason", "rescue"],
                    notes=f"store {args.store}; regime {regime.name}; {n_entries} entries")
    oks: list[bool] = []
    for n, raw in enumerate(Path(args.dialogue).read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        expect: Any = NA
        if "##" in raw:
            expect = raw.split("##", 1)[1].strip() == "1"
        kind, _, rest = line.partition(" ")
        rest = rest.strip()
        t0 = time.perf_counter()
        answer: Any = ""
        reason: Any = ""
        rescue: Any = ""
        if kind == "holder":
            position.holder = rest
        elif kind == "assert":
            position.assert_(*[TripleAtom.from_name(x, base.resolver) for x in _split(rest)])
            answer = f"{len(position.accepted)} asserted"
        elif kind == "deny":
            position.deny([TripleAtom.from_name(x, base.resolver).triple for x in _split(rest)])
            answer = f"{len(position.rejected)} denied"
        elif kind == "withdraw":
            position.withdraw(*[TripleAtom.from_name(x, base.resolver) for x in _split(rest)])
            answer = f"{len(position.accepted)} asserted"
        elif kind == "read":
            holder = position.holder
            position = Position.of(base, rest, holder=holder)
            answer = f"{len(position.accepted)} asserted"
        elif kind == "commit":
            answer = f"{position.commit()} new"
        elif kind == "coherent?":
            v = position.coherent()
            answer, reason, rescue = bool(v), v.reason or "", ", ".join(v.rescue)
        elif kind == "commits?":
            ant, con = _split_query(rest)
            v = position._ask(position.sequent(ant, con))
            answer, reason = bool(v), v.reason or ""
        elif kind == "precludes?":
            v = position.precludes(*[TripleAtom.from_name(x, base.resolver) for x in _split(rest)])
            answer, reason, rescue = bool(v), v.reason or "", ", ".join(v.rescue)
        else:
            raise ValueError(f"line {n}: unknown move {kind!r}")
        ms = (time.perf_counter() - t0) * 1000
        ok: Any = NA
        if expect is not NA and isinstance(answer, bool):
            ok = answer == expect
            oks.append(ok)
            if not ok:
                logger.warning("PREDICTION FAILED at line %d (%s): expected %s, got %s", n, line,
                               expect, answer)
        moves.add(n, kind, rest[:90], answer, NA if expect is NA else int(expect), ok,
                  round(ms, 3), reason, rescue)
    summary = Section("dialogue:summary", ["questions", "predicted", "holder", "asserted",
                                           "denied", "moves"])
    summary.add(len(oks), f"{sum(oks)}/{len(oks)}" if oks else NA, position.holder or NA,
                len(position.accepted), len(position.rejected), len(position.log))
    backend.close()
    return [moves, summary]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.replay_dialogue",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True)
    parser.add_argument("--regime", default="rdfs", choices=["simple", "rdfs", "owl2rl"])
    parser.add_argument("--rules")
    parser.add_argument("--regime-name")
    parser.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI")
    parser.add_argument("--dialogue", required=True, type=Path)
    parser.add_argument("--entries", type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    print(f"pyNMMS replay_dialogue  sha={git_sha()}  {env_info()}  label={args.label!r}\n")
    sections = replay(args)
    for section in sections:
        print(section.render(), end="\n\n")
    if not args.no_write:
        print(f"record: {write_record(sections, args.out, quick=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
