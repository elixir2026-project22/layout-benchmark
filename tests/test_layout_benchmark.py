import math
import re

import pytest
from scipy.spatial.distance import pdist

from layout_benchmark.drawing import SPACING
from layout_benchmark.graph import read_sbml
from layout_benchmark.layouts import LAYOUTS, layout
from layout_benchmark.metrics import (
    compartment_metrics,
    general_metrics,
    overlaps,
    participant_consistency,
    reference_similarity,
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


EXTERNAL = (
    "rules-claude",
    "ecmapper-brenda",
    "ecmapper-brenda-packed",
    "metacarto",
    "sbml2escher",
    "sbmlnetwork",
)  # need their own environments under .tools/


@pytest.mark.parametrize("name", [n for n in LAYOUTS if n not in EXTERNAL])
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
    """gdMetriX's metrics are tested upstream; here only that they run on our graphs."""
    p = read_sbml(tiny_sbml)
    m = general_metrics(p, layout("graphviz-neato", p).node_positions())
    assert m["crossings"] >= 0
    assert m["aspect_ratio"] > 0


def _line(tmp_path):
    """One reaction S -> r -> P."""
    return read_sbml(make_sbml(tmp_path / "line.xml", [("r", ["S"], ["P"], [])]))


def test_overlaps(tmp_path):
    p = _line(tmp_path)
    apart = {"S": (0, 0), "r": (100, 0), "P": (200, 0)}
    assert overlaps(p, apart)["overlapping_pairs"] == 0
    # species boxes are 60 wide: S and P 30 apart overlap, the reaction (10 wide) sits in between
    close = {"S": (0, 0), "r": (500, 0), "P": (30, 0)}
    assert overlaps(p, close)["overlapping_pairs"] == 1
    touching = {"S": (0, 0), "r": (500, 0), "P": (60, 0)}
    assert overlaps(p, touching)["overlapping_pairs"] == 0


def test_participant_consistency(tmp_path):
    p = _line(tmp_path)
    assert participant_consistency(p, {"S": (0, 0), "r": (100, 0), "P": (200, 0)}) == 1.0
    # product on the reactant's side
    assert participant_consistency(p, {"S": (0, 0), "r": (100, 0), "P": (10, 50)}) == 0.0


def test_compartment_metrics(tmp_path):
    path = make_sbml(
        tmp_path / "comp.xml",
        [("r1", ["A", "B"], ["C"], []), ("r2", ["X", "Y"], ["Z"], [])],
        compartments=("c1", "c2"),
        species_compartment={"X": "c2", "Y": "c2", "Z": "c2"},
    )
    p = read_sbml(path)
    separate = {
        "A": (0, 0),
        "B": (100, 0),
        "C": (50, 100),
        "X": (500, 0),
        "Y": (600, 0),
        "Z": (550, 100),
        "r1": (50, 50),
        "r2": (550, 50),
    }
    assert compartment_metrics(p, separate)["species_in_other_compartment"] == 0
    mixed = dict(separate, Z=(50, 30))  # Z inside the hull of c1
    assert compartment_metrics(p, mixed)["species_in_other_compartment"] == pytest.approx(1 / 6)


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
