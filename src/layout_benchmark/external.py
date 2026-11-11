"""External layout tools, each run in its own environment under ``.tools/`` (see the README):

- MetaCarto 2 (https://github.com/forxhunter/MetaCarto, CC BY 4.0): constructive layout for metabolic networks
  (pathways drawn one by one, then packed on one canvas), read through COBRApy, written as an Escher map.
- sbml2map (https://github.com/elixir2026-project22/sbml2map, formerly sbml2escher): constraint-based grid layout
  (an exact optimisation, heuristic placement on large models), written as an Escher map.
- ecmapper (https://github.com/elixir2026-project22/ecmapper, GPL-3.0): draft maps from the BRENDA pathway map,
  matched by EC number; the subsystems arranged with few crossing links, or packed. An Escher map.
- sbml_pathway_layout
  (https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude): the project's layout
  rules (cycles as rings, pathways as layered backbones, cofactors written in the reaction box). An Escher map.

Escher maps are read back as a ``Drawing`` (``escher_drawing``): every metabolite node, clones included, and
every reaction (at its midmarker), with each participant's edge routed through the map's markers as drawn.
COBRApy drops SBML's ``M_`` / ``R_`` id prefixes, and sbml2map also decodes the ``__45__`` escapes (``glc__45__D``:
``glc-D``); ids are matched in all these forms.
"""

from __future__ import annotations

import json
import re
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
    for alias, n in list(lookup.items()):  # SBML's escapes of characters ids can't hold: __45__ is "-"
        lookup.setdefault(re.sub(r"__(\d+)__", lambda m: chr(int(m.group(1))), alias), n)
    return lookup


def escher_drawing(pathway: Pathway, escher_map: list | dict) -> Drawing:
    """The drawing of an Escher map (y up): its metabolite nodes (clones included; non-primary ones smaller), its
    reactions at their midmarkers (a reaction drawn more than once: clones), and an edge per drawn participant,
    routed through the segment markers."""
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

    for key, reaction in body["reactions"].items():
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
        did = rid if rid not in g else f"{rid}@{key}"  # a reaction drawn more than once: clones
        g.add_node(
            did, of=rid, kind=REACTION, label=d["label"], sbgn=d.get("sbgn"), width=d["width"], height=d["height"]
        )
        pos[did] = xy(nodes[mid])
        coefficient = {m["bigg_id"]: m["coefficient"] for m in reaction.get("metabolites", [])}
        for nid in seg:
            if nid not in drawn:
                continue
            path = nx.shortest_path(seg, nid, mid)
            inner = [xy(nodes[n]) for n in path[1:-1] if n in nodes]
            bigg = nodes[nid]["bigg_id"]
            if coefficient.get(bigg, 0) > 0:  # product: reaction -> metabolite
                g.add_edge(did, drawn[nid], arc=PRODUCTION)
                routes[(did, drawn[nid])] = inner[::-1]
            else:
                g.add_edge(drawn[nid], did, arc=CONSUMPTION)
                routes[(drawn[nid], did)] = inner
    return Drawing(graph=g, pos=pos, routes=routes)


def _run_tool(name: str, args: list[str], out_glob: str, pathway: Pathway) -> Drawing:
    """Run a tool under ``.tools/<name>`` (its own ``.venv``) with an output folder, read the Escher map it
    writes (``out_glob`` inside that folder)."""
    tool = TOOLS_DIR / name
    python = _python(name)
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
        maps = sorted(Path(tmp).glob(out_glob))  # tools may exit non-zero on their own checks and still write it
        return _escher_file(pathway, maps[0] if maps else Path(tmp) / out_glob, result)


