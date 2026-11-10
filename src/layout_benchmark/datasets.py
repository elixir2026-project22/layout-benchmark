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


def fetch_gallery(dest: str | Path) -> list[Path]:
    """Download the metabolismregulation gallery maps (SBML without layout + SBGN-ML with the hand-made layout)
    into ``dest``: ``<map>.xml`` and ``<map>.sbgn``. Files already there are kept. Returns the SBML files that
    have an SBGN partner. The map diagrams and data files are CC BY 4.0
    (https://metabolismregulation.github.io/about/); the report credits them."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tree_url = f"https://api.github.com/repos/{GALLERY_REPO}/git/trees/HEAD?recursive=1"
    tree = json.loads(_get(tree_url))["tree"]
    files = [
        t["path"] for t in tree if t["path"].startswith("atlas-downloads/") and t["path"].endswith((".xml", ".sbgn"))
    ]

    def fetch(f):
        target = dest / Path(f).name
        if not target.exists():
            target.write_bytes(_get(f"https://raw.githubusercontent.com/{GALLERY_REPO}/HEAD/{f}"))

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(fetch, files))
    # where each map comes from, for the report's links
    for f in files:
        if f.endswith(".xml"):
            stem = Path(f).stem
            sources = {
                "model": f"https://github.com/{GALLERY_REPO}/blob/HEAD/{f}",
                "reference": f"https://github.com/{GALLERY_REPO}/blob/HEAD/atlas-downloads/{stem}.sbgn",
                "page": "https://metabolismregulation.github.io/gallery/",
                "credit": "Map and layout: metabolismregulation gallery, CC BY 4.0",
                "licence": "https://metabolismregulation.github.io/about/",
            }
            (dest / f"{stem}.source.json").write_text(json.dumps(sources, indent=1))
    return sorted(p for p in dest.glob("*.xml") if p.with_suffix(".sbgn").exists())
