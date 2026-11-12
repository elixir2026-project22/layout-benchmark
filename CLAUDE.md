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
  per layout (name, function, group, documentation link, `tool` under `.tools/`), in the expected order (also the
  report's order); `LAYOUTS`, `GROUP`, `LINKS`, `expected_rank` are derived from it. `js/layout.mjs` runs the
  cytoscape.js layouts headless in Node.
  **Adding a layout**: a function `(pathway, seed) -> positions or Drawing` (in `layouts.py`; an external tool in
  `external.py`, Escher output through `_run_tool`), one `LayoutSpec` in `REGISTRY`, a README row (and setup
  commands for an external tool). Then `run benchmark.yaml -o results/all --append --layouts <name>`.
- `external.py`: MetaCarto, sbml2map, ecmapper (`ecmapper-brenda`, `-packed`) and sbml_pathway_layout
  (`rules-claude`); all write Escher maps, read back as drawings (clones of metabolites and reactions, routes kept).
  `sbmlnet.py` + `sbmlnetwork_helper.py`: SBMLNetwork's auto layout and its reader for SBML Layout; the helper runs
  in SBMLNetwork's own environment.
- `drawing.py`: `Drawing`, what a tool draws (clones, routes, compartment boxes), its JSON, and the common scale.
- `reference.py`: reference layouts (`reference_drawing`: SBGN maps, matching SBML ids to glyphs, compartment
  glyphs; Escher maps; SBML Layout).
- `render.py`: the one SVG renderer. `report.py`: the HTML page. `runner.py`: runs and results.
- `manifest.py` + `benchmark.yaml`: the benchmark's sets of models, with where each comes from (URLs, GitHub globs,
  local files), references, links and credits; the cache paths (`<data>/<set>/<name>`) and the lock file.
- `metrics.py`: gdMetriX's general metrics plus our pathway-specific ones (`--metrics`; not yet in the report).
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
  3. `uv run layout-benchmark publish results/all results/site --name all`: a copy without local paths.
  4. Publish: `results/site` as the single commit of the `gh-pages` branch, force-pushed (it replaces the site).
- `results.csv` is written after every model, so a stopped run keeps everything that finished.

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
- **Compartment boxes only where they are real**: in references, and in cytoscape.js's compound layouts
  (`*-compartments`). Never derived by us. MetaCarto and sbml2map draw none.
- **The manifest is the one place for inputs**: where each model comes from, its reference, links (shown in the
  report, GitHub files at their commit) and credits. No side files, no links derived from local checkouts.
- **References are data, not runs**: `render` rebuilds them from their files. Gallery SBGN maps are matched by their
  id scheme (`s_n0` is glyph `n0`), else by name (MINERVA exports); `reference: layout` in the manifest uses a
  model's own SBML Layout (the Reactome pathway); `"{stem}.escher.json"` an Escher map (the IMD maps, whose model
  is made from the map itself).
- **Metrics**: the general graph-drawing metrics come from gdMetriX (imported, not copied; GPL-3.0), checked against
  GraphDrawingBenchmark's published values (961 of 1,000 crossing counts equal, the rest off by one: a different
  definition). Don't reimplement what gdMetriX has.
- **Licences**: code MIT. Gallery maps CC BY 4.0 (credited per model in the report). The Stress Knowledge Map (PSS)
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
