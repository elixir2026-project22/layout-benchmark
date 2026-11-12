# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

**layout-benchmark**: a benchmark of automatic layout algorithms for pathway maps in SBML, from BioHackathon Europe
2026, project 22 (*Open Pathway Maps*). Every model is laid out with many algorithms (34), drawn the same way, and
shown side by side with its reference layout where it has one. The report is published at
<https://elixir2026-project22.github.io/layout-benchmark/>. `README.md` is the user documentation: keep it in step
with changes (layouts, options, output).

## Code (`src/layout_benchmark/`)

- `graph.py`: an SBML model as a graph (`Pathway`): species and reactions as nodes, one edge per participant;
  SBGN class per species (from SBO terms), SBGN arc per edge, fixed node sizes per class.
- `layouts.py`: Graphviz, igraph, networkx and cytoscape.js adapters and the registry: `REGISTRY`, one `LayoutSpec`
  per layout (name, function, group, documentation link, `sizes` for the overlap metrics, `tool` under `.tools/`),
  in the expected order (also the report's order); `LAYOUTS`, `GROUP`, `LINKS`, `expected_rank` are derived from
  it. `js/layout.mjs` runs the cytoscape.js layouts headless in Node.
- `external.py`: MetaCarto, sbml2map, ecmapper (`ecmapper-brenda`, `-packed`) and sbml_pathway_layout
  (`rules-claude`); all write Escher maps, read back as drawings (clones of metabolites and reactions, routes kept).
  `sbmlnet.py` + `sbmlnetwork_helper.py`: SBMLNetwork's auto layout and its reader for SBML Layout; the helper runs
  in SBMLNetwork's own environment.
- `drawing.py`: `Drawing`, what a tool draws (clones, routes, compartment boxes), its JSON, and the common scale.
- `reference.py`: reference layouts (`reference_drawing`: SBGN maps, matching SBML ids to glyphs, compartment
  glyphs; Escher maps; SBML Layout).
- `render.py`: the one SVG renderer. `report.py`: the HTML page (pictures, a score table per model) and
  `summary.html` (median rank per layout and metric; the columns come from `metrics.METRICS`). `runner.py`: runs
  and results.
- `manifest.py` + `benchmark.yaml`: the benchmark's sets of models, with where each comes from (URLs, GitHub globs,
  local files), references, links and credits; the cache paths (`<data>/<set>/<name>`) and the lock file.
