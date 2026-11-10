import math
import re

import pytest

from layout_benchmark.graph import read_sbml
from layout_benchmark.layouts import EDGE_LENGTH, LAYOUTS, layout
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


EXTERNAL = ("metacarto", "sbml2escher", "sbmlnetwork")  # need their own environments under .tools/


@pytest.mark.parametrize("name", [n for n in LAYOUTS if n not in EXTERNAL])
def test_every_layout_places_every_node(tiny_sbml, name):
    p = read_sbml(tiny_sbml)
    d = layout(name, p, seed=1)
    assert d.placed() == set(p.graph)
    assert all(math.isfinite(c) for xy in d.pos.values() for c in xy)


def test_layout_is_normalised_and_reproducible(tiny_sbml):
    p = read_sbml(tiny_sbml)
    a = layout("networkx-spring", p, seed=3).node_positions()
    b = layout("networkx-spring", p, seed=3).node_positions()
    assert a == b
    lengths = sorted(math.dist(a[u], a[v]) for u, v in p.graph.edges())
    assert lengths[len(lengths) // 2] == pytest.approx(EDGE_LENGTH, rel=0.2)


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
