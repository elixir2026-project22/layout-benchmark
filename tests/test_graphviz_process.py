"""Graphviz layouts give the same drawing for the same seed in every process (issue #19).

fdp, called through pygraphviz in a process that has read an SBML model, came out as a different drawing from one
process to the next (the same DOT through the fdp binary or a clean process was always the same). Each test run
here is a new Python process that reads the model and lays it out, as the benchmark's runs do.
"""

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import make_sbml

SCRIPT = """
import json, sys
from layout_benchmark.graph import read_sbml
from layout_benchmark.layouts import LAYOUTS
pos = LAYOUTS[sys.argv[2]](read_sbml(sys.argv[1]), 0)
print(json.dumps(sorted((str(n), [round(c, 6) for c in xy]) for n, xy in pos.items())))
"""


@pytest.fixture
def chain_sbml(tmp_path):
    """A chain of 30 reactions with some enzymes and eight cross links: 79 nodes, enough for fdp to vary."""
    rng = random.Random(1)
    reactions = [(f"r{i}", [f"S{i}"], [f"S{i + 1}"], [f"E{i}"] if i % 3 == 0 else []) for i in range(30)]
    reactions += [(f"x{i}", [f"S{rng.randrange(30)}"], [f"S{rng.randrange(30)}"], []) for i in range(8)]
    return make_sbml(tmp_path / "chain.xml", reactions)


def _layout_in_new_process(path: Path, layout: str) -> list:
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(path), layout], capture_output=True, text=True, check=True, timeout=120
    )
    return json.loads(out.stdout)


@pytest.mark.parametrize("layout", ["graphviz-fdp", "graphviz-neato", "graphviz-sfdp"])
def test_graphviz_same_seed_same_drawing_in_every_process(chain_sbml, layout):
    runs = [_layout_in_new_process(chain_sbml, layout) for _ in range(4)]
    assert len(runs[0]) == 79
    assert all(r == runs[0] for r in runs[1:]), f"{layout}: {len({json.dumps(r) for r in runs})} drawings in 4 runs"


@pytest.mark.parametrize("layout", ["graphviz-dot", "graphviz-neato"])
def test_graphviz_draws_the_graph_as_built_in_process(chain_sbml, layout):
    # the child builds the graph as the adapter used to, in-process: the same node and edge order and attributes
    # (DOT text would drop label="" and reorder edges, and dot and neato would draw something else)
    import pygraphviz

    from layout_benchmark.graph import read_sbml
    from layout_benchmark.layouts import LAYOUTS

    pathway = read_sbml(chain_sbml)
    prog = layout.removeprefix("graphviz-")
    a = pygraphviz.AGraph(directed=True, strict=False)
    a.graph_attr.update(start="0", overlap="scale" if prog != "dot" else "true", splines="false")
    a.node_attr.update(shape="box", fixedsize="true", label="")
    ids = {n: f"n{i}" for i, n in enumerate(pathway.graph)}
    for n, d in pathway.graph.nodes(data=True):
        a.add_node(ids[n], width=d["width"] / 72, height=d["height"] / 72)
    for u, v in pathway.graph.edges():
        a.add_edge(ids[u], ids[v])
    a.layout(prog=prog)
    back = {i: n for n, i in ids.items()}
    in_process = {back[str(n)]: tuple(map(float, n.attr["pos"].split(",")[:2])) for n in a.nodes()}
    assert LAYOUTS[layout](pathway, 0) == in_process
