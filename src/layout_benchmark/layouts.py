"""Layout algorithms behind one interface: ``layout(name, pathway, seed) -> Drawing``.

An algorithm returns node centres ``{node: (x, y)}`` (y up), or a ``Drawing`` when it draws more than the pathway
graph (clones, routed edges; see ``drawing``). Results keep the tool's own coordinates (y up); the common scale
for pictures and metrics is applied later (``Drawing.normalised``).
"""

from __future__ import annotations

import json
import random
import subprocess
from collections.abc import Callable
from pathlib import Path

import igraph as ig
import networkx as nx

from .drawing import Drawing, Positions
from .graph import REACTION, Pathway, reaction_compartment

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


def _cytoscape(algorithm: str, compound: bool = False, reactions: bool = True) -> Callable[[Pathway, int], Positions]:
    """A cytoscape.js layout run by ``js/layout.mjs`` (needs Node and ``npm ci`` in ``js/``). With ``compound``,
    compartments are compound parent nodes holding their species; with ``reactions`` (the option, on by default),
    reactions are placed in a compartment too (``graph.reaction_compartment``: their SBML compartment, else that of
    their reactants and products; transports stay between the compartments). The compound algorithms expect every
    node in a compartment: left outside, reactions stretch their edges across the picture."""

    def run(pathway: Pathway, seed: int) -> Positions:
        if not (JS_DIR / "node_modules").exists():
            raise RuntimeError(f"cytoscape.js layouts need: cd {JS_DIR} && npm ci")
        g = pathway.graph
        parents = sorted({d["compartment"] for _, d in g.nodes(data=True) if d.get("compartment")})

        def parent(n, d):
            if compound and reactions and d["kind"] == REACTION:
                return reaction_compartment(pathway, n)
            return d.get("compartment")

        payload = {
            "algorithm": algorithm,
            "seed": seed,
            "compound": compound and len(parents) > 1,
            "parents": parents,
            "nodes": [
                {"id": n, "width": d["width"], "height": d["height"], "parent": parent(n, d)}
                for n, d in g.nodes(data=True)
            ],
            "edges": [{"source": u, "target": v} for u, v in g.edges() if u != v],
        }
        result = subprocess.run(
            ["node", str(JS_DIR / "layout.mjs")], input=json.dumps(payload), capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:])
        out = json.loads(result.stdout)
        pos = {n: (float(x), -float(y)) for n, (x, y) in out["positions"].items()}  # y up
        if not out.get("compartments"):
            return pos
        # compound layouts: the compartments' boxes as cytoscape.js computed them (y up)
        drawing = Drawing.of(pathway, pos)
        drawing.compartments = {
            c: {"box": [x1, -y2, x2, -y1], "label": pathway.compartments.get(c, c)}
            for c, (x1, y1, x2, y2) in out["compartments"].items()
        }
        return drawing

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
    from .external import ecmapper, ecmapper_packed, metacarto, rules_layout, sbml2map
    from .sbmlnet import autolayout

    LAYOUTS["rules-claude"] = rules_layout
    LAYOUTS["ecmapper-brenda"] = ecmapper
    LAYOUTS["ecmapper-brenda-packed"] = ecmapper_packed
    LAYOUTS["metacarto"] = metacarto
    LAYOUTS["sbml2map"] = sbml2map
    LAYOUTS["sbmlnetwork"] = autolayout


_register_external()


def layout(name: str, pathway: Pathway, seed: int = 0) -> Drawing:
    """Lay out with a registered algorithm, in its own coordinates. Tools that draw only part of a model (e.g.
    leave out boundary species) place fewer nodes: ``Drawing.placed()``."""
    if name not in LAYOUTS:
        raise ValueError(f"unknown layout {name!r}, one of: {', '.join(LAYOUTS)}")
    result = LAYOUTS[name](pathway, seed)
    drawing = result if isinstance(result, Drawing) else Drawing.of(pathway, result)
    if not drawing.pos:
        raise RuntimeError(f"{name}: no positions")
    return drawing


