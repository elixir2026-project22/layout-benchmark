"""The project's layout rules, calculated on a drawing (raw values: no thresholds, no scores).

BioHackathon Europe 2026 project 22 has two implementations of its layout rules, now aligned on one rule set: the
browser scorer (``build/core.js`` in elixir2026-project22/frontend-tool-pathway-scorer) and ``svg_layout_metrics.py`` in
automatic_layout_following_our_rules. This module computes the same rules on our ``Drawing`` (the drawing as shown, in
the tool's own coordinates, at the tool's own node sizes), written from their definitions.
Where the two define a rule differently, we choose (see ``metrics.METRICS`` for each choice):

1. the shared definition, where they agree;
2. else the one that measures the layout itself, not the file format, not what else a tool draws (compartment or
   label boxes), not a computing limit;
3. else the scorer's (core.js).

Not here: "reproducible" (the ``reproducibility`` command) and "labels at fixed positions" (our renderer places
the labels, the same way for every layout). "No overlapping nodes" is ``metrics.overlaps``.
"""

from __future__ import annotations

import itertools
import math
import re

import networkx as nx
import numpy as np
from shapely import STRtree, box
from shapely.geometry import LineString, Point

from .drawing import Drawing
from .graph import (
    CATALYSIS,
    CONSUMPTION,
    INHIBITION,
    MODULATION,
    NECESSARY_STIMULATION,
    PRODUCTION,
    REACTION,
    SPECIES,
    STIMULATION,
)

# the scorer's cofactor names (core.js CURRENCY_DEFAULT; svg_layout_metrics.py uses the same list)
COFACTORS = frozenset(
    [
        "atp",
        "adp",
        "amp",
        "gtp",
        "gdp",
        "gmp",
        "utp",
        "udp",
        "ump",
        "ctp",
        "cdp",
        "nad",
        "nad+",
        "nadh",
        "nadp",
        "nadp+",
        "nadph",
        "fad",
        "fadh2",
        "fmn",
        "h2o",
        "water",
        "co2",
        "o2",
        "h+",
        "h",
        "pi",
        "ppi",
        "phosphate",
        "pyrophosphate",
        "diphosphate",
        "coa",
        "coa-sh",
        "coash",
        "nh3",
        "nh4+",
        "ammonia",
        "hco3-",
        "bicarbonate",
        "h2o2",
        "e-",
        "camp",
        "sam",
        "sah",
        "acceptor",
        "glutathione",
        "nh4",
    ]
) | {"reduced acceptor"}
MODIFIER_ARCS = {CATALYSIS, MODULATION, STIMULATION, INHIBITION, NECESSARY_STIMULATION}
# cycles: simple cycles of 3 to CYCLE_MAX_LEN metabolites, at most CYCLE_CAP of them (as both implementations)
CYCLE_MAX_LEN, CYCLE_CAP = 16, 20000
# a route point is a bend where the line turns by more than this (degrees; svg_layout_metrics.py)
BEND_DEGREES = 25.0
# "a line through a node": the node's shape shrunk by this share of its size first (0: the exact shape). Both
# implementations shrink by 2 px, so that a line grazing an edge does not count; px mean nothing in a tool's units
THROUGH_SHRINK = 0.0

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁺⁻", "0123456789+-")


def _norm(s: str | None) -> str:
    """core.js normName: subscripts as digits, lower case, single spaces."""
    return re.sub(r"\s+", " ", (s or "").translate(_SUB).strip().lower())


def is_cofactor(data: dict, node_id: str = "") -> bool:
    """A drawn species whose name, or id without an ``M_`` prefix and compartment suffix, is on the scorer's list
    (core.js matches the name and the BiGG id without its compartment)."""
    if data.get("kind") != SPECIES:
        return False
    base = re.sub(r"^M_", "", str(data.get("of") or node_id))
    keys = {_norm(data.get("label")), _norm(base), _norm(re.sub(r"_[a-z0-9]{1,2}$", "", base, flags=re.IGNORECASE))}
    return bool(keys & COFACTORS)


def _polyline(drawing: Drawing, u: str, v: str) -> list[tuple[float, float]]:
    return [drawing.pos[u], *drawing.routes.get((u, v), []), drawing.pos[v]]


