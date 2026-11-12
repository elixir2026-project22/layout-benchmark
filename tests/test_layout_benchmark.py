import math
import re

import pytest
from scipy.spatial.distance import pdist

from layout_benchmark.drawing import SPACING, Drawing
from layout_benchmark.graph import read_sbml
from layout_benchmark.layouts import REGISTRY, layout
from layout_benchmark.metrics import (
    all_metrics,
    compartment_metrics,
    general_metrics,
    overlaps,
    own_sizes,
    participant_consistency,
    reference_similarity,
    segment_graph,
)

from .conftest import make_sbml


def test_read_sbml(tiny_sbml):
    p = read_sbml(tiny_sbml)
    assert sorted(p.species) == ["A", "B", "C", "E"]
    assert sorted(p.reactions) == ["r1", "r2", "r3"]
    roles = {(u, v): d["role"] for u, v, d in p.graph.edges(data=True)}
    assert roles[("A", "r1")] == "reactant"
    assert roles[("r1", "B")] == "product"
    assert roles[("E", "r1")] == "modifier"


@pytest.mark.parametrize("name", [s.name for s in REGISTRY if s.tool is None])  # tools: own environments
def test_every_layout_places_every_node(tiny_sbml, name):
    p = read_sbml(tiny_sbml)
    d = layout(name, p, seed=1)
    assert d.placed() == set(p.graph)
    assert all(math.isfinite(c) for xy in d.pos.values() for c in xy)


def test_layout_is_reproducible_and_scaled_only_for_drawing(tiny_sbml):
    p = read_sbml(tiny_sbml)
    a = layout("networkx-spring", p, seed=3)
    b = layout("networkx-spring", p, seed=3)
    assert a.node_positions() == b.node_positions()
    # the common scale: nearest neighbours SPACING median node widths apart; a uniform scale, shapes unchanged
    import numpy as np
    from scipy.spatial import cKDTree

    scaled = a.normalised()
    xy = np.array(list(scaled.pos.values()))
    nn = cKDTree(xy).query(xy, k=2)[0][:, 1]
    widths = [d["width"] for _, d in scaled.graph.nodes(data=True)]
    assert np.median(nn) == pytest.approx(SPACING * np.median(widths))
    raw = np.array(list(a.pos.values()))
    ratio = pdist(xy) / pdist(raw)
    assert np.allclose(ratio, ratio[0])


def test_graphviz_keeps_its_coordinates(tiny_sbml):
    """A layout is returned in the tool's own coordinates (Graphviz: points), not rescaled."""
    p = read_sbml(tiny_sbml)
    d = layout("graphviz-neato", p)
    xs = [x for x, _ in d.pos.values()]
    assert min(xs) >= 0  # Graphviz's own coordinates start at its margin, not centred on 0


def test_json_round_trip(tiny_sbml):
    from layout_benchmark.drawing import Drawing
    from layout_benchmark.render import to_svg

    d = layout("graphviz-dot", read_sbml(tiny_sbml))
    back = Drawing.from_json(d.to_json())
    assert to_svg(back.normalised()) == to_svg(d.normalised())


def test_general_metrics_smoke(tiny_sbml):
    """gdMetriX's metrics are tested upstream; here only that they run on our drawings."""
    p = read_sbml(tiny_sbml)
    m = general_metrics(layout("graphviz-neato", p))
    assert m["crossings"] >= 0
    assert m["aspect_ratio"] > 0


def _line(tmp_path):
    """One reaction S -> r -> P."""
    return read_sbml(make_sbml(tmp_path / "line.xml", [("r", ["S"], ["P"], [])]))


def _drawn(p, pos, routes=None, **sizes):
    d = Drawing.of(p, pos)
    d.routes = routes or {}
    for n, (w, h) in sizes.items():
        d.graph.nodes[n].update(own_shape="box", own_width=w, own_height=h)
    return d


def test_metrics_on_a_drawing_with_clones_and_left_out_nodes(tmp_path):
    """The drawing as shown: a clone is a node with its own edge, a node left out is absent (no error)."""
    p = read_sbml(make_sbml(tmp_path / "two.xml", [("r1", ["A"], ["B"], []), ("r2", ["B"], ["C"], [])]))
    d = Drawing.of(p, {"A": (0, 0), "r1": (100, 0), "B": (200, 0), "r2": (300, 100)})  # C left out
    d.graph.add_node("B@2", **{**d.graph.nodes["B"], "of": "B"})  # B drawn again, next to r2
    d.pos["B@2"] = (300, 0)
    d.graph.remove_edge("B", "r2")
    d.graph.add_edge("B@2", "r2", arc="consumption")
    m = all_metrics(d, p, layout="test")
    assert m["species_drawn"] == pytest.approx(2 / 3) and m["reactions_drawn"] == 1
    assert m["drawn_per_node"] == pytest.approx(5 / 4)
    assert m["crossings"] == 0 and m["overlapping_pairs"] is None  # no node sizes for an unknown layout


