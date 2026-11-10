"""Runs in SBMLNetwork's own environment (``.tools/sbmlnetwork``), called by ``layout_benchmark.sbmlnet``.
Imports only SBMLNetwork and the standard library.

    python sbmlnetwork_helper.py layout MODEL OUT.json [--save LAYOUT.xml]   auto layout, as a drawing
    python sbmlnetwork_helper.py read LAYOUT.xml OUT.json                    a model's own layout, as a drawing

Drawings (JSON): {"nodes": [{"id", "of", "kind", "x", "y", "w", "h"}], "edges": [{"source", "target", "role"}],
"compartments": [{"id", "x", "y", "w", "h"}]} (compartment boxes: top-left corner and size);
x, y are node centres in SBML Layout coordinates (y down). Glyph positions in SBMLNetwork are top-left corners.
Edges are drawn straight by layout-benchmark (SBMLNetwork's curves are not used).
"""

import json
import sys

import sbmlnetwork


def _centre(element):
    (x, y), (w, h) = element.get_position(), element.get_size()
    return x + w / 2, y + h / 2, w, h


def dump(net) -> dict:
    nodes, edges = [], []
    for s in net.get_species_list():
        x, y, w, h = _centre(s)
        nodes.append({"id": s.get_id(), "of": s.get_species_id(), "kind": "species", "x": x, "y": y, "w": w, "h": h})
    for r in net.get_reactions_list():
        x, y, w, h = _centre(r)
        nodes.append({"id": r.get_id(), "of": r.get_reaction_id(), "kind": "reaction", "x": x, "y": y, "w": w, "h": h})
        for c in r.get_curves_list():
            species = c.get_species()
            if species is None:
                continue
            role = str(c.get_role()).lower()
            if role in ("product", "sideproduct"):
                edges.append({"source": r.get_id(), "target": species.get_id(), "role": role})
            else:
                edges.append({"source": species.get_id(), "target": r.get_id(), "role": role})
    compartments = []
    for c in net.get_compartments_list():
        if getattr(c, "is_hidden", lambda: False)():
            continue
        (x, y), (w, h) = c.get_position(), c.get_size()
        compartments.append({"id": c.get_compartment_id(), "x": x, "y": y, "w": w, "h": h})
    return {"nodes": nodes, "edges": edges, "compartments": compartments}


def main(argv):
    cmd = argv[0]
    save = argv[argv.index("--save") + 1] if "--save" in argv else None
    net = sbmlnetwork.load(argv[1])
    if cmd == "layout":
        net.auto_layout()
    elif cmd != "read":
        raise SystemExit(f"unknown command {cmd}")
    with open(argv[2], "w") as f:
        json.dump(dump(net), f)
    if save:
        net.save(save)


if __name__ == "__main__":
    main(sys.argv[1:])
