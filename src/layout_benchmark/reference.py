"""Reference (hand-made) layouts to compare against."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .drawing import Positions
from .graph import Pathway


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


def read_sbgn_boxes(path: str | Path) -> dict[str, tuple[float, float, float, float]]:
    """Centre and size (x, y, w, h; y up) of the glyphs of an SBGN-ML map, by glyph id (any SBGN-ML namespace)."""
    root = ET.parse(path).getroot()
    boxes = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "glyph" or "id" not in el.attrib:
            continue
        bbox = next((c for c in el if c.tag.rsplit("}", 1)[-1] == "bbox"), None)
        if bbox is None:
            continue
        x, y, w, h = (float(bbox.get(k)) for k in ("x", "y", "w", "h"))
        boxes[el.get("id")] = (x + w / 2, -(y + h / 2), w, h)  # y up, as in the layouts
    return boxes


def read_sbgn_positions(path: str | Path) -> dict[str, tuple[float, float]]:
    """Centres of the glyphs of an SBGN-ML map, by glyph id."""
    return {g: (x, y) for g, (x, y, _, _) in read_sbgn_boxes(path).items()}


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


def reference_drawing(pathway: Pathway, path: str | Path, kind: str):
    """A model's reference layout, read from its file, in its own coordinates (y up):

    - ``sbgn``: an SBGN-ML map (nodes matched by ``match_glyphs``, and its compartment glyphs);
    - ``escher``: an Escher map (clones and routes as drawn);
    - ``sbml-layout``: the model's own SBML Layout, read by SBMLNetwork (aliases are clones; None without it);
    - ``brenda-map``: the model's pathway on BRENDA's pathway map (``brenda_map_drawing``).
    """
    from .drawing import Drawing

    if kind == "sbgn":
        drawing = Drawing.of(pathway, gallery_reference(pathway, path))
        drawing.compartments = sbgn_compartments(pathway, path)
        boxes, glyph = read_sbgn_boxes(path), match_glyphs(pathway, path)
        for n, d in drawing.graph.nodes(data=True):  # the glyphs' own sizes (for the overlap metric)
            if glyph.get(n) in boxes:
                _, _, w, h = boxes[glyph[n]]
                d.update(own_shape="box", own_width=w, own_height=h)
        return drawing
    if kind == "escher":
        import json

        from .external import escher_drawing

        return escher_drawing(pathway, json.loads(Path(path).read_text()))
    if kind == "sbml-layout":
        from . import sbmlnet

        return sbmlnet.read_layout(pathway, Path(path)) if sbmlnet.available() else None
    if kind == "brenda-map":
        return brenda_map_drawing(pathway, path)
    raise ValueError(f"unknown reference kind {kind!r}")


def _reaction_ecs(source) -> dict[str, set[str]]:
    """EC numbers of each reaction of an SBML file, from its identifiers.org annotations."""
    import re

    out: dict[str, set[str]] = {}
    if source is None:
        return out
    for el in ET.parse(source).getroot().iter():
        if _local(el.tag) == "reaction" and el.get("id"):
            text = ET.tostring(el, encoding="unicode")
            out[el.get("id")] = set(re.findall(r"identifiers\.org/ec-code/([0-9.\-a-zA-Z]+)", text))
    return out


def _name_key(name: str) -> str:
    """A name for matching only: lower case, without stereo prefixes (D-, L-, alpha-, beta-, (R)-, (S)-), "di" for
    "bis", and without spaces and punctuation ("fructose-1,6-bisphosphate" is "D-fructose 1,6-bisphosphate")."""
    import re

    n = name.lower().replace("bisphosphate", "diphosphate")
    n = re.sub(r"(^|[\s(,-])(d|l|dl|alpha|beta|\(r\)|\(s\))-", r"\1", n)
    return re.sub(r"[^a-z0-9]", "", n)


def brenda_map_drawing(pathway: Pathway, path: str | Path):
    """A pathway of BRENDA's pathway map as the reference of a model made from it, read from ecmapper's export of
    the map (``BRENDA_map_reactions.json``: every enzyme and metabolite node with its centre and size, and which
    metabolites each enzyme node is linked to). The pathway is the map's subsystem that shares the most BRENDA
    reaction ids with the model (its reactions are named by them: BR…, BS…). Map reactions are matched to model
    reactions by those ids, then by EC number among the rest; metabolite nodes by name (BRENDA's or the shown
    one, compared by ``_name_key``), and where one model participant and one map metabolite of a reaction are left
    over, by that. A metabolite drawn at several places is a clone. The map doesn't say which main metabolite is consumed
    and which produced (its links have arrows at both ends): edges take their direction from the model. Node
    sizes: the map's rectangles (``own_width``, ``own_height``). None if no subsystem shares a reaction."""
    import json
    from collections import defaultdict

    import networkx as nx

    from .drawing import Drawing
    from .graph import CONSUMPTION, PRODUCTION, REACTION, SPECIES

    data = json.loads(Path(path).read_text())
    g0 = pathway.graph
    by_label = defaultdict(list)
    for r in pathway.reactions:
        by_label[g0.nodes[r]["label"]].append(r)
    by_subsystem = defaultdict(list)
    for r in data["reactions"]:
        by_subsystem[r["subsystem"]].append(r)

    def shared(entries):
        return sum(any(i in by_label for i in e["brenda_reaction_ids"]) for e in entries)

    subsystem = max(by_subsystem, key=lambda s: shared(by_subsystem[s]))
    if not shared(by_subsystem[subsystem]):
        return None
    entries = by_subsystem[subsystem]

    # map reaction node -> model reaction: by BRENDA id, then by EC among the unmatched (one candidate only)
    matched: dict[str, str] = {}
    for e in entries:
        candidates = [r for i in e["brenda_reaction_ids"] for r in by_label.get(i, [])]
        if candidates:
            matched[e["node_id"]] = candidates[0]
    ecs = _reaction_ecs(pathway.source)
    rest = [r for r in pathway.reactions if r not in set(matched.values())]
    for e in entries:
        if e["node_id"] in matched:
            continue
        candidates = [r for r in rest if ecs.get(r, set()) & set(e["ec_numbers"])]
        if len(candidates) == 1:
            matched[e["node_id"]] = candidates[0]
            rest.remove(candidates[0])

    species_by_name = defaultdict(list)
    for s in pathway.species:
        species_by_name[_name_key(g0.nodes[s]["label"])].append(s)

    g = nx.DiGraph()
    pos = {}

    def node(did, of, kind, x, y, w, h):
        if did not in g:
            d = g0.nodes[of]
            g.add_node(
                did,
                of=of,
                kind=kind,
                label=d["label"],
                sbgn=d.get("sbgn"),
                width=d["width"],
                height=d["height"],
                own_shape="box",
                own_width=w,
                own_height=h,
            )
            pos[did] = (x, -y)  # the map's y is down
        return did

    metabolites = {m["node_id"]: m for m in data["metabolite_nodes"]}
    for e in entries:
        rid = matched.get(e["node_id"])
        if rid is None:
            continue
        lay = e["layout"]
        did = rid if rid not in g else f"{rid}@{e['node_id']}"  # a reaction drawn twice: a clone
        rnode = node(did, rid, REACTION, lay["x"], lay["y"], lay["width"], lay["height"])
        partners = e["main_metabolites"] + [
            c for k in ("consumed", "produced", "undirected") for c in e["cofactors"][k]
        ]
        participants = {s for s in nx.all_neighbors(g0, rid) if g0.nodes[s]["kind"] == SPECIES}
        pairs, left = [], []
        for m in partners:
            if m["node_id"] not in metabolites:
                continue
            keys = {_name_key(m.get("brenda_name") or ""), _name_key(m.get("display_name") or "")}
            species = [s for k in keys for s in species_by_name.get(k, []) if s in participants]
            (pairs.append((m, species[0])) if species else left.append(m))
        unpaired = participants - {s for _, s in pairs}
        if len(left) == 1 and len(unpaired) == 1:  # the one left on each side: the same metabolite, named apart
            pairs.append((left[0], unpaired.pop()))
        for m, s in pairs:
            met = metabolites[m["node_id"]]
            snode = node(f"{s}@{m['node_id']}", s, SPECIES, met["x"], met["y"], met["width"], met["height"])
            if g0.has_edge(s, rid):
                g.add_edge(snode, rnode, arc=g0.edges[s, rid].get("arc", CONSUMPTION))
            else:
                g.add_edge(rnode, snode, arc=PRODUCTION)
    return Drawing(graph=g, pos=pos) if pos else None