def test_crossings_follow_the_routes(tmp_path):
    """Two edges whose straight lines don't cross, but whose drawn routes do; a piece shared by two edges counts
    once (no crossing with itself)."""
    p = read_sbml(make_sbml(tmp_path / "x.xml", [("r1", ["A"], ["B"], []), ("r2", ["C"], ["D"], [])]))
    pos = {"A": (0, 0), "r1": (100, 0), "B": (200, 0), "C": (0, 100), "r2": (100, 100), "D": (200, 100)}
    assert general_metrics(_drawn(p, pos))["crossings"] == 0
    routed = _drawn(p, pos, routes={("A", "r1"): [(50, 150)]})  # A -> up across C-r2 -> back down across it -> r1
    assert general_metrics(routed)["crossings"] == 2
    shared = _drawn(p, pos, routes={("A", "r1"): [(50, 0)], ("r1", "B"): [(150, 0)]})
    g, _ = segment_graph(shared)
    assert g.number_of_edges() == 4 + 2  # A-bend-r1, r1-bend-B, and r2's two straight edges


def test_overlaps_use_the_tools_own_sizes(tmp_path):
    p = _line(tmp_path)
    close = {"S": (0, 0), "r": (500, 0), "P": (30, 0)}
    assert overlaps(_drawn(p, close), None)["overlapping_pairs"] is None  # no sizes: not applicable
    # boxes 60 wide: S and P 30 apart overlap; 60 apart they only touch
    sized = {"S": (60, 20), "r": (10, 10), "P": (60, 20)}
    d = _drawn(p, close, **sized)
    assert overlaps(d, own_sizes(d, p))["overlapping_pairs"] == 1
    d = _drawn(p, dict(close, P=(60, 0)), **sized)
    assert overlaps(d, own_sizes(d, p))["overlapping_pairs"] == 0
    # small own sizes: no overlap at the same positions (our SBGN sizes would overlap)
    d = _drawn(p, close, S=(20, 20), r=(10, 10), P=(20, 20))
    assert overlaps(d, own_sizes(d, p))["overlapping_pairs"] == 0
    # the sizes we give Graphviz and cytoscape.js; Escher's circles for the Escher tools
    assert own_sizes(_drawn(p, close), p, "graphviz-dot")["S"][0] == "box"
    assert own_sizes(_drawn(p, close), p, "sbml2map")["S"] == ("circle", 40.0, 40.0)
    assert own_sizes(_drawn(p, close), p, "igraph-fr") is None


def test_participant_consistency(tmp_path):
    p = _line(tmp_path)
    assert participant_consistency(_drawn(p, {"S": (0, 0), "r": (100, 0), "P": (200, 0)})) == 1.0
    # product on the reactant's side
    assert participant_consistency(_drawn(p, {"S": (0, 0), "r": (100, 0), "P": (10, 50)})) == 0.0
    # ... but its drawn route leaves the reaction on the other side
    routed = _drawn(p, {"S": (0, 0), "r": (100, 0), "P": (10, 50)}, routes={("r", "P"): [(150, 0), (150, 50)]})
    assert participant_consistency(routed) == 1.0


def test_compartment_metrics_use_the_drawn_boxes(tmp_path):
    path = make_sbml(
        tmp_path / "comp.xml",
        [("r1", ["A", "B"], ["C"], []), ("r2", ["X", "Y"], ["Z"], [])],
        compartments=("c1", "c2"),
        species_compartment={"X": "c2", "Y": "c2", "Z": "c2"},
    )
    p = read_sbml(path)
    pos = {"A": (0, 0), "B": (100, 0), "C": (50, 100), "X": (500, 0), "Y": (600, 0), "Z": (550, 100)}
    d = _drawn(p, {**pos, "r1": (50, 50), "r2": (550, 50)})
    assert compartment_metrics(d, p)["species_outside_compartment"] is None  # no boxes drawn
    d.compartments = {"c1": {"box": [-10, -10, 110, 110]}, "c2": {"box": [490, -10, 610, 110]}}
    m = compartment_metrics(d, p)
    assert m["species_outside_compartment"] == 0 and m["compartments_overlapping"] == 0
    d.pos["Z"] = (50, 30)  # Z drawn in c1's box
    assert compartment_metrics(d, p)["species_outside_compartment"] == pytest.approx(1 / 6)
    d.compartments["c2"] = {"box": [20, 20, 40, 40]}  # nested in c1: fine
    assert compartment_metrics(d, p)["compartments_overlapping"] == 0
    d.compartments["c2"] = {"box": [100, 100, 200, 200]}  # half over c1
    assert compartment_metrics(d, p)["compartments_overlapping"] == 1