- `metrics.py`: gdMetriX's general metrics plus our pathway-specific ones, on the drawing as shown (`score`,
  `run --metrics`); `METRICS`: one `Metric` per column (label, group, direction, what it measures, source, how it is
  calculated), `SOURCES`: where metrics come from (shown in the report's headers and summary).
- `datasets.py`: `fetch` (downloads a manifest's files, GitHub with a token for private repositories) and
  `escher_to_sbml` (models from Escher maps that come without one: the IMD maps).
- `scripts/gallery_manifest.py`: writes the gallery's entries of `benchmark.yaml` (one-off, run when it changes).

## Environment and commands

- `uv sync --extra tests`; `(cd src/layout_benchmark/js && npm ci)`; `uv run pytest` (unit tests need no external
  tools; the tools' layouts are skipped in the per-layout test).
- External tools live in `.tools/` (untracked), each in its own uv environment: MetaCarto (v2.0.0), sbml2map,
  ecmapper, sbml_pathway_layout, SBMLNetwork (0.5.12, needs IPython and Skia). Setup commands are in the README.
  Without a tool, its layout reports an error.
- Graphviz from the system (`pygraphviz`). Distribution builds may lack GTS: the force-directed programs use
  `overlap=scale`, and sfdp prints "not built with triangulation library" but still returns a layout.
- Data: `uv run layout-benchmark fetch benchmark.yaml` caches every model in `data/<set>/` and writes
  `data/manifest.lock.json` (commits, expanded globs); after that no command needs the network. data_shared is
  private: `fetch` uses `GITHUB_TOKEN` or `gh auth token`.
- The full cycle:
  1. `uv run layout-benchmark run benchmark.yaml -o results/all` (hours on the big models). For part of a run:
     `run benchmark.yaml -o results/all --append --only <names> [--layouts a,b]`, which replaces only those
     models' (or layouts') rows.
  2. `uv run layout-benchmark render results/all --manifest benchmark.yaml`: redraws every picture and the page from
     the saved positions in seconds, without rerunning layouts.
     `uv run layout-benchmark score results/all --manifest benchmark.yaml`: the metrics, from the saved drawings,
     into `results.csv` (`--only`, `--layouts` for part; `--jobs 6` on this machine, 8 cores; each drawing in its own
     process with `--timeout`, 600 s; failures in `metrics_error`).
  3. `uv run layout-benchmark publish results/all results/site --name all`: a copy without local paths.
  4. Publish: `results/site` as the single commit of the `gh-pages` branch, force-pushed (it replaces the site).
- `results.csv` is written after every model, so a stopped run keeps everything that finished. Each command
  reads it once and rewrites it whole, so only one command per OUT folder at a time (`locked`, `OUT/.lock`; ad hoc
  scripts must not call `_apply_manifest` on a partial set of rows: it writes them back). `run --append --layouts X`
  keeps the reference rows and their scores.

## How to add

Results are local: after each addition, update `results/all` with the commands below (one command per folder at a
time), check the report, and publish only on the user's go-ahead.

**A layout**
1. A function `(pathway, seed) -> positions or Drawing`: positions `{node id: (x, y)}` (y up, the tool's own
   units), or a `Drawing` when the tool draws more (clones, routes, compartment boxes, its own node sizes as
   `own_width`/`own_height`/`own_shape`). Library or cytoscape.js layouts in `layouts.py` (the `_graphviz`,
   `_igraph`, `_networkx`, `_cytoscape` factories; a new cytoscape.js extension also in `js/package.json` and
   `js/layout.mjs`). A tool with its own environment: clone it into `.tools/<folder>/` with its own uv `.venv`, a
   function in `external.py`; a tool writing Escher maps goes through `_run_tool(folder, args, out_glob, pathway)`
   (`sbml2map()` is the shortest example), anything else is read into a `Drawing` (as `sbmlnet.py` does).
   Keep the tool's output as is: no rescaling or rerouting (see Decisions).
2. One `LayoutSpec(name, run, group, link, sizes, tool)` in `REGISTRY`, at its place in the expected order:
   `sizes` "given" (we give it node sizes and it lays out around them), "escher" (Escher circles), or None (its
   `Drawing` carries its sizes, or it has none); `tool`: the `.tools/` folder, or None (then the per-layout test
   runs it; it needs no other change).
3. README: a row in the Layouts table, setup commands under Setup for an external tool, its limits (what it leaves
   out) under Layouts; CLAUDE.md: the tool under Code and Known tool limits.
4. `uv run pytest`; then `run benchmark.yaml -o results/all --append --layouts <name>` (the other layouts' rows and
   the references are kept) and `score results/all --manifest benchmark.yaml --layouts <name> --jobs 6`.

**A model (or a set of models)**
1. An entry in `benchmark.yaml` (format in `manifest.py`'s docstring): in an existing set, or a new set with
   `name`, `description`, `credit` and `licence` (check the source's licence page in full first: whatever is in
   the manifest is published). A model is a URL, a GitHub glob, a local path, or an entry (`name`, `url`,
   `reference`, `files`, `page`). References: per model (`reference:` URL), per set (`"{stem}.sbgn"`,
   `"{stem}.escher.json"`, `layout` for the model's own SBML Layout, or one shared file with `reference_kind`);
   Escher maps without SBML: `convert: escher`.
2. A new reference format: a reader in `reference.py` returning a `Drawing` matched to the model's ids (as
   `brenda_map_drawing`), a `reference_kind` in `manifest.py` (and `SHARED_REFERENCES` if one file serves a whole
   set), and a test.
3. `uv run layout-benchmark fetch benchmark.yaml` (downloads, updates `data/manifest.lock.json`; data_shared needs
   the GitHub token); `run benchmark.yaml -o results/all --append --only <names>`, then
   `score results/all --manifest benchmark.yaml --only <names> --jobs 6`. Leave out models too large to lay out
   (the whole PSS, Human2, CKN: hours per layout, mostly timeouts).
4. README: the Input section (sources, references, licences); CLAUDE.md: Licences under Decisions.

**A metric**
1. A function in `metrics.py` on the drawing as shown (`Drawing` in the tool's own coordinates; `segment_graph`
   for routes as drawn, `stub_graph` for angles at nodes, `own_sizes` for node sizes); use gdMetriX where it has
   the metric. Return None where it doesn't apply (no boxes, no sizes), never a made-up value; nothing that
   depends on our common picture scale.
2. Call it from `all_metrics` (or `general_metrics`), and add a `Metric(column, label, group, better,
   description, source, how)` to `METRICS`, next to the metrics of its source (the report's header bands follow
   that order): `better` "lower"/"higher" ranks it in the summary and marks the best value, None shows it unranked;
   `source` a key of `SOURCES` (gdMetriX, its definition in our code, our pathway-map metrics, the comparison with
   the reference); `how` how it is calculated, precisely (shown on the summary page). The report's tables and
   summary take their columns from `METRICS`, so nothing else changes there.
3. A test with a drawing whose value is known; the README Metrics table (rule, metric, column, direction) and, for
   a decision about it, Decisions below.
4. `score results/all --manifest benchmark.yaml --jobs 6` (all drawings: the new column for every model; about
   an hour on this machine), then check the report.

## Decisions (from the project lead)

- **Keep layouts as close to the tools' output as possible.** The JSON keeps each tool's own coordinates; pictures
  use one uniform scale (nearest neighbours 1.5 species widths apart: the median width of the drawn species, clones
  at their drawn size, reactions left out), which changes no shape. Scaling to each tool's own node sizes was tried
  and dropped (user, 2026-11-11): each tool's sizes mean something else (label boxes, glyphs, Escher circles with
  labels beside them), and it needed an exception per tool. No edge routing of our own: edges are straight, except
  routes a tool returns itself (Escher maps).
- **Node sizes are fixed per SBGN class, never sized to the label**; long labels are cut with "…".
- **One SVG renderer for every picture**: SBGN shapes and arcs, SBGN clone markers, species coloured by compartment
  (with a legend). SBMLNetwork is used as a layout and a reader only: drawing with it needed too many workarounds.
- **Compartment boxes only where they are real**: in references, cytoscape.js's compound layouts
  (`*-compartments`) and SBMLNetwork (its compartment glyphs). Never derived by us. The Escher tools draw none.
- **The manifest is the one place for inputs**: where each model comes from, its reference, links (shown in the
  report, GitHub files at their commit) and credits. No side files, no links derived from local checkouts.
- **References are data, not runs**: `render` rebuilds them from their files. Gallery SBGN maps are matched by their
  id scheme (`s_n0` is glyph `n0`), else by name (MINERVA exports); `reference: layout` in the manifest uses a
  model's own SBML Layout (the Reactome pathway); `"{stem}.escher.json"` an Escher map (the IMD maps, whose model
  is made from the map itself); `reference_kind: brenda-map` the BRENDA pathways' place on BRENDA's map
  (`brenda_map_drawing`, from ecmapper's `BRENDAmap/BRENDA_map_reactions.json`, one file for the set: the subsystem
  sharing the most BRENDA reaction ids; reactions by id then EC, metabolites by `_name_key`, then the one left
  over per reaction; directions from the model, as the map's main links have arrows at both ends).
- **Metrics**: the general graph-drawing metrics come from gdMetriX (imported, not copied; GPL-3.0), checked against
  GraphDrawingBenchmark's published values (961 of 1,000 crossing counts equal, the rest off by one: a different
  definition). Don't reimplement what gdMetriX has. Decided with the user (2026-11-11), metric by metric:
  - on **the drawing as shown**, in the tool's own coordinates: clones are nodes, left-out nodes absent, routes as
    the polylines drawn (`segment_graph`; pieces shared by several edges once); `coverage` says how much is drawn;
  - **overlaps with each tool's own node sizes** (`own_sizes`: the sizes Graphviz/cytoscape.js are given, Escher's
    circles r 20/10/5, SBMLNetwork's and SBGN glyphs saved as `own_width`/`own_height`); none for igraph/networkx.
    Our common scale must not decide a metric (it's only for pictures);
  - **compartments only where the tool draws boxes**; the hull-based measure was dropped (nested compartments
    counted as wrong);
  - stress dropped for now (a sum over pairs, not comparable between models); area per node left out (it would
    depend on our scale).
- **Licences**: code MIT. Gallery maps CC BY 4.0 (credited per model in the report). BRENDA (its pathway map
  included) CC BY 4.0. MetaboMAPS' uploaded maps CC BY 4.0 (terms of use, "License for uploaded pathways"). The Stress Knowledge Map (PSS)
  data CC BY-NC 4.0. The IMD maps (data_shared, by jadziaann) state no licence: credited, licence to be asked.

## Known tool limits

- MetaCarto (COBRApy) and sbml2map (its own SBML reader) read models as metabolic networks: species that are
  only modifiers (enzymes, regulators) aren't drawn; sbml2map also leaves out inorganic species (water, protons,
  O2, CO2, phosphate, ammonium) and reactions with nothing else. MetaCarto ignores SBML Layout (checked: same
  result without it).
- sbml2map replaced sbml2escher (2026-11-11: the sbml2escher repository is gone; same options and output). Its
  optimisation stops at a time limit (`--time-limit`, 60 s), so results can depend on the machine's speed.
- ecmapper draws only what it matches to the BRENDA map; subsystems it sets aside go to a separate map (not read);
  `--split` (several maps without common coordinates) isn't used. sbml_pathway_layout writes cofactors inside
  reaction boxes (fewer nodes placed), is slow on large models in one drawing, and ignores the seed.
- sbml2map fails on variable stoichiometry (the PSS models). MetaCarto needs flux bounds for pFBA and falls back
  to `--no-fba`.
- The compound layouts (`*-compartments`, iVis-at-Bilkent) expect every node in a compartment; reactions (which
  SBML doesn't put in compartments, except an optional Level 3 attribute) get the compartment of their reactants
  and products (`graph.reaction_compartment`; the `reactions` option of `_cytoscape`), transports none.
- `js/layout.mjs` must exit after writing its output: cola and ELK leave timers or workers that keep Node alive.
- Downloads use a short timeout: where IPv6 is unreachable, Python tries it first and waits.

## Git

- Commit only when asked; never commit `data/`, `results/`, `.tools/` or `node_modules/`.
- Results are published only through the `gh-pages` site, not committed to `main`.
