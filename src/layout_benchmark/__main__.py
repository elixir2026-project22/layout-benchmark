from pathlib import Path

import click

from .layouts import EXPECTED


@click.group()
def main():
    """Benchmark of automatic layout algorithms for pathway maps in SBML."""


@main.command("layouts")
def list_layouts():
    """List the layout algorithms, from the expected most promising to the least, with their group."""
    for name, group in EXPECTED:
        click.echo(f"{name}\t{group}")


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
    with (out / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    main()
