"""Layout quality metrics, on the drawing as shown.

Every metric is computed on a ``Drawing`` in the tool's own coordinates: the drawn nodes (a clone is a node with
its own edges; nodes a tool leaves out are absent) and the drawn edges as polylines (route bends included). No
metric depends on our common drawing scale: the general ones don't change under a uniform scale, and overlaps use
each tool's own node sizes in its own units.

General graph-drawing metrics come from gdMetriX (https://github.com/livus/gdMetriX, GPL-3.0; imported, not
copied), given graphs built from the drawing (``segment_graph``: every straight piece of every drawn edge, shared
pieces once; ``stub_graph``: each edge's first and last piece, for angles at nodes). The pathway-specific ones are
here: coverage, overlaps with the tool's own node sizes, reaction participant consistency, compartments (where the
tool draws compartment boxes) and similarity to a reference layout. The project's layout rules are in ``rules``.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import gdMetriX
import networkx as nx
import numpy as np
from scipy.spatial import procrustes
from scipy.spatial.distance import pdist
from scipy.stats import spearmanr
from shapely import STRtree, box
from shapely.geometry import Point

from .drawing import Drawing, Positions
from .external import ESCHER_RADIUS
from .graph import CONSUMPTION, PRODUCTION, REACTION, SPECIES, Pathway
from .layouts import SPECS
from .rules import rule_metrics

# above this many drawn nodes, visual symmetry (it rasterises the drawing) is skipped
SYMMETRY_MAX_NODES = 300


# The metrics: (column, label, group, better: "lower", "higher" or None, what it measures). The report's tables and
# its summary page use this list; None: no direction (a property, not a score).
@dataclass(frozen=True)
class Metric:
    """A metric as the report shows it: its results.csv column, short label, group, direction ("lower"/"higher"
    is better, None: no direction, not ranked), what it measures, where it comes from (a key of SOURCES) and how
    it is calculated."""

    column: str
    label: str
    group: str
    better: str | None
    description: str
    source: str = ""
    how: str = ""


# where a metric comes from: (band in the report's table headers, short name, explanation)
SOURCES = {
    "gdMetriX": (
        "general graph drawing (gdMetriX)",
        "gdMetriX",
        "computed by gdMetriX, a library of general graph-drawing metrics",
    ),
    "gdMetriX definition": (
        "general graph drawing (gdMetriX)",
        "gdMetriX's definition, computed by this benchmark",
        "gdMetriX's definition, computed by this benchmark (on the drawn polylines)",
    ),
    "pathway": (
        "pathway maps (project 22's layout rules and this benchmark's checks)",
        "this benchmark: pathway maps",
        "this benchmark's own check of pathway maps (not one of project 22's rules)",
    ),
    "project rules": (
        "pathway maps (project 22's layout rules and this benchmark's checks)",
        "layout rule of BioHackathon 2026 project 22, computed by this benchmark",
        (
            "a layout rule of BioHackathon Europe 2026 project 22 (Open Pathway Maps), as defined by its two "
            "implementations (the project's browser pathway layout scorer, core.js, and "
            "automatic_layout_following_our_rules's svg_layout_metrics.py), computed by this benchmark on the drawing; "
            "where the two differ, the choice is stated"
        ),
    ),
    "scorer": (
        "pathway maps (project 22's layout rules and this benchmark's checks)",
        "project 22's pathway layout scorer: its thresholds and weights, on this benchmark's rule values",
        (
            "the combined score of BioHackathon Europe 2026 project 22's pathway layout scorer (core.js, its "
            "thresholds and weights: its own choices), applied to the rule values this benchmark computes"
        ),
    ),
    "reference": (
        "comparison with the reference",
        "this benchmark: comparison with the reference",
        "this benchmark's comparison with the reference layout (standard shape-comparison measures)",
    ),
}

_PIECES = (
    "the drawn edge pieces (every straight piece of every drawn edge, route bends included; a piece several edges "
    "share counted once)"
)
METRICS = [
    Metric(
        "crossings",
        "crossings",
        "crossings",
        "lower",
        "edge crossings",
        "gdMetriX",
        f"number_of_crossings on {_PIECES}; where more than two pieces cross in a point, each pair counts",
    ),
    Metric(
        "crossing_density",
        "density",
        "crossings",
        "higher",
        "crossings against how many there could be",
        "gdMetriX",
        "crossing_density: 1 - crossings / Purchase's estimate of the most crossings possible (pairs of pieces that "
        "don't share an end)",
    ),
    Metric(
        "crossing_angular_resolution",
        "angles",
        "crossings",
        "higher",
        "edges cross at large angles (near 90 degrees)",
        "gdMetriX",
        "crossing_angular_resolution: 1 - the mean over crossings of |optimal - smallest angle| / optimal, the optimal "
        "angle being 180 degrees / the number of crossing pieces (90 for two); empty without crossings",
    ),
    Metric(
        "edge_length_deviation",
        "length dev.",
        "lines",
        "lower",
        "edges of even length",
        "gdMetriX definition",
        "Purchase's edge length deviation (gdMetriX's edge_length_deviation): the mean over drawn edges of "
        "|mean length - length| / mean length, each length measured along the drawn polyline",
    ),
    Metric(
        "angular_resolution",
        "angle dev.",
        "lines",
        "lower",
        "edges spread evenly around their nodes",
        "gdMetriX",
        "angular_resolution (Purchase): the mean over nodes with two or more edges of |optimal - smallest angle| / "
        "optimal, optimal = 360 degrees / degree; the angles are those between the edges' first pieces at the node",
    ),
    Metric(
        "edge_orthogonality",
        "orthogonal",
        "lines",
        "higher",
        "horizontal and vertical lines",
        "gdMetriX",
        f"edge_orthogonality (Purchase): 1 - the mean deviation of {_PIECES} from the nearest horizontal or "
        "vertical direction (1: all axis-parallel)",
    ),
    Metric(
        "aspect_ratio",
        "aspect",
        "shape",
        None,
        "how square the drawing is",
        "gdMetriX",
        "aspect_ratio: the shorter side / the longer side of the bounding box of the node centres (1: square)",
    ),
    Metric(
        "homogeneity",
        "homogeneity",
        "shape",
        None,
        "nodes spread evenly over the drawing",
        "gdMetriX",
        "homogeneity (Taylor and Rodgers): from the numbers of nodes in the four quadrants of the bounding box, "
        "against an even split",
    ),
    Metric(
        "coherence_to_average_flow",
        "flow",
        "shape",
        None,
        "edges flowing in one main direction",
        "gdMetriX",
        "coherence_to_average_flow: the share of drawn edges (start to end, from substrate to reaction to product) "
        "that point along the average edge direction (positive dot product with the mean unit edge vector)",
    ),
    Metric(
        "visual_symmetry",
        "symmetry",
        "shape",
        None,
        "visual symmetry",
        "gdMetriX",
        "visual_symmetry: the drawing of the edge pieces rasterised and blurred, compared with its reflections and "
        "rotations; left out above 300 nodes (too slow)",
    ),
    Metric(
        "rule_cycles",
        "cycles",
        "cycles",
        None,
        "metabolite cycles found (hard rule: cycles look like cycles)",
        "project rules",
        "the main metabolite cycles: simple cycles of 3-16 metabolites (at most 20000) through main steps (a "
        "reaction's input to its output), cofactors (scorer's list, as core.js) and Escher's secondary metabolites "
        "left out; repeatedly the longest drawn as a closed loop (if at least half as long as the longest left), else "
        "the longest, then every cycle sharing a metabolite with it set aside (as both implementations)",
    ),
    Metric(
        "rule_cycles_closed",
        "as loops",
        "cycles",
        "higher",
        "cycles look like cycles (hard rule)",
        "project rules",
        "the share of main cycles drawn as a closed loop in cycle order: the metabolites and each step's reaction "
        "node in order wind once around their centre in one direction, without crossing themselves or folding "
        "inwards (a circle, stadium or rounded rectangle all pass; as both implementations)",
    ),
    Metric(
        "rule_cofactor_hubs",
        "cofactor hubs",
        "cofactors",
        "lower",
        "cofactors drawn as clones (hard rule)",
        "project rules",
        "cofactors (the scorer's list of names, matched on name or id) drawn once but linked to more than one "
        "reaction (as both implementations); empty without cofactors",
    ),
    Metric(
        "rule_crossings_per_line",
        "crossings",
        "crossing",
        "lower",
        "no crossings (hard rule)",
        "project rules",
        "proper crossings between the straight pieces of drawn lines, skipping two lines that share an end node, / the "
        "drawn lines (as both implementations, neither with a size limit)",
    ),
    Metric(
        "rule_lines_through_nodes",
        "through nodes",
        "through",
        "lower",
        "no line through a node (hard rule)",
        "project rules",
        "(line, species) pairs where a drawn line passes through the inside of a species node it doesn't connect, at "
        "the tool's own node sizes and shapes; reaction nodes left out (as core.js; svg_layout_metrics.py counts "
        "them); the exact shape (both implementations shrink it by 2 px first; ours: rules.THROUGH_SHRINK, a share of the node, 0); empty "
        "without node sizes",
    ),
    Metric(
        "rule_opposite_share",
        "opposite",
        "placement",
        "higher",
        "consistent participant placement (hard rule)",
        "project rules",
        "the share of drawn reactions with an input and an output whose inputs' centre and outputs' centre, seen "
        "from the reaction node, are at least 120 degrees apart (as both implementations)",
    ),
    Metric(
        "rule_modifiers_beside",
        "modifiers beside",
        "placement",
        "higher",
        "modifiers beside their reaction (hard rule)",
        "project rules",
        "the share of modifier nodes 60-120 degrees from their reaction's flow (outputs' centre minus inputs' "
        "centre), seen from the reaction node (as both implementations)",
    ),
    Metric(
        "participant_consistency",
        "through",
        "placement",
        "higher",
        "reactants and products on opposite sides of their reaction",
        "pathway",
        "over every drawn reaction, each (reactant, product) pair: whether the first pieces of their edges at the "
        "reaction node point to opposite sides (more than 90 degrees apart); the share of such pairs. A reaction "
        "drawn as a corner scores 0",
    ),
    Metric(
        "rule_aspect",
        "aspect",
        "aspect",
        None,
        "width / height (hard rule: aspect ratio, target 0.5-2)",
        "project rules",
        "width / height of the drawn nodes' extent (their shapes at own sizes, else their centres); compartment "
        "boxes left out (as svg_layout_metrics.py; core.js includes them)",
    ),
    Metric(
        "rule_longest_over_median",
        "longest",
        "long lines",
        "lower",
        "avoid long lines (soft rule)",
        "project rules",
        "the longest drawn line (along its route) / the median drawn line (as both implementations). A line is a "
        "participant's whole line to its reaction (core.js takes each Escher segment as a line)",
    ),
    Metric(
        "rule_bends_per_line",
        "bends",
        "bends",
        "lower",
        "avoid bends (soft rule)",
        "project rules",
        "route points where a drawn line turns by more than 25 degrees, per drawn line (as svg_layout_metrics.py; "
        "core.js counts every stored bend point, and none on Escher's curves). Escher's lines are read as straight "
        "pieces between their markers, so a curve through a marker counts as a bend there",
    ),
    Metric(
        "rule_density",
        "density",
        "density",
        None,
        "node area / extent (soft rule: density, target 5-30%)",
        "project rules",
        "the drawn nodes' area at the tool's own sizes and shapes / the area of their extent (compartment boxes "
        "left out, as svg_layout_metrics.py); empty without node sizes",
    ),
    Metric(
        "overlapping_pairs",
        "pairs",
        "overlaps",
        "lower",
        "nodes don't overlap (soft rule)",
        "pathway",
        "pairs of drawn nodes whose shapes intersect with a positive area (touching isn't overlapping), every node "
        "at the tool's own size and shape (the box Graphviz and cytoscape.js are given, Escher's circles, "
        "SBMLNetwork's and the reference's glyphs); empty where the tool has no node sizes (igraph, networkx). Also "
        "the project's rule \"no overlapping nodes\" (core.js's test: any overlap counts; svg_layout_metrics.py allows "
        "1 px and skips a node inside another)",
    ),
    Metric(
        "overlap_area_share",
        "area",
        "overlaps",
        "lower",
        "how much nodes overlap",
        "pathway",
        "the summed intersection area of the overlapping pairs / the summed area of all drawn nodes, at the tool's "
        "own sizes",
    ),
    Metric(
        "species_drawn",
        "species",
        "drawn",
        "higher",
        "the whole model is drawn: its species",
        "pathway",
        "the model's species with at least one drawn node / the model's species",
    ),
    Metric(
        "reactions_drawn",
        "reactions",
        "drawn",
        "higher",
        "the whole model is drawn: its reactions",
        "pathway",
        "the model's reactions with a drawn node / the model's reactions",
    ),
    Metric(
        "drawn_per_node",
        "per node",
        "drawn",
        None,
        "clones: nodes drawn more than once",
        "pathway",
        "drawn nodes (each clone counted) / the model nodes drawn; above 1 where species or reactions are drawn "
        "more than once",
    ),
    Metric(
        "species_outside_compartment",
        "outside",
        "compartments",
        "lower",
        "species inside their compartment",
        "pathway",
        "drawn species whose centre is outside the box of their own compartment / drawn species whose compartment "
        "has a box; only where the tool draws compartment boxes",
    ),
    Metric(
        "compartments_overlapping",
        "overlapping",
        "compartments",
        "lower",
        "compartments nested, not overlapping",
        "pathway",
        "pairs of compartment boxes that intersect without one holding the other / all pairs of boxes; only where "
        "the tool draws compartment boxes",
    ),
    Metric(
        "procrustes",
        "procrustes",
        "reference",
        "lower",
        "the same shape as the reference",
        "reference",
        "Procrustes disparity (scipy) between the layout's and the reference's positions of the model nodes both "
        "draw (one position per node), after translation, scaling, rotation and mirroring; 0: the same shape",
    ),
    Metric(
        "distance_correlation",
        "distances",
        "reference",
        "higher",
        "near and far as in the reference",
        "reference",
        "Spearman rank correlation between all pairwise node distances in the layout and in the reference",
    ),
    Metric(
        "knn_preservation",
        "neighbours",
        "reference",
        "higher",
        "the same neighbours as in the reference",
        "reference",
        "for each node, the share of its 5 nearest neighbours that are among its 5 nearest in the reference; the mean",
    ),
    Metric(
        "reference_nodes",
        "nodes",
        "reference",
        None,
        "how much of the model the comparison covers",
        "reference",
        "the model nodes placed in both the layout and the reference",
    ),
]
# the report's order of the sources: the pathway maps (the project's rules, then our own checks), the comparison
# with the reference, general graph drawing last; within a source, as listed above
_SOURCE_ORDER = {"project rules": 0, "pathway": 0, "reference": 1, "gdMetriX": 2, "gdMetriX definition": 2}
METRICS.sort(key=lambda m: _SOURCE_ORDER[m.source])


# --- graphs from the drawing -------------------------------------------------------------------------------------


def _polyline(drawing: Drawing, u: str, v: str) -> list[tuple[float, float]]:
    return [drawing.pos[u], *drawing.routes.get((u, v), []), drawing.pos[v]]


def _point_key(p) -> str:
    return f"@{p[0]:.6g},{p[1]:.6g}"


def segment_graph(drawing: Drawing) -> tuple[nx.Graph, Positions]:
    """Every straight piece of every drawn edge as an edge: route bends become nodes, keyed by their position, so a
    piece that several edges share (Escher's segments to a reaction's markers) is one edge, drawn once."""
    g = nx.Graph()
    pos = dict(drawing.pos)
    g.add_nodes_from(drawing.pos)
    for u, v in drawing.graph.edges():
        points = _polyline(drawing, u, v)
        keys = [u] + [_point_key(p) for p in points[1:-1]] + [v]
        for k, p in zip(keys, points):
            pos.setdefault(k, (float(p[0]), float(p[1])))
            g.add_node(k)
        for a, b in itertools.pairwise(keys):
            if a != b and pos[a] != pos[b]:
                g.add_edge(a, b)
    return g, pos


def stub_graph(drawing: Drawing) -> tuple[nx.Graph, Positions]:
    """Each drawn edge as two stubs: its first piece from one end and its last piece into the other (straight edges:
    the edge itself, twice), so the angles at every drawn node are those of the picture; stub ends are leaves."""
    g = nx.Graph()
    pos = dict(drawing.pos)
    g.add_nodes_from(drawing.pos)
    for i, (u, v) in enumerate(drawing.graph.edges()):
        points = _polyline(drawing, u, v)
        for end, towards, tag in ((u, points[1], "a"), (v, points[-2], "b")):
            stub = f"#{i}{tag}"
            pos[stub] = (float(towards[0]), float(towards[1]))
            g.add_edge(end, stub)
    return g, pos


def _lengths(drawing: Drawing) -> list[float]:
    out = []
    for u, v in drawing.graph.edges():
        pts = np.array(_polyline(drawing, u, v), dtype=float)
        out.append(float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()))
    return out


# --- general metrics ---------------------------------------------------------------------------------------------


def general_metrics(drawing: Drawing) -> dict[str, float | None]:
    """gdMetriX metrics on the drawing as shown (see the module docstring)."""
    segments, spos = segment_graph(drawing)
    stubs, stub_pos = stub_graph(drawing)
    flow = nx.DiGraph(drawing.graph.edges())  # the drawn edges' directions, end to end
    nodes = drawing.graph.number_of_nodes()
    crossings = gdMetriX.get_crossings(segments, spos) if segments.number_of_edges() > 1 else []
    lengths = [x for x in _lengths(drawing) if x > 0]
    mean = float(np.mean(lengths)) if lengths else 0.0
    m = {
        "crossings": len(crossings) and gdMetriX.number_of_crossings(segments, spos, crossing_list=crossings),
        "crossing_density": gdMetriX.crossing_density(segments, spos, crossing_list=crossings),
        "crossing_angular_resolution": (
            gdMetriX.crossing_angular_resolution(segments, spos, crossing_list=crossings) if crossings else None
        ),
        "angular_resolution": gdMetriX.angular_resolution(stubs, stub_pos),
        # gdMetriX's edge_length_deviation (Purchase), on the drawn lengths of the polylines
        "edge_length_deviation": float(np.mean([abs(mean - x) / mean for x in lengths])) if mean else None,
        "edge_orthogonality": gdMetriX.edge_orthogonality(segments, spos) if segments.number_of_edges() else None,
        "aspect_ratio": gdMetriX.aspect_ratio(drawing.graph, drawing.pos),
        "homogeneity": gdMetriX.homogeneity(drawing.graph, drawing.pos),
        "coherence_to_average_flow": gdMetriX.coherence_to_average_flow(flow, drawing.pos)
        if flow.number_of_edges()
        else None,
        "visual_symmetry": gdMetriX.visual_symmetry(segments, spos) if nodes <= SYMMETRY_MAX_NODES else None,
    }
    return {k: (float(v) if v is not None else None) for k, v in m.items()}


# --- pathway metrics ---------------------------------------------------------------------------------------------


def coverage(drawing: Drawing, pathway: Pathway) -> dict[str, float | None]:
    """The share of the model's species and of its reactions drawn, and drawn nodes per drawn model node (clones:
    above 1)."""
    placed = drawing.placed()
    species, reactions = pathway.species, pathway.reactions
    return {
        "species_drawn": sum(n in placed for n in species) / len(species) if species else None,
        "reactions_drawn": sum(n in placed for n in reactions) / len(reactions) if reactions else None,
        "drawn_per_node": drawing.graph.number_of_nodes() / len(placed) if placed else None,
    }


def own_sizes(drawing: Drawing, pathway: Pathway, layout: str | None = None) -> dict[str, tuple] | None:
    """Each drawn node's size as the tool itself draws it, in its own units: (shape, width, height), shape "box" or
    "circle". From the drawing (``own_width``, ``own_height``, ``own_shape``) where the tool gave them; else: the
    sizes we give Graphviz and cytoscape.js (they lay out around them); Escher's circles for the Escher tools. None
    where the tool has no node sizes (igraph, networkx)."""
    nodes = drawing.graph.nodes(data=True)
    if all(d.get("own_width") for _, d in nodes):
        return {n: (d.get("own_shape", "box"), d["own_width"], d["own_height"]) for n, d in nodes}
    sizes = SPECS[layout].sizes if layout in SPECS else None  # LayoutSpec.sizes
    if sizes == "given":  # the sizes we give the tool, in the same units as its positions
        return {n: ("box", d["width"], d["height"]) for n, d in nodes}
    if sizes == "escher":  # saved drawings from before own sizes were stored
        out = {}
        for n, d in nodes:
            if d["kind"] == REACTION:
                r = ESCHER_RADIUS["marker"]
            else:  # escher_drawing draws secondary metabolites at 0.6 of the species' size
                primary = (
                    d["width"] >= 0.99 * pathway.graph.nodes[d["of"]]["width"] if d["of"] in pathway.graph else True
                )
                r = ESCHER_RADIUS["primary" if primary else "secondary"]
            out[n] = ("circle", 2 * r, 2 * r)
        return out
    return None


def overlaps(drawing: Drawing, sizes: dict[str, tuple] | None) -> dict[str, float | None]:
    """Pairs of drawn nodes whose shapes overlap (touching is no overlap) at the tool's own sizes, and the overlap
    area relative to the total node area. Empty without sizes."""
    if not sizes:
        return {"overlapping_pairs": None, "overlap_area_share": None}
    shapes = []
    for n, (shape, w, h) in sizes.items():
        x, y = drawing.pos[n]
        if shape == "circle":
            shapes.append(Point(x, y).buffer(w / 2, quad_segs=16))
        else:
            shapes.append(box(x - w / 2, y - h / 2, x + w / 2, y + h / 2))
    tree = STRtree(shapes)
    pairs, area = 0, 0.0
    for i, s in enumerate(shapes):
        for j in tree.query(s):
            if j > i:
                inter = s.intersection(shapes[j]).area
                if inter > 0:
                    pairs += 1
                    area += inter
    total = sum(s.area for s in shapes)
    return {"overlapping_pairs": float(pairs), "overlap_area_share": area / total if total else 0.0}


def participant_consistency(drawing: Drawing) -> float | None:
    """Share of (reactant, product) pairs, over all drawn reactions, that leave their reaction on opposite sides:
    the directions of their edges' pieces at the reaction node are more than 90 degrees apart. 1 = every reaction
    reads "through" its node. None without a drawn reaction that has both."""
    g, pos = drawing.graph, drawing.pos
    opposite, pairs = 0, 0
    for r, d in g.nodes(data=True):
        if d["kind"] != REACTION:
            continue
        c = np.array(pos[r], dtype=float)
        ins = [np.array(_polyline(drawing, u, r)[-2]) - c for u, _, a in g.in_edges(r, data="arc") if a == CONSUMPTION]
        outs = [np.array(_polyline(drawing, r, v)[1]) - c for _, v, a in g.out_edges(r, data="arc") if a == PRODUCTION]
        for a in ins:
            for b in outs:
                pairs += 1
                opposite += float(np.dot(a, b)) < 0
    return opposite / pairs if pairs else None


def compartment_metrics(drawing: Drawing, pathway: Pathway) -> dict[str, float | None]:
    """Where the tool draws compartment boxes: the share of drawn species outside the box of their own compartment,
    and the share of pairs of boxes that overlap without one holding the other. Empty without boxes."""
    boxes = {c: box(*b["box"]) for c, b in drawing.compartments.items()}
    if not boxes:
        return {"species_outside_compartment": None, "compartments_overlapping": None}
    species = [
        (n, pathway.graph.nodes[d["of"]].get("compartment"))
        for n, d in drawing.graph.nodes(data=True)
        if d["kind"] == SPECIES and d["of"] in pathway.graph
    ]
    species = [(n, c) for n, c in species if c in boxes]
    outside = sum(not boxes[c].covers(Point(drawing.pos[n])) for n, c in species)
    ids = sorted(boxes)
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1 :]]
    crossing = sum(
        boxes[a].intersection(boxes[b]).area > 0 and not (boxes[a].covers(boxes[b]) or boxes[b].covers(boxes[a]))
        for a, b in pairs
    )
    return {
        "species_outside_compartment": outside / len(species) if species else None,
        "compartments_overlapping": crossing / len(pairs) if pairs else None,
    }


def reference_similarity(pos: Positions, reference: Positions, k: int = 5) -> dict[str, float | None]:
    """Similarity to a reference layout on the model nodes both draw (one position each: the primary clone),
    invariant to translation, scale, rotation and mirroring: Procrustes disparity (0 = identical), Spearman
    correlation of pairwise distances, and the mean share of each node's k nearest neighbours that are the same."""
    common = sorted(set(pos) & set(reference))
    if len(common) < 3:
        return {"procrustes": None, "distance_correlation": None, "knn_preservation": None, "reference_nodes": None}
    a = np.array([pos[n] for n in common], dtype=float)
    b = np.array([reference[n] for n in common], dtype=float)
    _, _, disparity = procrustes(b, a)
    corr = spearmanr(pdist(a), pdist(b)).statistic
    k = min(k, len(common) - 1)

    def knn(xy):
        d = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
        np.fill_diagonal(d, math.inf)
        return [set(np.argsort(row)[:k]) for row in d]

    ka, kb = knn(a), knn(b)
    preservation = float(np.mean([len(x & y) / k for x, y in zip(ka, kb)]))
    return {
        "procrustes": float(disparity),
        "distance_correlation": float(corr),
        "knn_preservation": preservation,
        "reference_nodes": float(len(common)),
    }


def all_metrics(
    drawing: Drawing, pathway: Pathway, reference: Drawing | None = None, layout: str | None = None
) -> dict[str, float | None]:
    """Every metric of a drawing (in its own coordinates). ``layout``: the layout's name, for node sizes of drawings
    saved without them (``own_sizes``); ``reference``: the model's reference drawing, if any."""
    m = coverage(drawing, pathway)
    m.update(general_metrics(drawing))
    sizes = own_sizes(drawing, pathway, layout)
    m.update(overlaps(drawing, sizes))
    m["participant_consistency"] = participant_consistency(drawing)
    m.update(compartment_metrics(drawing, pathway))
    m.update(rule_metrics(drawing, sizes))
    if reference is not None:
        m.update(reference_similarity(drawing.node_positions(), reference.node_positions()))
    return m


__all__ = [
    "METRICS",
    "SOURCES",
    "Metric",
    "all_metrics",
    "compartment_metrics",
    "coverage",
    "general_metrics",
    "overlaps",
    "own_sizes",
    "participant_consistency",
    "reference_similarity",
    "segment_graph",
    "stub_graph",
]
