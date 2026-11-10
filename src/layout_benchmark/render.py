"""One SVG renderer for every layout, so the pictures compare fairly.

A species drawn more than once (a clone) has SBGN's clone marker, its lower part filled dark. Arcs are drawn with
SBGN Process Description arrowheads: consumption (no head), production (filled arrow),
catalysis (open circle), inhibition (bar), stimulation (open arrow), necessary stimulation (bar and open arrow),
modulation (open diamond). Lines end at the node's boundary, so the heads are visible.
"""

from __future__ import annotations

from html import escape

from .drawing import Drawing
from .graph import (
    CATALYSIS,
    COMPLEX,
    CONSUMPTION,
    INHIBITION,
    MACROMOLECULE,
    MODULATION,
    NECESSARY_STIMULATION,
    NUCLEIC_ACID_FEATURE,
    PERTURBING_AGENT,
    PHENOTYPE,
    PRODUCTION,
    REACTION,
    SIMPLE_CHEMICAL,
    STIMULATION,
)

WIDTH = 900  # px, of the picture
LINE = "#222"

# marker id per arc class; markers are drawn in user space (px), independent of the stroke width
MARKERS = {
    PRODUCTION: (
        "production",
        '<path d="M0,0 L10,5 L0,10 z" fill="{c}"/>',
        10,
        10,
        10,
        5,
    ),
    STIMULATION: (
        "stimulation",
        '<path d="M1,1 L10,5 L1,9 z" fill="#fff" stroke="{c}" stroke-width="1.2"/>',
        11,
        10,
        10,
        5,
    ),
    CATALYSIS: (
        "catalysis",
        '<circle cx="5" cy="5" r="4" fill="#fff" stroke="{c}" stroke-width="1.2"/>',
        10,
        10,
        9,
        5,
    ),
    INHIBITION: (
        "inhibition",
        '<path d="M1,0 L1,10" stroke="{c}" stroke-width="2"/>',
        4,
        10,
        1,
        5,
    ),
    NECESSARY_STIMULATION: (
        "necessary-stimulation",
        (
            '<path d="M1,0 L1,10" stroke="{c}" stroke-width="1.6"/>'
            '<path d="M4,1 L13,5 L4,9 z" fill="#fff" stroke="{c}" stroke-width="1.2"/>'
        ),
        14,
        10,
        13,
        5,
    ),
    MODULATION: (
        "modulation",
        '<path d="M1,5 L6,1 L11,5 L6,9 z" fill="#fff" stroke="{c}" stroke-width="1.2"/>',
        12,
        10,
        11,
        5,
    ),
}


def _defs() -> str:
    out = ["<defs>"]
    for mid, shape, w, h, rx, ry in MARKERS.values():
        out.append(
            f'<marker id="{mid}" viewBox="0 0 {w} {h}" refX="{rx}" refY="{ry}" markerWidth="{w * 0.8:.1f}" '
            f'markerHeight="{h * 0.8:.1f}" markerUnits="userSpaceOnUse" orient="auto">{shape.format(c=LINE)}</marker>'
        )
    out.append("</defs>")
    return "".join(out)


def _clip(x1, y1, x2, y2, hw, hh):
    """The point where the segment from the centre (x2, y2) of a box (half-sizes hw, hh) towards (x1, y1) leaves
    the box."""
    dx, dy = x1 - x2, y1 - y2
    if dx == 0 and dy == 0:
        return x2, y2
    t = min(hw / abs(dx) if dx else float("inf"), hh / abs(dy) if dy else float("inf"))
    t = min(t, 1.0)
    return x2 + dx * t, y2 + dy * t


STROKE = 'fill="#fff" stroke="#222" stroke-width="1"'
# pale fills, one per compartment (largest compartment first); boxes use the same colour, lighter
PALETTE = ["#cfe2f3", "#fce5cd", "#d9ead3", "#f4cccc", "#d9d2e9", "#fff2cc", "#d0e0e3", "#ead1dc"]
LEGEND_ROW = 16  # px


def compartment_colours(pathway) -> dict[str, str]:
    """A colour per compartment of a model with more than one (largest first), else none."""
    if pathway is None:
        return {}
    sizes: dict[str, int] = {}
    for _, d in pathway.graph.nodes(data=True):
        if d["kind"] != REACTION and d.get("compartment"):
            sizes[d["compartment"]] = sizes.get(d["compartment"], 0) + 1
    if len(sizes) < 2:
        return {}
    order = sorted(sizes, key=lambda c: (-sizes[c], c))
    return {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(order)}