def test_reference_similarity_invariances():
    ref = {"a": (0, 0), "b": (1, 0), "c": (0, 2), "d": (3, 1), "e": (2, 4)}
    # rotated 90°, scaled 5x, mirrored, moved
    moved = {n: (-5 * y + 7, -5 * x - 2) for n, (x, y) in ref.items()}
    m = reference_similarity(moved, ref, k=2)
    assert m["procrustes"] == pytest.approx(0, abs=1e-12)
    assert m["distance_correlation"] == pytest.approx(1)
    assert m["knn_preservation"] == pytest.approx(1)


def test_node_size_does_not_depend_on_label(tmp_path):
    """Nodes have a fixed size per SBGN class; a long label is cut, the node does not grow."""
    from layout_benchmark.render import to_svg

    short = read_sbml(make_sbml(tmp_path / "a.xml", [("r", ["S"], ["P"], [])]))
    long_name = read_sbml(make_sbml(tmp_path / "b.xml", [("r", ["S" * 80], ["P"], [])]))
    assert short.graph.nodes["S"]["width"] == long_name.graph.nodes["S" * 80]["width"]
    svg = to_svg(layout("graphviz-neato", long_name))
    shown = re.findall(r"<text[^>]*>([^<]*)", svg)  # the visible label text, without its tooltip
    assert "S" * 80 not in shown
    assert any(t.startswith("SSS") and t.endswith("…") for t in shown)


def test_manifest(tmp_path):
    """Sets in order, globs relative to the manifest, references by pattern, credits; a model in two sets counts
    once (the first)."""
    from layout_benchmark.manifest import load

    (tmp_path / "maps").mkdir()
    for name in ("a", "b"):
        make_sbml(tmp_path / "maps" / f"{name}.xml", [("r", ["S"], ["P"], [])])
    (tmp_path / "maps" / "a.sbgn").write_text("<sbgn/>")
    (tmp_path / "benchmark.yaml").write_text(
        "sets:\n"
        "  - name: First\n    models: maps/a.xml\n    reference: '{stem}.sbgn'\n    credit: Map, CC BY 4.0\n"
        "  - name: Second\n    description: The rest\n    models: [maps/*.xml]\n"
    )
    sets, specs = load(tmp_path / "benchmark.yaml")
    assert [s.name for s in sets] == ["First", "Second"]
    assert sets[1].description == "The rest"
    assert [(s.path.name, s.set) for s in specs] == [("a.xml", "First"), ("b.xml", "Second")]
    assert specs[0].reference.name == "a.sbgn" and specs[0].credit == "Map, CC BY 4.0"
    assert specs[1].reference is None


def _two_compartments(tmp_path):
    path = make_sbml(
        tmp_path / "two.xml",
        [("r1", ["A"], ["B"], []), ("r2", ["B"], ["X"], [])],
        compartments=("cyt", "nuc"),
        species_compartment={"X": "nuc"},
    )
    return read_sbml(path)


def test_compartment_colours_and_legend(tmp_path):
    from layout_benchmark.render import PALETTE, compartment_colours, to_svg

    p = _two_compartments(tmp_path)
    colours = compartment_colours(p)
    assert colours == {"cyt": PALETTE[0], "nuc": PALETTE[1]}  # the larger compartment first
    svg = to_svg(layout("graphviz-neato", p).normalised(), "two", p)
    assert f'fill="{PALETTE[1]}"' in svg  # X, in the nucleus
    assert ">nuc</text>" in svg  # the legend
    single = read_sbml(make_sbml(tmp_path / "one.xml", [("r", ["S"], ["P"], [])]))
    assert compartment_colours(single) == {}


def test_compartment_boxes_round_trip(tmp_path):
    from layout_benchmark.drawing import Drawing
    from layout_benchmark.render import to_svg

    p = _two_compartments(tmp_path)
    d = layout("graphviz-dot", p)
    d.compartments = {"nuc": {"box": [0.0, 0.0, 100.0, 50.0], "label": "nucleus"}}
    back = Drawing.from_json(d.to_json())
    assert back.compartments == d.compartments
    scaled = back.normalised()
    x0, y0, x1, y1 = scaled.compartments["nuc"]["box"]
    assert (x1 - x0) / (y1 - y0) == pytest.approx(2.0)  # scaled with the nodes
    assert ">nucleus</text>" in to_svg(scaled, "two", p)


