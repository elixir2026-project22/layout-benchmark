"""Input data with reference layouts."""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GALLERY_REPO = "metabolismregulation/metabolismregulation.github.io"
# short: where IPv6 is unreachable, urllib tries it first and only falls back to IPv4 after the timeout
TIMEOUT = 8


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read()


def gallery_maps(paths: list[str]) -> dict[str, dict[str, str]]:
    """Per gallery map (by name): its SBML and SBGN paths in the repository. Maps are in ``atlas-downloads/`` or, for
    some, only in ``atlas-downloads/copy/``; there a map has a CellDesigner file (``<map>.xml``) and a plain SBML
    export (``<map>-SBML.xml``): the plain SBML is used. A map in both folders is taken from the top one."""
    maps: dict[str, dict[str, str]] = {}
    for path in sorted(paths, key=lambda p: ("/copy/" in p, p)):  # the top folder first
        name = Path(path).name
        if name.endswith("-SBML.xml"):
            stem, kind = name[: -len("-SBML.xml")], "sbml"
        elif name.endswith(".xml"):
            stem, kind = name[: -len(".xml")], "celldesigner_or_sbml"
        elif name.endswith(".sbgn"):
            stem, kind = name[: -len(".sbgn")], "sbgn"
        else:
            continue
        folder = str(Path(path).parent)
        entry = maps.setdefault(stem, {"folder": folder})
        if entry["folder"] == folder:  # only files from the folder the map was first found in
            entry.setdefault(kind, path)
    for entry in maps.values():  # the plain SBML export where there is one
        entry["sbml"] = entry.get("sbml") or entry.pop("celldesigner_or_sbml", None)
        entry.pop("celldesigner_or_sbml", None)
    return {stem: e for stem, e in maps.items() if e.get("sbml")}


def fetch_gallery(dest: str | Path) -> list[Path]:
    """Download the metabolismregulation gallery maps into ``dest``: per map ``<map>.xml`` (SBML) and, where it has
    one, ``<map>.sbgn`` (SBGN-ML with the hand-made layout), and ``<map>.source.json`` (links and credit). Files
    already there are kept. Returns the SBML files that have an SBGN partner. The map diagrams and data files are
    CC BY 4.0 (https://metabolismregulation.github.io/about/); the report credits them."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tree_url = f"https://api.github.com/repos/{GALLERY_REPO}/git/trees/HEAD?recursive=1"
    tree = json.loads(_get(tree_url))["tree"]
    maps = gallery_maps([t["path"] for t in tree if t["path"].startswith("atlas-downloads/")])

    def fetch(item):
        path, target = item
        if not target.exists():
            target.write_bytes(_get(f"https://raw.githubusercontent.com/{GALLERY_REPO}/HEAD/{path}"))

    jobs = []
    for stem, entry in maps.items():
        jobs.append((entry["sbml"], dest / f"{stem}.xml"))
        if entry.get("sbgn"):
            jobs.append((entry["sbgn"], dest / f"{stem}.sbgn"))
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(fetch, jobs))
    for stem, entry in maps.items():  # where each map comes from, for the report's links
        sources = {"model": f"https://github.com/{GALLERY_REPO}/blob/HEAD/{entry['sbml']}"}
        if entry.get("sbgn"):
            sources["reference"] = f"https://github.com/{GALLERY_REPO}/blob/HEAD/{entry['sbgn']}"
        sources.update(
            {
                "page": "https://metabolismregulation.github.io/gallery/",
                "credit": "Map and layout: metabolismregulation gallery, CC BY 4.0",
                "licence": "https://metabolismregulation.github.io/about/",
            }
        )
        (dest / f"{stem}.source.json").write_text(json.dumps(sources, indent=1))
    return sorted(p for p in dest.glob("*.xml") if p.with_suffix(".sbgn").exists())