def _shape(sbgn: str | None, x: float, y: float, hw: float, hh: float, label: str, fill: str = "#fff") -> str:
    """An SBGN Process Description glyph centred on (x, y), half-sizes hw, hh."""
    t = f"<title>{label}</title>"
    if fill != "#fff":
        return _shape(sbgn, x, y, hw, hh, label).replace('fill="#fff"', f'fill="{fill}"', 1)
    if sbgn == "process":
        return f'<rect x="{x - hw:.1f}" y="{y - hh:.1f}" width="{2 * hw:.1f}" height="{2 * hh:.1f}" {STROKE}>{t}</rect>'
    if sbgn == SIMPLE_CHEMICAL:
        r = min(hh, hw)
        return (
            f'<rect x="{x - hw:.1f}" y="{y - hh:.1f}" width="{2 * hw:.1f}" height="{2 * hh:.1f}" rx="{r:.1f}" '
            f"{STROKE}>{t}</rect>"
        )
    if sbgn == MACROMOLECULE:
        r = min(hw, hh) * 0.35
        return (
            f'<rect x="{x - hw:.1f}" y="{y - hh:.1f}" width="{2 * hw:.1f}" height="{2 * hh:.1f}" rx="{r:.1f}" '
            f"{STROKE}>{t}</rect>"
        )
    if sbgn == NUCLEIC_ACID_FEATURE:  # rounded bottom corners
        r = min(hw, hh) * 0.45
        d = (
            f"M{x - hw:.1f},{y - hh:.1f} H{x + hw:.1f} V{y + hh - r:.1f} Q{x + hw:.1f},{y + hh:.1f} "
            f"{x + hw - r:.1f},{y + hh:.1f} H{x - hw + r:.1f} Q{x - hw:.1f},{y + hh:.1f} {x - hw:.1f},{y + hh - r:.1f} Z"
        )
        return f'<path d="{d}" {STROKE}>{t}</path>'
    if sbgn == COMPLEX:  # cut corners
        c = min(hw, hh) * 0.4
        pts = [
            (x - hw + c, y - hh),
            (x + hw - c, y - hh),
            (x + hw, y - hh + c),
            (x + hw, y + hh - c),
            (x + hw - c, y + hh),
            (x - hw + c, y + hh),
            (x - hw, y + hh - c),
            (x - hw, y - hh + c),
        ]
        return f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" {STROKE}>{t}</polygon>'
    if sbgn == PHENOTYPE:  # hexagon, pointed left and right
        c = hh * 0.8
        pts = [
            (x - hw, y),
            (x - hw + c, y - hh),
            (x + hw - c, y - hh),
            (x + hw, y),
            (x + hw - c, y + hh),
            (x - hw + c, y + hh),
        ]
        return f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" {STROKE}>{t}</polygon>'
    if sbgn == PERTURBING_AGENT:  # hexagon with the left and right sides pointing in
        c = hh * 0.8
        pts = [(x - hw + c, y), (x - hw, y - hh), (x + hw, y - hh), (x + hw - c, y), (x + hw, y + hh), (x - hw, y + hh)]
        return f'<polygon points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" {STROKE}>{t}</polygon>'
    # unspecified entity: an ellipse
    return f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{hw:.1f}" ry="{hh:.1f}" {STROKE}>{t}</ellipse>'


def _fit(label: str, width: float, font_size: float) -> str:
    """The label, cut with an ellipsis to fit a width (about 0.55 em per character)."""
    n = max(int(width / (0.55 * font_size)), 1)
    return label if len(label) <= n else label[: max(n - 1, 1)] + "…"


