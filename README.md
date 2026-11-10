# layout-benchmark

Benchmark of automatic layout algorithms for pathway maps in SBML, from
[BioHackathon Europe 2026](https://biohackathon-europe.org/), project 22, *Open Pathway Maps: Scalable and FAIR
Visualization of Metabolic Networks*.

Every model is laid out with many algorithms. Each result is scored with metrics derived from the project's layout
rules and written as standard SBML Layout + Render, so any viewer can open it. The results are compared side by side.

> Status: planning. The pipeline is being written; this README describes what it will do.

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

## Licence

MIT (code). The input data keep their own licences.
