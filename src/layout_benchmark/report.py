"""The HTML report: per model, the reference layout in its own box and the computed layouts in a scrolling strip
next to it, with links to the source files, and a table of their scores; and a summary page (``summary.html``):
per layout, its median rank per metric over the models."""

from __future__ import annotations

import json
import math
import statistics
from html import escape
from pathlib import Path

from .layouts import GROUP, LINKS, expected_rank
from .metrics import METRICS, SOURCES, Metric

REFERENCE = "reference"
# a colour per source band (CSS classes gd, pw, rf; run: the runs' own columns)
BAND_CLASS = {"gdMetriX": "gd", "gdMetriX definition": "gd", "pathway": "pw", "project rules": "pw", "reference": "rf"}


def _band(m: Metric) -> str:
    return BAND_CLASS.get(m.source, "run")


def _cell_classes(columns: list[Metric]) -> list[str]:
    """Per column: its band's class, plus ``first`` where a band starts (a white gap between bands)."""
    out, previous = [], None
    for m in columns:
        k = _band(m)
        out.append(f"c-{k}" + (" first" if k != previous else ""))
        previous = k
    return out


# the reproducibility check's table (`layout-benchmark reproducibility ... -o OUT/reproducibility.csv`), if there
REPRODUCIBILITY = "reproducibility.csv"
REPRODUCIBLE = Metric(
    "reproducible",
    "reproducible",
    "reproducible",
    None,
    "the same drawing twice from one seed (hard rule)",
    "project rules",
    "the layout run twice on the model with the same seed, each run in its own process, and the drawn nodes "
    "compared in the tool's own coordinates (`layout-benchmark reproducibility`): exact (the same coordinates), "
    "congruent (the same drawing moved, scaled, turned or mirrored; mirrored: a cycle the other way round) or "
    "differs; shown where the check has been run. Summary: the models reproduced (exact or congruent, not "
    "mirrored) / the models compared",
)


def read_reproducibility(out: Path) -> dict[tuple[str, str], dict]:
    """The reproducibility check's rows in ``out`` by (model, layout); empty if it hasn't been run there."""
    path = out / REPRODUCIBILITY
    if not path.exists():
        return {}
    import csv

    return {(r["model"], r["layout"]): r for r in csv.DictReader(path.open())}


def _reproduced(row: dict) -> bool | None:
    """Whether a check reproduced the drawing (exact, or congruent without mirroring); None: nothing compared."""
    if row["verdict"] in ("exact", "congruent"):
        return row["verdict"] == "exact" or row.get("mirrored") not in ("True", "true", "1")
    return False if row["verdict"] == "differs" else None


def _verdict_cell(row: dict | None, cls: str) -> str:
    """A model's reproducibility verdict for one layout, coloured: reproduced, not, or nothing to say."""
    if row is None:
        return f'<td data-v="" class="{cls}">–</td>'
    text = row["verdict"].replace("_", " ")
    if row["verdict"] == "congruent" and row.get("mirrored") in ("True", "true", "1"):
        text = "mirrored"
    ok = _reproduced(row)
    mark = " yes" if ok else (" no" if ok is False else "")
    shift = _number(row.get("max_shift"))
    title = f"max shift {shift:.3g} of the diagonal" if shift else (row.get("error") or "")
    return f'<td data-v="{escape(text)}" class="{cls}{mark}" title="{escape(title)}">{escape(text)}</td>'


def _with_reproducible(columns: list[Metric]) -> list[Metric]:
    """The columns with REPRODUCIBLE first in the pathway-maps band (its first hard rule)."""
    at = next((i for i, m in enumerate(columns) if _band(m) == "pw"), len(columns))
    return [*columns[:at], REPRODUCIBLE, *columns[at:]]


def _legend() -> str:
    """What the column colours mean."""
    items = [
        ("gd", "general graph drawing (gdMetriX)"),
        ("pw", "pathway maps: project 22's layout rules and this benchmark's checks"),
        ("rf", "comparison with the reference"),
        ("run", "the runs"),
    ]
    return (
        "<div class=legend>" + "".join(f"<span style='--k:var(--{k})'>{escape(t)}</span>" for k, t in items) + "</div>"
    )


