"""pynmms.rdf -- NMMS reasoning over RDF graphs.

Implements the implication-space semantics for RDF (Allen, "Implication-Space
Semantics for RDF", unpublished manuscript) on top of the propositional NMMS core:

* :class:`TripleAtom` -- an RDF triple as an atomic sentence (a ``str``
  subclass whose value is the canonical quoted-atom name ``<s p o>``).
* :class:`GraphView` -- an antecedent that is a reference to a graph in a
  backend plus a small diff, so that Γ is never materialised in Python.
* :class:`RDFBase` -- a material base over ground triples (Definition 25),
  with explicit entries and robustness policies from the core.
* :class:`RegimeBase` -- the base specified by an entailment regime
  (Definition 9): ``Γ |~ Δ`` iff Γ is R-inconsistent or ``Δ ∩ cl_R(Γ) ≠ ∅``.
  Closure of the stored graph lives in the backend; closure of the per-node
  extras is an in-process semi-naive step (:mod:`pynmms.rdf.closure`).
* Backends (:mod:`pynmms.rdf.backends`): in-memory rdflib, SPARQL endpoint.

Requires the ``rdf`` extra: ``pip install pyNMMS[rdf]``.
"""

from pynmms.rdf.atoms import PatternAtom, Resolver, TripleAtom
from pynmms.rdf.base import RDFBase, RegimeBase
from pynmms.rdf.convert import onto_to_graph, onto_to_rules
from pynmms.rdf.rules import OWL2RL, RDFS, SIMPLE, Regime, Rule, Var, parse_rule
from pynmms.rdf.view import GraphView

__all__ = [
    "TripleAtom",
    "PatternAtom",
    "Resolver",
    "GraphView",
    "RDFBase",
    "RegimeBase",
    "Regime",
    "Rule",
    "Var",
    "RDFS",
    "OWL2RL",
    "SIMPLE",
    "onto_to_graph",
    "onto_to_rules",
    "parse_rule",
]
