import libsbml
import pytest


def make_sbml(path, reactions, compartments=("c",), species_compartment=None):
    """Write a small SBML model: reactions as (id, reactants, products, modifiers)."""
    doc = libsbml.SBMLDocument(3, 2)
    m = doc.createModel()
    m.setId("tiny")
    for c in compartments:
        comp = m.createCompartment()
        comp.setId(c)
        comp.setConstant(True)
    species = sorted({s for _, r, p, mod in reactions for s in (*r, *p, *mod)})
    for s in species:
        sp = m.createSpecies()
        sp.setId(s)
        sp.setName(s)
        sp.setCompartment((species_compartment or {}).get(s, compartments[0]))
        sp.setHasOnlySubstanceUnits(False)
        sp.setBoundaryCondition(False)
        sp.setConstant(False)
    for rid, reactants, products, modifiers in reactions:
        r = m.createReaction()
        r.setId(rid)
        r.setReversible(False)
        for s in reactants:
            sr = r.createReactant()
            sr.setSpecies(s)
            sr.setConstant(True)
        for s in products:
            sr = r.createProduct()
            sr.setSpecies(s)
            sr.setConstant(True)
        for s in modifiers:
            r.createModifier().setSpecies(s)
    libsbml.writeSBMLToFile(doc, str(path))
    return path


@pytest.fixture
def tiny_sbml(tmp_path):
    """A small cycle: A -> B -> C -> A, with an enzyme E on the first reaction."""
    return make_sbml(
        tmp_path / "tiny.xml",
        [("r1", ["A"], ["B"], ["E"]), ("r2", ["B"], ["C"], []), ("r3", ["C"], ["A"], [])],
    )
