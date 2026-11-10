"""Layout quality metrics.

General graph-drawing metrics come from gdMetriX (https://github.com/livus/gdMetriX, GPL-3.0; imported, not
copied). The pathway-specific ones are here: node box overlaps, reaction participant consistency, compartments,
and similarity to a reference layout.
"""

from __future__ import annotations

import math

import gdMetriX
import numpy as np
from scipy.spatial import ConvexHull, procrustes
from scipy.spatial.distance import pdist
from scipy.stats import spearmanr
from shapely import STRtree, box
from shapely.geometry import Point, Polygon

from .drawing import Positions
from .graph import PRODUCT, REACTANT, SPECIES, Pathway

# above this many nodes, the expensive gdMetriX metrics are skipped
SYMMETRY_MAX_NODES = 300


def general_metrics(pathway: Pathway, pos: Positions) -> dict[str, float | None]:
    """gdMetriX metrics on the undirected graph (and, for flow, the directed one)."""
    g = pathway.undirected()
    n = g.number_of_nodes()
    m = {
        "crossings": gdMetriX.number_of_crossings(g, pos=pos),
        "crossing_density": gdMetriX.crossing_density(g, pos=pos),
        "crossing_angular_resolution": gdMetriX.crossing_angular_resolution(g, pos=pos),
        "angular_resolution": gdMetriX.angular_resolution(g, pos=pos),
        "edge_length_deviation": gdMetriX.edge_length_deviation(g, pos=pos),
        "edge_orthogonality": gdMetriX.edge_orthogonality(g, pos=pos),
        "stress": gdMetriX.stress(g, pos=pos),
        "aspect_ratio": gdMetriX.aspect_ratio(g, pos=pos),
        "area_per_node": gdMetriX.area(g, pos=pos) / max(n, 1),
        "homogeneity": gdMetriX.homogeneity(g, pos=pos),
        "coherence_to_average_flow": gdMetriX.coherence_to_average_flow(pathway.graph, pos=pos),
        "visual_symmetry": gdMetriX.visual_symmetry(g, pos=pos) if n <= SYMMETRY_MAX_NODES else None,
    }
    return {k: (float(v) if v is not None else None) for k, v in m.items()}


def _boxes(pathway: Pathway, pos: Positions):
    nodes = list(pathway.graph)
    boxes = []
    for n in nodes:
        d = pathway.graph.nodes[n]
        x, y = pos[n]
        w, h = d["width"] / 2, d["height"] / 2
        boxes.append(box(x - w, y - h, x + w, y + h))
    return nodes, boxes


def overlaps(pathway: Pathway, pos: Positions) -> dict[str, float]:
    """Pairs of node boxes that overlap (touching is no overlap), and the overlap area relative to the node area."""
    _, boxes = _boxes(pathway, pos)
    tree = STRtree(boxes)
    pairs, area = 0, 0.0
    for i, b in enumerate(boxes):
        for j in tree.query(b):
            if j > i:
                inter = b.intersection(boxes[j]).area
                if inter > 0:
                    pairs += 1
                    area += inter
    total = sum(b.area for b in boxes)
    return {"overlapping_pairs": float(pairs), "overlap_area_share": area / total if total else 0.0}


def participant_consistency(pathway: Pathway, pos: Positions) -> float | None:
    """Share of (reactant, product) pairs, over all reactions, that lie on opposite sides of their reaction node:
    their directions from the reaction node are more than 90 degrees apart. 1 = every reaction reads "through"
    its node. None without reactions that have both reactants and products."""
    g = pathway.graph
    opposite, pairs = 0, 0
    for r in pathway.reactions:
        c = np.array(pos[r], dtype=float)
        reactants = [np.array(pos[u]) - c for u, _, d in g.in_edges(r, data=True) if d["role"] == REACTANT]
        products = [np.array(pos[v]) - c for _, v, d in g.out_edges(r, data=True) if d["role"] == PRODUCT]
        for a in reactants:
            for b in products:
                pairs += 1
                opposite += float(np.dot(a, b)) < 0
    return opposite / pairs if pairs else None


def compartment_metrics(pathway: Pathway, pos: Positions) -> dict[str, float | None]:
    """With several compartments: the share of species that lie inside the hull of a compartment other than
    their own (0 = compartments well separated)."""
    by_comp: dict[str, list[str]] = {}
    for n, d in pathway.graph.nodes(data=True):
        if d["kind"] == SPECIES and d.get("compartment"):
            by_comp.setdefault(d["compartment"], []).append(n)
    if len(by_comp) < 2:
        return {"species_in_other_compartment": None}
    hulls = {}
    for c, members in by_comp.items():
        pts = np.array([pos[n] for n in members])
        if len(pts) >= 3:
            try:
                hulls[c] = Polygon(pts[ConvexHull(pts).vertices])
            except (ValueError, RuntimeError):  # collinear points: no hull (Qhull error)
                continue
    species = [n for members in by_comp.values() for n in members]
    intruders = sum(
        1
        for n in species
        if any(c != pathway.graph.nodes[n]["compartment"] and h.contains(Point(pos[n])) for c, h in hulls.items())
    )
    return {"species_in_other_compartment": intruders / len(species)}


def reference_similarity(pos: Positions, reference: Positions, k: int = 5) -> dict[str, float | None]:
    """Similarity to a reference layout on the nodes both have, invariant to translation, scale, rotation and
    mirroring: Procrustes disparity (0 = identical), Spearman correlation of pairwise distances, and the mean
    share of each node's k nearest neighbours that are the same."""
    common = sorted(set(pos) & set(reference))
    if len(common) < 3:
        return {"procrustes": None, "distance_correlation": None, "knn_preservation": None}
    a = np.array([pos[n] for n in common], dtype=float)
    b = np.array([reference[n] for n in common], dtype=float)
    _, _, disparity = procrustes(b, a)
    da, db = pdist(a), pdist(b)
    corr = spearmanr(da, db).statistic
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


def all_metrics(pathway: Pathway, pos: Positions, reference: Positions | None = None) -> dict[str, float | None]:
    m = general_metrics(pathway, pos)
    m.update(overlaps(pathway, pos))
    m["participant_consistency"] = participant_consistency(pathway, pos)
    m.update(compartment_metrics(pathway, pos))
    if reference is not None:
        m.update(reference_similarity(pos, reference))
    return m


__all__ = [
    "all_metrics",
    "compartment_metrics",
    "general_metrics",
    "overlaps",
    "participant_consistency",
    "reference_similarity",
]
