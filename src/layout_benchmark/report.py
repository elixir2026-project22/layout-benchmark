"""The HTML report: per model, the reference layout in its own box and the computed layouts in a scrolling strip
next to it, with links to the source files."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .layouts import GROUP, LINKS, expected_rank

REFERENCE = "reference"

CSS = """
:root { --ref: #b5651d; --line: #d0d7de; --muted: #57606a; --bg: #f6f8fa; }
body { font-family: system-ui, sans-serif; margin: 16px; color: #1f2328; background: #fff; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin: 0 0 4px; }
section { border-top: 1px solid var(--line); padding: 14px 0 18px; scroll-margin-top: 64px; }
nav { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid var(--line);
      padding: 8px 0; font-size: 13px; display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: center; }
nav details { position: relative; }
nav summary { cursor: pointer; font-weight: 600; }
nav details ul { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 6px;
                 padding: 8px 14px; margin: 4px 0 0; list-style: none; max-height: 60vh; overflow-y: auto;
                 white-space: nowrap; box-shadow: 0 4px 12px rgba(0,0,0,.08); }
nav details li { margin: 2px 0; }
h2.set { font-size: 18px; margin: 28px 0 4px; padding-top: 8px; border-top: 3px solid #1f2328;
         scroll-margin-top: 64px; }
.badge { font-size: 11px; font-weight: normal; color: var(--muted); border: 1px solid var(--line);
         border-radius: 10px; padding: 1px 7px; margin-left: 6px; vertical-align: middle; }
h3 { font-size: 15px; margin: 0 0 4px; }
.meta { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.meta a { margin-right: 12px; }
.row { display: flex; gap: 14px; align-items: flex-start; padding: 3px; }
.ref { box-shadow: 0 0 0 3px var(--ref); background: #fffaf3; }  /* an outline: no change to the size */
.ref figcaption b { color: var(--ref); }
.ref.none { box-shadow: none; border-style: dashed; color: var(--muted); font-size: 13px; display: flex; align-items: center; justify-content: center; height: 560px; }
.strip { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 8px; scroll-snap-type: x proximity; }
figure { flex: 0 0 600px; box-sizing: border-box; margin: 0; border: 1px solid var(--line); border-radius: 6px; padding: 6px;
         background: var(--bg); scroll-snap-align: start; }
figure img { width: 100%; height: 520px; object-fit: contain; background: #fff; display: block; }
figcaption { font-size: 12px; margin-top: 4px; }
figcaption .t { color: var(--muted); }
.error { height: 520px; display: flex; align-items: center; justify-content: center; text-align: center;
         font-size: 12px; color: #a40e26; background: #fff; padding: 8px; box-sizing: border-box; }
"""


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
        "<h1>Layout benchmark</h1>",
        (
            "<p class=meta>Per model: the reference layout (brown box, where there is one), then every computed "
            "layout, from the expected most promising to the least (by group, before any scoring); scroll sideways. "
            "Every picture is drawn the same way (SBGN shapes and arcs, fixed node sizes). Positions are each "
            "tool's own, drawn at a common scale (nearest neighbours 1.5 species widths apart); the layouts "
            "themselves are not changed. Species are coloured by compartment (models with more than one; legend in each "
            "picture). Compartment boxes are drawn only where the reference or the tool has them: the references, "
            "and cytoscape.js's compound layouts (with compartments: reactions are placed in the compartment of "
            "their reactants and products, transports between). MetaCarto and sbml2escher have none. "
            "Click a picture to open it full size.</p>"
        ),
    ]
    models = list(dict.fromkeys(r["model"] for r in rows))
    has_ref = {m: any(r["layout"] == REFERENCE for r in rows if r["model"] == m) for m in models}
    first_row = {}
    for r in rows:
        first_row.setdefault(r["model"], r)
    grouped: dict[str, list[str]] = {}
    for m in models:
        grouped.setdefault(model_set(first_row[m]), []).append(m)
    order, descriptions = _set_order(out, list(grouped))
    by_set = {name: grouped[name] for name in order}
    nav = ["<nav>"]
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
    nav.append("</nav>")
    parts.extend(nav)
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
            _model_section(parts, model, rows, out, local)
    path = out / "index.html"
    path.write_text("\n".join(parts))
    return path


def _model_section(parts: list, model: str, rows: list[dict], out: Path, local: bool):
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
        parts.append(f"<figure class=ref>{body}<figcaption>{caption}</figcaption></figure>")
    else:
        parts.append("<figure class='ref none'>No reference layout</figure>")
    parts.append("<div class=strip>")
    for r in sorted(mr, key=lambda r: expected_rank(r["layout"])):
        if r["layout"] == REFERENCE:
            continue
        body, caption = _figure(model, r, out)
        parts.append(f"<figure>{body}<figcaption>{caption}</figcaption></figure>")
    parts.append("</div></div></section>")


__all__ = ["model_links", "write_report"]
