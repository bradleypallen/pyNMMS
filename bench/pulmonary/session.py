"""Vignette sessions over the pulmonary base: the hold-you-back interaction.

A vignette is a :meth:`pynmms.rdf.dialogue.Dialogue.play` script over a
patient: ``holder`` and ``positum`` lines (the findings the respondent
stands by), then commitments (findings as they arrive, a diagnosis), the
opponent's tensions and probes computed from the base, and the
respondent's accepts and contests, with a prediction after each question
(``status? ## coherent``, ``tensions? ## 1``, ``commits? <atom> ## True``).
A prediction may differ by base: ``## placeholder=coherent models=aporia``.

``--check`` replays the benchmark itself against the base built from it:
for every item, a position holding the premises, whether the diagnosis is
licensed (``commits_to``) and whether it is precluded (``precludes``),
against the verdict the base was built from. Good should be licensed and
not precluded, a defeating bad precluded, and the rest neither.

The store is in memory (``MemoryBackend`` over ``vocabulary.ttl``, regime
simple): a vignette is a few triples, the base a few dozen entries. Not for
clinical use.

Usage::

    python -m bench.pulmonary.session [--base placeholder|models] [--entries FILE]
        [--session FILE ...] [--check] [--label TEXT] [--out DIR] [--no-write]
        [--save DIR]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

from .._util import Section, env_info, git_sha, write_record

logger = logging.getLogger("bench.pulmonary.session")
HERE = Path(__file__).parent


def make_base(entries: Path, *, source: str = "") -> object:
    """A RegimeBase over an in-memory store of the vocabulary, with the entries."""
    from rdflib import Graph

    from pynmms.rdf import RegimeBase
    from pynmms.rdf.backends import MemoryBackend
    from pynmms.rdf.entries import load_entries
    from pynmms.rdf.rules import SIMPLE

    g = Graph()
    g.parse(HERE / "vocabulary.ttl", format="turtle")
    base = RegimeBase(MemoryBackend(g, regime=SIMPLE))
    ground, patterns = load_entries(entries, base)
    logger.info("base %s from %s: %d ground, %d pattern entries", source or "-", entries.name,
                ground, patterns)
    return base


def _pick(script: str, name: str) -> str:
    """Resolve ``## a=x b=y`` predictions to the one for base *name*."""
    out = []
    for line in script.splitlines():
        if "##" in line:
            head, expect = line.split("##", 1)
            parts = dict(re.findall(r"(\w+)=(\S+)", expect))
            if parts:
                line = f"{head}## {parts.get(name, '')}" if name in parts else head.rstrip()
        out.append(line)
    return "\n".join(out)


def play_session(base: object, path: Path, name: str = "placeholder") -> tuple[object, object]:
    """Play one vignette file; returns (Dialogue, Outcome)."""
    from pynmms.rdf.dialogue import Dialogue
    from pynmms.syntax import split_top_level

    holder = ""
    positum: list[str] = []
    body: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("holder "):
            holder = s[7:].strip()
        elif s.startswith("positum "):
            positum = [x.strip() for x in split_top_level(s[8:], ",") if x.strip()]
        else:
            body.append(line)
    d = Dialogue(base, holder=holder, positum=positum)  # type: ignore[arg-type]
    outcome = d.play(_pick("\n".join(body), name))
    for n, (line, answer, expect, ok) in enumerate(outcome.answers, 1):
        logger.info("%s %2d %-60s -> %s (expected %s) %s", path.stem, n, line[:60], answer,
                    expect, "" if ok is None else ("ok" if ok else "WRONG"))
    return d, outcome


