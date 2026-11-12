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
from dataclasses import dataclass
from pathlib import Path

import igraph as ig
import networkx as nx

from .drawing import Drawing, Positions
from .external import ecmapper, ecmapper_packed, metacarto, rules_layout, sbml2map
from .graph import REACTION, Pathway, reaction_compartment
from .sbmlnet import autolayout

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


def _graphology(algorithm: str) -> Callable[[Pathway, int], Drawing]:
    """A graphology (Sigma.js) or Reagraph layout run by ``js/graph.mjs`` (Node, ``npm ci`` in ``js/``). Nodes keep
    the sizes the layout works with, in its units: Reagraph's spheres (radius 10), noverlap's circles; none for
    plain ForceAtlas2 (Sigma sizes nodes in screen pixels). With compartments (Reagraph's ``clusterAttribute``),
    species are grouped by compartment and reactions by ``graph.reaction_compartment``."""

    def run(pathway: Pathway, seed: int) -> Drawing:
        if not (JS_DIR / "node_modules").exists():
            raise RuntimeError(f"graphology and Reagraph layouts need: cd {JS_DIR} && npm ci")
        g = pathway.graph

        def group(n, d):
            return reaction_compartment(pathway, n) if d["kind"] == REACTION else d.get("compartment")

        payload = {
            "algorithm": algorithm,
            "seed": seed,
            "nodes": [
                {"id": n, "width": d["width"], "height": d["height"], "group": group(n, d)}
                for n, d in g.nodes(data=True)
            ],
            "edges": [{"source": u, "target": v} for u, v in g.edges() if u != v],
        }
        result = subprocess.run(
            ["node", str(JS_DIR / "graph.mjs")], input=json.dumps(payload), capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-500:])
        out = json.loads(result.stdout)
        drawing = Drawing.of(pathway, {n: (float(x), float(y)) for n, (x, y) in out["positions"].items()})  # y up
        for n, r in out.get("sizes", {}).items():
            drawing.graph.nodes[n].update(own_shape="circle", own_width=2 * r, own_height=2 * r)
        return drawing

    return run


# --- The registry ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutSpec:
    """A layout: its name, the function (``(pathway, seed) -> positions or Drawing``), its group, where it is
    documented, how its node sizes are known when a saved drawing lacks them (``sizes``: "given" = the sizes we
    give the tool, which lays out around them; "escher" = Escher's circles; None = no node sizes), and the tool it
    needs under ``.tools/`` (None: installed with the package), and the packages whose versions are recorded
    with each run (``"py:<name>"``, ``"npm:<name>"``, ``"graphviz:"``; see ``versions``)."""

    name: str
    run: Callable[[Pathway, int], Positions | Drawing]
    group: str
    link: str
    sizes: str | None = None
    tool: str | None = None
    packages: tuple[str, ...] = ()


_IGRAPH = "https://python.igraph.org/en/stable/api/igraph.Graph.html#"
_NETWORKX = "https://networkx.org/documentation/stable/reference/generated/networkx.drawing.layout."
_ELK = "https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-"
_ECMAPPER = "https://github.com/elixir2026-project22/ecmapper/blob/main/DRAFT_MAP.md"
_FCOSE = "https://github.com/iVis-at-Bilkent/cytoscape.js-fcose"
_COSE_BILKENT = "https://github.com/cytoscape/cytoscape.js-cose-bilkent"
_FA2 = "https://graphology.github.io/standard-library/layout-forceatlas2.html"
_REAGRAPH = "https://reagraph.dev/docs/getting-started/Layouts"


def _gv(prog: str, group: str) -> LayoutSpec:
    link = f"https://graphviz.org/docs/layouts/{prog}/"
    return LayoutSpec(
        f"graphviz-{prog}", _graphviz(prog), group, link, "given", packages=("py:pygraphviz", "graphviz:")
    )


def _cy(name: str, group: str, link: str, algorithm: str | None = None, **kwargs) -> LayoutSpec:
    algorithm = algorithm or name
    if algorithm == "cose":  # built into cytoscape.js
        extension = ()
    elif algorithm.startswith("elk"):
        extension = ("npm:cytoscape-elk", "npm:elkjs")
    else:
        extension = (f"npm:cytoscape-{algorithm}",)
    packages = ("npm:cytoscape", *extension)
    return LayoutSpec(f"cytoscape-{name}", _cytoscape(algorithm, **kwargs), group, link, "given", packages=packages)


def _ig(method: str, function: str, group: str, **kwargs) -> LayoutSpec:
    return LayoutSpec(f"igraph-{method}", _igraph(method, **kwargs), group, _IGRAPH + function, packages=("py:igraph",))


def _nx(name: str, group: str) -> LayoutSpec:
    link = f"{_NETWORKX}{name}_layout.html"
    return LayoutSpec(f"networkx-{name}", _networkx(name), group, link, packages=("py:networkx",))


