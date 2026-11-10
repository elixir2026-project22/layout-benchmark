"""Reference (hand-made) layouts to compare against."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .drawing import Positions
from .graph import Pathway
from .layouts import normalise

SBGN_NS = {"s": "http://sbgn.org/libsbgn/0.2", "s3": "http://sbgn.org/libsbgn/0.3"}


def _glyph_for(node_id: str, glyphs) -> str | None:
    """The gallery SBGN glyph of an SBML id: s_<glyph> / re_<glyph>; a component of a complex: s_n2_n0 is
    glyph n2__n0."""
    glyph = node_id.split("_", 1)[1] if "_" in node_id else node_id
    for candidate in (glyph, glyph.replace("_", "__")):
        if candidate in glyphs:
            return candidate
    return None


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
    n = 0
    for node, d in pathway.graph.nodes(data=True):
        glyph = _glyph_for(node, glyphs)
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


def gallery_reference(pathway: Pathway, sbgn: str | Path) -> Positions:
    """The reference layout of a metabolismregulation gallery map: SBML species ``s_<glyph>`` and reactions
    ``re_<glyph>`` are the SBGN glyphs ``<glyph>``. Normalised like the computed layouts."""
    glyphs = read_sbgn_positions(sbgn)
    pos = {}
    for n in pathway.graph:
        glyph = _glyph_for(n, glyphs)
        if glyph:
            pos[n] = glyphs[glyph]
    return normalise(pathway, pos) if pos else {}