def test_append_replaces_only_given_layouts(tmp_path, tiny_sbml):
    import csv

    from layout_benchmark.runner import run

    out = tmp_path / "out"
    run([tiny_sbml], ["graphviz-dot", "graphviz-neato"], out)
    first = {r["layout"]: r for r in csv.DictReader((out / "results.csv").open())}
    run([tiny_sbml], ["graphviz-neato"], out, append=True)
    rows = list(csv.DictReader((out / "results.csv").open()))
    assert sorted(r["layout"] for r in rows) == ["graphviz-dot", "graphviz-neato"]
    assert next(r for r in rows if r["layout"] == "graphviz-dot")["seconds"] == first["graphviz-dot"]["seconds"]


def test_append_of_some_layouts_keeps_the_reference_and_its_scores(tmp_path):
    """`run --append --layouts X` keeps each model's reference row (with its metrics); "reference" among the
    layouts redoes it."""
    import csv
    import json

    from layout_benchmark.datasets import escher_to_sbml
    from layout_benchmark.runner import REFERENCE, run

    sbml, reference = escher_to_sbml(_escher_map(), "Test map")
    (tmp_path / "m.xml").write_text(sbml)
    (tmp_path / "m.escher.json").write_text(json.dumps(reference))
    out = tmp_path / "out"

    def reference_row():
        return next(r for r in csv.DictReader((out / "results.csv").open()) if r["layout"] == REFERENCE)

    run([tmp_path / "m.xml"], ["graphviz-dot"], out, metrics=True)
    assert reference_row()["species_drawn"] != ""
    run([tmp_path / "m.xml"], ["graphviz-neato"], out, append=True)
    assert reference_row()["species_drawn"] != ""
    layouts = sorted(r["layout"] for r in csv.DictReader((out / "results.csv").open()))
    assert layouts == ["graphviz-dot", "graphviz-neato", REFERENCE]
    run([tmp_path / "m.xml"], [REFERENCE], out, append=True)  # redone, without metrics this time
    assert reference_row().get("species_drawn", "") == ""


def test_a_second_command_on_the_same_folder_stops(tmp_path):
    import click
    import pytest

    from layout_benchmark.__main__ import locked

    in_use = pytest.raises(click.ClickException, match="in use by another layout-benchmark command")
    with locked(tmp_path), in_use, locked(tmp_path):
        pass
    with locked(tmp_path):  # free again
        pass


def test_reaction_compartment(tmp_path):
    """For the compound layouts: a reaction within one compartment gets it, a transport gets none, an SBML
    reaction compartment wins."""
    from layout_benchmark.graph import reaction_compartment

    p = _two_compartments(tmp_path)  # r1: A -> B (both cyt); r2: B (cyt) -> X (nuc)
    assert reaction_compartment(p, "r1") == "cyt"
    assert reaction_compartment(p, "r2") is None
    p.graph.nodes["r2"]["compartment"] = "nuc"  # as read from an SBML Level 3 reaction compartment
    assert reaction_compartment(p, "r2") == "nuc"


def _escher_map():
    """A small Escher map as VMH draws them: man1p[c] -> man6p[c] by PMANM; ATP drawn twice (a clone); a
    multimarker between the metabolite and the midmarker; PMANM's metabolites include H+, not drawn."""

    def met(bigg, x, y, primary=True):
        name = bigg.split("[")[0].upper()
        return {"node_type": "metabolite", "bigg_id": bigg, "name": name, "x": x, "y": y, "node_is_primary": primary}

    nodes = {
        "1": met("man1p[c]", 0, 0),
        "2": met("man6p[c]", 0, 200),
        "3": {"node_type": "midmarker", "x": 0, "y": 100},
        "4": {"node_type": "multimarker", "x": 0, "y": 50},
        "5": met("atp[c]", 50, 80, False),
        "6": met("atp[c]", 300, 300, False),
    }

    def segment(a, b):
        return {"from_node_id": a, "to_node_id": b, "b1": None, "b2": None}

    reaction = {
        "bigg_id": "PMANM",
        "name": "Phosphomannomutase",
        "reversibility": True,
        "metabolites": [
            {"bigg_id": "man1p[c]", "coefficient": -1},
            {"bigg_id": "atp[c]", "coefficient": -1},
            {"bigg_id": "man6p[c]", "coefficient": 1},
            {"bigg_id": "h[c]", "coefficient": 2},
        ],
        "segments": {"a": segment("1", "4"), "b": segment("4", "3"), "c": segment("3", "2"), "d": segment("5", "3")},
    }
    return [{"map_name": "test"}, {"nodes": nodes, "reactions": {"0": reaction}, "text_labels": {}}]


