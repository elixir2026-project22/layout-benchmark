"""The benchmark manifest: which models, in which sets, with which reference layouts and credits.

A YAML file::

    sets:
      - name: metabolismregulation gallery
        models: data/gallery/*.xml            # a glob or a list of paths/globs, relative to the manifest
        reference: "{stem}.sbgn"              # optional: the reference layout next to each model
        credit: Map and layout, CC BY 4.0     # optional: shown with each model of the set
        licence: https://metabolismregulation.github.io/about/
        description: Hand-drawn maps ...      # optional: shown under the set's header
      - name: BRENDA pathways
        models: ../data_shared/brenda_*.xml

Sets keep the manifest's order; a model listed in two sets belongs to the first.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ModelSpec:
    path: Path
    set: str
    reference: Path | None = None
    credit: str | None = None
    licence: str | None = None


@dataclass(frozen=True)
class SetSpec:
    name: str
    description: str | None = None


def load(path: str | Path) -> tuple[list[SetSpec], list[ModelSpec]]:
    """The sets and the models of a manifest, in its order."""
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    base = path.resolve().parent
    sets, models, seen = [], [], set()
    for entry in data.get("sets", []):
        if "name" not in entry or "models" not in entry:
            raise ValueError(f"{path}: every set needs a name and models")
        sets.append(SetSpec(entry["name"], entry.get("description")))
        patterns = entry["models"] if isinstance(entry["models"], list) else [entry["models"]]
        files = []
        for pattern in patterns:
            matches = sorted(glob.glob(str(base / pattern)))
            if not matches:
                raise ValueError(f"{path}: set {entry['name']!r}: nothing matches {pattern!r}")
            files.extend(Path(m) for m in matches)
        for f in files:
            key = f.resolve()
            if key in seen:
                continue
            seen.add(key)
            reference = None
            if entry.get("reference"):
                candidate = f.parent / entry["reference"].format(stem=f.stem)
                reference = candidate if candidate.exists() else None
            models.append(
                ModelSpec(
                    path=f,
                    set=entry["name"],
                    reference=reference,
                    credit=entry.get("credit"),
                    licence=entry.get("licence"),
                )
            )
    return sets, models
