"""The benchmark manifest: which models, from where, in which sets, with which reference layouts, links and credits.

A YAML file::

    sets:
      - name: BRENDA pathways                   # models are cached in <data>/brenda-pathways/
        models: https://github.com/org/repo/blob/main/brenda_*.xml
        reference: https://github.com/org/ecmapper/blob/main/BRENDAmap/BRENDA_map_reactions.json
        reference_kind: brenda-map              # optional: the kind, where the extension doesn't say it (one
                                                #   file for every model of the set: BRENDA's map, cached once)
      - name: Escher maps
        models: "https://github.com/org/repo/blob/main/maps/**/*.json"
        convert: escher                         # each map becomes a model, and the map its reference layout
        credit: Maps by ...                     # optional: shown with each model of the set
        licence: https://...                    #   (the credit links to it)
        description: Hand-drawn maps ...        # optional: shown under the set's header
      - name: Gallery
        reference: "{stem}.sbgn"                # optional: the reference next to each model's source (SBGN-ML, or an
                                                #   Escher map: .json), or "layout": the model's own SBML Layout
        models:
          - name: F001-glycolysis               # an entry: name (in the report, and of the cached files), url,
            url: https://.../F001-glycolysis.xml  #   reference (a URL), files (companions, cached next to the
            reference: https://.../F001-glycolysis.sbgn  #   model), page (a link), credit and licence
            page: https://.../glycolysis/              #   (instead of the set's)
          - models/my-model.xml                 # a local file or glob, relative to the manifest (not cached)

A model is a URL, a GitHub glob (``https://github.com/<owner>/<repo>/blob/<ref>/<glob>``), a local path or glob,
or an entry. Remote files are cached as ``<data>/<set>/<name><suffix>`` (``fetch``); GitHub files are fetched at
the commit their ref had, recorded with the expanded globs in ``<data>/manifest.lock.json``. With the lock file,
``load`` needs no network; ``fetch --refresh`` resolves the refs and globs again.

Sets keep the manifest's order; a model listed in two sets belongs to the first. Model names are unique: the file
name, made unique with the nearest folders where files share it (``ja-model``, ``sa-model``).
"""

from __future__ import annotations

import glob
import json
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

LOCK = "manifest.lock.json"
# reference kinds whose file holds the references of many models (cached once per set)
SHARED_REFERENCES = ("brenda-map",)
GITHUB = re.compile(r"https://github\.com/([^/]+/[^/]+)/blob/([^/]+)/(.+)")


@dataclass(frozen=True)
class ModelSpec:
    path: Path  # the model file (cached, or local)
    set: str
    name: str | None = None
    reference: Path | None = None
    reference_kind: str | None = None  # "sbgn" (SBGN-ML), "escher" (an Escher map) or "sbml-layout" (its own)
    credit: str | None = None
    licence: str | None = None
    url: str | None = None  # where the model comes from (None: a local file)
    reference_url: str | None = None
    files: dict[Path, str] = field(default_factory=dict)  # companions: cached path -> URL
    convert: str | None = None  # "escher": url is an Escher map; path the model made from it
    links: dict[str, str] = field(default_factory=dict)  # shown in the report: model, reference, page

    def downloads(self) -> dict[Path, str]:
        """The files to fetch: cached path -> URL (none for a local model)."""
        if self.url is None:
            return {}
        out = {} if self.convert else {self.path: self.url}
        if self.reference_url and not self.convert:
            out[self.reference] = self.reference_url
        return {**out, **self.files}


@dataclass(frozen=True)
class SetSpec:
    name: str
    description: str | None = None


def reference_kind(path: str | PurePosixPath) -> str:
    """The kind of a reference layout file, by its extension: an Escher map (.json) or SBGN-ML."""
    return "escher" if str(path).endswith(".json") else "sbgn"


