import csv
import math

import pytest
from click.testing import CliRunner

from layout_benchmark.__main__ import main
from layout_benchmark.reproducibility import COLUMNS, check, compare_runs

# a 2 x 1 rectangle with a fifth node off-centre, so that it has no symmetry of its own
SHAPE = {"a": (0.0, 0.0), "b": (2.0, 0.0), "c": (2.0, 1.0), "d": (0.0, 1.0), "e": (0.5, 0.25)}


def _transformed(pos, angle=0.0, scale=1.0, shift=(0.0, 0.0), mirror=False):
    out = {}
    for n, (x, y) in pos.items():
        if mirror:
            x = -x
        xr = x * math.cos(angle) - y * math.sin(angle)
        yr = x * math.sin(angle) + y * math.cos(angle)
        out[n] = (scale * xr + shift[0], scale * yr + shift[1])
    return out


def test_identical_runs_are_exact():
    r = compare_runs(SHAPE, dict(SHAPE))
    assert r["verdict"] == "exact"
    assert r["max_shift"] == 0 and r["median_shift"] == 0
    assert r["procrustes"] == pytest.approx(0, abs=1e-12)
    assert r["mirrored"] is None
    assert r["nodes_compared"] == 5 and r["nodes_in_one_run"] == 0


def test_moved_turned_and_scaled_is_congruent_not_mirrored():
    r = compare_runs(SHAPE, _transformed(SHAPE, angle=0.7, scale=3.0, shift=(10.0, -4.0)))
    assert r["verdict"] == "congruent"
    assert r["mirrored"] is False
    assert r["max_shift"] > 0
    assert r["procrustes"] == pytest.approx(0, abs=1e-9)


def test_mirror_image_is_congruent_and_mirrored():
    # what the comparison with the reference cannot see: the same shape, drawn the other way round
    r = compare_runs(SHAPE, _transformed(SHAPE, angle=0.3, mirror=True))
    assert r["verdict"] == "congruent"
    assert r["mirrored"] is True


def test_one_node_moved_differs_with_a_known_shift():
    second = {**SHAPE, "c": (2.0, 2.0)}  # c moves up by 1; the second drawing is 2 x 2, diagonal sqrt(8)
    r = compare_runs(SHAPE, second)
    assert r["verdict"] == "differs"
    assert r["max_shift"] == pytest.approx(1 / math.sqrt(8))
    assert r["median_shift"] == 0  # the other four nodes stay
    assert r["procrustes"] > 1e-6
    assert r["mirrored"] is None


def test_runs_that_draw_other_nodes_differ():
    second = {**SHAPE, "f": (1.0, 1.0)}
    r = compare_runs(SHAPE, second)
    assert r["verdict"] == "differs"
    assert r["nodes_compared"] == 5 and r["nodes_in_one_run"] == 1


def test_too_small_to_compare():
    assert compare_runs({"a": (0, 0), "b": (1, 1)}, {"a": (0, 0), "b": (1, 1)})["verdict"] == "too_small"
    same_point = dict.fromkeys("abc", (1.0, 1.0))
    assert compare_runs(same_point, same_point)["verdict"] == "too_small"


def test_check_runs_each_layout_twice(tiny_sbml):
    rows = list(check([tiny_sbml], ["graphviz-neato", "networkx-spring"], seed=2, timeout=60))
    assert [r["layout"] for r in rows] == ["graphviz-neato", "networkx-spring"]
    for r in rows:
        assert list(r) == COLUMNS
        assert r["verdict"] == "exact", r
        assert r["model"] == "tiny" and r["seed"] == 2 and r["nodes"] == 7
        assert r["seconds_first"] is not None and r["seconds_second"] is not None


def test_check_reports_a_failing_layout_as_error(tiny_sbml):
    (row,) = check([tiny_sbml], ["no-such-layout"], timeout=60)
    assert row["verdict"] == "error" and row["error"]
    assert row["max_shift"] is None


def test_cli_reproducibility(tmp_path, tiny_sbml):
    out = tmp_path / "repro.csv"
    result = CliRunner().invoke(
        main, ["reproducibility", str(tiny_sbml), "-l", "graphviz-dot,igraph-kk", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert [(r["layout"], r["verdict"]) for r in rows] == [("graphviz-dot", "exact"), ("igraph-kk", "exact")]
    assert "graphviz-dot\texact 1" in result.output


def test_cli_reproducibility_rejects_an_unknown_layout(tmp_path, tiny_sbml):
    result = CliRunner().invoke(main, ["reproducibility", str(tiny_sbml), "-l", "nope", "-o", str(tmp_path / "r.csv")])
    assert result.exit_code != 0
    assert "unknown layouts: nope" in result.output