CSS = """
:root { --ref: #b5651d; --line: #dfe4e8; --muted: #5f6b76; --bg: #f4f6f8; --text: #1f2a33; --nav: #0e3b43;
        --accent: #12808a; --best: #1b6b30; --best-bg: #d6f0dd;
        /* one colour per source of metrics: band header, group header, cells */
        --gd: #3b6fb6; --gd-tint: #e3ecf8; --gd-cell: #f6f9fd;
        --pw: #12808a; --pw-tint: #dcefef; --pw-cell: #f4fafa;
        --rf: #8256b0; --rf-tint: #ece4f6; --rf-cell: #faf7fd;
        --run: #6b7785; --run-tint: #e9ecef; --run-cell: #fafbfc; }
* { box-sizing: border-box; }
body { font: 14px/1.5 system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; color: var(--text);
       background: #fff; }
a { color: var(--accent); }
main { padding: 0 24px 40px; }
.top { position: sticky; top: 0; z-index: 10; background: var(--nav); color: #fff; padding: 0 24px;
       display: flex; flex-wrap: wrap; align-items: center; gap: 6px 22px; min-height: 52px;
       box-shadow: 0 1px 3px rgba(0,0,0,.15); }
.top .brand { font-weight: 700; font-size: 17px; color: #fff; text-decoration: none; margin-right: 8px; }
.top a { color: rgba(255,255,255,.88); text-decoration: none; font-size: 14px; }
.top a:hover { color: #fff; text-decoration: underline; }
nav { display: contents; }
nav details { position: relative; font-size: 14px; }
nav summary { cursor: pointer; color: rgba(255,255,255,.88); list-style: none; }
nav summary::after { content: " \\25BE"; font-size: 11px; }
nav summary:hover { color: #fff; }
nav details ul { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 8px;
                 padding: 8px 14px; margin: 8px 0 0; list-style: none; max-height: 60vh; overflow-y: auto;
                 white-space: nowrap; box-shadow: 0 8px 24px rgba(16,24,40,.14); }
nav details ul a { color: var(--accent); }
nav details li { margin: 2px 0; }
.hero { background: var(--bg); border-bottom: 1px solid var(--line); padding: 22px 24px 16px; margin: 0 -24px 8px; }
h1 { font-size: 26px; margin: 0 0 8px; }
.hero .meta { max-width: 75em; font-size: 14px; }
h2 { font-size: 18px; margin: 32px 0 6px; padding-top: 10px; border-top: 1px solid var(--line); scroll-margin-top: 64px; }
section { border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px 16px; margin: 14px 0;
          scroll-margin-top: 70px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
h2.set { font-size: 20px; margin: 34px 0 6px; padding-top: 10px; border-top: 3px solid var(--nav);
         scroll-margin-top: 64px; }
.badge { font-size: 12px; font-weight: 600; color: var(--muted); background: var(--bg); border-radius: 4px;
         padding: 2px 8px; margin-left: 8px; vertical-align: middle; }
h3 { font-size: 16px; margin: 0 0 4px; }
.meta { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.meta a { margin-right: 12px; }
.row { display: flex; gap: 14px; align-items: flex-start; padding: 3px; }
.ref { box-shadow: 0 0 0 3px var(--ref); background: #fffaf3; }  /* an outline: no change to the size */
.ref figcaption b { color: var(--ref); }
.ref.none { box-shadow: none; border-style: dashed; color: var(--muted); font-size: 13px; display: flex; align-items: center; justify-content: center; height: 560px; }
.strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 8px; scroll-snap-type: x proximity; }
figure { flex: 0 0 600px; margin: 0; border: 1px solid var(--line); border-radius: 8px; padding: 6px;
         background: var(--bg); scroll-snap-align: start; }
figure img { width: 100%; height: 520px; object-fit: contain; background: #fff; display: block; border-radius: 4px; }
figcaption { font-size: 12px; margin-top: 4px; }
figcaption .t, .t { color: var(--muted); }
details.scores { margin-top: 10px; font-size: 12px; }
details.scores summary { cursor: pointer; color: var(--accent); font-weight: 600; }
table.sortable { border-collapse: separate; border-spacing: 0; font-size: 12px; margin-top: 8px;
                 font-variant-numeric: tabular-nums; border: 1px solid var(--line); border-radius: 8px; }
table.sortable th, table.sortable td { border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: right;
                                       white-space: nowrap; }
table.sortable th { background: var(--bg); cursor: pointer; font-weight: 600; color: var(--text); }
table.sortable th[data-col]:hover { text-decoration: underline; }
table.sortable th[data-dir=asc]::after { content: " \\25B2"; font-size: 9px; }
table.sortable th[data-dir=desc]::after { content: " \\25BC"; font-size: 9px; }
table.sortable th.group { cursor: default; text-align: center; font-weight: 600; }
table.sortable th.band { color: #fff; font-size: 12px; letter-spacing: .02em; }
table.sortable tbody tr:hover td { filter: brightness(.96); }
table.sortable tbody tr:last-child td { border-bottom: 0; }
table.sortable td:first-child, table.sortable th:first-child { text-align: left; background: #fff;
                                                              position: sticky; left: 0; z-index: 1; }
table.sortable td.best { font-weight: 700; color: var(--best); background: var(--best-bg); }
table.sortable tr.ref td { color: var(--ref); }
table.sortable td.yes { color: var(--best); font-weight: 600; }
table.sortable td.no { color: #c92a2a; font-weight: 600; }
table.sortable .first { border-left: 2px solid #fff; }
th.band.gd { background: var(--gd); } th.c-gd { background: var(--gd-tint); } td.c-gd { background: var(--gd-cell); }
th.band.pw { background: var(--pw); } th.c-pw { background: var(--pw-tint); } td.c-pw { background: var(--pw-cell); }
th.band.rf { background: var(--rf); } th.c-rf { background: var(--rf-tint); } td.c-rf { background: var(--rf-cell); }
th.band.run { background: var(--run); } th.c-run { background: var(--run-tint); } td.c-run { background: var(--run-cell); }
table.metrics { border-collapse: separate; border-spacing: 0; font-size: 12px; margin-top: 8px;
                border: 1px solid var(--line); border-radius: 8px; }
table.metrics th, table.metrics td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left;
                                     vertical-align: top; }
table.metrics th { background: var(--bg); }
table.metrics td:nth-child(4) { min-width: 320px; }
table.metrics tr.c-gd td:first-child { box-shadow: inset 4px 0 0 var(--gd); }
table.metrics tr.c-pw td:first-child { box-shadow: inset 4px 0 0 var(--pw); }
table.metrics tr.c-rf td:first-child { box-shadow: inset 4px 0 0 var(--rf); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: var(--muted); margin: 6px 0; }
.legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 2px;
                       margin-right: 5px; vertical-align: -1px; background: var(--k); }
select { font: inherit; padding: 3px 8px; border: 1px solid var(--line); border-radius: 6px; background: #fff; }
.scroll { overflow-x: auto; }
.error { height: 520px; display: flex; align-items: center; justify-content: center; text-align: center;
         font-size: 12px; color: #a40e26; background: #fff; padding: 8px; }
"""


