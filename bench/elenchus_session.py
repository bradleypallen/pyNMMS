"""Replay an Elenchus session, the loop of PLAN.md step 6, over a persisted store.

A session file is a :meth:`pynmms.rdf.dialogue.Dialogue.play` script: one
move per line (``commit``, ``deny``, ``withdraw``, ``accept N [retract ...
| refine old => new]``, ``contest N [unless ...]``, ``propose Γ |~ Δ``) and
questions with predictions (``status? ## coherent``, ``tensions? ## 1``,
``probes? ## 2``). A ``holder NAME`` line names the respondent and a
``positum <atoms>`` line the commitments that cannot be withdrawn. The
opponent is computed from the base. The record holds every answer against
its prediction and the transcript.

Usage::

    python -m bench.elenchus_session --store DIR --session FILE [--entries FILE]
        [--regime rdfs] [--rules FILE] [--regime-name NAME] [--prefix ex=IRI ...]
        [--label TEXT] [--out DIR] [--no-write] [--save STATE.json]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ._util import Section, env_info, git_sha, write_record

logger = logging.getLogger("bench.elenchus_session")


def run(args: argparse.Namespace) -> list[Section]:
    from rdflib import Graph

    from pynmms.rdf import RegimeBase
    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.backends import OxigraphBackend
    from pynmms.rdf.dialogue import Dialogue
    from pynmms.rdf.entries import load_entries
    from pynmms.rdf.rules import REGIMES, custom, parse_rules_text
    from pynmms.syntax import split_top_level

    prefixes: dict[str, str] = {}
    for item in args.prefix:
        pfx, iri = item.split("=", 1)
        prefixes[pfx.strip()] = iri.strip()
    regime = REGIMES[args.regime]
    if args.rules:
        resolver = Resolver(Graph())
        for pfx, iri in prefixes.items():
            resolver.bind(pfx, iri)
        regime = custom(args.regime_name or f"{regime.name}+{Path(args.rules).name}",
                        parse_rules_text(Path(args.rules).read_text(), resolver), extends=regime)
    elif args.regime_name:
        regime = custom(args.regime_name, [], extends=regime)
    backend = OxigraphBackend(args.store, regime=regime, prefixes=prefixes, materialize=False)
    if not backend.materialised:
        raise SystemExit(f"{args.store} is not materialised for regime {regime.name}")
    base = RegimeBase(backend, regime=regime)
    if args.entries:
        load_entries(Path(args.entries), base)

    text = Path(args.session).read_text()
    holder = ""
    positum: list[str] = []
    body: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("holder "):
            holder = s[7:].strip()
        elif s.startswith("positum "):
            positum = [x.strip() for x in split_top_level(s[8:], ",") if x.strip()]
        else:
            body.append(line)
    d = Dialogue(base, holder=holder, positum=positum)
    outcome = d.play("\n".join(body))

    moves = Section("elenchus:moves", ["#", "line", "answer", "expect", "ok"],
                    notes=f"store {args.store}; holder {holder or '-'}; positum {len(positum)}")
    for n, (line, answer, expect, ok) in enumerate(outcome.answers, 1):
        moves.add(n, line[:100], "" if answer is None else answer, expect or "", ok)
    transcript = Section("elenchus:transcript", ["n", "actor", "move", "args", "tensions",
                                                  "probes", "status", "ms"])
    for t in d.transcript:
        transcript.add(t.n, t.actor, t.move, ", ".join(t.args)[:80], len(t.tensions),
                       len(t.probes), t.status, round(t.ms, 1))
    summary = Section("elenchus:summary", ["questions", "predicted", "status", "open",
                                            "accepted", "contested", "proposals", "moves"])
    summary.add(len([a for a in outcome.answers if a[3] is not None]), outcome.predicted,
                d.status(), len(d.open), len(d.accepted), len(d.contested), len(d.proposals),
                len(d.transcript))
    if args.save:
        d.save(args.save)
    backend.close()
    return [moves, transcript, summary]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.elenchus_session",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True)
    parser.add_argument("--regime", default="rdfs", choices=["simple", "rdfs", "owl2rl"])
    parser.add_argument("--rules")
    parser.add_argument("--regime-name")
    parser.add_argument("--prefix", action="append", default=[], metavar="PFX=IRI")
    parser.add_argument("--session", required=True)
    parser.add_argument("--entries")
    parser.add_argument("--save", help="write the dialectical state as JSON")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    print(f"pyNMMS elenchus_session  sha={git_sha()}  {env_info()}  label={args.label!r}\n")
    sections = run(args)
    for s in sections:
        print(s.render(), end="\n\n")
    if not args.no_write:
        print(f"record: {write_record(sections, args.out, quick=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
