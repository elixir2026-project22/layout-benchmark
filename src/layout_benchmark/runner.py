"""Run layouts on models, score them, write pictures and a results table."""

from __future__ import annotations

import csv
import json
import multiprocessing as mp
import time
from pathlib import Path

from .drawing import Drawing
from .graph import read_sbml
from .layouts import LAYOUTS, layout
from .metrics import all_metrics
from .reference import apply_gallery_classes, gallery_reference
from .render import to_svg
from .report import write_report

REFERENCE = "reference"


def _layout_worker(name, pathway, seed, queue):
    try:
        queue.put(("ok", layout(name, pathway, seed)))
    except Exception as ex:  # noqa: BLE001 -- any failure is the run's result, reported as its error (last line)
        lines = [line.strip() for line in str(ex).splitlines() if line.strip()]
        queue.put(("error", f"{type(ex).__name__}: {lines[-1] if lines else ''}"))


def run_layout(name, pathway, seed=0, timeout=300.0):
    """A layout in its own process, with a timeout. Returns (positions or None, seconds, error or None)."""
    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    proc = ctx.Process(target=_layout_worker, args=(name, pathway, seed, queue))
    start = time.perf_counter()
    proc.start()
    try:
        status, value = queue.get(timeout=timeout)
    except Exception:  # noqa: BLE001 -- queue.Empty on timeout, or a worker that died
        proc.kill()
        return None, timeout, f"timeout after {timeout:.0f} s"
    finally:
        proc.join(5)
    seconds = time.perf_counter() - start
    return (value, seconds, None) if status == "ok" else (None, seconds, value)


def model_names(models: list[Path]) -> dict[Path, str]:
    """A unique name per model: the file name, or, where several files share it (e.g. ``ja/sbml/model.xml`` and
    ``sa/sbml/model.xml``), with the nearest folders that tell them apart (``ja-model``, ``sa-model``)."""

    def folders(m):  # nearest first, without folders named after the format
        return [f for f in reversed(m.resolve().parent.parts) if f.lower() not in ("sbml", "xml", "models")]

    names = {m: m.stem for m in models}
    for depth in range(1, 6):
        counts = {}
        for n in names.values():
            counts[n] = counts.get(n, 0) + 1
        clashing = [m for m in models if counts[names[m]] > 1]
        if not clashing:
            break
        for m in clashing:
            names[m] = "-".join([*reversed(folders(m)[:depth]), m.stem])
    return names


def run(
    models: list[Path],
    layouts: list[str] | None,
    out: Path,
    seed: int = 0,
    timeout: float = 300.0,
    metrics: bool = False,
) -> Path:
    """Lay out every model with every layout (and its reference, if a ``.sbgn`` sits next to it), write
    ``out/<model>/<layout>.svg`` and ``out/results.csv``. Returns the CSV path."""
    layouts = layouts or list(LAYOUTS)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    sources = {}
    names = model_names(models)
    for model in models:
        pathway = read_sbml(model, name=names[model])
        sources[pathway.name] = model
        folder = out / pathway.name
        folder.mkdir(exist_ok=True)
        sbgn = model.with_suffix(".sbgn")
        reference = None
        if sbgn.exists():
            reference = gallery_reference(pathway, sbgn)
            apply_gallery_classes(pathway, sbgn)  # gallery SBML has no SBO terms; its SBGN map has the classes
        base = {
            "model": pathway.name,
            "species": len(pathway.species),
            "reactions": len(pathway.reactions),
            "edges": pathway.graph.number_of_edges(),
            "source": str(model.resolve()),
        }
        runs = [(REFERENCE, Drawing.of(pathway, reference), 0.0, None)] if reference else []
        for name in layouts:
            drawing, seconds, error = run_layout(name, pathway, seed, timeout)
            runs.append((name, drawing, seconds, error))
        for name, drawing, seconds, error in runs:
            row = {**base, "layout": name, "seconds": round(seconds, 3), "error": error or ""}
            if drawing is not None:
                notes = []
                missing = len(set(pathway.graph) - drawing.placed())
                if missing:
                    notes.append(f"{missing} of {pathway.graph.number_of_nodes()} nodes not placed")
                if drawing.has_clones:
                    notes.append(f"{drawing.graph.number_of_nodes()} drawn nodes (clones)")
                row["note"] = "; ".join(notes)
                # partial layouts (references, tools that leave nodes out) are drawn without the missing nodes
                if metrics:
                    pos = drawing.node_positions()
                    row.update(all_metrics(pathway, pos, reference if name != REFERENCE else None))
                (folder / f"{name}.svg").write_text(to_svg(drawing, f"{pathway.name}: {name}"))
                (folder / f"{name}.json").write_text(json.dumps(drawing.to_json(), indent=1))
            rows.append(row)
            print(f"{pathway.name:30} {name:24} {row['seconds']:8.2f}s {row['error']}")
        write_report(out, rows, sources)  # after each model, so a long run can be followed
    fields = list(dict.fromkeys(k for r in rows for k in r))
    path = out / "results.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    write_report(out, rows, sources)
    return path
