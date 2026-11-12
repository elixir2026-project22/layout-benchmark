"""Reproducibility of a layout: the same model and seed laid out twice, and the two drawings compared.

"Reproducibility of the same layout, e.g. cycle direction" is one of the project's hard rules for pathway maps.
The comparison with the reference cannot check it: it is invariant to rotation and mirroring by design, so a
drawing that comes back flipped scores as identical to the one it flipped from, which is the case the rule names.

Not a metric of one drawing (``metrics.py`` scores a drawing as shown), so it has its own command,
``layout-benchmark reproducibility``, and its own table, ``reproducibility.csv``. Each run goes through
``runner.run_layout``, in a process of its own, as in the benchmark: within one process a Graphviz engine's first
layout can differ from its later ones (issue #4), so runs compared in one process would not say what the
benchmark's runs do.

Like the metrics, the comparison is on the drawings as shown, in the tool's own coordinates: drawn nodes (clones
are nodes), nothing rescaled.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from scipy.spatial import procrustes

from .drawing import Drawing, Positions
from .manifest import ModelSpec
from .runner import model_pathway, run_layout, spec_for

CONGRUENT_BELOW = 1e-6  # Procrustes disparity (0 to 1) under which two runs are the same drawing, moved or turned

COLUMNS = [
    "model",
    "nodes",
    "layout",
    "seed",
    "verdict",
    "max_shift",
    "median_shift",
    "procrustes",
    "mirrored",
    "nodes_compared",
    "nodes_in_one_run",
    "seconds_first",
    "seconds_second",
    "error",
]


def _mirrored(a: np.ndarray, b: np.ndarray) -> bool:
    """Whether the best similarity transform from a to b includes a reflection (the orthogonal map of the
    Procrustes alignment, from the SVD of the cross-covariance of the centred point sets, has determinant -1)."""
    a = a - a.mean(axis=0)
    b = b - b.mean(axis=0)
    u, _, vt = np.linalg.svd(a.T @ b)
    return bool(np.linalg.det(u @ vt) < 0)


def compare_runs(first: Positions, second: Positions) -> dict[str, object]:
    """Compare two runs of one layout on one model, from the positions of their drawn nodes.

    ``verdict``:

    - ``exact``: the same drawn nodes, each at the same coordinates in both runs.
    - ``congruent``: not exact, but the same drawing up to translation, uniform scale, rotation or mirroring
      (Procrustes disparity below ``CONGRUENT_BELOW``); ``mirrored`` then says whether the second run is a mirror
      image of the first (a cycle drawn the other way round).
    - ``differs``: a different drawing, or the runs don't draw the same nodes.
    - ``too_small``: fewer than three nodes in common, or all of them at one point; nothing to compare.

    ``max_shift`` and ``median_shift``: how far the nodes moved between the runs, in the tool's own coordinates,
    as a fraction of the larger drawing's diagonal (0 when exact). ``procrustes``: the disparity that remains
    after the best alignment (0 to 1). ``nodes_in_one_run``: drawn nodes that only one of the runs has.
    """
    nodes = sorted(set(first) & set(second))
    result: dict[str, object] = {
        "verdict": "too_small",
        "max_shift": None,
        "median_shift": None,
        "procrustes": None,
        "mirrored": None,
        "nodes_compared": len(nodes),
        "nodes_in_one_run": len(set(first) ^ set(second)),
    }
    if len(nodes) < 3:
        return result
    a = np.array([first[n] for n in nodes], dtype=float)
    b = np.array([second[n] for n in nodes], dtype=float)
    diagonal = max(math.hypot(*np.ptp(a, axis=0)), math.hypot(*np.ptp(b, axis=0)))
    if diagonal == 0:
        return result
    shifts = np.linalg.norm(a - b, axis=1) / diagonal
    result["max_shift"], result["median_shift"] = float(shifts.max()), float(np.median(shifts))
    try:
        disparity = float(procrustes(a, b)[2])
    except ValueError:  # one run puts every node at one point
        disparity = None
    result["procrustes"] = disparity
    if result["nodes_in_one_run"]:  # the runs don't draw the same nodes (other clones, nodes left out)
        result["verdict"] = "differs"
    elif result["max_shift"] == 0:
        result["verdict"] = "exact"
    elif disparity is not None and disparity < CONGRUENT_BELOW:
        result["verdict"] = "congruent"
        result["mirrored"] = _mirrored(a, b)
    else:
        result["verdict"] = "differs"
    return result


def _saved_run(against: Path, model: str, layout: str) -> Positions | None:
    """The drawn node positions a benchmark run saved (``<against>/<model>/<layout>.json``, the tool's own
    coordinates), or None where it saved none (the run failed or timed out)."""
    path = against / model / f"{layout}.json"
    if not path.exists():
        return None
    return Drawing.from_json(json.loads(path.read_text())).pos


def check(
    models: list[Path | ModelSpec],
    layouts: list[str],
    seed: int = 0,
    timeout: float = 300.0,
    names: dict[Path, str] | None = None,
    against: Path | None = None,
) -> Iterator[dict]:
    """One row (``COLUMNS``) per model and layout: the layout run twice with ``seed``, each run in its own process
    (``run_layout``), and the two drawings compared. A layout that fails or times out has ``verdict`` "error" and
    the reason in ``error``: no result about its reproducibility. ``names``: the models' names (as in a benchmark
    run; default: the file names). ``against``: a benchmark run's folder whose saved drawings (made with the same
    seed) serve as the first runs, so each layout runs only once more; where that run saved no drawing, the row is
    an error without running again. Each model is read as ``run`` reads it (``model_pathway``: a gallery model
    with its reference's classes and labels), so the drawings compared are the benchmark's."""
    for item in models:
        spec = item if isinstance(item, ModelSpec) else spec_for(item)
        model = (names or {}).get(spec.path, spec.name or spec.path.stem)
        pathway = model_pathway(spec, model)
        for name in layouts:
            row = dict.fromkeys(COLUMNS)
            row.update(model=model, nodes=pathway.graph.number_of_nodes(), layout=name, seed=seed)
            runs = []
            if against is not None:
                first = _saved_run(against, model, name)
                if first is None:
                    row.update(verdict="error", error=f"no drawing saved in {against.name} (the run failed)")
                    yield row
                    continue
                runs.append(first)
            for when in ("seconds_first", "seconds_second")[len(runs) :]:
                drawing, seconds, error = run_layout(name, pathway, seed=seed, timeout=timeout)
                row[when] = round(seconds, 3)
                if error or drawing is None:
                    row.update(verdict="error", error=error or "no drawing")
                    break
                runs.append(drawing.pos)
            else:
                row.update(compare_runs(*runs))
            yield row


SEED_COLUMNS = [
    "model",
    "nodes",
    "layout",
    "seed",
    "base_seed",
    "verdict",
    "max_shift",
    "median_shift",
    "procrustes",
    "mirrored",
    "nodes_compared",
    "nodes_in_one_run",
    "seconds_base",
    "seconds",
    "error",
]


def across_seeds(
    models: list[Path | ModelSpec],
    layouts: list[str],
    seeds: list[int],
    timeout: float = 300.0,
    names: dict[Path, str] | None = None,
) -> Iterator[dict]:
    """How much a layout's drawing depends on its seed: each layout run once per seed, each in its own process
    (``run_layout``), and each drawing compared (``compare_runs``) with the drawing of the first seed
    (``base_seed``). One row (``SEED_COLUMNS``) per model, layout and seed after the first.

    A layout that ignores its seed comes out exact; a seeded force-directed layout is expected to differ, and
    ``procrustes``, ``max_shift`` and ``median_shift`` say by how much. Mirrored drawings (``congruent``,
    ``mirrored``) are the case the same-seed check cannot show between seeds: the same drawing, the other way
    round. Where the first seed's run fails, every row of that layout is an error; where a later seed fails,
    only its row."""
    if len(set(seeds)) < 2 or len(set(seeds)) != len(seeds):
        raise ValueError(f"at least two distinct seeds needed, got {seeds}")
    base, *others = seeds
    for item in models:
        spec = item if isinstance(item, ModelSpec) else spec_for(item)
        model = (names or {}).get(spec.path, spec.name or spec.path.stem)
        pathway = model_pathway(spec, model)
        for name in layouts:
            first, seconds_base, base_error = run_layout(name, pathway, seed=base, timeout=timeout)
            for seed in others:
                row = dict.fromkeys(SEED_COLUMNS)
                row.update(
                    model=model,
                    nodes=pathway.graph.number_of_nodes(),
                    layout=name,
                    seed=seed,
                    base_seed=base,
                    seconds_base=round(seconds_base, 3),
                )
                if base_error or first is None:
                    row.update(verdict="error", error=f"seed {base}: {base_error or 'no drawing'}")
                    yield row
                    continue
                drawing, seconds, error = run_layout(name, pathway, seed=seed, timeout=timeout)
                row["seconds"] = round(seconds, 3)
                if error or drawing is None:
                    row.update(verdict="error", error=error or "no drawing")
                else:
                    compared = compare_runs(first.pos, drawing.pos)
                    row.update({k: v for k, v in compared.items() if k in SEED_COLUMNS})
                yield row