def to_svg(drawing: Drawing, title: str = "", pathway=None) -> str:
    """The picture of a drawing. With the ``pathway``: species are coloured by compartment (models with more than
    one), with a legend; compartment boxes are drawn where the drawing has them (the tool's or reference's own)."""
    g, pos = drawing.graph, drawing.pos
    placed = [n for n in g if n in pos]
    if not placed:
        return '<svg xmlns="http://www.w3.org/2000/svg"/>'
    colours = compartment_colours(pathway)
    names = pathway.compartments if pathway is not None else {}

    def compartment(n):
        of = g.nodes[n]["of"]
        if pathway is not None and of in pathway.graph:
            return pathway.graph.nodes[of].get("compartment")
        return g.nodes[n].get("compartment")

    pad = 40
    route_points = [p for pts in drawing.routes.values() for p in pts]
    xs = [pos[n][0] for n in placed] + [p[0] for p in route_points]
    ys = [pos[n][1] for n in placed] + [p[1] for p in route_points]
    for c in drawing.compartments.values():
        xs += [c["box"][0], c["box"][2]]
        ys += [c["box"][1], c["box"][3]]
    minx, maxx, miny, maxy = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    w, h = maxx - minx, maxy - miny
    scale = WIDTH / w if w else 1
    top = (len(colours) * LEGEND_ROW + 10) if colours else 0  # room for the legend above the drawing
    height = max(h * scale, 50) + top

    def q(point):  # y flipped: layouts have y up
        return (point[0] - minx) * scale, (maxy - point[1]) * scale + top

    def p(n):
        return q(pos[n])

    def half(n):
        d = g.nodes[n]
        return d["width"] * scale / 2, d["height"] * scale / 2

    out = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height:.0f}" '
            f'viewBox="0 0 {WIDTH} {height:.0f}" font-family="Helvetica, Arial, sans-serif">'
        ),
        f"<title>{escape(title)}</title>",
        _defs(),
        '<rect width="100%" height="100%" fill="#fff"/>',
    ]
    for i, (cid, c) in enumerate(colours.items()):  # the legend
        y = 6 + i * LEGEND_ROW
        out.append(
            f'<rect x="8" y="{y}" width="14" height="11" rx="2" fill="{c}" stroke="#666" stroke-width="0.6"/>'
            f'<text x="28" y="{y + 9.5}" font-size="11" fill="#333">{escape(names.get(cid, cid))}</text>'
        )
    for cid, c in drawing.compartments.items():  # the compartment boxes the tool or reference drew
        (x0, y1), (x1, y0) = q(c["box"][:2]), q(c["box"][2:])
        fill = colours.get(cid, "#f3f3f3")
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" rx="8" fill="{fill}" '
            f'fill-opacity="0.35" stroke="#777" stroke-width="1.6"><title>{escape(c.get("label") or cid)}</title></rect>'
            f'<text x="{x0 + 6:.1f}" y="{y0 + 13:.1f}" font-size="11" fill="#555">{escape(c.get("label") or cid)}</text>'
        )
    for u, v, d in g.edges(data=True):
        if u not in pos or v not in pos or u == v:
            continue
        inner = [q(pt) for pt in drawing.routes.get((u, v), [])]
        pts = [p(u), *inner, p(v)]
        # clip the ends at the node boxes, towards the neighbouring route point
        pts[0] = _clip(*pts[1], *pts[0], *half(u))
        pts[-1] = _clip(*pts[-2], *pts[-1], *half(v))
        arc = d.get("arc", CONSUMPTION)
        marker = f' marker-end="url(#{MARKERS[arc][0]})"' if arc in MARKERS else ""
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        out.append(
            f'<polyline points="{points}" fill="none" stroke="{LINE}" stroke-width="0.9"{marker}>'
            f"<title>{escape(arc)}</title></polyline>"
        )
    # SBGN clone marker: the lower part of every glyph that the drawing has more than once
    copies: dict[str, int] = {}
    for n in placed:
        copies[g.nodes[n]["of"]] = copies.get(g.nodes[n]["of"], 0) + 1
    for i, n in enumerate(placed):
        d = g.nodes[n]
        x, y = p(n)
        hw, hh = half(n)
        label = escape(d["label"])
        sbgn = d.get("sbgn") if d["kind"] != REACTION else "process"
        fill = colours.get(compartment(n), "#fff") if d["kind"] != REACTION else "#fff"
        out.append(_shape(sbgn, x, y, hw, hh, label, fill))
        if d["kind"] != REACTION and copies[d["of"]] > 1:
            outline = _shape(sbgn, x, y, hw, hh, "")
            out.append(
                f'<clipPath id="clone{i}">{outline}</clipPath>'
                f'<rect x="{x - hw:.1f}" y="{y + hh * 0.35:.1f}" width="{2 * hw:.1f}" height="{hh * 0.65:.1f}" '
                f'fill="#555" clip-path="url(#clone{i})"/>' + outline.replace('fill="#fff"', 'fill="none"', 1)
            )
        if d["kind"] != REACTION and hh >= 3.5:
            size = hh * 0.8  # font size: fixed relative to the node, which never grows for its label
            out.append(
                f'<text x="{x:.1f}" y="{y + size * 0.35:.1f}" font-size="{size:.1f}" text-anchor="middle">'
                f"{escape(_fit(d['label'], 2 * hw * 0.9, size))}<title>{label}</title></text>"
            )
    out.append("</svg>")
    return "\n".join(out)
