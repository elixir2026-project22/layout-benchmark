"""The project's layout rules (``rules``), on hand-made drawings."""

import math

import pytest

from layout_benchmark.drawing import Drawing
from layout_benchmark.graph import read_sbml
from layout_benchmark.metrics import all_metrics, own_sizes
from layout_benchmark.rules import (
    cofactor_hubs,
    crossings,
    cycles,
    is_cofactor,
    lines,
    lines_through_nodes,
    placement,
    shape,
)

from .conftest import make_sbml


def _drawn(p, pos, routes=None, **sizes):
    d = Drawing.of(p, pos)
    d.routes = routes or {}
    for n, (w, h) in sizes.items():
        d.graph.nodes[n].update(own_shape="box", own_width=w, own_height=h)
    return d


def _ring(tmp_path, n=4):
    """A cycle of n metabolites M0 -> M1 -> ... -> M0, one reaction per step."""
    ms = [f"M{i}" for i in range(n)]
    return read_sbml(make_sbml(tmp_path / "ring.xml", [(f"r{i}", [ms[i]], [ms[(i + 1) % n]], []) for i in range(n)]))


def _ring_pos(order, n=4, radius=100.0):
    """Metabolites on a circle in the given order, each step's reaction halfway (on the circle) between its two."""
    angle = {m: 2 * math.pi * k / n for k, m in enumerate(order)}
    pos = {m: (radius * math.cos(a), radius * math.sin(a)) for m, a in angle.items()}
    for i in range(n):
        a, b = angle[f"M{i}"], angle[f"M{(i + 1) % n}"]
        mid = math.atan2(math.sin(a) + math.sin(b), math.cos(a) + math.cos(b))
        pos[f"r{i}"] = (radius * math.cos(mid), radius * math.sin(mid))
    return pos


def test_a_cycle_drawn_as_a_loop_passes(tmp_path):
    p = _ring(tmp_path)
    assert cycles(Drawing.of(p, _ring_pos(["M0", "M1", "M2", "M3"]))) == {"rule_cycles": 1, "rule_cycles_closed": 1}


def test_a_cycle_drawn_out_of_order_fails(tmp_path):
    """The same metabolites on a circle, but not in cycle order: the loop crosses itself."""
    p = _ring(tmp_path)
    pos = _ring_pos(["M0", "M2", "M1", "M3"])
    assert cycles(Drawing.of(p, pos)) == {"rule_cycles": 1, "rule_cycles_closed": 0}


def test_a_stadium_is_a_loop_too(tmp_path):
    """Six metabolites on a long rounded rectangle: no circle, still a closed loop in order."""
    p = _ring(tmp_path, 6)
    ms = {"M0": (0, 0), "M1": (200, 0), "M2": (400, 0), "M3": (400, 100), "M4": (200, 100), "M5": (0, 100)}
    pos = dict(ms)
    for i in range(6):
        (x0, y0), (x1, y1) = ms[f"M{i}"], ms[f"M{(i + 1) % 6}"]
        pos[f"r{i}"] = ((x0 + x1) / 2, (y0 + y1) / 2)
    assert cycles(Drawing.of(p, pos))["rule_cycles_closed"] == 1


def test_cofactors_and_secondary_metabolites_make_no_cycle(tmp_path):
    """A -> B with ATP -> ADP, B -> A with ADP -> ATP: ATP/ADP would close a cycle; they are cofactors."""
    p = read_sbml(
        make_sbml(tmp_path / "c.xml", [("r1", ["A", "ATP"], ["B", "ADP"], []), ("r2", ["B", "ADP"], ["A", "ATP"], [])])
    )
    pos = {"A": (0, 0), "r1": (50, 0), "B": (100, 0), "r2": (50, 50), "ATP": (0, 50), "ADP": (100, 50)}
    assert cycles(Drawing.of(p, pos)) == {"rule_cycles": 0, "rule_cycles_closed": None}
    assert is_cofactor({"kind": "species", "of": "M_atp_c", "label": "x"})
    assert is_cofactor({"kind": "species", "of": "s1", "label": "NAD⁺"})
    assert not is_cofactor({"kind": "reaction", "of": "atp", "label": "atp"})


def test_cofactor_hubs_count_cofactors_drawn_once_for_several_reactions(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "h.xml", [("r1", ["A", "ATP"], ["B"], []), ("r2", ["B", "ATP"], ["C"], [])]))
    pos = {"A": (0, 0), "r1": (50, 0), "B": (100, 0), "r2": (150, 0), "C": (200, 0), "ATP": (100, 50)}
    d = Drawing.of(p, pos)
    assert cofactor_hubs(d) == 1
    # drawn twice, once per reaction: a clone, no hub
    d.graph.add_node("ATP@2", **{**d.graph.nodes["ATP"], "of": "ATP"})
    d.pos["ATP@2"] = (150, 50)
    d.graph.remove_edge("ATP", "r2")
    d.graph.add_edge("ATP@2", "r2", arc="consumption")
    assert cofactor_hubs(d) == 0
    no_cofactor = read_sbml(make_sbml(tmp_path / "n.xml", [("r", ["A"], ["B"], [])]))
    assert cofactor_hubs(Drawing.of(no_cofactor, {"A": (0, 0), "r": (1, 0), "B": (2, 0)})) is None