def slug(name: str) -> str:
    """A file name for a name: lower case ASCII, words joined by "-"."""
    dashes = "".join("-" if unicodedata.category(c) == "Pd" else c for c in name)  # N‑linked: a non-breaking hyphen
    ascii_name = unicodedata.normalize("NFKD", dashes).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def model_names(models: list) -> dict:
    """A unique name per model (a path or URL path): the file name, or, where several files share it (e.g.
    ``ja/sbml/model.xml`` and ``sa/sbml/model.xml``), with the nearest folders that tell them apart (``ja-model``,
    ``sa-model``)."""

    def folders(m):  # nearest first, without folders named after the format
        parent = m.resolve().parent if isinstance(m, Path) else m.parent
        return [f for f in reversed(parent.parts) if f.lower() not in ("sbml", "xml", "models")]

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


# --- GitHub ------------------------------------------------------------------------------------------------------


def _github_json(url: str):
    from .datasets import get

    return json.loads(get(url))


def _commit(repo: str, ref: str, lock: dict, online: bool) -> str:
    key = f"{repo}@{ref}"
    if key not in lock["commits"]:
        if not online:
            raise LookupError(key)
        lock["commits"][key] = _github_json(f"https://api.github.com/repos/{repo}/commits/{ref}")["sha"]
    return lock["commits"][key]


