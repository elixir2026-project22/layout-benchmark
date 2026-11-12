"""Layout quality metrics, on the drawing as shown.

Every metric is computed on a ``Drawing`` in the tool's own coordinates: the drawn nodes (a clone is a node with
its own edges; nodes a tool leaves out are absent) and the drawn edges as polylines (route bends included). No
metric depends on our common drawing scale: the general ones don't change under a uniform scale, and overlaps use
each tool's own node sizes in its own units.

General graph-drawing metrics come from gdMetriX (https://github.com/livus/gdMetriX, GPL-3.0; imported, not
copied), given graphs built from the drawing (``segment_graph``: every straight piece of every drawn edge, shared
pieces once; ``stub_graph``: each edge's first and last piece, for angles at nodes). The pathway-specific ones are
here: coverage, overlaps with the tool's own node sizes, reaction participant consistency, compartments (where the
tool draws compartment boxes) and similarity to a reference layout.
"""

from __future__ import annotations

import itertools
import math

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

# above this many drawn nodes, visual symmetry (it rasterises the drawing) is skipped
SYMMETRY_MAX_NODES = 300


# The metrics: (column, label, group, better: "lower", "higher" or None, what it measures). The report's tables and
# its summary page use this list; None: no direction (a property, not a score).
METRICS = [
    ("species_drawn", "species", "drawn", "higher", "share of the model's species drawn"),
    ("reactions_drawn", "reactions", "drawn", "higher", "share of the model's reactions drawn"),
    ("drawn_per_node", "per node", "drawn", None, "drawn nodes per drawn model node (above 1: clones)"),
    ("crossings", "crossings", "crossings", "lower", "edge crossings, on the drawn polylines"),
    ("crossing_density", "density", "crossings", "higher", "1 - crossings / an estimated maximum (gdMetriX)"),
    ("crossing_angular_resolution", "angles", "crossings", "higher", "crossings near 90 degrees (gdMetriX)"),
    ("overlapping_pairs", "pairs", "overlaps", "lower", "node pairs that overlap, at the tool's own node sizes"),
    ("overlap_area_share", "area", "overlaps", "lower", "overlap area / node area, at the tool's own node sizes"),
    ("edge_length_deviation", "length dev.", "lines", "lower", "mean deviation from the mean drawn edge length"),
    ("angular_resolution", "angle dev.", "lines", "lower", "smallest angle at a node against the ideal (deviation)"),
    ("edge_orthogonality", "orthogonal", "lines", "higher", "horizontal and vertical edge pieces (1: all)"),
    ("participant_consistency", "through", "reactions", "higher", "reactants and products on opposite sides"),
    ("species_outside_compartment", "outside", "compartments", "lower", "species outside their compartment's box"),
    ("compartments_overlapping", "overlapping", "compartments", "lower", "compartment boxes overlapping, not nested"),
    ("aspect_ratio", "aspect", "shape", None, "longer side / shorter side"),
    ("homogeneity", "homogeneity", "shape", None, "nodes spread over the four quadrants"),
    ("coherence_to_average_flow", "flow", "shape", None, "edges along the main direction"),
    ("visual_symmetry", "symmetry", "shape", None, "visual symmetry (up to 300 nodes)"),
    ("procrustes", "procrustes", "reference", "lower", "distance to the reference after alignment"),
    ("distance_correlation", "distances", "reference", "higher", "rank correlation of distances with the reference"),
    ("knn_preservation", "neighbours", "reference", "higher", "shared 5 nearest neighbours with the reference"),
    ("reference_nodes", "nodes", "reference", None, "model nodes both drawings have"),
]


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
    m.update(overlaps(drawing, own_sizes(drawing, pathway, layout)))
    m["participant_consistency"] = participant_consistency(drawing)
    m.update(compartment_metrics(drawing, pathway))
    if reference is not None:
        m.update(reference_similarity(drawing.node_positions(), reference.node_positions()))
    return m


__all__ = [
    "METRICS",
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