def _angle(a, b) -> float:
    na, nb = math.hypot(*a), math.hypot(*b)
    if na == 0 or nb == 0:
        return math.nan
    return math.degrees(math.acos(max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))))


def _cross(p1, p2, p3, p4) -> bool:
    """Do segments p1-p2 and p3-p4 cross properly (core.js segX: touching or collinear is no crossing)?"""

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    return orient(p3, p4, p1) * orient(p3, p4, p2) < 0 and orient(p1, p2, p3) * orient(p1, p2, p4) < 0


# --- the rules ---------------------------------------------------------------------------------------------------


def crossings(drawing: Drawing) -> float | None:
    """Rule "no crossings": crossings between the pieces of drawn lines, skipping two lines that share an end node,
    per drawn line (as both implementations, neither with a size limit)."""
    edges = list(drawing.graph.edges())
    if not edges:
        return None
    pieces, owner = [], []
    for i, (u, v) in enumerate(edges):
        for a, b in itertools.pairwise(_polyline(drawing, u, v)):
            if a != b:
                pieces.append((a, b))
                owner.append(i)
    tree = STRtree([LineString(p) for p in pieces])
    n = 0
    for i, (a, b) in enumerate(pieces):
        for j in tree.query(LineString((a, b))):
            if j <= i or owner[i] == owner[j] or set(edges[owner[i]]) & set(edges[owner[j]]):
                continue
            n += _cross(a, b, *pieces[j])
    return n / len(edges)


def _shape(x, y, shape, w, h, shrink=0.0):
    w, h = w * (1 - shrink), h * (1 - shrink)
    if shape == "circle":
        return Point(x, y).buffer(w / 2, quad_segs=16)
    return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def lines_through_nodes(drawing: Drawing, sizes: dict[str, tuple] | None) -> float | None:
    """Rule "no line through a node": (line, species node) pairs where the line passes through the inside of a
    species it doesn't connect, at the tool's own sizes (shrunk by THROUGH_SHRINK). Reaction nodes left out (as
    core.js; svg_layout_metrics.py counts them). None without node sizes."""
    if not sizes:
        return None
    species = [n for n, d in drawing.graph.nodes(data=True) if d.get("kind") == SPECIES and n in sizes]
    shapes = [_shape(*drawing.pos[n], *sizes[n], THROUGH_SHRINK) for n in species]
    tree = STRtree(shapes)
    n = 0
    for u, v in drawing.graph.edges():
        line = LineString(_polyline(drawing, u, v))
        if line.length == 0:
            continue
        for k in tree.query(line):
            if species[k] not in (u, v) and line.intersects(shapes[k]) and not line.touches(shapes[k]):
                n += 1
    return float(n)


def cofactor_hubs(drawing: Drawing) -> float | None:
    """Rule "cofactors drawn as clones": cofactors (the scorer's list) drawn once but linked to more than one
    reaction (as both implementations). None without cofactors."""
    g = drawing.graph
    drawn = {}
    for _, d in g.nodes(data=True):
        drawn[d["of"]] = drawn.get(d["of"], 0) + 1
    cof = [n for n, d in g.nodes(data=True) if is_cofactor(d, n)]
    if not cof:
        return None
    return float(sum(drawn[g.nodes[n]["of"]] == 1 and len(set(nx.all_neighbors(g, n))) > 1 for n in cof))


def placement(drawing: Drawing) -> dict[str, float | None]:
    """Rule "consistent participant placement" (as both implementations): per drawn reaction with an input and an
    output, whether the centre of its inputs and the centre of its outputs, seen from the reaction node, are at
    least 120 degrees apart; and per modifier, whether it sits 60-120 degrees from the flow (outputs' centre minus
    inputs' centre). The shares."""
    g, pos = drawing.graph, drawing.pos
    opposite, beside = [], []
    for r, d in g.nodes(data=True):
        if d.get("kind") != REACTION:
            continue
        ins = [u for u, _, a in g.in_edges(r, data="arc") if a == CONSUMPTION]
        outs = [v for _, v, a in g.out_edges(r, data="arc") if a == PRODUCTION]
        mods = [u for u, _, a in g.in_edges(r, data="arc") if a in MODIFIER_ARCS]
        if not ins or not outs:
            continue
        c = np.array(pos[r], dtype=float)
        vi = np.mean([pos[n] for n in ins], axis=0) - c
        vo = np.mean([pos[n] for n in outs], axis=0) - c
        a = _angle(vi, vo)
        if not math.isnan(a):
            opposite.append(a >= 120)
        flow = vo - vi
        if math.hypot(*flow) > 0:
            for m in mods:
                b = _angle(np.array(pos[m], dtype=float) - c, flow)
                if not math.isnan(b):
                    beside.append(60 <= b <= 120)
    return {
        "rule_opposite_share": float(np.mean(opposite)) if opposite else None,
        "rule_modifiers_beside": float(np.mean(beside)) if beside else None,
    }