# click a header of a sortable table: sort by that column (again: the other way); cells without a value last
SORT_SCRIPT = (
    "<script>"
    "document.addEventListener('click',e=>{const th=e.target.closest('table.sortable th[data-col]');if(!th)return;"
    "const t=th.closest('table'),b=t.tBodies[0],i=+th.dataset.col,asc=th.dataset.dir!=='asc';"
    "t.querySelectorAll('th[data-col]').forEach(h=>delete h.dataset.dir);th.dataset.dir=asc?'asc':'desc';"
    "const v=r=>{const x=r.cells[i].dataset.v;return x===undefined||x===''?null:(isNaN(+x)?x:+x);};"
    "[...b.rows].sort((r,s)=>{const a=v(r),c=v(s);if(a===null)return c===null?0:1;if(c===null)return -1;"
    "return(a<c?-1:a>c?1:0)*(asc?1:-1);}).forEach(r=>b.appendChild(r));});"
    "</script>"
)
COUNTS = {"crossings", "overlapping_pairs", "reference_nodes"}  # shown as whole numbers


def _number(value) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _fmt(column: str, x: float | None) -> str:
    if x is None:
        return "–"
    if column in COUNTS:
        return str(round(x))
    return f"{x:.3g}"


def _anchor(model: str, layout: str) -> str:
    return f"{model}--{layout}"


def _best(rows: list[dict], column: str, better: str | None) -> float | None:
    """The best value of a column among the layouts (not the reference), by its direction."""
    values = [x for r in rows if r["layout"] != REFERENCE and (x := _number(r.get(column))) is not None]
    if not better or not values:
        return None
    return min(values) if better == "lower" else max(values)


