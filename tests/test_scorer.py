"""The pathway layout scorer's combined score (``scorer``), as core.js computes it."""

import math

import pytest

from layout_benchmark.scorer import RULES, band, evaluate, high_better, low_better

ASPECT = {"lo": 0.5, "hi": 2, "flo": 0.25, "fhi": 4}
DENSITY = {"lo": 0.05, "hi": 0.3, "flo": 0.02, "fhi": 0.5}


def test_lower_and_higher_better_are_linear_between_pass_and_fail():
    assert low_better(0.02, 0.02, 0.3) == 1 and low_better(0.3, 0.02, 0.3) == 0 and low_better(1, 0.02, 0.3) == 0
    assert low_better(0.16, 0.02, 0.3) == pytest.approx(0.5)
    assert high_better(0.8, 0.8, 0.5) == 1 and high_better(0.5, 0.8, 0.5) == 0
    assert high_better(0.65, 0.8, 0.5) == pytest.approx(0.5)


def test_band_is_one_inside_and_falls_to_zero_outside():
    assert band(1.0, ASPECT, log=True) == 1 and band(0.25, ASPECT, log=True) == 0 and band(5, ASPECT, log=True) == 0
    # on a log scale: halfway between 0.25 and 0.5 is their geometric mean
    assert band(math.sqrt(0.25 * 0.5), ASPECT, log=True) == pytest.approx(0.5)
    assert band(3, ASPECT, log=True) == pytest.approx(math.log(4 / 3) / math.log(2))
    assert band(0.4, DENSITY) == pytest.approx(0.5)  # linear: halfway between 0.3 and 0.5


def _row(**values):
    return {r.column: "" for r in RULES if r.column != "reproducible"} | {k: str(v) for k, v in values.items()}


def test_overall_is_the_weighted_mean_of_the_rules_that_apply():
    # crossings (hard) 50, bends (soft) 100: (2*50 + 1*100) / 3 = 66.67 -> 67
    e = evaluate(_row(rule_crossings_per_line=0.16, rule_bends_per_line=0.5))
    assert e["rules"]["crossings"] == 50 and e["rules"]["bends"] == 100
    assert e["overall"] == 67
    assert (e["hard_pass"], e["hard_total"]) == (0, 1)
    assert e["rules"]["cycle"] is None and e["rules"]["reproducible"] is None


def test_reproducibility_and_hard_rules_passed():
    row = _row(rule_cycles_closed=1, rule_aspect=1.2, rule_opposite_share=0.6)
    e = evaluate(row, reproduced=True)
    assert e["rules"]["reproducible"] == 100
    assert (e["hard_pass"], e["hard_total"]) == (3, 4)  # placement 0.6: between fail and pass
    assert evaluate(row, reproduced=False)["rules"]["reproducible"] == 0


def test_halves_round_up_as_javascript():
    from layout_benchmark.scorer import _js_round

    assert [_js_round(x) for x in (0.5, 1.5, 2.5, 66.5, 2.4999)] == [1, 2, 3, 67, 2]  # Python's round: 0, 2, 2, 66


def test_nothing_applies():
    e = evaluate(_row())
    assert e["overall"] is None and e["hard_total"] == 0


def test_the_report_shows_the_score(tmp_path, tiny_sbml):
    from layout_benchmark.report import SCORE, write_summary

    row = _row(rule_crossings_per_line=0.16, rule_bends_per_line=0.5) | {
        "model": "tiny",
        "layout": "graphviz-dot",
        "error": "",
        "seconds": "1",
    }
    path = write_summary(tmp_path, [row], {"set": ["tiny"]})
    html = path.read_text()
    assert f">{SCORE.label}</th>" in html
    assert "67 <span class=t>(1)</span>" in html
