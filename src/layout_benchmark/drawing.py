"""A drawing: what a layout tool actually draws.

Most layouts draw the pathway graph as it is: one node per species and reaction, straight edges. Some tools draw
more: clones (a metabolite such as ATP drawn several times, each near the reaction that uses it) and routed edges
(with bends). A Drawing keeps that, so the picture shows the tool's layout as the tool meant it:

- ``graph``: the drawn nodes and edges. Every drawn node has ``of``, the pathway node it draws (clones share it),
  plus ``kind``, ``label``, ``width``, ``height``; edges have ``arc`` (SBGN arc class).
- ``pos``: drawn node centres (y up).
- ``routes``: per edge (u, v), the points between its ends (none: a straight line).
- ``compartments``: the compartment boxes the tool (or reference) drew, by compartment id:
  ``{"box": [x0, y0, x1, y1], "label": name}`` (y up). Empty when the tool draws no compartments.

Positions are the tool's own. For drawing (and for metrics that use node sizes), ``normalised()`` scales a drawing
uniformly, so that nearest neighbours are SPACING node widths apart: a uniform scale changes no shape, angle or
crossing of the layout, only how big the fixed-size nodes are relative to the spacing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from .graph import Pathway

# drawing scale: the median distance from a node to its nearest drawn neighbour, in median node widths
SPACING = 1.5
Point = tuple[float, float]
Positions = dict[str, Point]


@dataclass
class Drawing:
    graph: nx.DiGraph
    pos: Positions
    routes: dict[tuple[str, str], list[Point]] = field(default_factory=dict)
    compartments: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def of(cls, pathway: Pathway, pos: Positions) -> Drawing:
        """The pathway graph itself (no clones, straight edges), on the nodes that have a position."""
        g = pathway.graph.subgraph([n for n in pathway.graph if n in pos]).copy()
        nx.set_node_attributes(g, {n: n for n in g}, "of")
        return cls(graph=g, pos={n: pos[n] for n in g})

    @property
    def has_clones(self) -> bool:
        ofs = [d["of"] for _, d in self.graph.nodes(data=True)]
        return len(ofs) != len(set(ofs))

    def placed(self) -> set[str]:
        """The pathway nodes drawn at least once."""
        return {d["of"] for _, d in self.graph.nodes(data=True)}

    def node_positions(self) -> Positions:
        """One position per pathway node: its primary drawn node (``primary`` set), else the first."""
        pos: Positions = {}
        for n, d in self.graph.nodes(data=True):
            if d["of"] not in pos or d.get("primary"):
                pos[d["of"]] = self.pos[n]
        return pos

    def scale_factor(self) -> float:
        """The factor that puts nearest neighbours SPACING median node widths apart (1 if undefined)."""
        if len(self.pos) < 2:
            return 1.0
        nodes = list(self.pos)
        xy = np.array([self.pos[n] for n in nodes], dtype=float)
        distances = cKDTree(xy).query(xy, k=2)[0][:, 1]
        distances = distances[distances > 0]  # nodes drawn on top of each other say nothing about the spacing
        widths = [self.graph.nodes[n].get("width") or 0 for n in nodes]
        width = float(np.median([w for w in widths if w > 0])) if any(w > 0 for w in widths) else 1.0
        if not len(distances):
            return 1.0
        return SPACING * width / float(np.median(distances))

    def normalised(self) -> Drawing:
        """Centred and scaled uniformly by ``scale_factor()``; nothing else changes."""
        if not self.pos:
            return self
        xy = np.array(list(self.pos.values()), dtype=float)
        centre = xy.mean(axis=0)
        scale = self.scale_factor()

        def t(p):
            return (float((p[0] - centre[0]) * scale), float((p[1] - centre[1]) * scale))

        def box(c):
            (x0, y0), (x1, y1) = t(c["box"][:2]), t(c["box"][2:])
            return {**c, "box": [x0, y0, x1, y1]}

        return Drawing(
            graph=self.graph,
            pos={n: t(p) for n, p in self.pos.items()},
            routes={e: [t(p) for p in pts] for e, pts in self.routes.items()},
            compartments={k: box(c) for k, c in self.compartments.items()},
        )

    def to_json(self) -> dict:
        """The drawing as data: nodes (centre x, y with y up; size; the pathway node they draw), edges (with their
        arc class and route points, if any)."""
        return {
            "nodes": [
                {
                    "id": n,
                    "of": d["of"],
                    "kind": d["kind"],
                    "sbgn": d.get("sbgn"),
                    "label": d.get("label"),
                    "x": self.pos[n][0],
                    "y": self.pos[n][1],
                    "width": d.get("width"),
                    "height": d.get("height"),
                }
                for n, d in self.graph.nodes(data=True)
            ],
            "edges": [
                {"source": u, "target": v, "arc": d.get("arc"), "route": self.routes.get((u, v), [])}
                for u, v, d in self.graph.edges(data=True)
            ],
            "compartments": self.compartments,
        }

    @classmethod
    def from_json(cls, data: dict) -> Drawing:
        """The inverse of ``to_json``."""
        g = nx.DiGraph()
        pos = {}
        for n in data["nodes"]:
            attributes = {k: v for k, v in n.items() if k not in ("id", "x", "y")}
            g.add_node(n["id"], **attributes)
            pos[n["id"]] = (float(n["x"]), float(n["y"]))
        routes = {}
        for e in data["edges"]:
            g.add_edge(e["source"], e["target"], arc=e.get("arc"))
            if e.get("route"):
                routes[(e["source"], e["target"])] = [tuple(p) for p in e["route"]]
        return cls(graph=g, pos=pos, routes=routes, compartments=data.get("compartments") or {})