def _expand(url: str, lock: dict, online: bool) -> list[str]:
    """The URLs a GitHub glob matches (from the lock file, or the repository's tree at its ref's commit)."""
    m = GITHUB.match(url)
    if not m or not any(c in m.group(3) for c in "*?["):
        return [url]
    if url not in lock["globs"]:
        if not online:
            raise LookupError(url)
        repo, ref, pattern = m.groups()
        sha = _commit(repo, ref, lock, online)
        tree = _github_json(f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1")["tree"]
        paths = [t["path"] for t in tree if t["type"] == "blob" and _match(t["path"], pattern)]
        lock["globs"][url] = [f"https://github.com/{repo}/blob/{ref}/{p}" for p in sorted(paths)]
    return lock["globs"][url]


def _match(path: str, pattern: str) -> bool:
    """A glob match where ``**/`` is any number of folders (none included) and ``*`` stays in one folder."""
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.fullmatch(regex, path) is not None


def pinned(url: str, lock: dict, online: bool = False) -> tuple[str, str]:
    """(download URL, link) of a source: a GitHub file at its ref's commit (raw, and its GitHub page); others as
    they are."""
    m = GITHUB.match(url)
    if not m:
        return url, url
    repo, ref, path = m.groups()
    sha = _commit(repo, ref, lock, online)
    quoted = urllib.parse.quote(path)
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{quoted}", f"https://github.com/{repo}/blob/{sha}/{quoted}"


# --- loading -----------------------------------------------------------------------------------------------------


def _source_path(source: str) -> PurePosixPath:
    m = GITHUB.match(source)
    return PurePosixPath(m.group(3) if m else urllib.parse.unquote(urllib.parse.urlparse(source).path))


def read_lock(data: Path) -> dict:
    path = data / LOCK
    lock = json.loads(path.read_text()) if path.exists() else {}
    return {"commits": lock.get("commits", {}), "globs": lock.get("globs", {})}


def load(
    path: str | Path, data: str | Path = "data", lock: dict | None = None, online: bool = False
) -> tuple[list[SetSpec], list[ModelSpec]]:
    """The sets and the models of a manifest, in its order. Remote models are cached under ``data``; GitHub refs
    and globs are resolved from ``lock`` (default: the lock file in ``data``), or online with ``online`` (filling
    in ``lock``)."""
    path, data = Path(path), Path(data)
    lock = read_lock(data) if lock is None else lock
    text = yaml.safe_load(path.read_text()) or {}
    base = path.resolve().parent
    sets, raw, seen = [], [], set()
    try:
        for entry in text.get("sets", []):
            if "name" not in entry or "models" not in entry:
                raise ValueError(f"{path}: every set needs a name and models")
            sets.append(SetSpec(entry["name"], entry.get("description")))
            items = entry["models"] if isinstance(entry["models"], list) else [entry["models"]]
            for item in items:
                item = item if isinstance(item, dict) else {"url": item}
                source = item.get("url")
                if not source:
                    raise ValueError(f"{path}: set {entry['name']!r}: a model without a url")
                if "://" in source:
                    sources = _expand(source, lock, online)
                else:
                    sources = sorted(glob.glob(str(base / source)))
                if not sources:
                    raise ValueError(f"{path}: set {entry['name']!r}: nothing matches {source!r}")
                for s in sources:
                    if s not in seen:
                        seen.add(s)
                        raw.append((entry, item if len(sources) == 1 else {**item, "url": s}, s))
    except LookupError as missing:
        raise RuntimeError(f"{missing} is not in {data / LOCK}: run `layout-benchmark fetch {path}`") from None

    # names: given, else the file name (made unique over the whole manifest; converted maps: their slug)
    unnamed = {}
    for entry, item, s in raw:
        if not item.get("name"):
            unnamed[s] = Path(s) if "://" not in s else _source_path(s)
    names = model_names(list(unnamed.values()))
    models = []
    for entry, item, s in raw:
        name = item.get("name") or names[unnamed[s]]
        if entry.get("convert") and not item.get("name"):
            name = slug(name)
        models.append(_spec(entry, item, s, name, data, base, lock, online))
    return sets, models


def _spec(entry, item, source, name, data, base, lock, online) -> ModelSpec:
    convert = entry.get("convert")
    reference_pattern = item.get("reference") or entry.get("reference")
    given_kind = item.get("reference_kind") or entry.get("reference_kind")
    links = {}
    common = {  # a model's own credit and licence win over its set's
        "set": entry["name"],
        "credit": item.get("credit") or entry.get("credit"),
        "licence": item.get("licence") or entry.get("licence"),
    }
    page = item.get("page") or entry.get("page")
    if "://" not in source:  # a local file
        model = Path(source)
        reference, kind = None, None
        if reference_pattern == "layout":
            reference, kind = model, "sbml-layout"
        elif reference_pattern:
            candidate = model.parent / reference_pattern.format(stem=model.stem)
            if candidate.exists():
                reference, kind = candidate, given_kind or reference_kind(candidate)
        if page:
            links["page"] = page
        return ModelSpec(path=model, name=name, reference=reference, reference_kind=kind, links=links, **common)

    folder = data / slug(entry["name"])
    src = _source_path(source)
    download, links["model"] = pinned(source, lock, online)
    if convert == "escher":
        model = folder / f"{name}.xml"
        reference, kind, reference_url = folder / f"{name}.escher.json", "escher", source
        links["reference"] = links["model"]
    else:
        model = folder / f"{name}{src.suffix}"
        reference, kind, reference_url = None, None, None
        if reference_pattern == "layout":
            reference, kind = model, "sbml-layout"
        elif reference_pattern:
            ref_source = reference_pattern if "://" in reference_pattern else _sibling(source, reference_pattern, src)
            kind = given_kind or reference_kind(ref_source)
            if kind in SHARED_REFERENCES:  # one file for the whole set
                reference = folder / _source_path(ref_source).name
            else:
                reference = folder / f"{name}{'.escher.json' if kind == 'escher' else '.sbgn'}"
            reference_url, links["reference"] = pinned(ref_source, lock, online)
    files = {}
    for companion in item.get("files", []):
        files[folder / f"{name}{_source_path(companion).suffix}"] = pinned(companion, lock, online)[0]
    if page:
        links["page"] = page
    return ModelSpec(
        path=model,
        name=name,
        reference=reference,
        reference_kind=kind,
        url=download,
        reference_url=reference_url,
        files=files,
        convert=convert,
        links=links,
        **common,
    )


def _sibling(source: str, pattern: str, src: PurePosixPath) -> str:
    """The URL of a file next to a source: ``{stem}.sbgn`` next to ``.../F001.xml``."""
    return source[: source.rindex("/") + 1] + pattern.format(stem=src.stem)
