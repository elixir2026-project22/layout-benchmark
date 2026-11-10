// Headless cytoscape.js layouts for layout-benchmark.
// stdin: {"algorithm": "fcose", "seed": 0, "compound": true,
//         "nodes": [{"id", "width", "height", "parent"}], "parents": ["c1", ...], "edges": [{"source", "target"}]}
// stdout: {"positions": {"<id>": [x, y]}, "compartments": {"<parent>": [x1, y1, x2, y2]}}
//         (node centres and, with compound parents, their boxes; y down, as in cytoscape)
import cytoscape from "cytoscape";
import fcose from "cytoscape-fcose";
import coseBilkent from "cytoscape-cose-bilkent";
import cola from "cytoscape-cola";
import dagre from "cytoscape-dagre";
import elk from "cytoscape-elk";
import klay from "cytoscape-klay";

cytoscape.use(fcose);
cytoscape.use(coseBilkent);
cytoscape.use(cola);
cytoscape.use(dagre);
cytoscape.use(elk);
cytoscape.use(klay);

// seeded Math.random (mulberry32), so that randomised layouts are reproducible
function seedRandom(seed) {
  let a = seed >>> 0;
  Math.random = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const OPTIONS = {
  fcose: { name: "fcose", quality: "proof", randomize: true, animate: false, nodeDimensionsIncludeLabels: false },
  "cose-bilkent": { name: "cose-bilkent", quality: "proof", randomize: true, animate: false },
  cose: { name: "cose", randomize: true, animate: false },
  cola: { name: "cola", animate: false, randomize: true, maxSimulationTime: 8000, avoidOverlap: true },
  dagre: { name: "dagre", rankDir: "TB" },
  klay: { name: "klay" },
  "elk-layered": { name: "elk", elk: { algorithm: "layered", "elk.direction": "DOWN" } },
  "elk-stress": { name: "elk", elk: { algorithm: "stress" } },
  "elk-force": { name: "elk", elk: { algorithm: "force" } },
  "elk-mrtree": { name: "elk", elk: { algorithm: "mrtree" } },
};

const input = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.on("data", (c) => (data += c));
  process.stdin.on("end", () => resolve(data));
}));

seedRandom(input.seed ?? 0);
const options = OPTIONS[input.algorithm];
if (!options) {
  console.error(`unknown algorithm ${input.algorithm}`);
  process.exit(2);
}

const elements = [];
if (input.compound) {
  for (const p of input.parents) elements.push({ group: "nodes", data: { id: `__parent__${p}` } });
}
for (const n of input.nodes) {
  const data = { id: n.id, width: n.width, height: n.height };
  if (input.compound && n.parent) data.parent = `__parent__${n.parent}`;
  elements.push({ group: "nodes", data });
}
input.edges.forEach((e, i) => elements.push({ group: "edges", data: { id: `e${i}`, source: e.source, target: e.target } }));

const cy = cytoscape({
  headless: true,
  styleEnabled: true,
  elements,
  style: [{ selector: "node", style: { width: "data(width)", height: "data(height)", shape: "rectangle" } }],
});

const layout = cy.layout(options);
const done = new Promise((resolve) => layout.one("layoutstop", resolve));
layout.run();
await done;

const positions = {};
for (const n of input.nodes) {
  const p = cy.getElementById(n.id).position();
  positions[n.id] = [p.x, p.y];
}
const compartments = {};
if (input.compound) {
  for (const p of input.parents) {
    const b = cy.getElementById(`__parent__${p}`).boundingBox();
    if (b.w > 0 && b.h > 0) compartments[p] = [b.x1, b.y1, b.x2, b.y2];
  }
}
// exit once written: some layouts (cola, ELK) leave timers or workers behind that keep Node alive
process.stdout.write(JSON.stringify({ positions, compartments }), () => process.exit(0));