def test_escher_species_on_both_sides_take_their_side_from_the_segments(tmp_path):
    """A -> A (one id on both sides, as when a tool merges species by name): each copy's side comes from its
    segment's direction (metabolite -> midmarker: consumed; midmarker -> metabolite: produced)."""
    from layout_benchmark.external import escher_drawing
    from layout_benchmark.graph import CONSUMPTION, PRODUCTION

    p = read_sbml(make_sbml(tmp_path / "m.xml", [("r1", ["A"], ["B"], [])]))
    nodes = {
        "1": {"node_type": "metabolite", "bigg_id": "A", "x": 0, "y": 200, "node_is_primary": True},
        "2": {"node_type": "midmarker", "x": 0, "y": 100},
        "3": {"node_type": "metabolite", "bigg_id": "A", "x": 0, "y": 0, "node_is_primary": True},
    }
    segments = {"a": {"from_node_id": "1", "to_node_id": "2"}, "b": {"from_node_id": "2", "to_node_id": "3"}}
    reaction = {
        "bigg_id": "r1",
        "metabolites": [{"bigg_id": "A", "coefficient": -1}, {"bigg_id": "A", "coefficient": 1}],
        "segments": segments,
    }
    d = escher_drawing(p, [{}, {"nodes": nodes, "reactions": {"0": reaction}}])
    assert d.graph.edges["A@1", "r1"]["arc"] == CONSUMPTION
    assert d.graph.edges["r1", "A@3"]["arc"] == PRODUCTION


def test_escher_to_sbml(tmp_path):
    """An Escher map without a model: SBML from its reactions (stoichiometry, compartments from the ids), and the
    map as the reference, matched to the SBML ids, clones and routes kept."""
    import json

    from layout_benchmark.datasets import escher_to_sbml, slug
    from layout_benchmark.reference import reference_drawing

    assert slug("N‑linked protein glycosylation") == "n-linked-protein-glycosylation"
    sbml, reference = escher_to_sbml(_escher_map(), "Test map")
    (tmp_path / "m.xml").write_text(sbml)
    (tmp_path / "m.escher.json").write_text(json.dumps(reference))
    p = read_sbml(tmp_path / "m.xml")
    assert sorted(p.species) == ["M_atp_c", "M_h_c", "M_man1p_c", "M_man6p_c"]
    assert list(p.reactions) == ["R_PMANM"]
    assert p.graph.nodes["M_man1p_c"]["label"] == "MAN1P"
    assert p.compartments == {"C_c": "cytosol"}
    roles = {(u, v): d["role"] for u, v, d in p.graph.edges(data=True)}
    assert roles[("M_atp_c", "R_PMANM")] == "reactant" and roles[("R_PMANM", "M_h_c")] == "product"

    d = reference_drawing(p, tmp_path / "m.escher.json", "escher")
    assert d.has_clones and d.placed() == {"M_atp_c", "M_man1p_c", "M_man6p_c", "R_PMANM"}  # H+ isn't drawn
    pos = d.node_positions()
    assert pos["M_man1p_c"] == (0.0, 0.0) and pos["M_man6p_c"] == (0.0, -200.0) and pos["R_PMANM"] == (0.0, -100.0)
    assert d.routes[("M_man1p_c@1", "R_PMANM")] == [(0.0, -50.0)]  # through the multimarker


def test_manifest_escher_reference(tmp_path):
    """A reference pattern ending in .json is an Escher map; a plain model file finds <stem>.escher.json."""
    from layout_benchmark.manifest import load
    from layout_benchmark.runner import spec_for

    make_sbml(tmp_path / "a.xml", [("r", ["S"], ["P"], [])])
    (tmp_path / "a.escher.json").write_text("[]")
    (tmp_path / "benchmark.yaml").write_text(
        "sets:\n  - name: Maps\n    models: a.xml\n    reference: '{stem}.escher.json'\n"
    )
    _, specs = load(tmp_path / "benchmark.yaml")
    assert specs[0].reference.name == "a.escher.json" and specs[0].reference_kind == "escher"
    spec = spec_for(tmp_path / "a.xml")
    assert spec.reference.name == "a.escher.json" and spec.reference_kind == "escher"


