"""pynmms.rdf -- NMMS reasoning over RDF graphs.

Implements the implication-space semantics for RDF (Allen, "Implication-Space
Semantics for RDF", unpublished manuscript) on top of the propositional NMMS core:

* :class:`TripleAtom` -- an RDF triple as an atomic sentence (a ``str``
  subclass whose value is the canonical quoted-atom name ``<s p o>``).
* :class:`GraphView` -- an antecedent that is a reference to a graph in a
  backend plus a small diff, so that Γ is never materialised in Python.
* :class:`RDFBase` -- a material base over ground triples (``def:fitness``),
  with explicit entries and robustness policies from the core.
* :class:`RegimeBase` -- the regime-relative material base ``B_{R,I}``: the
  base a regime specifies (``def:fitness``; ``Γ |~ Δ`` iff Γ is R-inconsistent
  or ``Δ ∩ cl_R(Γ) ≠ ∅``) with material entries read through the closure
  (theory page, Section 8).
  Closure of the stored graph lives in the backend; closure of the per-node
  extras is an in-process semi-naive step (:mod:`pynmms.rdf.closure`).
* Backends (:mod:`pynmms.rdf.backends`): in-memory rdflib, SPARQL endpoint.

Requires the ``rdf`` extra: ``pip install pyNMMS[rdf]``.
"""

from pynmms.rdf.atoms import PatternAtom, Resolver, TripleAtom
from pynmms.rdf.base import RDFBase, RegimeBase
from pynmms.rdf.convert import onto_to_graph, onto_to_rules
from pynmms.rdf.defeasible import DefeasibleRule, parse_defeasible_rule
from pynmms.rdf.dialogue import Dialogue, Tension
from pynmms.rdf.position import Challenge, Move, Position, Report, Round, Verdict
from pynmms.rdf.provenance import PROV, Ground, RecordPattern
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
    "Position",
    "Challenge",
    "Round",
    "Report",
    "Ground",
    "RecordPattern",
    "PROV",
    "DefeasibleRule",
    "Dialogue",
    "Tension",
    "parse_defeasible_rule",
    "Verdict",
    "Move",
]
