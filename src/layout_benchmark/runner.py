"""Run layouts on models, score them, write pictures and a results table."""

from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import signal
import time
from pathlib import Path

from .graph import read_sbml
from .layouts import LAYOUTS, layout
from .manifest import ModelSpec, SetSpec, model_names, reference_kind
from .metrics import all_metrics
from .reference import apply_gallery_classes
from .reference import reference_drawing as reference_drawing_of
from .render import to_svg
from .report import write_report

REFERENCE = "reference"


def _layout_worker(name, pathway, seed, queue):
    os.setsid()  # its own process group: a timeout kills the tools it started too
    try:
        queue.put(("ok", layout(name, pathway, seed)))
    except Exception as ex:  # noqa: BLE001 -- any failure is the run's result, reported as its error (last line)
        lines = [line.strip() for line in str(ex).splitlines() if line.strip()]
        queue.put(("error", f"{type(ex).__name__}: {lines[-1] if lines else ''}"))


def run_layout(name, pathway, seed=0, timeout=300.0):
    """A layout in its own process, with a timeout. Returns (positions or None, seconds, error or None).

    The process matters for reproducibility too, not only for the timeout: a Graphviz engine's first layout in a
    process can differ from later ones (sfdp, issue #4). On a timeout, the worker's whole process group is killed,
    with the external tools it started."""
    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    proc = ctx.Process(target=_layout_worker, args=(name, pathway, seed, queue))
    start = time.perf_counter()
    proc.start()
    try:
        status, value = queue.get(timeout=timeout)
    except Exception:  # noqa: BLE001 -- queue.Empty on timeout, or a worker that died
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # gone already, or not yet its own group
            proc.kill()
        return None, timeout, f"timeout after {timeout:.0f} s"
    finally:
        proc.join(5)
    seconds = time.perf_counter() - start
    return (value, seconds, None) if status == "ok" else (None, seconds, value)


def has_sbml_layout(path: Path) -> bool:
    """Whether an SBML file has a layout of its own (SBML Layout package)."""
    import libsbml

    model = libsbml.readSBMLFromFile(str(path)).getModel()
    plugin = model.getPlugin("layout") if model is not None else None
    return bool(plugin and plugin.getNumLayouts())


def spec_for(path: Path) -> ModelSpec:
    """A model given as a plain file: its set is its folder; its reference the ``<stem>.sbgn`` or
    ``<stem>.escher.json`` next to it, else its own SBML Layout if it has one."""
    for reference in (path.with_suffix(".sbgn"), path.with_suffix(".escher.json")):
        if reference.exists():
            folder = path.resolve().parent.name
            return ModelSpec(path=path, set=folder, reference=reference, reference_kind=reference_kind(reference))
    if has_sbml_layout(path):
        return ModelSpec(path=path, set=path.resolve().parent.name, reference=path, reference_kind="sbml-layout")
    return ModelSpec(path=path, set=path.resolve().parent.name)


def run(
    models: list[Path | ModelSpec],
    layouts: list[str] | None,
    out: Path,
    seed: int = 0,
    timeout: float = 300.0,
    metrics: bool = False,
    append: bool = False,
    sets: list[SetSpec] | None = None,
) -> Path:
    """Lay out every model with every layout (and its reference layout, if it has one), write
    ``out/<model>/<layout>.svg`` and ``.json`` and ``out/results.csv``. Models are manifest entries (``ModelSpec``)
    or plain files. ``sets``: the manifest's sets (order, descriptions), saved as ``out/sets.json`` for the report.
    Returns the CSV path."""
    requested = set(layouts) if layouts else None  # with append: only these layouts' rows are replaced
    layouts = layouts or list(LAYOUTS)
    out.mkdir(parents=True, exist_ok=True)
    specs = [m if isinstance(m, ModelSpec) else spec_for(Path(m)) for m in models]
    if sets:
        (out / "sets.json").write_text(json.dumps([s.__dict__ for s in sets], indent=1))
    rows = []
    unnamed = model_names([s.path for s in specs if not s.name])
    names = {s.path: s.name or unnamed[s.path] for s in specs}
    kept = []  # with append: the rows of the other models already in out/results.csv
    if append and (out / "results.csv").exists():
        kept = [
            r
            for r in csv.DictReader((out / "results.csv").open())
            if r["model"] not in names.values()
            or (requested is not None and r["layout"] not in requested and r["layout"] != REFERENCE)
        ]
    for spec in specs:
        model = spec.path
        pathway = read_sbml(model, name=names[model])
        folder = out / pathway.name
        folder.mkdir(exist_ok=True)
        reference, reference_drawing = None, None
        if spec.reference:
            if spec.reference_kind == "sbgn":
                # its SBGN map has the classes and labels (the gallery SBML has no SBO terms, encoded names)
                apply_gallery_classes(pathway, spec.reference)
            reference_drawing = reference_drawing_of(pathway, spec.reference, spec.reference_kind)
            reference = reference_drawing.node_positions() if reference_drawing else None
        base = {
            "model": pathway.name,
            "set": spec.set,
            "species": len(pathway.species),
            "reactions": len(pathway.reactions),
            "edges": pathway.graph.number_of_edges(),
            "source": str(model.resolve()),
            "reference_file": str(spec.reference.resolve()) if spec.reference else "",
            "reference_kind": spec.reference_kind or "",
            "credit": spec.credit or "",
            "licence": spec.licence or "",
            "links": json.dumps(spec.links) if spec.links else "",
        }
        runs = []
        if reference:
            runs = [(REFERENCE, reference_drawing, 0.0, None)]
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
                # the JSON keeps the tool's own coordinates; pictures and metrics use the common scale
                (folder / f"{name}.json").write_text(json.dumps(drawing.to_json(), indent=1))
                scaled = drawing.normalised()
                if metrics:
                    row.update(all_metrics(pathway, scaled.node_positions(), reference if name != REFERENCE else None))
                (folder / f"{name}.svg").write_text(to_svg(scaled, f"{pathway.name}: {name}", pathway))
            rows.append(row)
            print(f"{pathway.name:30} {name:24} {row['seconds']:8.2f}s {row['error']}")
        # after each model, so a long run can be followed, and a stopped one loses nothing finished
        _write_results(out, kept + rows)
        write_report(out, kept + rows)
    return out / "results.csv"


def _write_results(out: Path, rows: list[dict]) -> Path:
    fields = list(dict.fromkeys(k for r in rows for k in r))
    path = out / "results.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path