def test_fetch_caches_per_set(tmp_path):
    """Remote models are cached as <data>/<set>/<name><suffix>, with their reference (a pattern next to the source)
    and companions; Escher maps of a `convert: escher` set become a model and its reference; links and credits come
    from the manifest; the lock file is written."""
    import json

    from layout_benchmark.datasets import fetch
    from layout_benchmark.manifest import LOCK, load

    remote = tmp_path / "remote"
    (remote / "maps").mkdir(parents=True)
    make_sbml(remote / "F001.xml", [("r", ["S"], ["P"], [])])
    (remote / "F001.sbgn").write_text("<sbgn/>")
    (remote / "F001.json").write_text("{}")
    (remote / "maps" / "Test map.json").write_text(json.dumps(_escher_map()))
    url = remote.as_uri()
    (tmp_path / "benchmark.yaml").write_text(
        "sets:\n"
        "  - name: My Gallery\n    reference: '{stem}.sbgn'\n    credit: Maps, CC BY 4.0\n    models:\n"
        f"      - name: glycolysis\n        url: {url}/F001.xml\n        files: [{url}/F001.json]\n"
        "        page: https://example.org/glycolysis/\n"
        f"  - name: Escher maps\n    convert: escher\n    models: '{url}/maps/Test%20map.json'\n"
    )
    data = tmp_path / "data"
    specs = fetch(tmp_path / "benchmark.yaml", data)
    gallery, escher = specs
    assert gallery.path == data / "my-gallery" / "glycolysis.xml" and gallery.path.exists()
    assert gallery.reference == data / "my-gallery" / "glycolysis.sbgn" and gallery.reference.exists()
    assert (data / "my-gallery" / "glycolysis.json").exists()  # a companion, next to the model
    assert gallery.links == {
        "model": f"{url}/F001.xml",
        "reference": f"{url}/F001.sbgn",
        "page": "https://example.org/glycolysis/",
    }
    assert gallery.credit == "Maps, CC BY 4.0" and gallery.set == "My Gallery"
    assert escher.name == "test-map" and escher.reference_kind == "escher"
    assert list(read_sbml(escher.path).reactions) == ["R_PMANM"] and escher.reference.exists()
    assert (data / LOCK).exists()
    assert [s.path for s in load(tmp_path / "benchmark.yaml", data)[1]] == [gallery.path, escher.path]


def test_github_sources_are_pinned_to_their_commit(tmp_path, monkeypatch):
    """A GitHub glob expands over the tree of its ref's commit; files are downloaded and linked at that commit;
    the lock file lets the manifest be read again without network, and its absence says to fetch."""
    from layout_benchmark import manifest

    calls = []

    def github(url):
        calls.append(url)
        if url.endswith("/commits/main"):
            return {"sha": "abc123"}
        return {"tree": [{"path": p, "type": "blob"} for p in ("a.xml", "b.xml", "sub/c.xml", "a.sbgn")]}

    monkeypatch.setattr(manifest, "_github_json", github)
    (tmp_path / "benchmark.yaml").write_text(
        "sets:\n  - name: Repo\n    models: https://github.com/org/repo/blob/main/*.xml\n"
    )
    lock = {"commits": {}, "globs": {}}
    _, specs = manifest.load(tmp_path / "benchmark.yaml", tmp_path / "data", lock=lock, online=True)
    assert [s.name for s in specs] == ["a", "b"]  # * stays in its folder
    assert specs[0].url == "https://raw.githubusercontent.com/org/repo/abc123/a.xml"
    assert specs[0].links["model"] == "https://github.com/org/repo/blob/abc123/a.xml"
    assert len(calls) == 2
    _, again = manifest.load(tmp_path / "benchmark.yaml", tmp_path / "data", lock=lock)  # offline, from the lock
    assert [s.url for s in again] == [s.url for s in specs] and len(calls) == 2
    with pytest.raises(RuntimeError, match="fetch"):
        manifest.load(tmp_path / "benchmark.yaml", tmp_path / "data")  # no lock file yet
    assert manifest._match("IMD Maps/A/b c.json", "IMD Maps/**/*.json")
    assert manifest._match("IMD Maps/b.json", "IMD Maps/**/*.json")


def test_report_links_from_the_manifest(tmp_path):
    from layout_benchmark.report import model_links

    row = {"links": '{"page": "https://example.org/p/"}', "source": str(tmp_path / "m.xml")}
    assert model_links(row) == {"page": "https://example.org/p/", "local file": (tmp_path / "m.xml").as_uri()}
    assert model_links(row, local=False) == {"page": "https://example.org/p/"}


def _drawing(n_species, n_reactions, spacing=100.0):
    """A row of species (48 wide) and reactions (10 wide), ``spacing`` apart."""
    import networkx as nx

    from layout_benchmark.drawing import Drawing

    g = nx.DiGraph()
    pos = {}
    for i in range(n_species + n_reactions):
        kind = "species" if i < n_species else "reaction"
        n = f"n{i}"
        g.add_node(n, of=n, kind=kind, label=n, width=48.0 if kind == "species" else 10.0, height=24.0)
        pos[n] = (i * spacing, 0.0)
    return Drawing(graph=g, pos=pos)


def test_scale_uses_species_width():
    """Nearest neighbours SPACING species widths apart, however many reactions there are."""
    few, many = _drawing(4, 2), _drawing(2, 6)
    assert few.scale_factor() == pytest.approx(SPACING * 48 / 100)
    assert many.scale_factor() == pytest.approx(SPACING * 48 / 100)  # was 10-wide reactions' median


