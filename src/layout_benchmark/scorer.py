"""The project's pathway layout scorer's combined score, from this benchmark's rule values.

The scorer (``build/core.js`` in elixir2026-project22/frontend-tool-pathway-scorer, at commit c1f2ef7) turns each of
project 22's layout rules into a score of 0-100 with its own pass and fail values (linear between them, or a band
for aspect ratio and density), and the rules into one ``overall`` score: the weighted mean of the rule scores (hard
rules weight 2, soft rules 1) over the rules that apply. Its thresholds and weights are taken here as data, and
applied to this benchmark's values of the rules (``rules.py``; where our definition of a rule differs from the
scorer's, the score follows ours). A rule without a value doesn't apply (left out, as the scorer does): "labels at
fixed positions" always (our renderer places the labels), "reproducible" where the check hasn't been run, cycles
where a model has none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SCORER = "https://github.com/elixir2026-project22/frontend-tool-pathway-scorer"
SCORER_COMMIT = "c1f2ef7"

# core.js DEFAULT_THRESHOLDS at SCORER_COMMIT (labels left out: never applies here)
THRESHOLDS = {
    "reproducible": {"pass": 0, "fail": 1},
    "cycle": {"pass": 1, "fail": 0.5},
    "through": {"pass": 0, "fail": 5},
    "clones": {"pass": 0, "fail": 3},
    "crossings": {"pass": 0.02, "fail": 0.3},
    "placement": {"pass": 0.8, "fail": 0.5},
    "aspect": {"lo": 0.5, "hi": 2, "flo": 0.25, "fhi": 4},
    "longlines": {"pass": 6, "fail": 15},
    "bends": {"pass": 0.5, "fail": 2},
    "density": {"lo": 0.05, "hi": 0.3, "flo": 0.02, "fhi": 0.5},
    "overlaps": {"pass": 0, "fail": 5},
}
WEIGHTS = {"hard": 2, "soft": 1}


@dataclass(frozen=True)
class Rule:
    """A scorer rule: its id in core.js, hard or soft, our value (a results.csv column; "reproducible" comes from the
    reproducibility check) and how it is scored: "lower" or "higher" is better, or "band" (log: on a log scale)."""

    id: str
    kind: str
    name: str
    column: str
    form: str
    log: bool = False


RULES = [
    Rule("reproducible", "hard", "reproducible", "reproducible", "lower"),
    Rule("cycle", "hard", "cycles look like cycles", "rule_cycles_closed", "higher"),
    Rule("clones", "hard", "cofactors drawn as clones", "rule_cofactor_hubs", "lower"),
    Rule("crossings", "hard", "no crossings", "rule_crossings_per_line", "lower"),
    Rule("placement", "hard", "consistent participant placement", "rule_opposite_share", "higher"),
    Rule("through", "hard", "no line through a node", "rule_lines_through_nodes", "lower"),
    Rule("aspect", "hard", "aspect ratio", "rule_aspect", "band", log=True),
    Rule("longlines", "soft", "avoid long lines", "rule_longest_over_median", "lower"),
    Rule("bends", "soft", "avoid bends", "rule_bends_per_line", "lower"),
    Rule("density", "soft", "density", "rule_density", "band"),
    Rule("overlaps", "soft", "no overlapping nodes", "overlapping_pairs", "lower"),
]


def low_better(v: float, p: float, f: float) -> float:
    return 1.0 if v <= p else 0.0 if v >= f else (f - v) / (f - p)


def high_better(v: float, p: float, f: float) -> float:
    return 1.0 if v >= p else 0.0 if v <= f else (v - f) / (p - f)


def band(v: float, t: dict, log: bool = False) -> float:
    """1 inside [lo, hi], falling to 0 at flo and fhi (on a log scale with ``log``)."""
    T = math.log if log else (lambda x: x)
    if t["lo"] <= v <= t["hi"]:
        return 1.0
    if v < t["lo"]:
        return 0.0 if v <= t["flo"] else (T(v) - T(t["flo"])) / (T(t["lo"]) - T(t["flo"]))
    return 0.0 if v >= t["fhi"] else (T(t["fhi"]) - T(v)) / (T(t["fhi"]) - T(t["hi"]))


def _js_round(x: float) -> int:
    """JavaScript's Math.round (halves up), as core.js rounds."""
    return math.floor(x + 0.5)


def _value(row: dict, column: str) -> float | None:
    x = row.get(column)
    if x in (None, ""):
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def rule_fraction(rule: Rule, v: float) -> float:
    """A rule's score for its value, 0-1 (core.js's ``s``)."""
    t = THRESHOLDS[rule.id]
    if rule.form == "band":
        return band(v, t, rule.log)
    if rule.form == "lower":
        return low_better(v, t["pass"], t["fail"])
    return high_better(v, t["pass"], t["fail"])


def evaluate(row: dict, reproduced: bool | None = None) -> dict:
    """The scorer's scores of one drawing: ``rules`` (id: 0-100, or None where it doesn't apply), ``overall`` (the
    weighted mean, None if no rule applies), ``hard_pass`` and ``hard_total`` (hard rules passed / applying).
    ``row``: a results.csv row; ``reproduced``: the reproducibility check's answer (None: not checked)."""
    scores: dict[str, int | None] = {}
    total = weights = hard_pass = hard_total = 0
    for rule in RULES:
        if rule.id == "reproducible":
            v = None if reproduced is None else (0.0 if reproduced else 1.0)
        else:
            v = _value(row, rule.column)
        if v is None:
            scores[rule.id] = None
            continue
        s = rule_fraction(rule, v)
        score = _js_round(s * 100)
        scores[rule.id] = score
        w = WEIGHTS[rule.kind]
        total += w * score
        weights += w
        if rule.kind == "hard":
            hard_total += 1
            hard_pass += s >= 0.999  # core.js's status "pass"
    return {
        "rules": scores,
        "overall": _js_round(total / weights) if weights else None,
        "hard_pass": hard_pass,
        "hard_total": hard_total,
    }