# The layouts in the order of how promising they are expected to be for pathway maps (before any scoring), with
# their group: tools made for pathway maps; force-directed with compartments as groups; layered (flows read in one
# direction); stress-based; generic force-directed; for large graphs; radial, circular and tree; baselines.
EXPECTED = [
    ("rules-claude", "pathway-specific"),
    ("ecmapper-brenda", "pathway-specific"),
    ("ecmapper-brenda-packed", "pathway-specific"),
    ("metacarto", "pathway-specific"),
    ("sbml2map", "pathway-specific"),
    ("sbmlnetwork", "SBML-specific"),
    ("cytoscape-fcose-compartments", "compartments as groups"),
    ("cytoscape-cose-bilkent-compartments", "compartments as groups"),
    ("cytoscape-fcose", "compound-capable force-directed"),
    ("cytoscape-cose-bilkent", "compound-capable force-directed"),
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


_IGRAPH = "https://python.igraph.org/en/stable/api/igraph.Graph.html#"
_NETWORKX = "https://networkx.org/documentation/stable/reference/generated/networkx.drawing.layout."
_ELK = "https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-"
# where each layout algorithm is documented (shown in the report)
LINKS = {
    "rules-claude": "https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude",
    "ecmapper-brenda": "https://github.com/elixir2026-project22/ecmapper/blob/main/DRAFT_MAP.md",
    "ecmapper-brenda-packed": "https://github.com/elixir2026-project22/ecmapper/blob/main/DRAFT_MAP.md",
    "metacarto": "https://github.com/forxhunter/MetaCarto",
    "sbml2map": "https://github.com/elixir2026-project22/sbml2map",
    "sbmlnetwork": "https://github.com/sys-bio/SBMLNetwork",
    "cytoscape-fcose": "https://github.com/iVis-at-Bilkent/cytoscape.js-fcose",
    "cytoscape-fcose-compartments": "https://github.com/iVis-at-Bilkent/cytoscape.js-fcose",
    "cytoscape-cose-bilkent": "https://github.com/cytoscape/cytoscape.js-cose-bilkent",
    "cytoscape-cose-bilkent-compartments": "https://github.com/cytoscape/cytoscape.js-cose-bilkent",
    "cytoscape-cose": "https://js.cytoscape.org/#layouts/cose",
    "cytoscape-cola": "https://github.com/cytoscape/cytoscape.js-cola",
    "cytoscape-dagre": "https://github.com/cytoscape/cytoscape.js-dagre",
    "cytoscape-klay": "https://github.com/cytoscape/cytoscape.js-klay",
    "cytoscape-elk-layered": _ELK + "layered.html",
    "cytoscape-elk-stress": _ELK + "stress.html",
    "cytoscape-elk-force": _ELK + "force.html",
    "cytoscape-elk-mrtree": _ELK + "mrtree.html",
    **{
        f"graphviz-{p}": f"https://graphviz.org/docs/layouts/{p}/"
        for p in ("dot", "neato", "fdp", "sfdp", "twopi", "circo")
    },
    "igraph-fr": _IGRAPH + "layout_fruchterman_reingold",
    "igraph-kk": _IGRAPH + "layout_kamada_kawai",
    "igraph-drl": _IGRAPH + "layout_drl",
    "igraph-graphopt": _IGRAPH + "layout_graphopt",
    "igraph-lgl": _IGRAPH + "layout_lgl",
    "igraph-mds": _IGRAPH + "layout_mds",
    "igraph-sugiyama": _IGRAPH + "layout_sugiyama",
    "networkx-spring": _NETWORKX + "spring_layout.html",
    "networkx-kamada_kawai": _NETWORKX + "kamada_kawai_layout.html",
    "networkx-spectral": _NETWORKX + "spectral_layout.html",
}
assert set(LINKS) == set(LAYOUTS), set(LINKS) ^ set(LAYOUTS)
