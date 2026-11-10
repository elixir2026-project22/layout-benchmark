"""Reference (hand-made) layouts to compare against."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .drawing import Positions
from .graph import Pathway

SBGN_NS = {"s": "http://sbgn.org/libsbgn/0.2", "s3": "http://sbgn.org/libsbgn/0.3"}


def _glyph_for(node_id: str, glyphs) -> str | None:
    """The gallery SBGN glyph of an SBML id: s_<glyph> / re_<glyph>; a component of a complex: s_n2_n0 is
    glyph n2__n0."""
    glyph = node_id.split("_", 1)[1] if "_" in node_id else node_id
    for candidate in (glyph, glyph.replace("_", "__")):
        if candidate in glyphs:
            return candidate
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sbgn_processes(path: str | Path) -> dict[str, set[str]]:
    """Per glyph id: the process glyphs it is connected to by an arc (ports resolved to their process)."""
    root = ET.parse(path).getroot()
    owner = {}  # port id -> glyph id
    kind = {}
    for el in root.iter():
        if _local(el.tag) == "glyph" and el.get("id"):
            kind[el.get("id")] = el.get("class")
            for c in el:
                if _local(c.tag) == "port" and c.get("id"):
                    owner[c.get("id")] = el.get("id")
    links: dict[str, set[str]] = {}
    for el in root.iter():
        if _local(el.tag) != "arc":
            continue
        a, b = (owner.get(el.get(k), el.get(k)) for k in ("source", "target"))
        for x, y in ((a, b), (b, a)):
            if kind.get(y) == "process":
                links.setdefault(x, set()).add(y)
    return links


def match_glyphs(pathway: Pathway, sbgn: str | Path) -> dict[str, str]:
    """The SBGN glyph of each pathway node it can be matched to.

    - The gallery's own scheme: SBML ``s_<glyph>`` / ``re_<glyph>`` (a component of a complex: ``s_n2_n0`` is
      glyph ``n2__n0``), or the same id.
    - Otherwise (e.g. MINERVA exports: reactions keep their ids, species become ``species_0``): reactions by id,
      species by name (the SBML name is the glyph's label); a name used more than once is told apart by the
      reactions the species takes part in.
    """
    glyphs = read_sbgn_glyphs(sbgn)
    by_scheme = {}
    for n in pathway.graph:
        glyph = n if n in glyphs else _glyph_for(n, glyphs)
        if glyph:
            by_scheme[n] = glyph
    if len(by_scheme) >= 0.5 * pathway.graph.number_of_nodes():
        return by_scheme

    from .graph import REACTION

    match = {n: n for n, d in pathway.graph.nodes(data=True) if d["kind"] == REACTION and n in glyphs}
    processes = _sbgn_processes(sbgn)
    by_label: dict[str, list[str]] = {}
    for gid, (cls, label) in glyphs.items():
        if cls not in ("process", "compartment") and label:
            by_label.setdefault(label.strip().lower(), []).append(gid)
    used = set()
    for n, d in pathway.graph.nodes(data=True):
        if d["kind"] == REACTION:
            continue
        candidates = [g for g in by_label.get(d["label"].strip().lower(), []) if g not in used]
        if not candidates:
            continue
        reactions = {r for r in _neighbours(pathway, n) if r in match}
        best = max(candidates, key=lambda g: len(processes.get(g, set()) & reactions))
        match[n] = best
        used.add(best)
    return match


def _neighbours(pathway: Pathway, node: str) -> set[str]:
    g = pathway.graph
    return set(g.predecessors(node)) | set(g.successors(node))


def read_sbgn_glyphs(path: str | Path) -> dict[str, tuple[str, str]]:
    """(class, label) of each glyph of an SBGN-ML map, by glyph id."""
    root = ET.parse(path).getroot()
    out = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "glyph" or not el.get("id") or not el.get("class"):
            continue
        label = next((c.get("text") for c in el if c.tag.rsplit("}", 1)[-1] == "label"), None)
        out[el.get("id")] = (el.get("class"), label or "")
    return out


def apply_gallery_classes(pathway: Pathway, sbgn: str | Path) -> int:
    """Set the species' SBGN classes (and sizes) and labels from a gallery map's SBGN file: its SBML has no SBO
    terms, and its SBML names are encoded (``_beta__minus_D_minus_fructose_minus_6P``). Returns how many species
    got a class."""
    from .graph import SBGN_ML_CLASSES, SPECIES, set_class

    glyphs = read_sbgn_glyphs(sbgn)
    match = match_glyphs(pathway, sbgn)
    # compartment names from the map's compartment glyphs (the gallery SBML names are encoded)
    for cid in pathway.compartments:
        glyph = _glyph_for(cid, glyphs)
        if glyph and glyphs[glyph][0] == "compartment" and glyphs[glyph][1]:
            pathway.compartments[cid] = glyphs[glyph][1]
    n = 0
    for node, d in pathway.graph.nodes(data=True):
        glyph = match.get(node)
        if not glyph:
            continue
        cls, label = glyphs[glyph]
        if d["kind"] == SPECIES and cls in SBGN_ML_CLASSES:
            set_class(d, SBGN_ML_CLASSES[cls])
            n += 1
        if label:
            d["label"] = label
    return n


def read_sbgn_positions(path: str | Path) -> dict[str, tuple[float, float]]:
    """Centres of the top-level glyphs of an SBGN-ML map, by glyph id (any SBGN-ML namespace)."""
    root = ET.parse(path).getroot()
    pos = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "glyph" or "id" not in el.attrib:
            continue
        bbox = next((c for c in el if c.tag.rsplit("}", 1)[-1] == "bbox"), None)
        if bbox is None:
            continue
        x, y, w, h = (float(bbox.get(k)) for k in ("x", "y", "w", "h"))
        pos[el.get("id")] = (x + w / 2, -(y + h / 2))  # y up, as in the layouts
    return pos


def sbgn_compartments(pathway: Pathway, sbgn: str | Path) -> dict[str, dict]:
    """The compartment glyphs of an SBGN-ML map as boxes (y up), keyed by the pathway's compartment id where it
    matches (the same id, or ``c_n0`` for glyph ``n0``), else by glyph id."""
    root = ET.parse(sbgn).getroot()
    glyphs = {}
    for el in root.iter():
        if _local(el.tag) == "glyph" and el.get("class") == "compartment" and el.get("id"):
            glyphs[el.get("id")] = el
    key = {}
    for cid in pathway.compartments:
        glyph = cid if cid in glyphs else _glyph_for(cid, glyphs)
        if glyph:
            key[glyph] = cid
    out = {}
    for gid, el in glyphs.items():
        bbox = next((c for c in el if _local(c.tag) == "bbox"), None)
        if bbox is None:
            continue
        x, y, w, h = (float(bbox.get(k)) for k in ("x", "y", "w", "h"))
        label = next((c.get("text") for c in el if _local(c.tag) == "label"), None) or gid
        out[key.get(gid, gid)] = {"box": [x, -(y + h), x + w, -y], "label": label}
    return out


def gallery_reference(pathway: Pathway, sbgn: str | Path) -> Positions:
    """The reference layout of a gallery map, from its SBGN map (nodes matched by ``match_glyphs``). In the map's
    own coordinates (y up)."""
    glyphs = read_sbgn_positions(sbgn)
    return {n: glyphs[g] for n, g in match_glyphs(pathway, sbgn).items() if g in glyphs}