def test_escher_ids_match_sbml_ids():
    import networkx as nx

    from layout_benchmark.external import _id_lookup
    from layout_benchmark.graph import Pathway

    g = nx.DiGraph()
    g.add_nodes_from(["M_glc__45__D_e", "R_EX_glc__45__D_e", "s_n0"])
    lookup = _id_lookup(Pathway(name="t", graph=g))
    assert lookup["glc-D_e"] == lookup["glc__45__D_e"] == lookup["M_glc__45__D_e"] == "M_glc__45__D_e"
    assert lookup["EX_glc-D_e"] == "R_EX_glc__45__D_e" and lookup["s_n0"] == "s_n0"


def test_timeout_kills_the_tools_a_layout_started(tiny_sbml, tmp_path, monkeypatch):
    import subprocess
    import time
    from pathlib import Path

    from layout_benchmark import layouts, runner
    from layout_benchmark.graph import read_sbml

    pid_file = tmp_path / "pid"

    def hangs(pathway, seed):  # an external tool that runs past the timeout
        child = subprocess.Popen(["sleep", "60"])
        pid_file.write_text(str(child.pid))
        child.wait()

    monkeypatch.setitem(layouts.LAYOUTS, "hangs", hangs)
    positions, _, error = runner.run_layout("hangs", read_sbml(tiny_sbml), timeout=1)
    assert positions is None and error.startswith("timeout")
    pid = int(pid_file.read_text())
    for _ in range(50):  # the kill is asynchronous
        if not Path(f"/proc/{pid}").exists() or "Z" in Path(f"/proc/{pid}/stat").read_text().split()[2]:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the tool's process is still running")


def test_score_drawings_times_out_and_runs_in_parallel(tiny_sbml, monkeypatch):
    """A drawing whose metrics run past the timeout gets an error, the others their metrics; jobs run at once."""
    import time

    from layout_benchmark import runner
    from layout_benchmark.graph import read_sbml

    def metrics(drawing, pathway, reference, layout):
        if layout == "slow":
            time.sleep(60)
        if layout == "broken":
            raise ValueError("no\nmetrics here")
        time.sleep(1)
        return {"crossings": 0.0}

    monkeypatch.setattr(runner, "all_metrics", metrics)
    pathway = read_sbml(tiny_sbml)
    tasks = [(name, None, pathway, None, name) for name in ("slow", "a", "b", "broken")]
    start = time.perf_counter()
    results = {key: (values, error) for key, values, error in runner.score_drawings(tasks, timeout=3, jobs=4)}
    assert time.perf_counter() - start < 10
    assert results["a"] == ({"crossings": 0.0}, None) and results["b"] == ({"crossings": 0.0}, None)
    assert results["slow"] == (None, "metrics timeout after 3 s")
    assert results["broken"] == (None, "ValueError: metrics here")


def test_score_writes_the_metrics_of_saved_drawings(tmp_path, tiny_sbml):
    """`score` computes the metrics from the saved drawings, the same as `run --metrics`, and keeps the other
    columns."""
    import csv

    from click.testing import CliRunner

    from layout_benchmark.__main__ import main
    from layout_benchmark.runner import run

    out = tmp_path / "out"
    run([tiny_sbml], ["graphviz-dot", "igraph-fr"], out, metrics=True)
    scored_by_run = {r["layout"]: r for r in csv.DictReader((out / "results.csv").open())}
    run([tiny_sbml], ["graphviz-dot", "igraph-fr"], out)  # without metrics
    result = CliRunner().invoke(main, ["score", str(out)])
    assert result.exit_code == 0, result.output
    rows = {r["layout"]: r for r in csv.DictReader((out / "results.csv").open())}
    for name, row in rows.items():
        assert row["crossings"] == scored_by_run[name]["crossings"] and row["seconds"] != ""
    assert rows["graphviz-dot"]["overlapping_pairs"] != "" and rows["igraph-fr"]["overlapping_pairs"] == ""


