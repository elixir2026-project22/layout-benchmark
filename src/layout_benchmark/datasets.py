"""Fetching the benchmark's input files, and making models from Escher maps that come without one."""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .manifest import LOCK, ModelSpec, load, read_lock, slug

# short: where IPv6 is unreachable, urllib tries it first and only falls back to IPv4 after the timeout
TIMEOUT = 8


@functools.cache
def github_token() -> str | None:
    """A GitHub token for private repositories: GITHUB_TOKEN or GH_TOKEN, else the GitHub CLI's (``gh auth
    token``); None without one."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def get(url: str) -> bytes:
    """A URL's content; GitHub requests with a token where there is one (private repositories)."""
    headers = {"User-Agent": "layout-benchmark"}
    host = urllib.parse.urlparse(url).hostname
    if host in ("api.github.com", "raw.githubusercontent.com") and github_token():
        headers["Authorization"] = f"token {github_token()}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
            return r.read()
    except OSError as error:  # HTTPError, URLError, timeouts: say which URL
        hint = (
            " (a private repository needs a token: GITHUB_TOKEN, or `gh auth login`)" if "github" in str(host) else ""
        )
        raise OSError(f"{url}: {error}{hint}") from error


def fetch(manifest: str | Path, data: str | Path = "data", refresh: bool = False) -> list[ModelSpec]:
    """Download every remote model of a manifest, with its reference and companions, into ``data`` (files already
    there are kept; ``refresh``: GitHub refs and globs resolved again and everything downloaded again). Escher maps
    of ``convert: escher`` sets become a model and its reference (``escher_to_sbml``). Writes the lock file (the
    commits and the expanded globs). Returns the models."""
    data = Path(data)
    lock = {"commits": {}, "globs": {}} if refresh else read_lock(data)
    _, specs = load(manifest, data, lock=lock, online=True)
    jobs = {}
    for spec in specs:
        for path, url in spec.downloads().items():
            if refresh or not path.exists():
                jobs[path] = url

    def download(item):
        path, url = item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(url))

    def convert(spec):
        if refresh or not spec.path.exists() or not spec.reference.exists():
            title = urllib.parse.unquote(spec.url.rsplit("/", 1)[-1]).rsplit(".", 1)[0].strip()  # the map's file name
            sbml, reference = escher_to_sbml(json.loads(get(spec.url)), title)
            spec.path.parent.mkdir(parents=True, exist_ok=True)
            spec.path.write_text(sbml)
            spec.reference.write_text(json.dumps(reference))

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(download, jobs.items()))
        list(pool.map(convert, [s for s in specs if s.convert == "escher"]))
    data.mkdir(parents=True, exist_ok=True)
    (data / LOCK).write_text(json.dumps(lock, indent=1, sort_keys=True))
    return specs


# Recon3D's compartments (the suffix of its metabolite ids: man1p[c])
RECON_COMPARTMENTS = {
    "c": "cytosol",
    "e": "extracellular space",
    "g": "Golgi apparatus",
    "i": "inner mitochondrial compartment",
    "l": "lysosome",
    "m": "mitochondria",
    "n": "nucleus",
    "r": "endoplasmic reticulum",
    "x": "peroxisome",
}


def _sbml_id(escher_id: str) -> str:
    """An Escher (BiGG / VMH) id as an SBML SId without its prefix: man1p[c] -> man1p_c."""
    return re.sub(r"\W", "_", escher_id.replace("[", "_").replace("]", ""))


def escher_to_sbml(escher_map: list | dict, name: str) -> tuple[str, list | dict]:
    """A model for an Escher map that comes without one: SBML Level 3 with the map's reactions (all their
    metabolites, with their stoichiometry, as the map lists them) and metabolites (named as on the map; the
    compartment from the id's suffix, ``man1p[c]``). Ids become SBML ids (``M_man1p_c``, ``R_PMANM``); returns the
    SBML and the map with its ids changed to match (Escher's ids without the prefixes), the reference layout."""
    import copy

    import libsbml

    escher_map = copy.deepcopy(escher_map)
    body = escher_map[1] if isinstance(escher_map, list) else escher_map
    names = {}
    for node in body["nodes"].values():
        if node.get("node_type") == "metabolite":
            names.setdefault(node["bigg_id"], node.get("name") or node["bigg_id"])

    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    model.setId(f"M_{_sbml_id(slug(name))}")
    model.setName(name)
    compartments, species, reactions = set(), set(), set()

    def add_species(bigg_id: str) -> str:
        sid = _sbml_id(bigg_id)
        if sid in species:
            return sid
        species.add(sid)
        match = re.search(r"\[(\w+)\]$|_(\w)$", bigg_id)
        cid = (match.group(1) or match.group(2)) if match else "c"
        if cid not in compartments:
            compartments.add(cid)
            c = model.createCompartment()
            c.setId(f"C_{cid}")
            c.setName(RECON_COMPARTMENTS.get(cid, cid))
            c.setConstant(True)
        s = model.createSpecies()
        s.setId(f"M_{sid}")
        s.setName(names.get(bigg_id, bigg_id))
        s.setCompartment(f"C_{cid}")
        s.setSBOTerm(247)  # simple chemical
        s.setHasOnlySubstanceUnits(False)
        s.setBoundaryCondition(False)
        s.setConstant(False)
        return sid

    for reaction in body["reactions"].values():
        rid = _sbml_id(reaction["bigg_id"])
        reaction["bigg_id"] = rid
        for m in reaction.get("metabolites", []):
            m["bigg_id"] = add_species(m["bigg_id"])
        if rid in reactions:  # a reaction drawn twice: one SBML reaction
            continue
        reactions.add(rid)
        r = model.createReaction()
        r.setId(f"R_{rid}")
        r.setName(reaction.get("name") or rid)
        r.setReversible(bool(reaction.get("reversibility")))
        for m in sorted(reaction.get("metabolites", []), key=lambda m: m["bigg_id"]):
            ref = r.createReactant() if m["coefficient"] < 0 else r.createProduct()
            ref.setSpecies(f"M_{m['bigg_id']}")
            ref.setStoichiometry(abs(float(m["coefficient"])))
            ref.setConstant(True)
    for node in body["nodes"].values():
        if node.get("node_type") == "metabolite":
            node["bigg_id"] = add_species(node["bigg_id"])  # also metabolites drawn without a reaction
    return libsbml.writeSBMLToString(doc), escher_map
