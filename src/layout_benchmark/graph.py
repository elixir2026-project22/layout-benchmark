"""A pathway as one graph: species and reactions as nodes, one edge per participant."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import libsbml
import networkx as nx

# node sizes, in layout units (a median edge is scaled to EDGE_LENGTH, see layouts.normalise)
SPECIES_SIZE = (60.0, 24.0)
REACTION_SIZE = (10.0, 10.0)

SPECIES = "species"
REACTION = "reaction"
REACTANT, PRODUCT, MODIFIER = "reactant", "product", "modifier"

# SBGN arc classes, for drawing
CONSUMPTION, PRODUCTION = "consumption", "production"
CATALYSIS, INHIBITION, STIMULATION = "catalysis", "inhibition", "stimulation"
NECESSARY_STIMULATION, MODULATION = "necessary stimulation", "modulation"


# SBGN Process Description entity classes of species, from their SBO terms (the common terms and their usual
# children); species without a known term are "unspecified entity"
SIMPLE_CHEMICAL, MACROMOLECULE, NUCLEIC_ACID_FEATURE = "simple chemical", "macromolecule", "nucleic acid feature"
COMPLEX, PERTURBING_AGENT, PHENOTYPE = "complex", "perturbing agent", "phenotype"
UNSPECIFIED_ENTITY, PROCESS = "unspecified entity", "process"
SBGN_CLASSES = (
    SIMPLE_CHEMICAL,
    MACROMOLECULE,
    NUCLEIC_ACID_FEATURE,
    COMPLEX,
    PERTURBING_AGENT,
    PHENOTYPE,
    UNSPECIFIED_ENTITY,
)
_SPECIES_SBO = {
    247: SIMPLE_CHEMICAL,
    327: SIMPLE_CHEMICAL,
    328: SIMPLE_CHEMICAL,  # simple chemical, non-macromolecular ion/radical
    245: MACROMOLECULE,
    248: MACROMOLECULE,
    252: MACROMOLECULE,
    246: MACROMOLECULE,  # macromolecule, polypeptide, ...
    243: NUCLEIC_ACID_FEATURE,
    250: NUCLEIC_ACID_FEATURE,
    251: NUCLEIC_ACID_FEATURE,  # gene, RNA, DNA
    278: NUCLEIC_ACID_FEATURE,
    316: NUCLEIC_ACID_FEATURE,
    334: NUCLEIC_ACID_FEATURE,  # mRNA, microRNA, ncRNA
    354: NUCLEIC_ACID_FEATURE,
    404: NUCLEIC_ACID_FEATURE,  # informational molecule segment, unit of genetic info.
    253: COMPLEX,
    296: COMPLEX,
    297: COMPLEX,  # non-covalent complex, macromolecular complex, protein complex
    405: PERTURBING_AGENT,  # perturbing agent
    358: PHENOTYPE,
    375: PHENOTYPE,  # phenotype; process (PSS models processes, e.g. stomatal closure, as species)
    285: UNSPECIFIED_ENTITY,
    289: UNSPECIFIED_ENTITY,  # material entity of unspecified nature, functional entity
}

# SBGN-ML glyph classes (as in SBGN files) -> the classes here
SBGN_ML_CLASSES = {
    "simple chemical": SIMPLE_CHEMICAL,
    "simple chemical multimer": SIMPLE_CHEMICAL,
    "macromolecule": MACROMOLECULE,
    "macromolecule multimer": MACROMOLECULE,
    "nucleic acid feature": NUCLEIC_ACID_FEATURE,
    "nucleic acid feature multimer": NUCLEIC_ACID_FEATURE,
    "complex": COMPLEX,
    "complex multimer": COMPLEX,
    "perturbing agent": PERTURBING_AGENT,
    "phenotype": PHENOTYPE,
    "unspecified entity": UNSPECIFIED_ENTITY,
}


def species_class(sbo: int) -> str:
    """The SBGN entity class of a species from its SBO term."""
    return _SPECIES_SBO.get(sbo, UNSPECIFIED_ENTITY)


# node sizes per SBGN class, in layout units: fixed, never from the label (a label is cut to fit its node)
CLASS_SIZE = {SIMPLE_CHEMICAL: (48.0, 24.0), PROCESS: REACTION_SIZE}


def node_size(sbgn: str) -> tuple[float, float]:
    return CLASS_SIZE.get(sbgn, SPECIES_SIZE)


def set_class(attributes: dict, sbgn: str) -> None:
    """Set a node's SBGN class, and the size that goes with it."""
    attributes["sbgn"] = sbgn
    attributes["width"], attributes["height"] = node_size(sbgn)


# modifier SBO terms -> SBGN arc (the common terms and their usual children; anything else is modulation)
_MODIFIER_SBO = {
    13: CATALYSIS,
    460: CATALYSIS,  # catalyst, enzymatic catalyst
    20: INHIBITION,
    206: INHIBITION,
    207: INHIBITION,
    536: INHIBITION,
    537: INHIBITION,  # inhibitor, ...
    459: STIMULATION,
    21: STIMULATION,
    462: STIMULATION,
    535: STIMULATION,  # stimulator, potentiator, ...
    461: NECESSARY_STIMULATION,  # essential activator
}


