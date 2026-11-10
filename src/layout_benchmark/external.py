"""External layout tools, each run in its own environment under ``.tools/`` (see the README):

- MetaCarto 2 (https://github.com/forxhunter/MetaCarto, CC BY 4.0): constructive layout for metabolic networks
  (pathways drawn one by one, then packed on one canvas), read through COBRApy, written as an Escher map.
- sbml2escher (https://github.com/elixir2026-project22/sbml2escher): constraint-based grid layout, written as an
  Escher map.

Escher maps are read back as a ``Drawing`` (``escher_drawing``): every metabolite node, clones included, and
every reaction (at its midmarker), with each participant's edge routed through the map's markers as drawn.
COBRApy drops SBML's ``M_`` / ``R_`` id prefixes; ids are matched with and without them.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import networkx as nx

from .drawing import Drawing
from .graph import CONSUMPTION, PRODUCTION, REACTION, SPECIES, Pathway

TOOLS_DIR = Path(__file__).resolve().parents[2] / ".tools"


def _id_lookup(pathway: Pathway) -> dict[str, str]:
    """Escher / COBRApy id -> SBML id."""
    lookup = {}
    for n in pathway.graph:
        lookup[n] = n
        for prefix in ("M_", "R_"):
            if n.startswith(prefix):
                lookup.setdefault(n[len(prefix) :], n)
    return lookup


def escher_drawing(pathway: Pathway, escher_map: list | dict) -> Drawing:
    """The drawing of an Escher map (y up): its metabolite nodes (clones included; non-primary ones smaller), its
    reactions at their midmarkers, and an edge per drawn participant, routed through the segment markers."""
    body = escher_map[1] if isinstance(escher_map, list) else escher_map
    nodes = body["nodes"]
    lookup = _id_lookup(pathway)
    g = nx.DiGraph()
    pos = {}
    routes = {}

    def xy(node):
        return float(node["x"]), -float(node["y"])

    drawn = {}  # escher node id -> drawing node id
    for nid, node in nodes.items():
        if node.get("node_type") != "metabolite" or node.get("bigg_id") not in lookup:
            continue
        sid = lookup[node["bigg_id"]]
        primary = bool(node.get("node_is_primary"))
        d = pathway.graph.nodes[sid]
        scale = 1.0 if primary else 0.6  # Escher draws secondary clones (cofactors) smaller
        did = f"{sid}@{nid}"
        g.add_node(
            did,
            of=sid,
            kind=SPECIES,
            label=d["label"],
            sbgn=d.get("sbgn"),
            width=d["width"] * scale,
            height=d["height"] * scale,
            primary=primary,
        )
        pos[did] = xy(node)
        drawn[nid] = did

    for reaction in body["reactions"].values():
        rid = lookup.get(reaction.get("bigg_id"))
        if rid is None or pathway.graph.nodes[rid]["kind"] != REACTION:
            continue
        seg = nx.Graph()
        for s in reaction["segments"].values():
            seg.add_edge(s["from_node_id"], s["to_node_id"])
        mid = next((n for n in seg if nodes.get(n, {}).get("node_type") == "midmarker"), None)
        if mid is None:
            continue
        d = pathway.graph.nodes[rid]
        g.add_node(
            rid, of=rid, kind=REACTION, label=d["label"], sbgn=d.get("sbgn"), width=d["width"], height=d["height"]
        )
        pos[rid] = xy(nodes[mid])
        coefficient = {m["bigg_id"]: m["coefficient"] for m in reaction.get("metabolites", [])}
        for nid in seg:
            if nid not in drawn:
                continue
            path = nx.shortest_path(seg, nid, mid)
            inner = [xy(nodes[n]) for n in path[1:-1] if n in nodes]
            bigg = nodes[nid]["bigg_id"]
            if coefficient.get(bigg, 0) > 0:  # product: reaction -> metabolite
                g.add_edge(rid, drawn[nid], arc=PRODUCTION)
                routes[(rid, drawn[nid])] = inner[::-1]
            else:
                g.add_edge(drawn[nid], rid, arc=CONSUMPTION)
                routes[(drawn[nid], rid)] = inner
    return Drawing(graph=g, pos=pos, routes=routes)


def _run_tool(name: str, args: list[str], out_glob: str, pathway: Pathway) -> Drawing:
    """Run a tool under ``.tools/<name>`` (its own ``.venv``) with an output folder, read the Escher map it
    writes (``out_glob`` inside that folder)."""
    tool = TOOLS_DIR / name
    python = tool / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"{name} is not set up in {tool} (see the README)")
    if pathway.source is None:
        raise RuntimeError(f"{name} needs the SBML file")
    model = str(Path(pathway.source).resolve())
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [str(python), *[a.format(model=model, out=tmp) for a in args]],
            cwd=tool,
            capture_output=True,
            text=True,
            check=False,
        )
        maps = sorted(Path(tmp).glob(out_glob))
        if not maps:  # tools may exit non-zero on their own quality checks and still write the map
            raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or "no map written")
        drawing = escher_drawing(pathway, json.loads(maps[0].read_text()))
    if not drawing.pos:
        raise RuntimeError("no node of the model found in the map")
    return drawing


def metacarto(pathway: Pathway, seed: int) -> Drawing:
    """MetaCarto 2, the whole model on one canvas (``layout_v2.py --canvas-only``), with pFBA directions; for
    models where FBA cannot run (no objective, no flux bounds), without them (``--no-fba``). Deterministic:
    ``seed`` is ignored."""
    args = ["layout_v2.py", "--model", "{model}", "--canvas-only", "--out", "{out}", "--quiet"]
    try:
        return _run_tool("MetaCarto", args, "**/*_Canvas.json", pathway)
    except RuntimeError:
        return _run_tool("MetaCarto", [*args, "--no-fba"], "**/*_Canvas.json", pathway)


def sbml2escher(pathway: Pathway, seed: int) -> Drawing:
    """sbml2escher, structural map (no flux sampling), every eligible reaction."""
    args = [
        "sbml2escher.py",
        "--model",
        "{model}",
        "--no-sampling",
        "--coverage",
        "100",
        "--seed",
        str(seed),
        "--output-dir",
        "{out}",
    ]
    return _run_tool("sbml2escher", args, "escher_map.json", pathway)