def test_crossings_skip_lines_that_share_an_end(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "x.xml", [("r1", ["A"], ["B"], []), ("r2", ["C"], ["D"], [])]))
    apart = {"A": (0, 0), "r1": (100, 0), "B": (200, 0), "C": (0, 100), "r2": (100, 100), "D": (200, 100)}
    assert crossings(Drawing.of(p, apart)) == 0
    # A-r1 crosses C-r2 (no shared end): 1 crossing over 4 lines
    crossed = dict(apart, A=(50, 150), C=(50, -50))
    assert crossings(Drawing.of(p, crossed)) == pytest.approx(1 / 4)
    # lines into the same reaction never count, even when they cross
    q = read_sbml(make_sbml(tmp_path / "y.xml", [("r", ["A", "C"], ["B"], [])]))
    d = _drawn(q, {"A": (0, 0), "C": (0, 100), "r": (100, 50), "B": (200, 50)}, routes={("A", "r"): [(50, 150)]})
    assert crossings(d) == 0


def test_lines_through_species_nodes_not_reactions(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "t.xml", [("r1", ["A"], ["B"], []), ("r2", ["C"], ["D"], [])]))
    pos = {"A": (0, 0), "r1": (100, 0), "B": (200, 0), "C": (100, -100), "r2": (100, 100), "D": (300, 300)}
    sized = {n: (20, 20) for n in pos}
    d = _drawn(p, pos, **sized)
    sizes = own_sizes(d, p)
    # C -> r2 passes through r1 (a reaction: not counted); move B onto it: counted
    assert lines_through_nodes(d, sizes) == 0
    d = _drawn(p, dict(pos, B=(100, 50)), **sized)
    assert lines_through_nodes(d, own_sizes(d, p)) == 1
    # grazing an edge is no pass-through
    d = _drawn(p, dict(pos, B=(110, 50)), **sized)
    assert lines_through_nodes(d, own_sizes(d, p)) == 0
    assert lines_through_nodes(d, None) is None


def test_placement_opposite_and_modifiers_beside(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "p.xml", [("r", ["S"], ["P"], ["E"])]))
    assert placement(Drawing.of(p, {"S": (0, 0), "r": (100, 0), "P": (200, 0), "E": (100, 80)})) == {
        "rule_opposite_share": 1,
        "rule_modifiers_beside": 1,
    }
    # product at 90 degrees, enzyme along the line
    same_side = placement(Drawing.of(p, {"S": (0, 0), "r": (100, 0), "P": (100, 100), "E": (300, 0)}))
    assert same_side["rule_opposite_share"] == 0


def test_shape_uses_the_nodes_extent_and_own_sizes(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "s.xml", [("r", ["S"], ["P"], [])]))
    d = _drawn(p, {"S": (0, 0), "r": (100, 0), "P": (200, 0)}, S=(20, 20), r=(20, 20), P=(20, 20))
    d.compartments = {"c": {"box": [-500, -500, 500, 500], "label": "c"}}  # not part of the extent
    s = shape(d, own_sizes(d, p))
    assert s["rule_aspect"] == pytest.approx(220 / 20)
    assert s["rule_density"] == pytest.approx(3 * 400 / (220 * 20))
    assert shape(Drawing.of(p, {"S": (0, 0), "r": (100, 0), "P": (200, 100)}), None) == {
        "rule_aspect": 2.0,
        "rule_density": None,
    }


def test_bends_count_turns_over_25_degrees(tmp_path):
    p = read_sbml(make_sbml(tmp_path / "b.xml", [("r", ["S"], ["P"], [])]))
    pos = {"S": (0, 0), "r": (100, 0), "P": (300, 0)}
    gentle = {("r", "P"): [(200, 20)]}  # about 11 degrees
    sharp = {("r", "P"): [(200, 100)]}  # one point, turning 90 degrees
    assert lines(_drawn(p, pos, gentle))["rule_bends_per_line"] == 0
    assert lines(_drawn(p, pos, sharp))["rule_bends_per_line"] == pytest.approx(1 / 2)
    assert lines(_drawn(p, pos))["rule_longest_over_median"] == pytest.approx(200 / 150)


def test_all_metrics_has_the_rules(tiny_sbml):
    p = read_sbml(tiny_sbml)
    pos = {"A": (0, 0), "r1": (50, 30), "B": (100, 0), "r2": (80, -50), "C": (50, -80), "r3": (20, -50), "E": (50, 90)}
    m = all_metrics(Drawing.of(p, pos), p, layout="graphviz-dot")
    assert {k for k in m if k.startswith("rule_")} >= {"rule_cycles_closed", "rule_crossings_per_line", "rule_aspect"}
    assert m["rule_cycles"] == 1