def _modifier_arc(sbo: int) -> str:
    """The SBGN arc class of a modifier from its SBO term."""
    return _MODIFIER_SBO.get(sbo, MODULATION)
    for term, arc in ((13, CATALYSIS), (20, INHIBITION), (461, NECESSARY_STIMULATION), (459, STIMULATION)):
        if sbo == term or libsbml.SBO.isChildOf(sbo, term):
            return arc
    return MODULATION


@dataclass
class Pathway:
    """A pathway graph.

    ``graph`` is a directed graph. Nodes have ``kind`` (species or reaction), ``label``, ``compartment``,
    ``width``, ``height`` and ``sbgn`` (the SBGN class: of a species from its SBO term, "process" for reactions);
    edges have ``role``: reactant (species -> reaction), product (reaction -> species)
    or modifier (species -> reaction), and ``arc``, the SBGN arc class (consumption, production, catalysis,
    inhibition, stimulation, necessary stimulation, modulation).
    """

    name: str
    graph: nx.DiGraph
    compartments: dict[str, str] = field(default_factory=dict)  # id -> name
    source: Path | None = None  # the file it was read from (for tools that read the file themselves)

    @property
    def species(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True) if d["kind"] == SPECIES]

    @property
    def reactions(self) -> list[str]:
        return [n for n, d in self.graph.nodes(data=True) if d["kind"] == REACTION]

    def undirected(self) -> nx.Graph:
        """The simple undirected graph (for layout algorithms and general metrics)."""
        g = nx.Graph()
        g.add_nodes_from(self.graph.nodes(data=True))
        g.add_edges_from((u, v) for u, v in self.graph.edges() if u != v)
        return g


def _add_species(g, sid, label, compartment, sbo=-1):
    sbgn = species_class(sbo)
    w, h = node_size(sbgn)
    g.add_node(sid, kind=SPECIES, label=label or sid, compartment=compartment, width=w, height=h, sbgn=sbgn)


def _add_reaction(g, rid, label, compartment=None):
    w, h = node_size(PROCESS)
    g.add_node(rid, kind=REACTION, label=label or rid, compartment=compartment, width=w, height=h, sbgn=PROCESS)


def read_sbml(path: str | Path, name: str | None = None) -> Pathway:
    """Read an SBML file (core reactions, or SBML-qual transitions) into a Pathway."""
    path = Path(path)
    doc = libsbml.readSBMLFromFile(str(path))
    if doc.getNumErrors(libsbml.LIBSBML_SEV_FATAL) or doc.getModel() is None:
        raise ValueError(f"{path}: not a readable SBML model")
    model = doc.getModel()
    g = nx.DiGraph()
    compartments = {c.getId(): c.getName() or c.getId() for c in model.getListOfCompartments()}

    for s in model.getListOfSpecies():
        _add_species(g, s.getId(), s.getName(), s.getCompartment(), s.getSBOTerm())
    for r in model.getListOfReactions():
        rid = r.getId()
        _add_reaction(g, rid, r.getName(), r.getCompartment() if r.isSetCompartment() else None)
        for sr in r.getListOfReactants():
            g.add_edge(sr.getSpecies(), rid, role=REACTANT, arc=CONSUMPTION)
        for sr in r.getListOfProducts():
            g.add_edge(rid, sr.getSpecies(), role=PRODUCT, arc=PRODUCTION)
        for sr in r.getListOfModifiers():
            if not g.has_edge(sr.getSpecies(), rid):
                g.add_edge(sr.getSpecies(), rid, role=MODIFIER, arc=_modifier_arc(sr.getSBOTerm()))

    qual = model.getPlugin("qual")
    if qual is not None and qual.getNumTransitions():
        for s in qual.getListOfQualitativeSpecies():
            _add_species(g, s.getId(), s.getName(), s.getCompartment(), s.getSBOTerm())
        for t in qual.getListOfTransitions():
            tid = t.getId()
            _add_reaction(g, tid, t.getName())
            for i in t.getListOfInputs():
                sign = i.getSign() if i.isSetSign() else None
                arc = {libsbml.INPUT_SIGN_POSITIVE: STIMULATION, libsbml.INPUT_SIGN_NEGATIVE: INHIBITION}.get(
                    sign, MODULATION
                )
                g.add_edge(i.getQualitativeSpecies(), tid, role=MODIFIER, arc=arc)
            for o in t.getListOfOutputs():
                g.add_edge(tid, o.getQualitativeSpecies(), role=PRODUCT, arc=PRODUCTION)

    # species no reaction uses carry no layout information
    g.remove_nodes_from([n for n in list(g) if g.degree(n) == 0])
    return Pathway(name=name or path.stem, graph=g, compartments=compartments, source=path)