def metacarto(pathway: Pathway, seed: int) -> Drawing:
    """MetaCarto 2, the whole model on one canvas (``layout_v2.py --canvas-only``), with pFBA directions; for
    models where FBA cannot run (no objective, no flux bounds), without them (``--no-fba``). Deterministic:
    ``seed`` is ignored."""
    args = ["layout_v2.py", "--model", "{model}", "--canvas-only", "--out", "{out}", "--quiet"]
    try:
        return _run_tool("MetaCarto", args, "**/*_Canvas.json", pathway)
    except RuntimeError:
        return _run_tool("MetaCarto", [*args, "--no-fba"], "**/*_Canvas.json", pathway)


def sbml2map(pathway: Pathway, seed: int) -> Drawing:
    """sbml2map, structural map (no flux sampling), every eligible reaction."""
    args = [
        "sbml2map.py",
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
    return _run_tool("sbml2map", args, "escher_map.json", pathway)


def _python(name: str) -> Path:
    python = TOOLS_DIR / name / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"{name} is not set up in {TOOLS_DIR / name} (see the README)")
    return python


def _escher_file(pathway: Pathway, path: Path, result: subprocess.CompletedProcess) -> Drawing:
    if not path.exists():
        raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or "no map written")
    drawing = escher_drawing(pathway, json.loads(path.read_text()))
    if not drawing.pos:
        raise RuntimeError("no node of the model found in the map")
    return drawing


def ecmapper(pathway: Pathway, seed: int, pack: bool = False) -> Drawing:
    """ecmapper's draft map: the model matched to the BRENDA map (``prepare``; with the subsystems from
    ``<model>.json`` next to the model, a BiGG JSON, where there is one), then the map (``run``): the subsystems
    arranged with few crossing links, or with ``pack`` packed without the links between them. Subsystems that
    ecmapper sets aside (drawn elsewhere already) go to a separate map, which isn't read."""
    python = _python("ecmapper")
    if pathway.source is None:
        raise RuntimeError("ecmapper needs the SBML file")
    model = Path(pathway.source).resolve()
    brenda = TOOLS_DIR / "ecmapper" / "BRENDAmap"
    with tempfile.TemporaryDirectory() as tmp:
        prep = Path(tmp) / "prep.pkl"
        args = ["-m", "ecmapper.draft_map.prepare", str(model), str(brenda / "BRENDA_map_reactions.json"), str(prep)]
        if model.with_suffix(".json").exists():
            args += ["--subsystems", str(model.with_suffix(".json"))]
        result = subprocess.run([str(python), *args], capture_output=True, text=True, check=False)
        if not prep.exists():
            raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or "prepare failed")
        out = Path(tmp) / "out"
        args = [
            "-m",
            "ecmapper.draft_map.run",
            str(prep),
            str(brenda / "BRENDA_map_reactions.json"),
            str(brenda / "BRENDA_map.svg"),
            str(out),
            "--seed",
            str(seed),
            *(["--pack"] if pack else []),
        ]
        result = subprocess.run([str(python), *args], capture_output=True, text=True, check=False)
        return _escher_file(pathway, out / "draft_map.escher.json", result)


def ecmapper_packed(pathway: Pathway, seed: int) -> Drawing:
    return ecmapper(pathway, seed, pack=True)


def rules_layout(pathway: Pathway, seed: int) -> Drawing:
    """sbml_pathway_layout.py, the whole model in one drawing (``--max-cluster`` above any model's size; by default
    models of more than 60 reactions are split into several drawings), read from its Escher map. Deterministic:
    ``seed`` is ignored."""
    python = _python("sbml_pathway_layout")
    if pathway.source is None:
        raise RuntimeError("sbml_pathway_layout needs the SBML file")
    with tempfile.TemporaryDirectory() as tmp:
        args = [
            str(TOOLS_DIR / "sbml_pathway_layout" / "sbml_pathway_layout.py"),
            str(Path(pathway.source).resolve()),
            "--out",
            str(Path(tmp) / "model"),
            "--max-cluster",
            "1000000",
            "--escher",
            "--no-sbml-layout",
        ]
        result = subprocess.run([str(python), *args], capture_output=True, text=True, check=False, cwd=tmp)
        return _escher_file(pathway, Path(tmp) / "model.escher.json", result)
