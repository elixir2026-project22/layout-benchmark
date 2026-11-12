// Headless graphology (Sigma.js) and Reagraph layouts for layout-benchmark.
// stdin: {"algorithm": "forceatlas2", "seed": 0,
//         "nodes": [{"id", "width", "height", "group"}], "edges": [{"source", "target"}]}
// stdout: {"positions": {"<id>": [x, y]}, "sizes": {"<id>": radius}}  (y up; sizes: the node radii the layout
//         worked with, in its own units, where it has them)
import Graph from "graphology";
import random from "graphology-layout/random.js";
import forceAtlas2 from "graphology-layout-forceatlas2";
import noverlap from "graphology-layout-noverlap";
import { buildGraph, layoutProvider } from "reagraph";

// seeded Math.random (mulberry32), as in layout.mjs
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

const input = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.on("data", (c) => (data += c));
  process.stdin.on("end", () => resolve(data));
}));
seedRandom(input.seed ?? 0);

// Reagraph draws every node as a sphere of its size: the default size (7) scaled into [5, 15], which for equal
// sizes gives 10 (GraphCanvas defaults)
const REAGRAPH_RADIUS = 10;
const FA2_ITERATIONS = 500;

function forceAtlas2Graph() {
  const g = new Graph({ type: "directed" });
  for (const n of input.nodes) g.addNode(n.id, { size: Math.max(n.width, n.height) / 2 });
  for (const e of input.edges) if (!g.hasEdge(e.source, e.target)) g.addEdge(e.source, e.target);
  random.assign(g, { scale: 100, center: 0 }); // a seeded random start, as Sigma's examples do
  forceAtlas2.assign(g, { iterations: FA2_ITERATIONS, settings: forceAtlas2.inferSettings(g) });
  return g;
}

function reagraph(clusterAttribute) {
  // the graph as Reagraph's GraphCanvas builds it (nodes with their data, edges with source and target)
  const nodes = input.nodes.map((n) => ({ id: n.id, data: n.group ? { compartment: n.group } : {} }));
  const edges = input.edges.map((e, i) => ({ id: `e${i}`, source: e.source, target: e.target }));
  const g = buildGraph(new Graph({ multi: true }), nodes, edges);
  const layout = layoutProvider({ type: "forceDirected2d", graph: g, drags: {}, clusters: new Map(), clusterAttribute });
  layout.step();
  const positions = {};
  for (const n of input.nodes) {
    const p = layout.getNodePosition(n.id);
    positions[n.id] = [p.x, p.y];
  }
  return positions;
}

const positions = {};
const sizes = {};
switch (input.algorithm) {
  case "forceatlas2":
  case "forceatlas2-noverlap": {
    const g = forceAtlas2Graph();
    if (input.algorithm === "forceatlas2-noverlap") {
      noverlap.assign(g); // graphology's defaults: nodes as circles of their size, margin 5
      g.forEachNode((id, a) => (sizes[id] = a.size));
    }
    g.forEachNode((id, a) => (positions[id] = [a.x, a.y]));
    break;
  }
  case "reagraph-force":
  case "reagraph-force-compartments":
    Object.assign(positions, reagraph(input.algorithm.endsWith("compartments") ? "compartment" : undefined));
    for (const n of input.nodes) sizes[n.id] = REAGRAPH_RADIUS;
    break;
  default:
    console.error(`unknown algorithm ${input.algorithm}`);
    process.exit(2);
}
process.stdout.write(JSON.stringify({ positions, sizes }), () => process.exit(0));
