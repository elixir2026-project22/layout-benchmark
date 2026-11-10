"""Layout algorithms behind one interface: ``layout(name, pathway, seed) -> Drawing``.

An algorithm returns node centres ``{node: (x, y)}`` (y up), or a ``Drawing`` when it draws more than the pathway
graph (clones, routed edges; see ``drawing``). Every result is normalised: the median edge length becomes
EDGE_LENGTH, so that metrics that use node sizes (overlaps) compare fairly across algorithms whose coordinates
have different units.
"""

from __future__ import annotations

import json
import random
import subprocess
from collections.abc import Callable
from pathlib import Path

import igraph as ig
import networkx as nx
import numpy as np

from .drawing import EDGE_LENGTH, Drawing, Positions
from .graph import Pathway


def normalise(pathway: Pathway, pos: Positions) -> Positions:
    """Scale (and centre) positions so that the median edge length is EDGE_LENGTH (for references)."""
    nodes = list(pos)
    xy = np.array([pos[n] for n in nodes], dtype=float)
    xy -= xy.mean(axis=0)
    lengths = [
        np.hypot(*np.subtract(pos[u], pos[v])) for u, v in pathway.graph.edges() if u != v and u in pos and v in pos
    ]
    median = float(np.median(lengths)) if lengths else 0.0
    if median > 0:
        xy *= EDGE_LENGTH / median
    return {n: (float(x), float(y)) for n, (x, y) in zip(nodes, xy)}


# --- Graphviz ------------------------------------------------------------------------------------------------


def _graphviz(prog: str) -> Callable[[Pathway, int], Positions]:
    def run(pathway: Pathway, seed: int) -> Positions:
        import pygraphviz

        a = pygraphviz.AGraph(directed=True, strict=False)
        # overlap removal: "scale" (the default, prism, needs Graphviz built with GTS, which distributions often lack)
        a.graph_attr.update(start=str(seed), overlap="scale" if prog != "dot" else "true", splines="false")
        a.node_attr.update(shape="box", fixedsize="true", label="")
        # stable ids for Graphviz (SBML ids can clash with its keywords)
        ids = {n: f"n{i}" for i, n in enumerate(pathway.graph)}
        for n, d in pathway.graph.nodes(data=True):
            a.add_node(ids[n], width=d["width"] / 72, height=d["height"] / 72)
        for u, v in pathway.graph.edges():
            a.add_edge(ids[u], ids[v])
        a.layout(prog=prog)
        back = {i: n for n, i in ids.items()}
        return {back[str(node)]: tuple(map(float, node.attr["pos"].split(",")[:2])) for node in a.nodes()}

    return run


# --- igraph --------------------------------------------------------------------------------------------------


def _igraph(method: str, **kwargs) -> Callable[[Pathway, int], Positions]:
    def run(pathway: Pathway, seed: int) -> Positions:
        nodes = list(pathway.graph)
        index = {n: i for i, n in enumerate(nodes)}
        g = ig.Graph(n=len(nodes), edges=[(index[u], index[v]) for u, v in pathway.graph.edges()], directed=True)
        random.seed(seed)
        ig.set_random_number_generator(random)
        if method == "sugiyama":
            layout = g.layout_sugiyama(**kwargs)
        else:
            layout = g.as_undirected().layout(method, **kwargs)
        coords = layout.coords[: len(nodes)]  # sugiyama adds dummy vertices after the real ones
        return {n: (float(c[0]), float(c[1])) for n, c in zip(nodes, coords)}

    return run


# --- networkx ------------------------------------------------------------------------------------------------


def _networkx(name: str) -> Callable[[Pathway, int], Positions]:
    def run(pathway: Pathway, seed: int) -> Positions:
        g = pathway.undirected()
        if name == "spring":
            pos = nx.spring_layout(g, seed=seed)
        elif name == "kamada_kawai":
            # per connected component, then side by side (KK needs a connected graph)
            pos = {}
            offset = 0.0
            for comp in sorted(nx.connected_components(g), key=len, reverse=True):
                sub = nx.kamada_kawai_layout(g.subgraph(comp)) if len(comp) > 1 else {next(iter(comp)): (0, 0)}
                for n, (x, y) in sub.items():
                    pos[n] = (x + offset, y)
                offset += 2.5
        elif name == "spectral":
            pos = nx.spectral_layout(g)
        else:
            raise ValueError(name)
        return {n: (float(x), float(y)) for n, (x, y) in pos.items()}

    return run


# --- cytoscape.js (Node, headless) -----------------------------------------------------------------------------

JS_DIR = Path(__file__).parent / "js"


def _cytoscape(algorithm: str, compound: bool = False) -> Callable[[Pathway, int], Positions]:
    """A cytoscape.js layout run by ``js/layout.mjs`` (needs Node and ``npm ci`` in ``js/``). With ``compound``,
    the species' compartments are compound parent nodes."""

    def run(pathway: Pathway, seed: int) -> Positions:
        if not (JS_DIR / "node_modules").exists():
            raise RuntimeError(f"cytoscape.js layouts need: cd {JS_DIR} && npm ci")
        g = pathway.graph
        parents = sorted({d["compartment"] for _, d in g.nodes(data=True) if d.get("compartment")})
        payload = {
            "algorithm": algorithm,
            "seed": seed,
            "compound": compound and len(parents) > 1,
            "parents": parents,
            "nodes": [
                {"id": n, "width": d["width"], "height": d["height"], "parent": d.get("compartment")}
                for n, d in g.nodes(data=True)
            ],
            "edges": [{"source": u, "target": v} for u, v in g.edges() if u != v],
        }
        result = subprocess.run(
            ["node", str(JS_DIR / "layout.mjs")], input=json.dumps(payload), capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:])
        positions = json.loads(result.stdout)["positions"]
        return {n: (float(x), -float(y)) for n, (x, y) in positions.items()}  # y up

    return run