def _extent(drawing: Drawing, sizes: dict[str, tuple] | None) -> tuple[float, float]:
    """Width and height of the drawn nodes (their shapes at own sizes, else their centres); compartment boxes
    left out (as svg_layout_metrics.py; core.js includes them)."""
    xs, ys = [], []
    for n, (x, y) in drawing.pos.items():
        w, h = (sizes[n][1], sizes[n][2]) if sizes and n in sizes else (0.0, 0.0)
        xs += [x - w / 2, x + w / 2]
        ys += [y - h / 2, y + h / 2]
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0.0, 0.0)


def shape(drawing: Drawing, sizes: dict[str, tuple] | None) -> dict[str, float | None]:
    """Rules "aspect ratio" (width / height of the drawn nodes' extent) and "density" (the drawn nodes' area at own
    sizes / that extent; None without sizes)."""
    w, h = _extent(drawing, sizes)
    area = None
    if sizes and w * h > 0:
        area = sum((math.pi / 4 if s == "circle" else 1.0) * a * b for s, a, b in sizes.values()) / (w * h)
    return {"rule_aspect": w / h if h else None, "rule_density": area}


def lines(drawing: Drawing) -> dict[str, float | None]:
    """Rules "avoid long lines" (longest drawn line / median, as both) and "avoid bends" (route points where the
    line turns by more than BEND_DEGREES, per line, as svg_layout_metrics.py; core.js counts every bend point)."""
    lengths, bends = [], 0
    for u, v in drawing.graph.edges():
        pts = np.array(_polyline(drawing, u, v), dtype=float)
        lengths.append(float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()))
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            t = _angle(b - a, c - b)
            bends += not math.isnan(t) and t > BEND_DEGREES
    positive = [x for x in lengths if x > 0]
    med = float(np.median(positive)) if positive else 0.0
    return {
        "rule_longest_over_median": max(positive) / med if med else None,
        "rule_bends_per_line": bends / len(lengths) if lengths else None,
    }


# --- cycles ------------------------------------------------------------------------------------------------------


def _fit_circle(pts: np.ndarray):
    """Least-squares (Kasa) circle: centre, radius; None if degenerate."""
    a = np.c_[2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))]
    sol, *_ = np.linalg.lstsq(a, (pts**2).sum(1), rcond=None)
    r2 = sol[2] + sol[0] ** 2 + sol[1] ** 2
    return (sol[:2], math.sqrt(r2)) if r2 > 0 else None