def _spans(values: list[str]) -> list[list]:
    """Runs of equal neighbouring values: [[value, length], ...]."""
    out: list[list] = []
    for v in values:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def _header(first: str, columns: list[Metric]) -> str:
    """Three header rows: where the metrics come from (gdMetriX, the pathway-map rules and checks, the comparison
    with the reference), their groups, then each column (sortable; its description, direction and source on hover)."""
    bands = _spans([(SOURCES[m.source][0] if m.source in SOURCES else "the runs", _band(m)) for m in columns])
    groups = _spans([(_band(m), m.group) for m in columns])
    band_row = "<th></th>" + "".join(
        f"<th class='group band {k} first' colspan={n}>{escape(b)}</th>" for (b, k), n in bands
    )
    group_row = "<th></th>" + "".join(f"<th class='group c-{k}' colspan={n}>{escape(g)}</th>" for (k, g), n in groups)
    classes = _cell_classes(columns)
    cells = [f"<th data-col=0>{escape(first)}</th>"]
    for i, (m, cls) in enumerate(zip(columns, classes), start=1):
        direction = {"lower": " (lower is better)", "higher": " (higher is better)"}.get(m.better, "")
        source = f". Source: {SOURCES[m.source][2]}" if m.source in SOURCES else ""
        cells.append(
            f'<th data-col={i} class="{cls}" title="{escape(m.description + direction + source)}">{escape(m.label)}</th>'
        )
    return f"<thead><tr>{band_row}</tr><tr>{group_row}</tr><tr>{''.join(cells)}</tr></thead>"


def _scores_table(model: str, mr: list[dict], repro: dict | None = None) -> str:
    """A model's scores: a row per layout (the reference first), a column per metric; best values bold. ``repro``:
    the reproducibility check's rows (``read_reproducibility``); its verdicts as a column where it has this model."""
    repro = {layout: row for (m, layout), row in (repro or {}).items() if m == model}
    columns = [m for m in METRICS if any(r.get(m.column) not in (None, "") for r in mr)]
    if repro:
        columns = _with_reproducible(columns)
    if not columns:
        return ""
    columns.append(Metric("seconds", "seconds", "run", "lower", "time to lay out"))
    best = {m.column: _best(mr, m.column, m.better) for m in columns if m is not REPRODUCIBLE}
    classes = dict(zip((m.column for m in columns), _cell_classes(columns)))
    body = []
    for r in sorted(mr, key=lambda r: (r["layout"] != REFERENCE, expected_rank(r["layout"]))):
        layout = r["layout"]
        name = "Reference" if layout == REFERENCE else layout
        failure = r.get("error") or r.get("metrics_error")
        title = f' title="{escape(failure)}"' if failure else ""
        cells = [
            (
                f'<td data-v="{-1 if layout == REFERENCE else expected_rank(layout)}"{title}>'
                f'<a href="#{escape(_anchor(model, layout))}">{escape(name)}</a>{" ✗" if failure else ""}</td>'
            )
        ]
        for column in (m.column for m in columns):
            if column == REPRODUCIBLE.column:
                cells.append(_verdict_cell(repro.get(layout), classes[column]))
                continue
            x = None if r.get("error") and column != "seconds" else _number(r.get(column))
            mark = " best" if x is not None and x == best[column] and layout != REFERENCE else ""
            cells.append(
                f'<td data-v="{"" if x is None else x}" class="{classes[column]}{mark}">{_fmt(column, x)}</td>'
            )
        body.append(f"<tr{' class=ref' if layout == REFERENCE else ''}>{''.join(cells)}</tr>")
    return (
        "<details class=scores><summary>Scores (click a column to sort; best values bold; hover a header for what it "
        "measures)</summary>" + _legend() + "<div class=scroll><table class=sortable>"
        f"{_header('layout', columns)}<tbody>{''.join(body)}</tbody></table></div></details>"
    )


