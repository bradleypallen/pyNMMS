"""Provenance as entitlement (PLAN.md step 4).

Brandom's scorekeeper keeps two scores: what a player is *committed* to,
and what they are *entitled* to, the commitments they have standing for,
either because they defended them against challenge or because they
inherited them from a source that had. A knowledge graph's provenance,
named graphs, PROV attributions, annotation records with evidence and
references, is that second score, read as such.

A :class:`Ground` is why a position holds a commitment:

* ``asserted``: the holder said it and has not yet defended it;
* ``defended``: the holder said it and the position survived a round of the
  opponent's probes (:meth:`~pynmms.rdf.position.Position.defend`);
* ``inherited``: read aloud from the store, with the source graph(s) and,
  through a :class:`RecordPattern`, the evidence and reference of the
  annotation record that carries it;
* ``derived``: a default the base commits the holder to
  (:meth:`~pynmms.rdf.position.Position.challenges`), via its entry.

A position is entitled to its defended and inherited commitments.
:meth:`~pynmms.rdf.position.Position.commit` writes a holder's assertions
into the holder's own named graph with ``prov:wasAttributedTo``, so the
store becomes a ledger of who committed to what.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rdflib import Literal, Namespace, URIRef
from rdflib.term import Node

PROV = Namespace("http://www.w3.org/ns/prov#")
HOLDER_NS = "urn:pynmms:holder:"

Triple = tuple[Node, Node, Node]


@dataclass(frozen=True)
class RecordPattern:
    """How annotation records carry a triple's provenance.

    A record ``r`` describes the triple ``(s, p, o)`` when ``r subject s``,
    ``r predicate p`` (omit *predicate* if records do not name it) and
    ``r object o`` hold; *evidence* and *reference* name the record's
    properties for those. GO's GAF records, as ``bench/gaf_to_nt.py`` writes
    them, are ``RecordPattern(go:gene_product, go:relation, go:class,
    go:evidence, go:reference)``.
    """

    subject: URIRef
    predicate: URIRef | None
    object: URIRef
    evidence: URIRef | None = None
    reference: URIRef | None = None


@dataclass(frozen=True)
class Ground:
    """Why a position holds a commitment."""

    kind: str  # asserted | defended | inherited | derived
    source: str | None = None
    evidence: str | None = None
    reference: str | None = None
    via: str | None = None

    @property
    def entitled(self) -> bool:
        return self.kind in ("defended", "inherited")


def holder_graph(holder: str) -> URIRef:
    return URIRef(HOLDER_NS + holder)


def provenance_of(base: Any, t: Triple, *, prefer_source: URIRef | None = None) -> Ground:
    """The inherited ground of a stored triple: its source graph and its record's evidence."""
    sources: list[str] = []
    graphs_of = getattr(base.backend, "graphs_of", None)
    if graphs_of is not None:
        sources = [str(g) for g in graphs_of(t)]
    source: str | None = None
    if prefer_source is not None and str(prefer_source) in sources:
        source = str(prefer_source)
    elif sources:
        source = sources[0]
    evidence = reference = None
    pattern: RecordPattern | None = getattr(base, "provenance", None)
    if pattern is not None:
        s, p, o = t
        for rec, _, _ in base.backend.triples((None, pattern.subject, s)):
            if pattern.predicate is not None and not base.backend.contains(
                (rec, pattern.predicate, p)
            ):
                continue
            if not base.backend.contains((rec, pattern.object, o)):
                continue
            if pattern.evidence is not None:
                for _, _, e in base.backend.triples((rec, pattern.evidence, None)):
                    evidence = str(e)
                    break
            if pattern.reference is not None:
                for _, _, r in base.backend.triples((rec, pattern.reference, None)):
                    reference = str(r)
                    break
            if source is None:
                source = str(rec)
            break
    return Ground("inherited", source, evidence, reference)


def attribution_triple(graph: URIRef, holder: str) -> Triple:
    return (graph, PROV.wasAttributedTo, Literal(holder))