# In the order of how promising they are expected to be for pathway maps (before any scoring; also the report's
# order), with their group: tools made for pathway maps; force-directed with compartments as groups; layered
# (flows read in one direction); stress-based; generic force-directed; for large graphs; radial, circular and
# tree; baselines.
REGISTRY: list[LayoutSpec] = [
    LayoutSpec(
        "rules-claude",
        rules_layout,
        "pathway-specific",
        "https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude",
        "escher",
        "sbml_pathway_layout",
    ),
    LayoutSpec("ecmapper-brenda", ecmapper, "pathway-specific", _ECMAPPER, "escher", "ecmapper"),
    LayoutSpec("ecmapper-brenda-packed", ecmapper_packed, "pathway-specific", _ECMAPPER, "escher", "ecmapper"),
    LayoutSpec(
        "metacarto", metacarto, "pathway-specific", "https://github.com/forxhunter/MetaCarto", "escher", "MetaCarto"
    ),
    LayoutSpec(
        "sbml2map",
        sbml2map,
        "pathway-specific",
        "https://github.com/elixir2026-project22/sbml2map",
        "escher",
        "sbml2map",
    ),
    # SBMLNetwork's drawings carry their own glyph sizes
    LayoutSpec(
        "sbmlnetwork", autolayout, "SBML-specific", "https://github.com/sys-bio/SBMLNetwork", None, "sbmlnetwork"
    ),
    _cy("fcose-compartments", "compartments as groups", _FCOSE, "fcose", compound=True),
    _cy("cose-bilkent-compartments", "compartments as groups", _COSE_BILKENT, "cose-bilkent", compound=True),
    LayoutSpec(
        "reagraph-force-compartments",
        _graphology("reagraph-force-compartments"),
        "compartments as groups",
        _REAGRAPH,
        packages=("npm:reagraph",),
    ),
    _cy("fcose", "compound-capable force-directed", _FCOSE),
    _cy("cose-bilkent", "compound-capable force-directed", _COSE_BILKENT),
    _cy("elk-layered", "layered", _ELK + "layered.html"),
    _gv("dot", "layered"),
    _cy("dagre", "layered", "https://github.com/cytoscape/cytoscape.js-dagre"),
    _cy("klay", "layered", "https://github.com/cytoscape/cytoscape.js-klay"),
    _ig("sugiyama", "layout_sugiyama", "layered"),
    _gv("neato", "stress"),
    _cy("elk-stress", "stress", _ELK + "stress.html"),
    _cy("cola", "stress, with constraints", "https://github.com/cytoscape/cytoscape.js-cola"),
    _nx("kamada_kawai", "stress"),
    _ig("kk", "layout_kamada_kawai", "stress"),
    _gv("sfdp", "force-directed"),
    _gv("fdp", "force-directed"),
    _ig("fr", "layout_fruchterman_reingold", "force-directed"),
    _nx("spring", "force-directed"),
    _cy("cose", "force-directed", "https://js.cytoscape.org/#layouts/cose"),
    _cy("elk-force", "force-directed", _ELK + "force.html"),
    LayoutSpec(
        "graphology-forceatlas2",
        _graphology("forceatlas2"),
        "force-directed",
        _FA2,
        packages=("npm:graphology", "npm:graphology-layout-forceatlas2"),
    ),
    LayoutSpec(
        "graphology-forceatlas2-noverlap",
        _graphology("forceatlas2-noverlap"),
        "force-directed",
        _FA2,
        packages=("npm:graphology", "npm:graphology-layout-forceatlas2", "npm:graphology-layout-noverlap"),
    ),
    LayoutSpec(
        "reagraph-force", _graphology("reagraph-force"), "force-directed", _REAGRAPH, packages=("npm:reagraph",)
    ),
    _ig("graphopt", "layout_graphopt", "force-directed"),
    _ig("drl", "layout_drl", "for large graphs"),
    _ig("lgl", "layout_lgl", "for large graphs"),
    _gv("twopi", "radial"),
    _gv("circo", "circular"),
    _cy("elk-mrtree", "tree", _ELK + "mrtree.html"),
    _ig("mds", "layout_mds", "baseline"),
    _nx("spectral", "baseline"),
]
SPECS = {s.name: s for s in REGISTRY}
assert len(SPECS) == len(REGISTRY), "duplicate layout names"
LAYOUTS: dict[str, Callable[[Pathway, int], Positions | Drawing]] = {s.name: s.run for s in REGISTRY}
GROUP = {s.name: s.group for s in REGISTRY}
LINKS = {s.name: s.link for s in REGISTRY}


def expected_rank(name: str) -> int:
    """Position in the registry (unknown layouts last)."""
    return next((i for i, s in enumerate(REGISTRY) if s.name == name), len(REGISTRY))


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