def ranks(rows: list[dict]) -> dict[tuple[str, str], dict[str, float]]:
    """Per (model, metric with a direction): each layout's rank among that model's layouts with a value (1 = best;
    ties share the mean rank). References and failed runs are not ranked."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for model in dict.fromkeys(r["model"] for r in rows):
        mr = [r for r in rows if r["model"] == model and r["layout"] != REFERENCE and not r.get("error")]
        for column, better in ((m.column, m.better) for m in METRICS):
            if not better:
                continue
            values = {r["layout"]: x for r in mr if (x := _number(r.get(column))) is not None}
            if not values:
                continue
            ordered = sorted(values.values(), reverse=better == "higher")
            first: dict[float, int] = {}
            for i, x in enumerate(ordered, start=1):
                first.setdefault(x, i)
            count = {x: ordered.count(x) for x in first}
            out[(model, column)] = {name: first[x] + (count[x] - 1) / 2 for name, x in values.items()}
    return out


def _metrics_table() -> str:
    """Every metric: what it measures, where it comes from, how it is calculated, and which way is better."""
    body = []
    for m in _with_reproducible(METRICS):
        better = {"lower": "lower", "higher": "higher"}.get(m.better, "– (not ranked)")
        body.append(
            f"<tr class=c-{_band(m)}><td><b>{escape(m.label)}</b> <span class=t>({escape(m.group)}; <code>{escape(m.column)}</code>)"
            f'</span></td><td title="{escape(SOURCES[m.source][2])}">{escape(SOURCES[m.source][1])}</td><td>{escape(m.description)}</td>'
            f"<td>{escape(m.how)}</td><td>{better}</td></tr>"
        )
    return (
        "<h2 id=metrics>The metrics</h2><p class=meta>Every metric is taken on the drawing as shown, in the tool's own "
        "coordinates: clones are nodes, nodes a tool leaves out are absent, routed edges are the polylines drawn. "
        "General graph-drawing metrics come from <a href='https://github.com/livus/gdMetriX' style='margin:0'>gdMetriX</a>; the "
        "pathway-map metrics follow the layout rules of BioHackathon Europe 2026 project 22 (Open Pathway Maps), as its "
        "<a href='https://github.com/elixir2026-project22/frontend-tool-pathway-scorer' style='margin:0'>pathway layout "
        "scorer</a> and automatic_layout_following_our_rules define them, computed by this benchmark (raw values, no "
        "thresholds), next to a few checks of this benchmark's own; the comparison with the reference is this "
        "benchmark's.</p>"
        "<div class=scroll><table class=metrics><thead><tr><th>metric</th><th>source</th><th>what it measures</th>"
        f"<th>how it is calculated</th><th>better</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def write_summary(out: Path, rows: list[dict], sets: dict[str, list[str]]) -> Path:
    """Write ``out/summary.html``: per layout, its median rank per metric over the models (all, or one set's), how
    many models it laid out, its failures and median time. No combined score."""
    ranked = ranks(rows)
    repro = read_reproducibility(out)
    columns = [m for m in METRICS if m.better]
    if repro:
        columns = _with_reproducible(columns)
    layouts = sorted({r["layout"] for r in rows if r["layout"] != REFERENCE}, key=expected_rank)
    tables = []
    for i, (set_name, models) in enumerate([("All sets", [m for ms in sets.values() for m in ms]), *sets.items()]):
        chosen = set(models)
        classes = dict(zip((m.column for m in columns), _cell_classes(columns)))
        best_rank = {}  # per column, the lowest median rank among the layouts
        for column in (m.column for m in columns if m is not REPRODUCIBLE):
            medians = []
            for layout in layouts:
                values = [ranked[(m, column)][layout] for m in models if layout in ranked.get((m, column), {})]
                if values:
                    medians.append(statistics.median(values))
            if medians:
                best_rank[column] = min(medians)
        body = []
        for layout in layouts:
            runs = [r for r in rows if r["layout"] == layout and r["model"] in chosen]
            if not runs:
                continue
            ok = [r for r in runs if not r.get("error")]
            seconds = [x for r in ok if (x := _number(r.get("seconds"))) is not None]
            # the versions its runs were made with (several: the models were laid out at different times)
            made_with = " / ".join(sorted({r["tool_version"] for r in runs if r.get("tool_version")}))
            cells = [
                (
                    f'<td data-v="{expected_rank(layout)}">{escape(layout)}'
                    f"{' <span class=t>(' + escape(GROUP[layout]) + ')</span>' if layout in GROUP else ''}"
                    f"{'<br><span class=t>' + escape(made_with) + '</span>' if made_with else ''}</td>"
                ),
                f'<td data-v="{len(ok)}" class="c-run first">{len(ok)} / {len(runs)}</td>',
                (
                    f'<td data-v="{statistics.median(seconds) if seconds else ""}" class=c-run>'
                    f"{_fmt('seconds', statistics.median(seconds) if seconds else None)}</td>"
                ),
            ]
            for column in (m.column for m in columns):
                if column == REPRODUCIBLE.column:
                    seen = [
                        ok for m in models if (row := repro.get((m, layout))) and (ok := _reproduced(row)) is not None
                    ]
                    shown = f"{sum(seen)} / {len(seen)}" if seen else "–"
                    share = sum(seen) / len(seen) if seen else ""
                    mark = " yes" if seen and all(seen) else (" no" if seen else "")
                    cells.append(f'<td data-v="{share}" class="{classes[column]}{mark}">{shown}</td>')
                    continue
                values = [ranked[(m, column)][layout] for m in models if layout in ranked.get((m, column), {})]
                median = statistics.median(values) if values else None
                shown = f"{median:.3g} <span class=t>({len(values)})</span>" if median is not None else "–"
                mark = " best" if median is not None and median == best_rank.get(column) else ""
                cells.append(
                    f'<td data-v="{"" if median is None else median}" class="{classes[column]}{mark}">{shown}</td>'
                )
            body.append(f"<tr>{''.join(cells)}</tr>")
        extra = [
            Metric("laid_out", "laid out", "runs", None, "models laid out / attempted (failures: errors, timeouts)"),
            Metric("seconds", "median s", "runs", "lower", "median time to lay out"),
        ]
        hidden = "" if i == 0 else " hidden"
        tables.append(
            f"<div class=scroll data-set='{escape(set_name)}'{hidden}><table class=sortable>"
            f"{_header('layout', extra + columns)}<tbody>{''.join(body)}</tbody></table></div>"
        )
    options = "".join(f"<option>{escape(name)}</option>" for name in ["All sets", *sets])
    parts = [
        "<!doctype html><html lang=en><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width, initial-scale=1'>",
        f"<title>Layout benchmark: summary</title><style>{CSS}</style>",
        (
            "<header class=top><a class=brand href='index.html'>Layout benchmark</a><a href='index.html'>Layouts</a>"
            "<a href='#'>Summary of scores</a><a href='#metrics'>The metrics</a></header>"
        ),
        "<main><div class=hero><h1>Summary of scores</h1>",
        (
            "<p class=meta>Per layout and metric: its <b>median rank</b> over the models (1 = the best of that model's "
            "layouts; ties share the mean rank), with the number of models ranked in brackets. A layout is ranked on a "
            "model only where it has a value: not where it failed, nor where a metric doesn't apply (overlaps without "
            "node sizes, compartments without boxes, similarity without a reference). Every metric is taken on the "
            "drawing as shown, in the tool's own coordinates (see the README). There is no combined score yet: the "
            "weights of the metrics are still to be decided. Click a column to sort; hover a header for what it "
            "measures. The header's top row says where each metric comes from; "
            "<a href='#metrics' style='margin:0'>the metrics</a> below says what each measures and how. The best "
            "median rank per column is highlighted.</p></div>"
        ),
        f"<p class=meta>Models: <select id=set>{options}</select></p>",
        _legend(),
        *tables,
        _metrics_table(),
        "</main>",
        (
            "<script>document.getElementById('set').addEventListener('change',e=>{"
            "document.querySelectorAll('[data-set]').forEach(d=>d.hidden=d.dataset.set!==e.target.value);});</script>"
        ),
        SORT_SCRIPT,
    ]
    path = out / "summary.html"
    path.write_text("\n".join(parts))
    return path


def model_links(row: dict, local: bool = True) -> dict[str, str]:
    """Links of a model (from the manifest: its source, reference, page), and its local file when ``local``."""
    links = json.loads(row["links"]) if row.get("links") else {}
    if local and row.get("source"):
        links["local file"] = Path(row["source"]).resolve().as_uri()
    return links


def model_set(row: dict) -> str:
    """A model's set: from the manifest (the row's ``set``), else the folder of its file."""
    if row.get("set"):
        return row["set"]
    return Path(row["source"]).parent.name if row.get("source") else "Other"


def _set_order(out: Path, names: list[str]) -> tuple[list[str], dict[str, str]]:
    """The sets in the manifest's order (``out/sets.json``, written by a manifest run), then any others in the order
    they first appear; and their descriptions."""
    order, descriptions = [], {}
    if (out / "sets.json").exists():
        for entry in json.loads((out / "sets.json").read_text()):
            order.append(entry["name"])
            if entry.get("description"):
                descriptions[entry["name"]] = entry["description"]
    return [n for n in order if n in names] + [n for n in names if n not in order], descriptions


def _figure(model: str, r: dict, out: Path) -> tuple[str, str]:
    """(picture or error, caption) of one run."""
    svg = f"{model}/{r['layout']}.svg"
    if r.get("error") or not (out / svg).exists():
        body = f'<div class="error">{escape(r.get("error") or "no picture")}</div>'
    else:
        body = f'<a href="{escape(svg)}" target="_blank"><img src="{escape(svg)}" loading="lazy" alt=""></a>'
    note = f" · {escape(r['note'])}" if r.get("note") else ""
    if r.get("tool_version"):
        note += f" · {escape(r['tool_version'])}"
    links = " ".join(
        f'<a href="{escape(f)}" target="_blank">{label}</a>'
        for f, label in ((svg, "SVG"), (f"{model}/{r['layout']}.json", "positions (JSON)"))
        if (out / f).exists()
    )
    group = f" <span class=t>({escape(GROUP[r['layout']])})</span>" if r["layout"] in GROUP else ""
    name = escape(r["layout"])
    if r["layout"] in LINKS:  # the layout's documentation
        name = f'<a href="{escape(LINKS[r["layout"]])}" target="_blank" rel="noopener">{name}</a>'
    return body, (f"<b>{name}</b>{group} <span class=t>{r['seconds']} s{note}</span>{'<br>' + links if links else ''}")


def write_report(out: Path, rows: list[dict], local: bool = True) -> Path:
    """Write ``out/index.html``. ``local``: with links to the local files (False for a published copy)."""
    parts = [
        "<!doctype html><html lang=en><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width, initial-scale=1'>",
        f"<title>Layout benchmark</title><style>{CSS}</style>",
    ]
    hero = [
        "<div class=hero><h1>Layout benchmark</h1>",
        (
            "<p class=meta>Per model: the reference layout (brown box, where there is one), then every computed "
            "layout, from the expected most promising to the least (by group, before any scoring); scroll sideways. "
            "Every picture is drawn the same way (SBGN shapes and arcs, fixed node sizes). Positions are each "
            "tool's own, drawn at a common scale (nearest neighbours 1.5 species widths apart); the layouts "
            "themselves are not changed. Species are coloured by compartment (models with more than one; legend in each "
            "picture). Compartment boxes are drawn only where the reference or the tool has them: the references, "
            "SBMLNetwork, and cytoscape.js's compound layouts (with compartments: reactions are placed in the "
            "compartment of their reactants and products, transports between). The Escher-based tools have none. "
            "Click a picture to open it full size. Under each model, its scores (a table; on the drawing as shown, "
            "in each tool's own coordinates); the summary page ranks the layouts over all models.</p></div>"
        ),
    ]
    models = list(dict.fromkeys(r["model"] for r in rows))
    repro = read_reproducibility(out)
    has_ref = {m: any(r["layout"] == REFERENCE for r in rows if r["model"] == m) for m in models}
    first_row = {}
    for r in rows:
        first_row.setdefault(r["model"], r)
    grouped: dict[str, list[str]] = {}
    for m in models:
        grouped.setdefault(model_set(first_row[m]), []).append(m)
    order, descriptions = _set_order(out, list(grouped))
    by_set = {name: grouped[name] for name in order}
    nav = ["<header class=top><a class=brand href='#'>Layout benchmark</a><nav>"]
    for set_name, ms in by_set.items():
        anchor = "set-" + "".join(c if c.isalnum() else "-" for c in set_name.lower())
        items = "".join(
            f'<li><a href="#{escape(m)}">{escape(m)}</a>{"" if has_ref[m] else " <span class=t>(no reference)</span>"}</li>'
            for m in ms
        )
        nav.append(
            f"<details><summary>{escape(set_name)} ({len(ms)})</summary>"
            f'<ul><li><a href="#{anchor}"><b>Jump to the start of {escape(set_name)}</b></a></li>{items}</ul></details>'
        )
    if any(_number(r.get(m.column)) is not None for r in rows for m in METRICS):
        nav.append("<a href='summary.html'><b>Summary of scores</b></a>")
    nav.append("</nav></header>")
    # a menu closes on a click outside it, on a model chosen in it, and on Escape (one menu open at a time)
    nav.append(
        "<script>"
        "function closeMenus(keep){document.querySelectorAll('nav details[open]')"
        ".forEach(d=>{if(d!==keep)d.open=false;});}"
        "document.addEventListener('click',e=>{const d=e.target.closest('nav details');"
        "closeMenus(d&&!e.target.closest('a')?d:null);});"
        "document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenus(null);});"
        "</script>"
    )
    parts.extend(nav)
    parts.append("<main>")
    parts.extend(hero)
    for set_name, ms in by_set.items():
        anchor = "set-" + "".join(c if c.isalnum() else "-" for c in set_name.lower())
        n_ref = sum(has_ref[m] for m in ms)
        parts.append(
            f"<h2 class=set id='{anchor}'>{escape(set_name)}"
            f"<span class=badge>{len(ms)} models, {n_ref} with a reference layout</span></h2>"
        )
        if set_name in descriptions:
            parts.append(f"<p class=meta>{escape(descriptions[set_name])}</p>")
        for model in ms:
            _model_section(parts, model, rows, out, local, repro)
    parts.append("</main>")
    parts.append(SORT_SCRIPT)
    write_summary(out, rows, by_set)
    path = out / "index.html"
    path.write_text("\n".join(parts))
    return path


def _model_section(parts: list, model: str, rows: list[dict], out: Path, local: bool, repro: dict):
    """One model: header with its sizes and source links, the reference (or a placeholder), the layouts."""
    mr = [r for r in rows if r["model"] == model]
    links = model_links(mr[0], local)
    credit, licence = mr[0].get("credit"), mr[0].get("licence")
    link_html = " ".join(
        f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}</a>' for label, url in links.items()
    )
    if credit:
        credit_html = (
            f'<a href="{escape(licence)}" target="_blank" rel="noopener">{escape(credit)}</a>'
            if licence
            else escape(credit)
        )
        link_html += f" · {credit_html}"
    badge = "" if any(r["layout"] == REFERENCE for r in mr) else "<span class=badge>no reference layout</span>"
    parts.append(f"<section id='{escape(model)}'><h3>{escape(model)}{badge}</h3>")
    parts.append(
        f"<div class=meta>{mr[0]['species']} species, {mr[0]['reactions']} reactions, {mr[0]['edges']} edges"
        f" · {link_html}</div>"
    )
    ref = next((r for r in mr if r["layout"] == REFERENCE), None)
    parts.append("<div class=row>")
    if ref:
        body, caption = _figure(model, ref, out)
        # where the reference layout comes from: its file (on GitHub when known)
        ref_file = Path(mr[0]["reference_file"]) if mr[0].get("reference_file") else None
        ref_url = links.get("reference") or (ref_file.resolve().as_uri() if ref_file and local else None)
        name = escape(ref_file.name) if ref_file else ""
        if name and mr[0].get("reference_kind") == "sbml-layout":  # the model file itself, its SBML Layout
            name += " (its SBML Layout)"
            ref_url = links.get("model") or ref_url
        origin = f': <a href="{escape(ref_url)}" target="_blank">{name}</a>' if ref_url and name else ""
        caption = caption.replace(f"<b>{REFERENCE}</b>", f"<b>Reference</b>{origin}", 1)
        parts.append(
            f"<figure class=ref id='{escape(_anchor(model, REFERENCE))}'>{body}<figcaption>{caption}</figcaption></figure>"
        )
    else:
        parts.append("<figure class='ref none'>No reference layout</figure>")
    parts.append("<div class=strip>")
    for r in sorted(mr, key=lambda r: expected_rank(r["layout"])):
        if r["layout"] == REFERENCE:
            continue
        body, caption = _figure(model, r, out)
        parts.append(
            f"<figure id='{escape(_anchor(model, r['layout']))}'>{body}<figcaption>{caption}</figcaption></figure>"
        )
    parts.append("</div></div>")
    parts.append(_scores_table(model, mr, repro))
    parts.append("</section>")


__all__ = ["model_links", "ranks", "read_reproducibility", "write_report", "write_summary"]