LAYOUTS: dict[str, Callable[[Pathway, int], Positions]] = {
    **{f"graphviz-{p}": _graphviz(p) for p in ("dot", "neato", "fdp", "sfdp", "twopi", "circo")},
    "igraph-fr": _igraph("fr"),
    "igraph-kk": _igraph("kk"),
    "igraph-drl": _igraph("drl"),
    "igraph-graphopt": _igraph("graphopt"),
    "igraph-lgl": _igraph("lgl"),
    "igraph-mds": _igraph("mds"),
    "igraph-sugiyama": _igraph("sugiyama"),
    "networkx-spring": _networkx("spring"),
    "networkx-kamada_kawai": _networkx("kamada_kawai"),
    "networkx-spectral": _networkx("spectral"),
    "cytoscape-fcose": _cytoscape("fcose"),
    "cytoscape-fcose-compartments": _cytoscape("fcose", compound=True),
    "cytoscape-cose-bilkent": _cytoscape("cose-bilkent"),
    "cytoscape-cose-bilkent-compartments": _cytoscape("cose-bilkent", compound=True),
    "cytoscape-cose": _cytoscape("cose"),
    "cytoscape-cola": _cytoscape("cola"),
    "cytoscape-dagre": _cytoscape("dagre"),
    "cytoscape-klay": _cytoscape("klay"),
    "cytoscape-elk-layered": _cytoscape("elk-layered"),
    "cytoscape-elk-stress": _cytoscape("elk-stress"),
    "cytoscape-elk-force": _cytoscape("elk-force"),
    "cytoscape-elk-mrtree": _cytoscape("elk-mrtree"),
}


def _register_external():
    from .external import metacarto, sbml2escher
    from .sbmlnet import autolayout

    LAYOUTS["metacarto"] = metacarto
    LAYOUTS["sbml2escher"] = sbml2escher
    LAYOUTS["sbmlnetwork"] = autolayout


_register_external()


def layout(name: str, pathway: Pathway, seed: int = 0) -> Drawing:
    """Lay out with a registered algorithm, normalised. Tools that draw only part of a model (e.g. leave out
    boundary species) place fewer nodes: ``Drawing.placed()``."""
    if name not in LAYOUTS:
        raise ValueError(f"unknown layout {name!r}, one of: {', '.join(LAYOUTS)}")
    result = LAYOUTS[name](pathway, seed)
    drawing = result if isinstance(result, Drawing) else Drawing.of(pathway, result)
    if not drawing.pos:
        raise RuntimeError(f"{name}: no positions")
    return drawing.normalised()


# The layouts in the order of how promising they are expected to be for pathway maps (before any scoring), with
# their group: tools made for pathway maps; force-directed with compartments as groups; layered (flows read in one
# direction); stress-based; generic force-directed; for large graphs; radial, circular and tree; baselines.
EXPECTED = [
    ("metacarto", "pathway-specific"),
    ("sbml2escher", "pathway-specific"),
    ("cytoscape-fcose-compartments", "compartments as groups"),
    ("cytoscape-cose-bilkent-compartments", "compartments as groups"),
    ("cytoscape-fcose", "compound-capable force-directed"),
    ("cytoscape-cose-bilkent", "compound-capable force-directed"),
    ("sbmlnetwork", "SBML-specific"),
    ("cytoscape-elk-layered", "layered"),
    ("graphviz-dot", "layered"),
    ("cytoscape-dagre", "layered"),
    ("cytoscape-klay", "layered"),
    ("igraph-sugiyama", "layered"),
    ("graphviz-neato", "stress"),
    ("cytoscape-elk-stress", "stress"),
    ("cytoscape-cola", "stress, with constraints"),
    ("networkx-kamada_kawai", "stress"),
    ("igraph-kk", "stress"),
    ("graphviz-sfdp", "force-directed"),
    ("graphviz-fdp", "force-directed"),
    ("igraph-fr", "force-directed"),
    ("networkx-spring", "force-directed"),
    ("cytoscape-cose", "force-directed"),
    ("cytoscape-elk-force", "force-directed"),
    ("igraph-graphopt", "force-directed"),
    ("igraph-drl", "for large graphs"),
    ("igraph-lgl", "for large graphs"),
    ("graphviz-twopi", "radial"),
    ("graphviz-circo", "circular"),
    ("cytoscape-elk-mrtree", "tree"),
    ("igraph-mds", "baseline"),
    ("networkx-spectral", "baseline"),
]
GROUP = dict(EXPECTED)
assert set(GROUP) == set(LAYOUTS), set(GROUP) ^ set(LAYOUTS)


def expected_rank(name: str) -> int:
    """Position in EXPECTED (unknown layouts last)."""
    order = [n for n, _ in EXPECTED]
    return order.index(name) if name in order else len(order)
