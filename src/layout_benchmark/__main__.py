import fcntl
import functools
import os
from contextlib import contextmanager
from pathlib import Path

import click

from .layouts import REGISTRY


@contextmanager
def locked(out: Path):
    """Hold OUT/.lock for a command that reads and rewrites OUT (results.csv is read once and rewritten whole, so
    two commands at once would overwrite each other's rows). A second command on the same folder stops at once."""
    out.mkdir(parents=True, exist_ok=True)
    f = (out / ".lock").open("a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.seek(0)
        holder = f.read().strip() or "?"
        f.close()
        raise click.ClickException(f"{out} is in use by another layout-benchmark command (pid {holder})") from None
    try:
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _locks_out(command):
    """Run a command holding its ``out`` folder's lock (``locked``)."""

    @functools.wraps(command)
    def wrapper(*args, **kwargs):
        with locked(kwargs["out"]):
            return command(*args, **kwargs)

    return wrapper


@click.group()
def main():
    """Benchmark of automatic layout algorithms for pathway maps in SBML."""


@main.command("layouts")
def list_layouts():
    """List the layout algorithms, from the expected most promising to the least, with their group, documentation
    and, for those that need a tool of their own, whether it is set up under .tools/."""
    from .external import TOOLS_DIR

    for spec in REGISTRY:
        tool = (
            ""
            if spec.tool is None
            else f"\t{'set up' if (TOOLS_DIR / spec.tool).is_dir() else 'not set up'}: {spec.tool}"
        )
        click.echo(f"{spec.name}\t{spec.group}\t{spec.link}{tool}")


@main.command()
@click.argument("models", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--layouts", "-l", default=None, help="Comma-separated layout names (default: all).")
@click.option("--out", "-o", default="results", type=click.Path(path_type=Path), help="Output folder.")
@click.option("--seed", default=0, show_default=True, help="Random seed.")
@click.option("--timeout", default=300.0, show_default=True, help="Seconds per layout run.")
@click.option("--metrics/--no-metrics", default=False, show_default=True, help="Also score the layouts.")
@click.option("--append", is_flag=True, help="Keep the other models already in OUT (their rows in results.csv).")
@click.option("--only", default=None, help="With a manifest: only these models (comma-separated names).")
@click.option(
    "--data",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="The manifest's cache of downloaded models (see `fetch`).",
)
@_locks_out
def run(models, layouts, out, seed, timeout, metrics, append, only, data):
    """Lay out SBML MODELS: a benchmark manifest (.yaml: sets, models, references, credits; fetched first with
    `fetch`), or SBML files (a <model>.sbgn or <model>.escher.json next to a model is its reference layout)."""
    from .manifest import load
    from .runner import run as run_all

    names = [x.strip() for x in layouts.split(",")] if layouts else None
    sets = None
    if len(models) == 1 and models[0].suffix in (".yaml", ".yml"):
        sets, specs = load(models[0], data)
        if only:
            wanted = {x.strip() for x in only.split(",")}
            specs = [s for s in specs if s.name in wanted]
            if missing := wanted - {s.name for s in specs}:
                raise click.UsageError(f"not in the manifest: {', '.join(sorted(missing))}")
        if absent := [str(s.path) for s in specs if not s.path.exists()]:
            raise click.UsageError(f"not fetched: {absent[0]} ({len(absent)} files); run `fetch {models[0]}`")
    else:
        specs = list(models)
    path = run_all(specs, names, out, seed, timeout, metrics, append, sets)
    click.echo(f"results: {path}")


@main.command()
@click.argument("out", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Take sets, reference files, links and credits from this manifest (for runs made without it).",
)
@click.option(
    "--data",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="The manifest's cache of downloaded models (see `fetch`).",
)
@_locks_out
def render(out, manifest, data):
    """Draw the pictures in OUT again from the saved positions (OUT/<model>/<layout>.json), with the current
    renderer and scale, and write OUT/index.html (without running the layouts)."""
    import csv
    import json

    from .drawing import Drawing
    from .reference import reference_drawing
    from .render import to_svg
    from .report import write_report

    rows = list(csv.DictReader((out / "results.csv").open())) if (out / "results.csv").exists() else []
    if manifest and rows:
        rows = _apply_manifest(out, rows, manifest, data)
    pathways = _pathways(rows)  # for compartment colours, names and reference boxes
    # every saved drawing (also of a run still going, whose newest models are not in results.csv yet)
    n = 0
    for path in sorted(out.glob("*/*.json")):
        drawing = Drawing.from_json(json.loads(path.read_text()))
        pathway, reference = pathways.get(path.parent.name, (None, None))
        if path.stem == "reference" and reference:
            # a reference is data, not a run: built again from its file (nodes and compartments in its own
            # coordinates), so older saved references (scaled, or without compartments) are replaced
            drawing = reference_drawing(pathway, *reference) or drawing
            path.write_text(json.dumps(drawing.to_json(), indent=1))
        title = f"{path.parent.name}: {path.stem}"
        path.with_suffix(".svg").write_text(to_svg(drawing.normalised(), title, pathway))
        n += 1
    if not rows:
        click.echo(f"{n} pictures (no results.csv yet: report not rewritten)")
        return
    click.echo(f"{n} pictures; report: {write_report(out, rows)}")


@main.command()
@click.argument("out", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--layouts", "-l", default=None, help="Comma-separated layout names (default: all).")
@click.option("--only", default=None, help="Only these models (comma-separated names).")
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Take reference files from this manifest (for runs made without it).",
)
@click.option(
    "--data",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="The manifest's cache of downloaded models (see `fetch`).",
)
@click.option("--timeout", default=600.0, show_default=True, help="Seconds per drawing.")
@click.option("--jobs", "-j", default=1, show_default=True, help="Drawings scored at once (processes).")
@_locks_out
def score(out, layouts, only, manifest, data, timeout, jobs):
    """Compute the metrics of the layouts in OUT from their saved drawings (OUT/<model>/<layout>.json, in each
    tool's own coordinates) and write them into OUT/results.csv (without running the layouts; other columns are
    kept). References are read again from their files, as in `render`. Each drawing is scored in its own process
    with a timeout, JOBS at a time; a drawing that fails or times out gets no metrics and its reason in the
    metrics_error column."""
    import copy
    import csv
    import json
    import time

    from .drawing import Drawing
    from .metrics import METRICS
    from .reference import reference_drawing
    from .report import write_report
    from .runner import REFERENCE, _write_results, score_drawings

    rows = list(csv.DictReader((out / "results.csv").open()))
    looked_up = _apply_manifest(out, copy.deepcopy(rows), manifest, data) if manifest else rows
    pathways = _pathways(looked_up)
    wanted_layouts = {x.strip() for x in layouts.split(",")} if layouts else None
    wanted_models = {x.strip() for x in only.split(",")} if only else None
    todo: dict[str, list[int]] = {}  # model -> indexes of its rows to score
    for i, row in enumerate(rows):
        model, name = row["model"], row["layout"]
        if (wanted_models and model not in wanted_models) or model not in pathways:
            continue
        if row.get("error") or not (out / model / f"{name}.json").exists():
            continue
        if wanted_layouts and name not in wanted_layouts:
            continue
        todo.setdefault(model, []).append(i)

    def tasks():
        for model, indexes in todo.items():
            pathway, ref = pathways[model]
            folder = out / model
            reference = reference_drawing(pathway, *ref) if ref else None
            if ref and reference is None and (folder / f"{REFERENCE}.json").exists():
                reference = Drawing.from_json(json.loads((folder / f"{REFERENCE}.json").read_text()))
            for i in indexes:
                name = rows[i]["layout"]
                drawing = (
                    reference
                    if name == REFERENCE and reference
                    else Drawing.from_json(json.loads((folder / f"{name}.json").read_text()))
                )
                yield i, drawing, pathway, reference if name != REFERENCE else None, name

    left = {model: len(indexes) for model, indexes in todo.items()}
    start, failed = time.perf_counter(), {model: 0 for model in todo}
    for i, values, error in score_drawings(tasks(), timeout, jobs):
        row = rows[i]
        for m in METRICS:  # no stale values from an earlier scoring
            row.pop(m.column, None)
        row.update(values or {})
        row["metrics_error"] = error or ""
        model = row["model"]
        if error:
            failed[model] += 1
            click.echo(f"  {model} {row['layout']}: {error}")
        left[model] -= 1
        if not left[model]:
            _write_results(out, rows)  # after each model: a stopped run keeps what is done
            n = len(todo[model])
            click.echo(f"{model:40} {n:3} drawings, {failed[model]} failed  ({time.perf_counter() - start:8.1f}s)")
    click.echo(f"results: {out / 'results.csv'}; report: {write_report(out, rows)}")


@main.command()
@click.argument("out", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--manifest",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Take sets, reference files, links and credits from this manifest (for runs made without it).",
)
@click.option(
    "--data",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="The manifest's cache of downloaded models (see `fetch`).",
)
@_locks_out
def report(out, manifest, data):
    """Write OUT/index.html again from OUT/results.csv (without running the layouts)."""
    import csv

    from .report import write_report

    rows = list(csv.DictReader((out / "results.csv").open()))
    if manifest:
        rows = _apply_manifest(out, rows, manifest, data)
    click.echo(f"report: {write_report(out, rows)}")


@main.command()
@click.argument("out", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("site", type=click.Path(file_okay=False, path_type=Path))
@click.option("--name", default=None, help="Folder name of the run in the site (default: OUT's name).")
@_locks_out
def publish(out, site, name):
    """Copy the run in OUT into SITE (a folder for GitHub Pages) as SITE/<name>/: the pictures, positions and
    results, with a report without local-file links; SITE/index.html lists the runs."""
    import csv
    import shutil
    from html import escape

    from .report import write_report

    name = name or out.name
    dest = site / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    rows = list(csv.DictReader((out / "results.csv").open()))
    for model in {r["model"] for r in rows}:
        if (out / model).is_dir():
            shutil.copytree(out / model, dest / model, ignore=shutil.ignore_patterns("*.png"))
    public_rows = [{k: v for k, v in r.items() if k not in ("source", "reference_file")} for r in rows]  # no paths
    if (out / "sets.json").exists():
        shutil.copy(out / "sets.json", dest / "sets.json")
    with (dest / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(public_rows[0]))
        w.writeheader()
        w.writerows(public_rows)
    write_report(dest, rows, local=False)
    runs = sorted(p.name for p in site.iterdir() if (p / "index.html").exists())
    items = "".join(f'<li><a href="{escape(r)}/index.html">{escape(r)}</a></li>' for r in runs)
    (site / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Layout benchmark</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:24px}</style>"
        "<h1>Layout benchmark</h1><p>BioHackathon Europe 2026, project 22 (Open Pathway Maps). "
        '<a href="https://github.com/elixir2026-project22/layout-benchmark">Code</a>.</p>'
        f"<ul>{items}</ul>"
    )
    (site / ".nojekyll").write_text("")
    click.echo(f"site: {site / 'index.html'}")


@main.command()
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--data",
    default="data",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Where to cache the models (<data>/<set>/).",
)
@click.option("--refresh", is_flag=True, help="Resolve GitHub refs and globs again, and download everything again.")
def fetch(manifest, data, refresh):
    """Download the models of MANIFEST, with their references and companion files, into DATA; Escher maps of
    `convert: escher` sets become models. Writes DATA/manifest.lock.json (the commits and expanded globs), so the
    other commands need no network."""
    from .datasets import fetch as fetch_all

    specs = fetch_all(manifest, data, refresh)
    remote = sum(1 for s in specs if s.url)
    click.echo(f"{len(specs)} models ({remote} fetched into {data}, {len(specs) - remote} local)")


def _pathways(rows: list[dict]) -> dict:
    """Per model of a run: its pathway (read again from its SBML, with the gallery's SBGN classes, labels and
    compartment names where it has an SBGN reference) and its reference (file, kind)."""
    from .graph import read_sbml
    from .manifest import reference_kind
    from .reference import apply_gallery_classes

    out = {}
    for r in rows:
        if r["model"] in out or not r.get("source") or not Path(r["source"]).exists():
            continue
        pathway = read_sbml(r["source"], name=r["model"])
        ref_file, kind = r.get("reference_file"), r.get("reference_kind") or ""
        if ref_file and not kind:
            kind = "sbml-layout" if ref_file == r["source"] else reference_kind(Path(ref_file))
        if ref_file and kind == "sbgn":
            apply_gallery_classes(pathway, ref_file)
        out[r["model"]] = (pathway, (ref_file, kind) if ref_file else None)
    return out


def _apply_manifest(out: Path, rows: list[dict], manifest: Path, data: Path) -> list[dict]:
    """Give an existing run's rows the sets, files, references, links and credits of a manifest (matched by model
    name), save the manifest's set order in OUT/sets.json, and write the rows back to OUT/results.csv."""
    import csv
    import json

    from .manifest import load

    sets, specs = load(manifest, data)
    by_name = {s.name: s for s in specs}
    for r in rows:
        spec = by_name.get(r["model"])
        if spec:
            r["set"] = spec.set
            r["source"] = str(spec.path.resolve())
            r["reference_file"] = str(spec.reference.resolve()) if spec.reference else ""
            r["reference_kind"] = spec.reference_kind or ""
            r["credit"] = spec.credit or ""
            r["licence"] = spec.licence or ""
            r["links"] = json.dumps(spec.links) if spec.links else ""
    (out / "sets.json").write_text(json.dumps([s.__dict__ for s in sets], indent=1))
    fields = list(dict.fromkeys(k for r in rows for k in r))
    path = out / "results.csv"
    if path.exists() and list(csv.DictReader(path.open())) == rows:
        return rows  # nothing changed: the file isn't rewritten
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    main()
