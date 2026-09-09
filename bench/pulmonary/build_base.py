"""Build the pulmonary material base from the CPE/ARDS placeholder benchmark.

The benchmark (``benchmark_v0.5.json``) is 35 defeasible diagnostic
inferences over 47 clinical statements, the bearers, eleven of whose
families are ordered tiers (BNP, P/F ratio, respiratory support, LVEF,
...). Each item is a set of premises, a target diagnosis, a variation
(base, strengthen, defeat, contested, monotonicity step, abstain anchor)
and a verdict, good, bad, or abstain. The verdicts here are placeholders
written without clinical credentials; the study replaces them with a
clinician panel's. **Not for clinical use.**

A verdict source is a base. This script writes the base as a tell-syntax
entries file for ``pynmms.rdf.entries.load_entries``:

* the eleven families as orderings, ``ordering bnp: bnp_lo < ... < bnp_vhi``;
* a **good** item as a default, ``premises |~ ?p pul:dx pul:<target>``, whose
  defeaters are the extra findings of every **bad** item in the same ladder
  (the findings the panel says overturn the diagnosis), and, for a
  contested good, the clinician's override ``?p pul:override "<id>"``;
* a **bad** defeat, contested or monotonicity item as an incompatibility
  between its premises and the diagnosis, ``premises, ?p pul:dx pul:<target>
  |~ false``, rescuable by the override when contested and not otherwise; a
  bad base, strengthen or anchor item says only that its premises are not
  enough, which is the absence of a default;
* a monotonicity ladder as one default over the tiers rated good,
  ``..., ?p pul:bnp ?v, [rank(bnp, ?v) >= rank(bnp, "bnp_mod")] |~ ...``, and
  one incompatibility over the tiers rated bad, when the verdicts are
  monotone in the tier, and one entry per tier otherwise;
* an **abstain** (or contested) item as nothing: the premises license neither;
* each family's tiers as mutually exclusive, and ``septic_shock`` entailing
  ``sep``, from the benchmark's structural rules.

Findings are triples of a patient: ``?p pul:has pul:ad`` for a plain bearer,
``?p pul:bnp "bnp_hi"`` for a tier, ``?p pul:dx pul:cpe`` for a diagnosis.

Usage::

    python -m bench.pulmonary.build_base [--source placeholder|models|majority]
        [--out FILE] [--vocabulary FILE]

``models`` takes the six-model panel's majority verdict for each item
(``model_verdicts_2026-07-08.json``); ``majority`` is the same with ties
counted as abstain.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
PUL = "http://pynmms.dev/pulmonary/"
DEFEATING = ("defeat", "contested", "monotonicity_step")


def load() -> tuple[dict, dict, dict]:
    bench = json.loads((HERE / "benchmark_v0.5.json").read_text())
    bearers = json.loads((HERE / "bearers_v0.5.json").read_text())
    models = json.loads((HERE / "model_verdicts_2026-07-08.json").read_text())
    return bench, bearers, models


def verdict_of(item: dict, source: str, models: dict) -> str:
    if source == "placeholder":
        return item["placeholder"]
    votes = Counter(models["verdicts"][item["id"]]["models"].values())
    top = votes.most_common()
    if source == "models":
        return top[0][0]
    if len(top) > 1 and top[0][1] == top[1][1]:
        return "abstain"
    return top[0][0]


def finding(bearer: str, families: dict[str, list[str]]) -> str:
    """The triple atom for a bearer on the patient variable ``?p``."""
    for fam, tiers in families.items():
        if bearer in tiers:
            return f'?p pul:{fam} "{bearer}"'
    return f"?p pul:has pul:{bearer}"


def _defeaters(item: dict, bad_items: list[dict], families: dict,
               ladder_family: str | None) -> list[str]:
    """The findings every bad item of the same target adds to this item's, as defeaters.

    A bad item that shares premises with the good one and adds findings the
    good one does not hold says those findings overturn the diagnosis. Skipped:
    additions impossible next to the item's premises (a second tier of a family
    the item fixes, or of the ladder's own family), and additions containing
    another defeater already listed.
    """
    fam_of = {t: f for f, ts in families.items() for t in ts}
    have = set(item["premises"])
    fixed = {fam_of[b] for b in have if b in fam_of}
    if ladder_family:
        fixed.add(ladder_family)
    cands: list[set[str]] = []
    for bad in bad_items:
        q = set(bad["premises"])
        extras = q - have
        if bad["id"] == item["id"] or not extras or not (q & have):
            continue
        if any(fam_of.get(b) in fixed for b in extras):
            continue
        cands.append(extras)
    cands.sort(key=len)
    kept: list[set[str]] = []
    for c in cands:
        if not any(k <= c for k in kept):
            kept.append(c)
    return [", ".join(finding(b, families) for b in sorted(e)) for e in kept]


def build(source: str = "placeholder") -> tuple[str, str]:
    """Return (entries text, vocabulary Turtle)."""
    bench, bearers, models = load()
    families: dict[str, list[str]] = bearers["families"]
    stmt = {bid: b["statement"] for bid, b in bearers["bearers"].items()}
    items = bench["items"]
    verdict = {it["id"]: verdict_of(it, source, models) for it in items}
    lines = [
        f"# The pulmonary material base from benchmark_v0.5.json, verdict source: {source}.",
        "# Placeholder research instrument; not for clinical use. Prefix pul = " + PUL,
        "# Findings: ?p pul:has pul:<bearer>; tiers: ?p pul:<family> \"<tier>\"; "
        "?p pul:dx pul:<target>.",
        "",
        "# --- the eleven evidence families as orderings, low to high ---",
    ]
    for fam, tiers in families.items():
        lines.append(f"ordering {fam}: {' < '.join(tiers)}")
    lines += ["", "# --- structural: one tier per family, and septic shock is sepsis ---"]
    for fam in families:
        lines.append(f"?p pul:{fam} ?a, ?p pul:{fam} ?b, [str(?a) < str(?b)] |~ false")
    lines.append("?p pul:has pul:septic_shock |~ ?p pul:has pul:sep monotone")
    ladders: dict[str, list[dict]] = {}
    for it in items:
        ladders.setdefault(it["ladder"], []).append(it)
    # A bad verdict on a defeat, contested or monotonicity item says its additions overturn
    # the diagnosis; on a base, strengthen or anchor item it says the premises are not
    # enough, which is the absence of a default, not an incompatibility.
    bad_items: dict[str, list[dict]] = {}
    for it in items:
        if verdict[it["id"]] == "bad" and it["variation"] in DEFEATING:
            bad_items.setdefault(it["target"], []).append(it)
    counts = {"good": 0, "bad": 0, "abstain": 0, "contested": 0}
    for ladder, its in ladders.items():
        common = set.intersection(*(set(it["premises"]) for it in its))
        target = its[0]["target"]
        dx = f"?p pul:dx pul:{target}"
        lines += ["", f"# --- ladder {ladder}: target {target} ({stmt[target]}); "
                      f"base {sorted(common)} ---"]
        for it in its:
            v = verdict[it["id"]]
            counts[v] += 1
            extras = sorted(set(it["premises"]) - common)
            added = "; ".join(stmt[b] for b in extras) or "-"
            lines.append(f"# {it['id']} ({it['variation']}, {v}): + {added}")
        mono = [it for it in its if it.get("monotonicity")]
        if mono:
            fam = mono[0]["monotonicity"]["family"]
            tiers = families[fam]
            by_tier = {it["monotonicity"]["tier"]: it for it in mono}
            fixed = [b for b in mono[0]["premises"] if b not in tiers]
            prem = ", ".join(finding(b, families) for b in fixed)
            vs = [verdict[by_tier[t]["id"]] if t in by_tier else None for t in tiers]
            goods = [i for i, x in enumerate(vs) if x == "good"]
            bads = [i for i, x in enumerate(vs) if x == "bad"]
            monotone = (not goods or goods == list(range(goods[0], len(tiers)))) and \
                       (not bads or bads == list(range(0, bads[-1] + 1))) and \
                       (not goods or not bads or bads[-1] < goods[0])
            if monotone:
                lines.append(f"# {fam} ladder over {tiers}: verdicts {vs}; one entry per range")
                if goods:
                    lo = tiers[goods[0]]
                    defs = _defeaters(by_tier[lo], bad_items.get(target, []), families, fam)
                    clause = " unless " + " ; ".join(defs) if defs else " monotone"
                    guard = f'[rank({fam}, ?v) >= rank({fam}, "{lo}")]'
                    lines.append(f"{prem}, ?p pul:{fam} ?v, {guard} |~ {dx}{clause}")
                if bads:
                    hi = tiers[bads[-1]]
                    guard = f'[rank({fam}, ?v) <= rank({fam}, "{hi}")]'
                    lines.append(f"{prem}, ?p pul:{fam} ?v, {guard}, {dx} |~ false")
                continue
            lines.append(f"# {fam} ladder is not monotone under {source}: {vs}; "
                         "one entry per tier")
        for it in its if not mono or not monotone else mono:
            v = verdict[it["id"]]
            prem = ", ".join(finding(b, families) for b in it["premises"])
            if v == "good":
                defs = _defeaters(it, bad_items.get(target, []), families, None)
                if it["variation"] == "contested":
                    defs.append(f'?p pul:override "{it["id"]}"')
                clause = " unless " + " ; ".join(defs) if defs else " monotone"
                lines.append(f"{prem} |~ {dx}{clause}")
            elif v == "bad" and it["variation"] in DEFEATING:
                contested = it["variation"] == "contested"
                rescue = f' unless ?p pul:override "{it["id"]}"' if contested else ""
                lines.append(f"{prem}, {dx} |~ false{rescue}")
            elif v == "bad":
                lines.append(f"# ({it['id']}: the premises are not enough; no default)")
    lines += ["", "# " + ", ".join(f"{n} {k}" for k, n in counts.items())
              + f"; {sum(1 for x in lines if '|~' in x and not x.startswith('#'))} entries"]
    vocab = ["@prefix pul: <" + PUL + "> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .", ""]
    for bid, b in bearers["bearers"].items():
        fam = ""
        if b["family"]:
            fam = f' ;\n    pul:family "{b["family"]}" ; pul:position {b["position"]}'
        label = json.dumps(b["statement"])
        vocab.append(f"pul:{bid} a pul:Bearer ;\n    rdfs:label {label}{fam} .")
    return "\n".join(lines) + "\n", "\n".join(vocab) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.pulmonary.build_base",
                                     description=__doc__.split("Usage::")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="placeholder",
                        choices=["placeholder", "models", "majority"])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--vocabulary", type=Path, default=HERE / "vocabulary.ttl")
    args = parser.parse_args(argv)
    entries, vocab = build(args.source)
    out = args.out or (HERE / f"pulmonary_{args.source}.txt")
    out.write_text(entries)
    args.vocabulary.write_text(vocab)
    print(f"wrote {out} and {args.vocabulary}")
    print(entries.splitlines()[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
