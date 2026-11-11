"""Reproducibility of a layout: run it twice on the same model with the same seed and compare.

The project's layout rules list "Reproducibility of the same layout, e.g. cycle direction" as a hard rule, but
nothing measures it. The existing metrics cannot: ``reference_similarity`` is invariant to rotation and mirroring
by design, so a drawing that comes back flipped scores as identical to the one it flipped from, which is exactly
the case the rule is about.

Three outcomes per (model, layout), from strict to loose:

exact        every node at the same coordinates, before any normalisation. The tool is deterministic.
congruent    the same drawing up to translation, uniform scale, rotation or mirroring (Procrustes disparity
             below PROCRUSTES_TOL) but not exact. Shapes agree; the orientation on the page may not, and
             ``mirrored`` says whether aligning the two runs needed a reflection -- a flipped cycle.
differs      a different drawing.

``max_shift`` and ``median_shift`` are node displacements between the two runs after each is centred and scaled
the way the benchmark normalises drawings for its pictures and metrics, as a fraction of the drawing's own
diagonal, so they are comparable across models.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import procrustes

PROCRUSTES_TOL = 1e-6
EXACT_TOL = 0.0


def _matrix(pos: dict, nodes: list[str]) -> np.ndarray:
    return np.array([pos[n] for n in nodes], dtype=float)


def _diagonal(a: np.ndarray) -> float:
    span = a.max(axis=0) - a.min(axis=0)
    d = float(math.hypot(*span))
    return d if d > 0 else 1.0


def _mirrored(a: np.ndarray, b: np.ndarray) -> bool | None:
    """Whether the best similarity transform taking a onto b includes a reflection.

    The optimal orthogonal map is found as in Procrustes alignment (the SVD of the cross-covariance of the
    centred, scaled point sets); a negative determinant means the two runs are mirror images.
    """
    if len(a) < 3:
        return None

    def prep(x):
        x = x - x.mean(axis=0)
        n = np.linalg.norm(x)
        return x / n if n else x

    u, _, vt = np.linalg.svd(prep(a).T @ prep(b))
    return bool(np.linalg.det(u @ vt) < 0)


def compare_runs(first: dict, second: dict) -> dict[str, object]:
    """Compare two runs of one layout on one model. ``first``/``second`` are normalised node positions."""
    nodes = sorted(set(first) & set(second))
    result: dict[str, object] = {
        "nodes_compared": len(nodes),
        "nodes_only_in_one_run": len(set(first) ^ set(second)),
    }
    if len(nodes) < 3:
        return {**result, "verdict": "too_small", "max_shift": None, "median_shift": None,
                "procrustes": None, "mirrored": None}

    a, b = _matrix(first, nodes), _matrix(second, nodes)
    scale = max(_diagonal(a), _diagonal(b))
    shifts = np.linalg.norm(a - b, axis=1) / scale
    max_shift, median_shift = float(shifts.max()), float(np.median(shifts))

    # Procrustes needs both configurations to have non-zero spread
    try:
        _, _, disparity = procrustes(a, b)
        disparity = float(disparity)
    except ValueError:
        disparity = None

    if max_shift <= EXACT_TOL:
        verdict = "exact"
    elif disparity is not None and disparity < PROCRUSTES_TOL:
        verdict = "congruent"
    else:
        verdict = "differs"

    return {
        **result,
        "verdict": verdict,
        "max_shift": max_shift,
        "median_shift": median_shift,
        "procrustes": disparity,
        "mirrored": _mirrored(a, b) if verdict == "congruent" else None,
    }


__all__ = ["compare_runs"]