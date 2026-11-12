"""Print the metabolismregulation gallery's models as entries for benchmark.yaml (one-off: run again when the
gallery changes, and paste the output into the gallery set).

    uv run python scripts/gallery_manifest.py > gallery.yaml

Per map: its SBML (the plain ``-SBML`` export where there is one, the map's ``.xml`` otherwise), its SBGN-ML
(the reference layout) and its page on the gallery site. Maps are in ``atlas-downloads/`` or, for some, only in
``atlas-downloads/copy/``; a map in both is taken from the top folder. A map's page is the project page
(``_projects/*.md``, its ``permalink``) that links the map's number (F001-glycolysis-cardiac: the F001 page,
/glycolysis/).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import PurePosixPath

REPO = "metabolismregulation/metabolismregulation.github.io"
# The gallery's last commit with atlas-downloads/: the folder was removed on 2026-11-11 (eecc7be, "Old Atlas folders
# removed"), so HEAD no longer has the maps. Pinned to the commit before it.
REF = "bbe4f694ba2a1a8d1630c1628be5d8d8f5ec526e"
SITE = "https://metabolismregulation.github.io"


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()


def gallery_maps(paths: list[str]) -> dict[str, dict[str, str]]:
    """Per map (by name): its SBML and SBGN paths in the repository (see the module docstring)."""
    maps: dict[str, dict[str, str]] = {}
    for path in sorted(paths, key=lambda p: ("/copy/" in p, p)):  # the top folder first
        name = PurePosixPath(path).name
        if name.endswith("-SBML.xml"):
            stem, kind = name[: -len("-SBML.xml")], "sbml"
        elif name.endswith(".xml"):
            stem, kind = name[: -len(".xml")], "celldesigner_or_sbml"
        elif name.endswith(".sbgn"):
            stem, kind = name[: -len(".sbgn")], "sbgn"
        else:
            continue
        folder = str(PurePosixPath(path).parent)
        entry = maps.setdefault(stem, {"folder": folder})
        if entry["folder"] == folder:  # only files from the folder the map was first found in
            entry.setdefault(kind, path)
    for entry in maps.values():  # the plain SBML export where there is one
        entry["sbml"] = entry.get("sbml") or entry.pop("celldesigner_or_sbml", None)
        entry.pop("celldesigner_or_sbml", None)
    return {stem: e for stem, e in maps.items() if e.get("sbml") and e.get("sbgn")}


def project_pages(texts: list[str]) -> dict[str, str]:
    """Map number (F001) -> the page of the project that links it."""
    pages = {}
    for text in texts:
        permalink = re.search(r"^permalink:\s*(\S+)", text, re.MULTILINE)
        if permalink:
            for number in sorted(set(re.findall(r"\b(F\d{3})-", text))):
                pages.setdefault(number, SITE + permalink.group(1))
    return pages


def main() -> None:
    tree = json.loads(get(f"https://api.github.com/repos/{REPO}/git/trees/{REF}?recursive=1"))["tree"]
    paths = [t["path"] for t in tree]
    maps = gallery_maps([p for p in paths if p.startswith("atlas-downloads/")])
    projects = [p for p in paths if p.startswith("_projects/") and p.endswith(".md")]
    pages = project_pages([get(f"https://raw.githubusercontent.com/{REPO}/{REF}/{p}").decode() for p in projects])
    blob = f"https://github.com/{REPO}/blob/{REF}"
    for stem, entry in sorted(maps.items()):
        page = pages.get(stem[:4])
        if page is None:
            print(f"{stem}: no project page", file=sys.stderr)
        print(f"      - name: {stem}")
        print(f"        url: {blob}/{entry['sbml']}")
        print(f"        reference: {blob}/{entry['sbgn']}")
        print(f"        page: {page or SITE + '/gallery/'}")


if __name__ == "__main__":
    main()