def closed_loop(pos, cycle: list[str], step: dict) -> tuple[bool, float]:
    """Is a cycle drawn as a closed loop in cycle order (both implementations' definition)? Its metabolites in
    order, each step's reaction node on the loop between them; the polygon must wind once around its centre in
    one direction, not cross itself and not fold inwards (a turn against the loop's direction sharper than 0.35).
    Returns (closed loop, circularity: 1 - std of the distances to a fitted circle / its radius)."""
    c = {n: np.array(pos[n], dtype=float) for n in cycle}
    g = np.mean(list(c.values()), axis=0)
    pts = []
    for a, b in zip(cycle, cycle[1:] + cycle[:1]):
        pts.append(c[a])
        want = (np.linalg.norm(c[a] - g) + np.linalg.norm(c[b] - g)) / 2
        rs = step.get(frozenset((a, b)), [])
        if rs:  # the step's reaction node on the loop
            r = min(rs, key=lambda r: abs(np.linalg.norm(np.array(pos[r]) - g) - want))
            pts.append(np.array(pos[r], dtype=float))
    pts = np.array(pts)
    cen = pts.mean(axis=0)
    th, prev, off = [], None, 0.0
    for p in [*pts, pts[0]]:
        t = math.atan2(p[1] - cen[1], p[0] - cen[0])
        if prev is not None:
            while t + off - prev > math.pi:
                off -= 2 * math.pi
            while t + off - prev < -math.pi:
                off += 2 * math.pi
        th.append(t + off)
        prev = t + off
    d = np.diff(th)
    order_ok = bool(np.all(d > -1e-9) or np.all(d < 1e-9)) and abs(abs(th[-1] - th[0]) - 2 * math.pi) < 0.5
    k = len(pts)
    edges = [(pts[i], pts[(i + 1) % k]) for i in range(k)]
    simple = not any(
        _cross(*edges[x], *edges[y]) for x in range(k) for y in range(x + 2, k) if not (x == 0 and y == k - 1)
    )
    turns = []
    for i in range(k):
        a, b, cc = pts[i - 1], pts[i], pts[(i + 1) % k]
        cr = (b[0] - a[0]) * (cc[1] - b[1]) - (b[1] - a[1]) * (cc[0] - b[0])
        turns.append(cr / ((np.linalg.norm(b - a) * np.linalg.norm(cc - b)) or 1.0))
    sign = np.sign(sum(turns)) or 1.0
    folds = sum(t * sign < -0.35 for t in turns)
    fit = _fit_circle(pts)
    circ = max(0.0, 1 - float(np.std(np.linalg.norm(pts - fit[0], axis=1))) / fit[1]) if fit else math.nan
    return order_ok and simple and folds == 0, circ


def cycles(drawing: Drawing) -> dict[str, float | None]:
    """Rule "cycles look like cycles": the metabolite cycles of the main steps (each reaction's input -> output,
    between drawn nodes), cofactors (the scorer's list, as core.js) and Escher's secondary metabolites left out;
    the main cycles (repeatedly: the longest drawn as a closed loop, if at least half as long as the longest left,
    else the longest; then every cycle sharing a node with it set aside); the share drawn as a closed loop."""
    g, pos = drawing.graph, drawing.pos

    def main_node(n):
        d = g.nodes[n]
        return d.get("kind") == SPECIES and d.get("primary", True) is not False and not is_cofactor(d, n)

    m, step = nx.Graph(), {}
    for r, d in sorted(g.nodes(data=True)):
        if d.get("kind") != REACTION:
            continue
        ins = [u for u, _, a in g.in_edges(r, data="arc") if a == CONSUMPTION and main_node(u)]
        outs = [v for _, v, a in g.out_edges(r, data="arc") if a == PRODUCTION and main_node(v)]
        for s, t in itertools.product(ins, outs):
            if s != t:
                m.add_edge(s, t)
                step.setdefault(frozenset((s, t)), []).append(r)
    found = [c for c in itertools.islice(nx.simple_cycles(m, length_bound=CYCLE_MAX_LEN), CYCLE_CAP) if len(c) >= 3]
    if not found:
        return {"rule_cycles": 0.0, "rule_cycles_closed": None}
    shapes = {tuple(c): closed_loop(pos, c, step) for c in found}
    main, pool = [], found
    while pool:
        longest = max(len(c) for c in pool)
        loops = [c for c in pool if shapes[tuple(c)][0] and len(c) >= 0.5 * longest]
        candidates = loops or [c for c in pool if len(c) == longest]
        pick = max(candidates, key=lambda c: (len(c), np.nan_to_num(shapes[tuple(c)][1], nan=-1.0)))
        main.append(pick)
        used = set(pick)
        pool = [c for c in pool if not used & set(c)]
    closed = sum(shapes[tuple(c)][0] for c in main)
    return {"rule_cycles": float(len(main)), "rule_cycles_closed": closed / len(main)}


def rule_metrics(drawing: Drawing, sizes: dict[str, tuple] | None) -> dict[str, float | None]:
    """Every rule value of a drawing; ``sizes``: the tool's own node sizes (``metrics.own_sizes``), or None."""
    m = {
        "rule_crossings_per_line": crossings(drawing),
        "rule_lines_through_nodes": lines_through_nodes(drawing, sizes),
        "rule_cofactor_hubs": cofactor_hubs(drawing),
    }
    m.update(cycles(drawing))
    m.update(placement(drawing))
    m.update(shape(drawing, sizes))
    m.update(lines(drawing))
    return m


__all__ = ["COFACTORS", "closed_loop", "is_cofactor", "rule_metrics"]
