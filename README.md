# layout-benchmark

Benchmark of automatic layout algorithms for pathway maps in SBML, from
[BioHackathon Europe 2026](https://biohackathon-europe.org/), project 22, *Open Pathway Maps: Scalable and FAIR
Visualization of Metabolic Networks*.

Every model is laid out with many algorithms. Each result is scored with metrics derived from the project's layout
rules and written as standard SBML Layout + Render, so any viewer can open it. The results are compared side by side.

> Status: in development. Layout runs and the report work; metrics are next.

## Input

- The SBML models in the project's
  [`data_shared`](https://github.com/elixir2026-project22/data_shared) repository: BRENDA pathways, E. coli core and
  iCH360, Reactome, Human2, *Mycoplasma*, and the Stress Knowledge Map (PSS pathways, whole PSS, CKN).
- **Reference layouts** (hand-made), for comparing the automatic ones against:
  - the [metabolismregulation](https://metabolismregulation.github.io/gallery/) maps (SBML, plus SBGN-ML with the
    layout);
  - Escher maps (E. coli core metabolism, carbohydrate metabolism);
  - Reactome diagrams.

The model is read as one graph: species and reactions as nodes, one edge per reactant, product and modifier, and
compartments as parents. Options: clones of common small metabolites and cofactors, and a split by pathway or
subsystem.

## Layouts

| Family | Algorithms |
|---|---|
| Graphviz | dot, neato, fdp, sfdp, twopi, circo; sfdp compartment by compartment |
| igraph | Fruchterman–Reingold, Kamada–Kawai, DrL, graphopt, LGL, MDS, Sugiyama |
| networkx | spring, Kamada–Kawai, spectral |
| cytoscape.js | fCoSE, CoSE-Bilkent, cola, dagre, ELK (layered, stress, force) |
| SBMLNetwork | autolayout |
| [sbml2escher](https://github.com/elixir2026-project22/sbml2escher) | constraint-based, on a grid |
| later | UNICON, Metabopolis |

Every run gets a fixed seed and a timeout.

## Metrics

All layouts are scored by the same code. The rules come from the project's discussion.

| Rule | Metric |
|---|---|
| Avoid crossings | edge crossings (total and per edge) |
| Avoid overlaps | node overlaps (count and area) |
| Avoid long lines | edge length mean and variation; share of very long edges |
| Place participants consistently | reactants on one side of the reaction, products on the other |
| Respect compartments | species outside their compartment; overlapping compartments |
| Aspect ratio, compactness | width / height; area per node |
| Reproducibility | the same seed twice, and different seeds |
| Build on a previous layout | how far nodes move when a few reactions are removed |
| Scale | runtime; the largest model finished in time |
| Close to the reference | after alignment: remaining distance, distance rank correlation, shared nearest neighbours |

## Output

For each model and layout:
- an SBML file with the layout (SBML Layout + Render);
- an SVG picture, drawn the same way for every layout;
- a row in `results.csv`.

An HTML report shows the table and the pictures side by side.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Graphviz (for `pygraphviz`) and Node.js (for the cytoscape.js
layouts).

```bash
uv sync --extra tests                       # the Python environment (.venv), from uv.lock
(cd src/layout_benchmark/js && npm ci)      # cytoscape.js and its layout extensions
uv run pytest
```

External tools run in their own environments under `.tools/` (not tracked):

```bash
# MetaCarto 2 (CC BY 4.0)
git clone --depth 1 --branch v2.0.0 https://github.com/forxhunter/MetaCarto.git .tools/MetaCarto
(cd .tools/MetaCarto && uv venv --python 3.12 && uv pip install -e .)

# sbml2escher (the project's own tool)
git clone https://github.com/elixir2026-project22/sbml2escher.git .tools/sbml2escher
(cd .tools/sbml2escher && uv venv --python 3.12 && uv pip install -r requirements-layout-lock.txt -r requirements-escher.txt)

# SBMLNetwork: its auto layout (a layout), and its reader for layouts stored in SBML
mkdir -p .tools/sbmlnetwork && (cd .tools/sbmlnetwork && uv venv --python 3.12 && uv pip install sbmlnetwork==0.5.12 ipython)
```

Each tool is optional: without it, its layout reports an error.

## Usage

```bash
uv run layout-benchmark layouts                          # the layout algorithms
uv run layout-benchmark gallery data/gallery             # maps with a hand-made reference layout
uv run layout-benchmark run data/gallery/*.xml path/to/model.xml -o results/run1
```

`results/run1/index.html` shows per model the reference (where there is one) and every layout, from the expected
most promising to the least; each layout also has its positions as JSON. `results.csv` has a row per run (time,
error, nodes not placed). A `<model>.sbgn` next to a model is used as its reference (and for its SBGN classes and
labels).

```bash
uv run layout-benchmark report results/run1                      # redo the page from results.csv
uv run layout-benchmark publish results/run1 site --name run1    # a copy for GitHub Pages (no local paths)
```

The published report is on the `gh-pages` branch:
<https://elixir2026-project22.github.io/layout-benchmark/>.

## Licence

MIT (code). The input data keep their own licences; the metabolismregulation gallery maps (reference layouts)
are CC BY 4.0 (<https://metabolismregulation.github.io/about/>), credited in the report. gdMetriX, used for the general metrics, is GPL-3.0: it is
imported, not included; a bundle that includes it must follow the GPL.
