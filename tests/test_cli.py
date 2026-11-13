from click.testing import CliRunner

from layout_benchmark.__main__ import main
from layout_benchmark.layouts import LAYOUTS


def test_cli_lists_layouts():
    result = CliRunner().invoke(main, ["layouts"])
    assert result.exit_code == 0
    names = [line.split("\t")[0] for line in result.output.splitlines()]
    assert sorted(names) == sorted(LAYOUTS)


def test_cli_run(tmp_path, tiny_sbml):
    result = CliRunner().invoke(
        main, ["run", str(tiny_sbml), "-l", "graphviz-neato,networkx-spring", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "results.csv").exists()
    assert (tmp_path / "tiny" / "graphviz-neato.svg").exists()


def test_cli_run_rejects_unknown_layouts(tmp_path, tiny_sbml):
    result = CliRunner().invoke(
        main, ["run", str(tiny_sbml), "-l", "graphviz-neato,no-such-layout", "-o", str(tmp_path)]
    )
    assert result.exit_code != 0 and "unknown layouts: no-such-layout" in result.output
    assert not (tmp_path / "results.csv").exists()


def test_every_layout_spec_is_complete():
    from layout_benchmark.layouts import REGISTRY

    for spec in REGISTRY:
        assert spec.group and spec.link.startswith("https://"), spec.name
        assert spec.sizes in ("given", "escher", None), spec.name
