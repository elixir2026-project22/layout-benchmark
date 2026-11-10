"""A drawing: what a layout tool actually draws.

Most layouts draw the pathway graph as it is: one node per species and reaction, straight edges. Some tools draw
more: clones (a metabolite such as ATP drawn several times, each near the reaction that uses it) and routed edges
(with bends). A Drawing keeps that, so the picture shows the tool's layout as the tool meant it:

- ``graph``: the drawn nodes and edges. Every drawn node has ``of``, the pathway node it draws (clones share it),
  plus ``kind``, ``label``, ``width``, ``height``; edges have ``arc`` (SBGN arc class).
- ``pos``: drawn node centres (y up).
- ``routes``: per edge (u, v), the points between its ends (none: a straight line).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from .graph import Pathway

EDGE_LENGTH = 100.0
Point = tuple[float, float]
Positions = dict[str, Point]


@dataclass
class Drawing:
    graph: nx.DiGraph
    pos: Positions
    routes: dict[tuple[str, str], list[Point]] = field(default_factory=dict)

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

    def normalised(self) -> Drawing:
        """Centred and scaled so that the median drawn edge (end to end, straight) is EDGE_LENGTH long."""
        if not self.pos:
            return self
        xy = np.array(list(self.pos.values()), dtype=float)
        centre = xy.mean(axis=0)
        lengths = [float(np.hypot(*np.subtract(self.pos[u], self.pos[v]))) for u, v in self.graph.edges() if u != v]
        median = float(np.median(lengths)) if lengths else 0.0
        scale = EDGE_LENGTH / median if median > 0 else 1.0

        def t(p):
            return (float((p[0] - centre[0]) * scale), float((p[1] - centre[1]) * scale))

        return Drawing(
            graph=self.graph,
            pos={n: t(p) for n, p in self.pos.items()},
            routes={e: [t(p) for p in pts] for e, pts in self.routes.items()},
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
        }
