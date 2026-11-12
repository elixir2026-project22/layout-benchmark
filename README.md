# layout-benchmark

Benchmark of automatic layout algorithms for pathway maps in SBML, from
[BioHackathon Europe 2026](https://biohackathon-europe.org/), project 22, *Open Pathway Maps: Scalable and FAIR
Visualization of Metabolic Networks*.

Every model is laid out with every algorithm, drawn the same way and shown side by side, next to a hand-drawn
reference layout where there is one. Every drawing is then scored: general graph-drawing metrics, metrics for what
a pathway map needs, and its similarity to the reference. Report: <https://elixir2026-project22.github.io/layout-benchmark/>
(per model the pictures and a table of scores; a summary page with each layout's median rank per metric).

> Status: 38 layouts on 48 models in 6 sets, all scored. No combined score yet: the weights of the metrics are
> still to be decided. Planned: reproducibility with different seeds (the same seed twice: `layout-benchmark reproducibility`),
> SBML Layout + Render output per layout, cofactor clones and a split by pathway.

## Input

All inputs are listed, with where they come from, in [`benchmark.yaml`](benchmark.yaml) (see Usage).

| Set | Models | Size (species, reactions) | Reference layout | Source, licence |
|---|---|---|---|---|
| metabolismregulation gallery | 22 | 10–58, 2–26 | the gallery's hand-drawn SBGN-ML map | [metabolismregulation.github.io](https://metabolismregulation.github.io/gallery/), CC BY 4.0 |
| Inborn metabolic disorders (IMD maps) | 11 | 15–54, 5–22 | the Escher map itself | Jadzia Murphy's Escher maps drawn on Recon3D for the [VMH](https://vmh.life/maps), via the project's `data_shared`; shown with permission, not for reuse. Only maps already online in the VMH: amino acid metabolism, glycolysis, pentose metabolism, pyruvate metabolism and the Krebs cycle; the others are unpublished |
| Stress Knowledge Map (PSS) | 2 (JA, SA pathways) | 117–193, 82–159 | – | [skm.nib.si](https://skm.nib.si), CC BY-NC 4.0 |
| BRENDA pathways | 8 | 13–102, 5–103 | the pathway on BRENDA's pathway map | project's `data_shared`; map: BRENDA, CC BY 4.0 |
| Reactome | 1 | 101, 47 | Reactome's diagram (the model's own SBML Layout) | [Reactome](https://reactome.org/content/detail/R-HSA-77289) |
| Genome-scale and core models | 4 (E. coli core, iCH360, *Mycoplasma*, iML1515) | 72–1877, 95–2712 | – | [BiGG Models](http://bigg.ucsd.edu/) (e_coli_core via `data_shared`, iML1515 directly; educational, research and non-profit use); [iCH360](https://github.com/marco-corrao/iCH360) (MIT) and *Mycoplasma genitalium* from The SEED (2013 version; licence not stated), via `data_shared` |

[`data_shared`](https://github.com/elixir2026-project22/data_shared) is private to the project. Left out as too
large for most layouts (hours per layout, mostly timeouts): Human2, the whole PSS and CKN.

How the references are read:
- gallery: SBGN-ML glyphs matched to the SBML ids (the map also gives the species' SBGN classes and labels);
- IMD maps: they come without SBML, so the model is made from each map (its reactions with all their metabolites
  and stoichiometry; compartments from the metabolite ids), and the map is the reference;
- BRENDA pathways: read from [ecmapper](https://github.com/elixir2026-project22/ecmapper)'s export of BRENDA's map
  (`BRENDA_map_reactions.json`: every enzyme and metabolite node with its position and size); reactions matched by
  BRENDA reaction id, then EC number; metabolites by name. The map doesn't say which main metabolite is consumed and
  which produced, so edges take their direction from the model.

Each model is read as one graph: species and reactions as nodes, one edge per reactant, product and modifier, and
compartments as parents. Each species gets its SBGN class from its SBO term (or from the model's SBGN file), and
each modifier its SBGN arc (catalysis, inhibition, stimulation, …).

## Layouts

| Family | Algorithms |
|---|---|
| [sbml_pathway_layout](https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude) (`rules-claude`) | the project's layout rules: cycles as rings, pathways as layered backbones, cofactors written inside the reaction box (whole model in one drawing) |
| [ecmapper](https://github.com/elixir2026-project22/ecmapper/blob/main/DRAFT_MAP.md) (`ecmapper-brenda`, `-packed`) | draft maps from the BRENDA pathway map, matched by EC number: the subsystems arranged with few crossing links, or packed without them |
| [MetaCarto](https://github.com/forxhunter/MetaCarto) | constructive layout of metabolic maps (whole-model canvas) |
| [sbml2map](https://github.com/elixir2026-project22/sbml2map) | constraint-based, on a grid (an exact optimisation with a time limit; heuristic placement on large models) |
| [SBMLNetwork](https://github.com/sys-bio/SBMLNetwork) | its auto layout |
| cytoscape.js | fCoSE and CoSE-Bilkent (also with compartments as groups: reactions are placed in the compartment of their reactants and products, or their SBML Level 3 compartment where set; transports stay between), CoSE, cola, dagre, klay, ELK (layered, stress, force, mrtree) |
| [Sigma.js](https://www.sigmajs.org/) / [graphology](https://graphology.github.io/) | ForceAtlas2, the layout Sigma.js uses (from graphology, with its inferred settings, 500 iterations), alone and followed by noverlap (overlap removal, with our node sizes) |
| [Reagraph](https://reagraph.dev/) | its force-directed layout (`forceDirected2d`, d3-force), alone and with nodes grouped by compartment (its `clusterAttribute`: species by compartment, reactions as for cytoscape.js's compartment layouts); it draws no compartment boxes |
| Graphviz | dot, neato, fdp, sfdp, twopi, circo |
| igraph | Fruchterman–Reingold, Kamada–Kawai, DrL, graphopt, LGL, MDS, Sugiyama |
| networkx | spring, Kamada–Kawai, spectral |
| planned | UNICON, Metabopolis |
| not included | Reagraph's tree, radial and hierarchical layouts (they need acyclic graphs or trees; pathways have cycles); NVL, the Neo4j Visualization Library (its licence allows it only with Neo4j's commercial products) |

`layout-benchmark layouts` lists them in the report's order, from the expected most promising for pathway maps to
the least, with their group, documentation and (for the external tools) whether the tool is set up. Every run gets
a fixed seed and a timeout (300 s); a timeout kills the layout with the tools it started.

What the tools draw is kept as is: the pathway-specific tools write Escher maps, read back with their clones (a
metabolite or reaction drawn more than once) and edge routes; SBMLNetwork's and cytoscape.js's compartment boxes
are kept. Known limits:
- MetaCarto, sbml2map and ecmapper read the model as a metabolic network and leave out species that are only
  modifiers (enzymes, regulators). sbml2map also leaves out inorganic species (water, protons, O2, CO2, phosphate,
  ammonium) and the reactions with nothing else, fails on variable stoichiometry (the PSS models), and its
  optimisation stops at a time limit, so its result can depend on the machine's speed.
- sbml_pathway_layout writes cofactors inside the reaction boxes instead of drawing them as nodes (our pictures
  don't show that text), and merges species that share a name within a compartment
  ([its issue #1](https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude/issues/1)).
  It doesn't write a drawing that breaks its own rules; the benchmark runs it with `--write-failing`
  ([its PR #3](https://github.com/elixir2026-project22/automatic_layout_following_our_rules-claude/pull/3)), so such
  drawings are shown (the picture doesn't say which of its rules failed).
- ecmapper draws only the reactions it can match to the BRENDA map (by EC number, or added next to matched ones),
  and puts subsystems drawn elsewhere already on a separate map (`set_aside`), which isn't read; its `--split` mode
  (several maps, no common coordinates) isn't used.
- Graphviz fdp isn't reproducible from its seed (#4).
- MetaCarto has no seed of its own, but its map depends on the order of Python's sets, which changes from process to
  process: the tools' Python runs with `PYTHONHASHSEED` set to the run's seed, so that a seed gives one map.

## Metrics

`layout-benchmark score OUT` computes the metrics from the saved drawings into `OUT/results.csv` (`run --metrics`
does the same during a run) and writes the report with them. Each drawing is scored in its own process with a
timeout (`--timeout`, 600 s), several at once with `--jobs N`; a drawing whose metrics fail or time out has no
metrics and the reason in the `metrics_error` column.

Every metric is taken on **the drawing as shown**, in the tool's own coordinates: a clone is a node with its own
edges, nodes a tool leaves out are absent, and routed edges count as the polylines drawn (a piece several edges
share counts once). No metric depends on our common drawing scale: the general ones don't change under a uniform
scale, and overlaps use each tool's own node sizes. The general graph-drawing metrics come from
[gdMetriX](https://github.com/livus/gdMetriX). The pathway-map metrics follow the layout rules of BioHackathon 2026
project 22, as raw values (no thresholds or scores), as its two implementations define them: the browser
[pathway layout scorer](https://github.com/elixir2026-project22/frontend-tool-pathway-scorer) (`core.js`) and
sbml_pathway_layout's `svg_layout_metrics.py`; where they differ, we take the definition that measures the layout
itself (not the file format, not what else a tool draws, not a computing limit), else the scorer's. "Reproducible"
is the reproducibility check; "labels at fixed positions" doesn't apply (our renderer places the labels). Next to
the rules, a few checks of our own (whole model drawn, compartments, placement by edge direction). The comparison
with the reference is this package's. The report says which is which (the
top row of each score table's header), and the summary page lists every metric with its source and how it is
calculated.

| What it checks | Source | Metric (column; better) |
|---|---|---|
| Avoid crossings | gdMetriX | edge crossings (`crossings`; lower), against an estimated maximum (`crossing_density`; higher), angles at crossings (`crossing_angular_resolution`; higher) |
| Even lines and angles | gdMetriX (edge lengths: its definition, our code on the drawn polylines) | deviation from the mean drawn edge length (`edge_length_deviation`; lower); smallest angle at a node against the ideal (`angular_resolution`, a deviation; lower); horizontal and vertical pieces (`edge_orthogonality`; higher) |
| Shape | gdMetriX | shorter / longer side (`aspect_ratio`), nodes spread over the four quadrants (`homogeneity`), one main flow direction (`coherence_to_average_flow`), visual symmetry (`visual_symmetry`, up to 300 nodes); no direction, not ranked |
| Pathway maps: the project's hard rules | layout rules of project 22, computed by this benchmark (`rules.py`); `participant_consistency` this benchmark's | cycles look like cycles: main metabolite cycles (`rule_cycles`) and the share drawn as a closed loop in cycle order (`rule_cycles_closed`; higher); cofactors drawn as clones: cofactors drawn once for several reactions (`rule_cofactor_hubs`; lower); no crossings: per line, skipping lines that share an end (`rule_crossings_per_line`; lower); no line through a node: lines through a species node (`rule_lines_through_nodes`; lower); consistent placement: inputs and outputs at least 120 degrees apart (`rule_opposite_share`; higher), modifiers beside the flow (`rule_modifiers_beside`; higher), and ours, by the direction each edge leaves the reaction (`participant_consistency`; higher: a reaction drawn as a corner, as sbml2map's grid routes do, scores 0); aspect ratio: width / height of the drawn nodes (`rule_aspect`; not ranked) |
| Pathway maps: the project's soft rules | layout rules of project 22, computed by this benchmark; overlaps this benchmark's | avoid long lines: longest / median line (`rule_longest_over_median`; lower); avoid bends: turns over 25 degrees per line (`rule_bends_per_line`; lower); density: node area / extent (`rule_density`; not ranked); no overlapping nodes: node pairs that overlap and the overlap area (`overlapping_pairs`, `overlap_area_share`; lower), with the tool's own node sizes: the sizes Graphviz and cytoscape.js are given, Escher's circles, Reagraph's spheres, noverlap's circles, SBMLNetwork's and the references' glyphs; empty where a tool has no node sizes in its own units (igraph, networkx, plain ForceAtlas2) |
| Pathway maps, ours: draw the whole model | this package: pathway maps | share of species and of reactions drawn (`species_drawn`, `reactions_drawn`; higher); drawn nodes per model node (`drawn_per_node`: clones) |
| Pathway maps, ours: respect compartments | this package: pathway maps | where the tool draws compartment boxes (the compound cytoscape.js layouts, SBMLNetwork, references): species outside their compartment's box, boxes that overlap without one holding the other (`species_outside_compartment`, `compartments_overlapping`; lower) |
| Close to the reference | this package: reference (standard measures) | on the model nodes both draw, after alignment: remaining distance (`procrustes`; lower), rank correlation of distances (`distance_correlation`; higher), shared 5 nearest neighbours (`knn_preservation`; higher) |
| Reproducibility (a hard rule of project 22) | this benchmark: `layout-benchmark reproducibility` (its own table, not a column of `results.csv`; written as `OUT/reproducibility.csv`, the report of OUT shows it: a verdict per model and layout, and per layout in the summary the models reproduced / compared, a mirrored drawing not counted as reproduced) | the same model and seed laid out twice, each run in its own process, and the drawn nodes compared in the tool's own coordinates: `verdict` exact (the same coordinates), congruent (the same drawing moved, scaled, turned or mirrored: Procrustes disparity below 1e-6; `mirrored` says whether a cycle comes back the other way round) or differs; how far nodes moved as a share of the drawing's diagonal (`max_shift`, `median_shift`; lower). Planned: different seeds |
| Build on a previous layout | | planned: how far nodes move when a few reactions are removed |
| Scale | | runtime and timeouts are in `results.csv`; not scored yet |

Left out for now: stress (a sum over node pairs, not comparable between models) and area per node (it would
depend on our drawing scale).

## Output

In the output folder (`-o OUT`), for each model and layout:
- `OUT/<model>/<layout>.svg`: the picture, drawn the same way for every layout: SBGN shapes and arcs, fixed node
  sizes per SBGN class, species coloured by compartment. The tool's positions are scaled uniformly (no shape
  changes), so that nearest neighbours are 1.5 species widths apart;
- `OUT/<model>/<layout>.json`: the drawing in the tool's own coordinates (every drawn node, clones included, with
  its own size where the tool has one; every edge with its arc class and route; compartment boxes);
- a row in `OUT/results.csv`: the model, layout, time, error, notes (nodes not placed, clones), the version of the
  layout's tool and packages (`tool_version`: a tool's git tag or commit, e.g. `sbml2map ca3873a`; package
  versions, e.g. `cytoscape 3.33.1, cytoscape-fcose 2.2.0`), the model's set, source, reference, credit and
  licence, and every metric.

Each picture's caption names the versions it was made with, and the summary lists them per layout (several where
models were laid out at different times). `OUT/index.html` shows per model the reference and then every layout side by side, with a table of scores under
them (sortable; the best value per metric in bold; failures marked with their reason). `OUT/summary.html` gives
per layout and metric the median rank over the models (all, or one set: 1 = the best of that model's layouts; ties
share the mean rank), with the number of models ranked, the models laid out and the median time, and the table of
the metrics.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/), Graphviz (for `pygraphviz`) and Node.js (for the cytoscape.js,
graphology and Reagraph layouts).

```bash
uv sync --extra tests                       # the Python environment (.venv), from uv.lock
(cd src/layout_benchmark/js && npm ci)      # cytoscape.js, graphology, Reagraph (package-lock.json)
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

Each tool is optional: without it, its layout reports an error. To update one, `git pull` in its folder and run
its layout again (below).

## Usage

The full cycle:

```bash
uv run layout-benchmark fetch benchmark.yaml                     # 1. download the models into data/<set>/
uv run layout-benchmark run benchmark.yaml -o results/all        # 2. lay out (hours on the big models)
uv run layout-benchmark score results/all --manifest benchmark.yaml --jobs 6   # 3. the metrics
uv run layout-benchmark publish results/all site --name all      # 4. a copy for GitHub Pages (no local paths)
```

Partial runs and redrawing:

```bash
uv run layout-benchmark layouts                                   # the layout algorithms
uv run layout-benchmark run benchmark.yaml -o results/all --append --only F001-glycolysis   # some models
uv run layout-benchmark run benchmark.yaml -o results/all --append --layouts sbml2map       # one layout again
uv run layout-benchmark score results/all --manifest benchmark.yaml --layouts sbml2map     # ... and its scores
uv run layout-benchmark render results/all --manifest benchmark.yaml   # redraw pictures and report from the JSON
uv run layout-benchmark report results/all                            # the report only, from results.csv
uv run layout-benchmark versions results/all                          # record tool versions on rows without them
uv run layout-benchmark run path/to/model.xml -o results/run1         # any SBML files
uv run layout-benchmark reproducibility benchmark.yaml -o reproducibility.csv   # each layout twice with one seed: the same drawing?
```

`--append` keeps the other models' rows in `results.csv`; with `--layouts`, only those layouts' rows are replaced
and the references (with their scores) are kept (add `reference` to the layouts to redo them). `score` never
touches the drawings: it only fills the metric columns and rewrites the report. One command at a time per output
folder: a second `run`, `score`, `render`, `report` or `publish` on the same folder stops at once (`OUT/.lock`), as
each rewrites `results.csv` whole.

`benchmark.yaml` is the benchmark manifest: the sets of models, in the report's order, and per model where it
comes from (a URL, a GitHub glob such as `https://github.com/<owner>/<repo>/blob/main/brenda_*.xml`, or a local
file), its reference layout (an SBGN-ML map or an Escher map, as a URL or a pattern next to the model such as
`"{stem}.sbgn"`; `layout` for the model's own SBML Layout; `reference_kind: brenda-map` for BRENDA's map),
companion files, a page to link, credit, licence and description; sets of Escher maps without SBML
(`convert: escher`) become models with the map as reference. The format is described in
`src/layout_benchmark/manifest.py`.

`fetch` downloads every model into `data/<set>/<model>` (`--data` for another folder) and writes
`data/manifest.lock.json`: the commit of each GitHub ref and the files each glob matched, so the files and the
report's links are pinned to that commit, and the other commands need no network. `fetch --refresh` updates
everything. data_shared is private: fetching from it needs a GitHub token (`GITHUB_TOKEN`, or the GitHub CLI's,
`gh auth login`). The gallery's entries are written by `scripts/gallery_manifest.py` (run it again when the
gallery changes). Models given as plain files are grouped by their folder, with a `<model>.sbgn` or
`<model>.escher.json` next to a model as its reference.

The layouts run locally; the published report is only the result, on the `gh-pages` branch:
<https://elixir2026-project22.github.io/layout-benchmark/>.

## Adding a layout, a model or a metric

- **A layout**: a function `(pathway, seed) -> positions or Drawing` (in `layouts.py`, or in `external.py` for a
  tool with its own environment under `.tools/`) and one `LayoutSpec` in `REGISTRY` (`layouts.py`): name, group,
  documentation link, where its node sizes come from, the tool folder it needs. Then
  `run ... --append --layouts <name>` and `score ... --layouts <name>`.
- **A model**: an entry in `benchmark.yaml` with its source, reference, credit and licence; then `fetch`,
  `run ... --append --only <name>` and `score ... --only <name>`.
- **A metric**: a function in `metrics.py` on the drawing as shown, called from `all_metrics`, and a `Metric` in
  `METRICS` (column, label, group, direction, what it measures, source, how it is calculated): the report's tables
  and summary take their columns from it. Then `score` on everything.

Step-by-step notes are in `CLAUDE.md` ("How to add").

## Licence

MIT (code). The input data keep their own licences, credited per model in the report: the metabolismregulation
gallery maps and BRENDA's pathway map are CC BY 4.0 (<https://metabolismregulation.github.io/about/>,
<https://www.brenda-enzymes.org/copy.php>); the Stress Knowledge Map data are CC BY-NC 4.0; the IMD maps are Jadzia
Murphy's, for the VMH, shown with permission and not for reuse; BiGG Models (e_coli_core, iML1515) are © 2019 The
Regents of the University of California, free for educational, research and non-profit use
(<https://bigg.ucsd.edu/>); iCH360 is MIT; the *Mycoplasma* model (The SEED, 2013) states no licence. gdMetriX, used for the general metrics, is GPL-3.0: it is imported, not included; a bundle that
includes it must follow the GPL. The JavaScript layout libraries (cytoscape.js and its extensions, graphology,
Reagraph) are installed from npm with their own licences: MIT, Reagraph Apache-2.0, ELK (elkjs) EPL-2.0 and KLay
(klayjs) EPL-1.0.
