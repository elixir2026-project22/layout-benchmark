"""Run every registered layout twice per model and report reproducibility."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from reproducibility import compare_runs  # noqa: E402

from layout_benchmark.graph import read_sbml  # noqa: E402
from layout_benchmark.layouts import GROUP, LAYOUTS  # noqa: E402
from layout_benchmark.runner import run_layout  # noqa: E402

SEED = 0
TIMEOUT = 120.0


def main(model_dir: str, out: str, limit_models: int, only: list[str]) -> None:
    models = sorted(Path(model_dir).glob("*.xml"))[:limit_models]
    names = only or list(LAYOUTS)
    rows = []
    for path in models:
        pathway = read_sbml(path)
        n = pathway.graph.number_of_nodes()
        for name in names:
            row = {"model": path.stem, "nodes": n, "layout": name, "group": GROUP.get(name, "")}
            try:
                runs, seconds, failure = [], [], None
                for _ in range(2):
                    drawing, secs, err = run_layout(name, pathway, seed=SEED, timeout=TIMEOUT)
                    seconds.append(secs)
                    if err or drawing is None:
                        failure = err or "no drawing"
                        break
                    runs.append(drawing.normalised().pos)
                row["seconds_run1"] = round(seconds[0], 3) if seconds else None
                row["seconds_run2"] = round(seconds[1], 3) if len(seconds) > 1 else None
                if failure:
                    row.update({"verdict": "error", "error": failure[:200]})
                else:
                    row.update(compare_runs(runs[0], runs[1]))
            except Exception as exc:  # a layout that cannot run at all is not a reproducibility result
                row.update({"verdict": "error", "error": f"{type(exc).__name__}: {exc}"[:200]})
            rows.append(row)
            v = row.get("verdict")
            extra = ""
            if v == "differs":
                extra = f"  max_shift={row['max_shift']:.3f} procrustes={row['procrustes']:.2e}"
            elif v == "congruent":
                extra = f"  mirrored={row['mirrored']}"
            print(f"{path.stem[:28]:30} {name:36} {v}{extra}", flush=True)

    fields = sorted({k for r in rows for k in r})
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("\n=== per layout ===")
    by_layout: dict[str, Counter] = {}
    for r in rows:
        by_layout.setdefault(r["layout"], Counter())[r["verdict"]] += 1
    for name in names:
        c = by_layout.get(name)
        if c:
            print(f"{name:36} " + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))
    print(json.dumps({"models": len(models), "layouts": len(names), "rows": len(rows)}))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("-o", "--out", default="repro.csv")
    ap.add_argument("-n", "--models", type=int, default=3)
    ap.add_argument("--only", nargs="*", default=[])
    a = ap.parse_args()
    main(a.model_dir, a.out, a.models, a.only)