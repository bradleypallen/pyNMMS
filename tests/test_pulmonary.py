"""The pulmonary base and vignette sessions from the CPE/ARDS placeholder benchmark.

Predictions first (2026-09-08). The base is built from the benchmark's
verdicts; the check replays the items against it, and the vignettes are
Elenchus sessions whose predictions are in the session files. Not for
clinical use.
"""

# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from bench.pulmonary import build_base
from bench.pulmonary.session import HERE, check_items, make_base, play_session
from pynmms.rdf.values import ORDERINGS

VIGNETTES = sorted((HERE / "vignettes").glob("*.txt"))


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    return {name: build_base.build(name)[0] for name in ("placeholder", "models")}


class TestBuilder:
    def test_placeholder_counts(self, texts):
        assert texts["placeholder"].splitlines()[-1] == \
            "# 19 good, 5 bad, 10 abstain, 1 contested; 30 entries"

    def test_a_default_with_the_ladder_defeaters(self, texts):
        assert ('?p pul:has pul:ad, ?p pul:bi "bi_mod", ?p pul:cv "cv_struct" |~ '
                '?p pul:dx pul:cpe unless ?p pul:bnp "bnp_lo" ; '
                '?p pul:fluid "fluid_neg", ?p pul:pv "pv_none"') in texts["placeholder"]

    def test_monotonicity_ladder_compressed_by_rank(self, texts):
        t = texts["placeholder"]
        assert ('?p pul:has pul:ad, ?p pul:bi "bi_mod", ?p pul:cv "cv_minor", ?p pul:bnp ?v, '
                '[rank(bnp, ?v) >= rank(bnp, "bnp_mod")] |~ ?p pul:dx pul:cpe unless '
                '?p pul:fluid "fluid_neg", ?p pul:pv "pv_none"') in t
        assert ('?p pul:bnp ?v, [rank(bnp, ?v) <= rank(bnp, "bnp_lo")], ?p pul:dx pul:cpe |~ false'
                ) in t
        assert "ordering bnp: bnp_lo < bnp_grey < bnp_mod < bnp_hi < bnp_vhi" in t

    def test_contested_bad_is_rescued_by_the_override(self, texts):
        assert ('?p pul:bnp "bnp_vhi", ?p pul:dx pul:ards |~ false unless ?p pul:override "B6"'
                ) in texts["placeholder"]

    def test_insufficient_bad_is_no_entry(self, texts):
        t = texts["models"]
        assert "# (A0: the premises are not enough; no default)" in t
        assert '?p pul:has pul:ad, ?p pul:bi "bi_mod", ?p pul:dx pul:cpe |~ false' not in t
        assert t.splitlines()[-1] == "# 23 good, 12 bad, 0 abstain, 0 contested; 34 entries"

    def test_structural_entries(self, texts):
        t = texts["placeholder"]
        assert "?p pul:has pul:septic_shock |~ ?p pul:has pul:sep monotone" in t
        assert '?p pul:bnp ?a, ?p pul:bnp ?b, [str(?a) < str(?b)] |~ false' in t

    def test_entries_load_with_orderings(self, tmp_path: Path, texts):
        f = tmp_path / "e.txt"
        f.write_text(texts["placeholder"])
        base = make_base(f)
        assert len(base.pattern_rules) == 30
        assert ORDERINGS["rs"] == ("rs_hfnc", "rs_niv", "rs_imvlow", "rs_imvmiddle", "rs_imvhigh")


class TestCheck:
    """The base against the verdicts it was built from.

    Predicted: the placeholder base agrees on 34/35, B5 excepted (aspiration
    plus reduced LVEF is an abstention, but B1's default fires from the
    aspiration alone: the abstention would need LVEF as a defeater, which
    the benchmark does not say); the model panel's base on 35/35. Observed
    33/35: F1 is the same case (reduced LVEF plus a negative balance is
    contested, but A2 fires from the LVEF alone; A8 needs no effusions
    too), missed in the prediction.
    """

    def test_placeholder(self):
        sec = check_items(make_base(HERE / "pulmonary_placeholder.txt"), "placeholder")
        assert sec.notes.endswith("33/35 agree")
        wrong = [r for r in sec.rows if not r[6]]
        assert [r[0] for r in wrong] == ["F1", "B5"]
        assert all(r[3:6] == [True, False, "neither"] for r in wrong)

    def test_models(self):
        sec = check_items(make_base(HERE / "pulmonary_models.txt"), "models")
        assert sec.notes.endswith("35/35 agree")


class TestVignettes:
    @pytest.mark.parametrize("path", VIGNETTES, ids=[p.stem for p in VIGNETTES])
    @pytest.mark.parametrize("name", ["placeholder", "models"])
    def test_predictions_hold(self, path: Path, name: str):
        base = make_base(HERE / f"pulmonary_{name}.txt")
        d, outcome = play_session(base, path, name)
        assert outcome.failures == [], outcome.failures
        assert d.status() == "coherent"