def test_brenda_map_reference(tmp_path):
    """The model's pathway on BRENDA's map: the subsystem sharing its reaction ids, metabolites matched by name
    (spelling aside) or as the one left over, directions from the model, clones, the map's sizes, y up."""
    import json

    from layout_benchmark.manifest import load
    from layout_benchmark.reference import reference_drawing

    path = make_sbml(
        tmp_path / "m.xml", [("BR1", ["D-glucose", "ATP"], ["Glc6P"], []), ("BR2", ["Glc6P"], ["F6P"], [])]
    )

    def met(node, name, x, y):
        return {"node_id": node, "brenda_name": name, "display_name": name, "x": x, "y": y, "width": 40, "height": 30}

    def link(node, name):
        return {"node_id": node, "brenda_name": name, "display_name": name}

    def reaction(node, sub, ids, x, y, main, consumed=()):
        return {
            "node_id": node,
            "subsystem": sub,
            "ec_numbers": [],
            "brenda_reaction_ids": ids,
            "layout": {"x": x, "y": y, "width": 60, "height": 30},
            "main_metabolites": main,
            "cofactors": {"consumed": list(consumed), "produced": [], "undirected": []},
        }

    brenda = {
        "reactions": [
            reaction(
                "e1",
                "glycolysis",
                ["BR1"],
                100,
                100,
                [link("m1", "glucose"), link("m2", "glucose 6-phosphate")],
                [link("c1", "ATP")],
            ),
            reaction("e2", "glycolysis", ["BR2"], 100, 300, [link("m2", "glucose 6-phosphate"), link("m3", "F6P")]),
            reaction("e9", "other", ["BR9"], 0, 0, []),
        ],
        "metabolite_nodes": [
            met("m1", "glucose", 100, 0),
            met("m2", "glucose 6-phosphate", 100, 200),
            met("m3", "F6P", 100, 400),
            met("c1", "ATP", 150, 80),
        ],
    }
    (tmp_path / "BRENDA_map_reactions.json").write_text(json.dumps(brenda))
    (tmp_path / "benchmark.yaml").write_text(
        "sets:\n  - name: B\n    models: m.xml\n    reference: BRENDA_map_reactions.json\n"
        "    reference_kind: brenda-map\n"
    )
    _, specs = load(tmp_path / "benchmark.yaml")
    assert specs[0].reference_kind == "brenda-map"
    p = read_sbml(path)
    d = reference_drawing(p, specs[0].reference, "brenda-map")
    assert d.placed() == set(p.graph)  # D-glucose by name, Glc6P as the one left over at BR1
    assert d.pos["BR2"] == (100, -300)  # y up
    g6p = [n for n, a in d.graph.nodes(data="of") if a == "Glc6P"]
    assert g6p == ["Glc6P@m2"]  # one map node shared by both reactions
    assert d.graph.has_edge("BR1", "Glc6P@m2") and d.graph.has_edge("Glc6P@m2", "BR2")  # directions from the model
    assert d.graph.nodes["BR1"]["own_width"] == 60


def test_ranks_share_ties_and_skip_missing_values():
    from layout_benchmark.report import ranks

    rows = [
        {"model": "m", "layout": "a", "crossings": "0", "species_drawn": "1"},
        {"model": "m", "layout": "b", "crossings": "0", "species_drawn": "0.5"},
        {"model": "m", "layout": "c", "crossings": "4", "species_drawn": ""},
        {"model": "m", "layout": "d", "crossings": "9", "error": "timeout"},  # failed: not ranked
        {"model": "m", "layout": "reference", "crossings": "0"},  # the reference: not ranked
    ]
    r = ranks(rows)
    assert r[("m", "crossings")] == {"a": 1.5, "b": 1.5, "c": 3}  # lower is better; a tie shares 1 and 2
    assert r[("m", "species_drawn")] == {"a": 1, "b": 2}  # higher is better; no value: not ranked


def test_report_has_score_tables_and_a_summary(tmp_path):
    from layout_benchmark.report import write_report

    rows = [
        {"model": "m", "layout": "graphviz-dot", "seconds": "1", "crossings": "3", "edge_orthogonality": "0.9"},
        {"model": "m", "layout": "igraph-fr", "seconds": "2", "crossings": "1", "edge_orthogonality": "0.5"},
    ]
    for r in rows:
        r.update(species="2", reactions="1", edges="2")
    index = write_report(tmp_path, rows).read_text()
    assert "<table class=sortable>" in index and "summary.html" in index
    assert '<td data-v="1.0" class=best>1</td>' in index  # igraph-fr's crossings: the fewest
    assert '<td data-v="0.9" class=best>0.9</td>' in index  # graphviz-dot's orthogonality: the highest
    summary = (tmp_path / "summary.html").read_text()
    assert "median rank" in summary and "igraph-fr" in summary
    # where each metric comes from, in the headers; what each measures and how, on the summary page
    assert "general graph drawing (gdMetriX)" in index and "pathway maps (this package)" in summary
    assert "<h2 id=metrics>The metrics</h2>" in summary and "number_of_crossings on the drawn edge pieces" in summary


def test_every_metric_says_where_it_comes_from_and_how():
    from layout_benchmark.metrics import METRICS, SOURCES

    assert len({m.column for m in METRICS}) == len(METRICS)
    for m in METRICS:
        assert m.source in SOURCES and m.description and m.how, m.column
        assert m.better in ("lower", "higher", None), m.column
