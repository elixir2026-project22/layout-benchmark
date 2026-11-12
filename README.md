# layout-benchmark

Benchmark of automatic layout algorithms for pathway maps in SBML, from
[BioHackathon Europe 2026](https://biohackathon-europe.org/), project 22, *Open Pathway Maps: Scalable and FAIR
Visualization of Metabolic Networks*.

Every model is laid out with many algorithms, and the results are compared side by side, next to a reference layout
where there is one: https://elixir2026-project22.github.io/layout-benchmark/. Next, each result is scored with
metrics derived from the project's layout rules.

> Status: in development. The layouts and the report work; the metrics are written but not yet in the report.
> Planned: SBML Layout + Render output per layout, cofactor clones and a split by pathway.

## Input

All inputs are listed, with where they come from, in [`benchmark.yaml`](benchmark.yaml) (see Usage):

- The SBML models in the project's [`data_shared`](https://github.com/elixir2026-project22/data_shared) repository
  (private to the project): BRENDA pathways, E. coli core and iCH360, Reactome, Human2, *Mycoplasma*, and the
  Stress Knowledge Map (PSS pathways, whole PSS, CKN); and
  [iML1515](http://bigg.ucsd.edu/models/iML1515) from BiGG.
- **Reference layouts** (drawn by hand), for comparing the automatic ones against:
  - the [metabolismregulation gallery](https://metabolismregulation.github.io/gallery/) maps (SBML, plus SBGN-ML
    with the layout; CC BY 4.0);
  - the IMD maps in `data_shared` (pathways of inborn metabolic disorders, Escher maps drawn on Recon3D): they come
    without SBML, so the model is made from each map (its reactions with all their metabolites and stoichiometry;
    compartments from the metabolite ids), and the map is its reference;
  - the Reactome pathway's own diagram (its SBML Layout);
  - for the BRENDA pathways, the pathway on BRENDA's pathway map (CC BY 4.0), read from
    [ecmapper](https://github.com/elixir2026-project22/ecmapper)'s export of the map (`BRENDA_map_reactions.json`:
    every enzyme and metabolite node with its position and size). The model's reactions are matched by their
    BRENDA reaction ids, then EC numbers; metabolites by name. The map doesn't say which main metabolite is consumed
    and which produced, so edges take their direction from the model.

The model is read as one graph: species and reactions as nodes, one edge per reactant, product and modifier, and
compartments as parents. Each species gets its SBGN class from its SBO term (or from the model's SBGN file), and
each modifier its SBGN arc (catalysis, inhibition, stimulation, …).

## Layouts

| Family | Algorithms |
|---|---|
| [sbml_pathway_layout](https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude) (`rules-claude`) | the project's layout rules: cycles as rings, pathways as layered backbones, cofactors written inside the reaction box (whole model in one drawing) |
| [ecmapper](https://github.com/elixir2026-project22/ecmapper/blob/main/DRAFT_MAP.md) (`ecmapper-brenda`, `-packed`) | draft maps from the BRENDA pathway map, matched by EC number: the subsystems arranged with few crossing links, or packed without them |
| [MetaCarto](https://github.com/forxhunter/MetaCarto) | constructive layout of metabolic maps (whole-model canvas) |
| [sbml2map](https://github.com/elixir2026-project22/sbml2map) (formerly sbml2escher) | constraint-based, on a grid (an exact optimisation with a time limit; heuristic placement on large models) |
| cytoscape.js | fCoSE and CoSE-Bilkent (also with compartments as groups: reactions are placed in the compartment of their reactants and products, or their SBML Level 3 compartment where set; transports stay between), CoSE, cola, dagre, klay, ELK (layered, stress, force, mrtree) |
| [SBMLNetwork](https://github.com/sys-bio/SBMLNetwork) | its auto layout |
| Graphviz | dot, neato, fdp, sfdp, twopi, circo |
| igraph | Fruchterman–Reingold, Kamada–Kawai, DrL, graphopt, LGL, MDS, Sugiyama |
| networkx | spring, Kamada–Kawai, spectral |
| planned | UNICON, Metabopolis |

`layout-benchmark layouts` lists them in the order the report uses, from the expected most promising for pathway
maps to the least, with their group, documentation and (for the external tools) whether the tool is set up.
Every run gets a fixed seed and a timeout. The pathway-specific tools write
Escher maps, read back with their clones (a metabolite or reaction drawn more than once) and edge routes.
MetaCarto, sbml2map and ecmapper read the model as a metabolic network and leave out species that are only
modifiers (enzymes, regulators); sbml2map also leaves out inorganic species (water, protons, O2, CO2, phosphate,
ammonium) and the reactions with nothing else, and its optimisation stops at a time limit, so its result can
depend on the machine's speed. sbml_pathway_layout writes cofactors inside the reaction boxes instead of drawing
them as nodes. ecmapper draws only the reactions it can match to the BRENDA map (by EC number, or added next to
matched ones), and puts subsystems drawn elsewhere already on a separate map (`set_aside`), which isn't read; its
`--split` mode (several maps, no common coordinates) isn't used.

## Metrics

All layouts are scored by the same code (`--metrics`; not yet in the report). The general graph-drawing metrics come
from [gdMetriX](https://github.com/livus/gdMetriX), the pathway-specific ones are this package's. The rules come
from the project's discussion.

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
- an SVG picture, drawn the same way for every layout: SBGN shapes and arcs, fixed node sizes. The tool's positions
  are scaled uniformly (no shape changes), so that nearest neighbours are 1.5 species widths apart;
- its positions as JSON, in the tool's own coordinates (every drawn node, clones included, and every edge with its
  arc class and route);
- a row in `results.csv` (time, error, nodes not placed).

An HTML report shows, per model, the reference layout and then every layout side by side.

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

# sbml2map (the project's own tool)
git clone https://github.com/elixir2026-project22/sbml2map.git .tools/sbml2map
(cd .tools/sbml2map && uv venv --python 3.12 && uv pip install -r requirements-layout.txt -r requirements-escher.txt)

# sbml_pathway_layout (the project's layout rules)
git clone https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude.git .tools/sbml_pathway_layout
(cd .tools/sbml_pathway_layout && uv venv --python 3.12 && uv pip install networkx numpy matplotlib)

# ecmapper (GPL-3.0): draft maps from the BRENDA map
git clone https://github.com/elixir2026-project22/ecmapper.git .tools/ecmapper
(cd .tools/ecmapper && uv venv --python 3.12 && uv pip install -e ".[draft-map]")

# SBMLNetwork: its auto layout (a layout), and its reader for layouts stored in SBML
mkdir -p .tools/sbmlnetwork && (cd .tools/sbmlnetwork && uv venv --python 3.12 && uv pip install sbmlnetwork==0.5.12 ipython)
```

Each tool is optional: without it, its layout reports an error.

## Usage

```bash
uv run layout-benchmark layouts                          # the layout algorithms
uv run layout-benchmark fetch benchmark.yaml             # download the manifest's models into data/<set>/
uv run layout-benchmark run benchmark.yaml -o results/all   # the models of the manifest
uv run layout-benchmark run benchmark.yaml -o results/all --append --only F001-glycolysis  # some of them
uv run layout-benchmark run path/to/model.xml -o results/run1  # or any SBML files
```

`benchmark.yaml` is the benchmark manifest: the sets of models, in the report's order, and per model where it
comes from (a URL, a GitHub glob such as `https://github.com/<owner>/<repo>/blob/main/brenda_*.xml`, or a local
file), its reference layout (an SBGN-ML map or an Escher map, as a URL or a pattern next to the model such as
`"{stem}.sbgn"`; or `layout`, the model's own SBML Layout; `reference_kind: brenda-map` for BRENDA's map),
companion files, a page to link, credit, licence and
description; sets of Escher maps without SBML (`convert: escher`) become models with the map as reference. The
format is described in `src/layout_benchmark/manifest.py`.

`fetch` downloads every model into `data/<set>/<model>` (`--data` for another folder) and writes
`data/manifest.lock.json`: the commit of each GitHub ref and the files each glob matched, so the files and the
report's links are pinned to that commit, and the other commands need no network. `fetch --refresh` updates
everything. data_shared is private: fetching from it needs a GitHub token (`GITHUB_TOKEN`, or the GitHub CLI's,
`gh auth login`). The gallery's entries are written by `scripts/gallery_manifest.py` (run it again when the
gallery changes). Models given as plain files are grouped by their folder, with a `<model>.sbgn` or
`<model>.escher.json` next to a model as its reference.

`results/run1/index.html` shows per model the reference (where there is one) and every layout, from the expected
most promising to the least; each layout also has its positions as JSON. `results.csv` has a row per run (time,
error, nodes not placed). An SBGN-ML reference also gives the model's SBGN classes and labels.

```bash
uv run layout-benchmark report results/run1                      # redo the page from results.csv
uv run layout-benchmark render results/run1 [--manifest benchmark.yaml]  # redraw the pictures from the saved positions
uv run layout-benchmark publish results/run1 site --name run1    # a copy for GitHub Pages (no local paths)
```

The layouts run locally; the published report is only the result, on the `gh-pages` branch:
<https://elixir2026-project22.github.io/layout-benchmark/>.

## Licence

MIT (code). The input data keep their own licences; the metabolismregulation gallery maps (reference layouts)
are CC BY 4.0 (<https://metabolismregulation.github.io/about/>), credited in the report, as is BRENDA's pathway
map (CC BY 4.0, <https://www.brenda-enzymes.org/copy.php>). gdMetriX, used for the
general metrics, is GPL-3.0: it is imported, not included; a bundle that includes it must follow the GPL.
