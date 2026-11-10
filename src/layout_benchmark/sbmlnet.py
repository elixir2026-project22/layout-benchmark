"""SBMLNetwork (https://github.com/sys-bio/SBMLNetwork): its auto layout as a layout, and its reader for layouts
stored in SBML (SBML Layout). It runs in its own environment, ``.tools/sbmlnetwork`` (see the README), through
``sbmlnetwork_helper.py``. (Pictures are drawn by layout-benchmark's own SVG renderer, the same way for every
layout.)
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import networkx as nx

from .drawing import Drawing
from .graph import CONSUMPTION, MODULATION, PRODUCTION, REACTION, SPECIES, Pathway

TOOL = Path(__file__).resolve().parents[2] / ".tools" / "sbmlnetwork"
HELPER = Path(__file__).with_name("sbmlnetwork_helper.py")


def available() -> bool:
    return (TOOL / ".venv" / "bin" / "python").exists()


def _helper(*args: str, timeout: float = 600) -> None:
    if not available():
        raise RuntimeError(f"SBMLNetwork is not set up in {TOOL} (see the README)")
    result = subprocess.run(
        [str(TOOL / ".venv" / "bin" / "python"), str(HELPER), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode:
        lines = [x for x in (result.stderr or result.stdout).strip().splitlines() if x.strip()]
        raise RuntimeError(lines[-1] if lines else f"SBMLNetwork helper failed ({result.returncode})")


def _to_drawing(pathway: Pathway, data: dict) -> Drawing:
    """An SBMLNetwork drawing (y down) as a Drawing (y up); arcs from the pathway graph where it has the edge."""
    g = nx.DiGraph()
    pos = {}
    for n in data["nodes"]:
        if n["of"] not in pathway.graph:
            continue
        d = pathway.graph.nodes[n["of"]]
        g.add_node(
            n["id"],
            of=n["of"],
            kind=REACTION if n["kind"] == "reaction" else SPECIES,
            label=d["label"],
            sbgn=d.get("sbgn"),
            width=d["width"],
            height=d["height"],
        )
        pos[n["id"]] = (n["x"], -n["y"])
    for e in data["edges"]:
        u, v = e["source"], e["target"]
        if u not in g or v not in g:
            continue
        a, b = g.nodes[u]["of"], g.nodes[v]["of"]
        if pathway.graph.has_edge(a, b):
            arc = pathway.graph.edges[a, b].get("arc", CONSUMPTION)
        else:
            arc = PRODUCTION if g.nodes[u]["kind"] == REACTION else MODULATION
        g.add_edge(u, v, arc=arc)
    compartments = {
        c["id"]: {
            "box": [c["x"], -(c["y"] + c["h"]), c["x"] + c["w"], -c["y"]],
            "label": pathway.compartments.get(c["id"], c["id"]),
        }
        for c in data.get("compartments", [])
        if c["w"] > 0 and c["h"] > 0
    }
    return Drawing(graph=g, pos=pos, compartments=compartments)


def autolayout(pathway: Pathway, seed: int) -> Drawing:
    """SBMLNetwork's auto layout (it adds aliases for well-connected species). ``seed`` is not used."""
    if pathway.source is None:
        raise RuntimeError("SBMLNetwork needs the SBML file")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "drawing.json"
        _helper("layout", str(Path(pathway.source).resolve()), str(out))
        return _to_drawing(pathway, json.loads(out.read_text()))


def read_layout(pathway: Pathway, layout_sbml: Path) -> Drawing:
    """The layout stored in an SBML file (SBML Layout), read by SBMLNetwork."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "drawing.json"
        _helper("read", str(Path(layout_sbml).resolve()), str(out))
        return _to_drawing(pathway, json.loads(out.read_text()))