def check_items(base: object, name: str) -> Section:
    """Replay the benchmark's items against the base built from them."""
    from pynmms.rdf.position import Position

    from .build_base import DEFEATING, finding, load, verdict_of

    bench, bearers, models = load()
    families = bearers["families"]
    sec = Section("pulmonary:check", ["item", "variation", "verdict", "licensed", "precluded",
                                      "expected", "agree", "ms"],
                  notes=f"base {name}; a position holding the premises of each item")
    agree = 0
    for it in bench["items"]:
        source = name if name in ("placeholder", "models", "majority") else "placeholder"
        v = verdict_of(it, source, models)
        patient = f"pul:p{it['id']}"
        atoms = ["<" + finding(b, families).replace("?p", patient) + ">" for b in it["premises"]]
        dx = f"<{patient} pul:dx pul:{it['target']}>"
        t0 = time.perf_counter()
        pos = Position(base, holder="check")  # type: ignore[arg-type]
        pos.assert_(*atoms)
        licensed = bool(pos.commits_to(dx))
        precluded = bool(pos.precludes(dx))
        ms = (time.perf_counter() - t0) * 1000
        if v == "good":
            expected = "licensed"
        elif v == "bad" and it["variation"] in DEFEATING:
            expected = "precluded"
        else:
            expected = "neither"
        got = "licensed" if licensed and not precluded else "precluded" if precluded else "neither"
        ok = got == expected
        agree += ok
        sec.add(it["id"], it["variation"], v, licensed, precluded, expected, ok, round(ms, 1))
    sec.notes += f"; {agree}/{len(bench['items'])} agree"
    return sec


def run(args: argparse.Namespace) -> list[Section]:
    name = args.base
    entries = Path(args.entries) if args.entries else HERE / f"pulmonary_{name}.txt"
    sections: list[Section] = []
    if args.check:
        sections.append(check_items(make_base(entries, source=name), name))
    paths = [Path(p) for p in args.session] or sorted((HERE / "vignettes").glob("*.txt"))
    summary = Section("pulmonary:summary", ["vignette", "base", "questions", "predicted",
                                            "status", "open", "accepted", "contested",
                                            "proposals", "moves", "ms"])
    for path in paths:
        base = make_base(entries, source=name)  # a fresh base: contests revise it
        t0 = time.perf_counter()
        d, outcome = play_session(base, path, name)
        ms = (time.perf_counter() - t0) * 1000
        holder = d.position.holder or "-"  # type: ignore[attr-defined]
        moves = Section(f"pulmonary:{path.stem}", ["#", "line", "answer", "expect", "ok"],
                        notes=f"base {name}; holder {holder}; positum {len(d.positum)}")  # type: ignore[attr-defined]
        for n, (line, answer, expect, ok) in enumerate(outcome.answers, 1):  # type: ignore[attr-defined]
            moves.add(n, line[:100], "" if answer is None else answer, expect or "", ok)
        sections.append(moves)
        answers = outcome.answers  # type: ignore[attr-defined]
        summary.add(path.stem, name, len([a for a in answers if a[3] is not None]),
                    outcome.predicted, d.status(), len(d.open), len(d.accepted),  # type: ignore[attr-defined]
                    len(d.contested), len(d.proposals), len(d.transcript), round(ms, 1))  # type: ignore[attr-defined]
        if args.save:
            Path(args.save).mkdir(parents=True, exist_ok=True)
            d.save(Path(args.save) / f"{path.stem}_{name}.json")  # type: ignore[attr-defined]
    sections.append(summary)
    return sections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.pulmonary.session",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="placeholder", help="placeholder or models")
    parser.add_argument("--entries", help="an entries file instead of the built base")
    parser.add_argument("--session", action="append", default=[], metavar="FILE")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--save", help="directory for the dialectical states as JSON")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, default=HERE.parent / "results")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("pynmms").setLevel(logging.WARNING)
    print(f"pyNMMS pulmonary.session  sha={git_sha()}  {env_info()}  label={args.label!r}\n")
    sections = run(args)
    for s in sections:
        print(s.render(), end="\n\n")
    if not args.no_write:
        print(f"record: {write_record(sections, args.out, quick=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
