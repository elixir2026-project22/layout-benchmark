"""The version of the code behind each layout, recorded with every run (``results.csv`` column ``tool_version``).

A layout's tool under ``.tools/`` is named by its git tag or commit (``-dirty`` with local changes), or, for a
folder that is no clone of its own (SBMLNetwork, installed with pip), by the version installed in its environment.
Python packages are named by their installed version, JavaScript packages by the version in ``js/node_modules``,
and Graphviz by the version pygraphviz is built with.
"""

from __future__ import annotations

import functools
import importlib.metadata
import json
import subprocess
from pathlib import Path

from .external import TOOLS_DIR
from .layouts import JS_DIR, SPECS, LayoutSpec


def _run(args: list[str], cwd: Path | None = None) -> str | None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _tool_version(folder: Path, package: str) -> str:
    if not folder.is_dir():
        return "not set up"
    top = _run(["git", "rev-parse", "--show-toplevel"], cwd=folder)
    if top and Path(top).resolve() == folder.resolve():  # its own clone (not the benchmark's repository)
        described = _run(["git", "describe", "--tags", "--always", "--dirty"], cwd=folder)
        if described:
            return described
    python = folder / ".venv" / "bin" / "python"
    if python.exists():
        code = f"import importlib.metadata as m; print(m.version({package!r}))"
        installed = _run([str(python), "-c", code])
        if installed:
            return installed
    return "unknown"


def _package_version(entry: str) -> str:
    kind, name = entry.split(":", 1)
    if kind == "graphviz":
        import pygraphviz

        return f"Graphviz {pygraphviz.__graphviz_version__}"
    if kind == "npm":
        manifest = JS_DIR / "node_modules" / name / "package.json"
        version = json.loads(manifest.read_text())["version"] if manifest.exists() else "not installed"
        return f"{name} {version}"
    try:
        return f"{name} {importlib.metadata.version(name)}"
    except importlib.metadata.PackageNotFoundError:
        return f"{name} not installed"


def spec_version(spec: LayoutSpec) -> str:
    """The versions of a layout's tool and packages, e.g. ``sbml2map ca3873a`` or
    ``cytoscape 3.33.1, cytoscape-fcose 2.2.0``."""
    parts = [f"{spec.tool} {_tool_version(TOOLS_DIR / spec.tool, spec.tool)}"] if spec.tool else []
    parts += [_package_version(p) for p in spec.packages]
    return ", ".join(parts)


@functools.cache
def tool_version(layout: str) -> str:
    """``spec_version`` of a registered layout (once per process); empty for unknown names (the reference)."""
    return spec_version(SPECS[layout]) if layout in SPECS else ""


__all__ = ["spec_version", "tool_version"]
