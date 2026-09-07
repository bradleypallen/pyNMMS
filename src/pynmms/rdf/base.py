"""Material bases over RDF triples.

:class:`RDFBase` is Definition 25 of the paper: a base whose lexicon is the
ground triples over a vocabulary and whose relation satisfies Containment.
The lexicon is intensional (any well-formed triple is a sentence), explicit
entries with robustness policies come from :class:`~pynmms.base.MaterialBase`,
and the stored graph is reached through a backend.

:class:`RegimeBase` adds the base ``B_R`` specified by an entailment regime:
``Γ |~ Δ`` iff Γ is R-inconsistent or ``Δ ∩ cl_R(Γ) ≠ ∅``. With Γ a
:class:`~pynmms.rdf.view.GraphView` over the backend, ``cl_R(Γ)`` is the
backend's materialised closure of G extended by the per-node extras.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Union

from rdflib import BNode, Graph
from rdflib.term import Node

from pynmms.base import MaterialBase
from pynmms.base import Sequent as BasePair
from pynmms.rdf.atoms import PatternAtom, Resolver, Triple, TripleAtom, skolemize_triple
from pynmms.rdf.backends import GraphBackend, MemoryBackend
from pynmms.rdf.closure import ClosureEngine, _TripleIndex, match_patterns
from pynmms.rdf.rules import SIMPLE, Regime, Var
from pynmms.rdf.view import GraphView
from pynmms.robustness import Robustness
from pynmms.sequent import AtomSet, AtomsView, Sequent, _partition
from pynmms.syntax import ATOM, IMPL, NEG, Sentence

logger = logging.getLogger(__name__)


def _coerce_atom(name: str, resolver: Resolver | None, *, antecedent: bool) -> str:
    """Canonical atom for *name*: a TripleAtom (Skolemized on the left) or a PatternAtom."""
    pat = PatternAtom.coerce(name, resolver)
    if pat is not None:
        if antecedent:
            raise ValueError(
                f"Pattern atom {name!r} cannot occur in an antecedent; Skolemize its "
                f"blank nodes and list its triples instead"
            )
        return pat
    t = TripleAtom.coerce(name, resolver)
    if t is None:
        raise ValueError(f"{name!r} is not a triple atom <s p o> or a pattern atom <{{ ... }}>")
    if antecedent and any(isinstance(n, BNode) for n in t.triple):
        return TripleAtom(*skolemize_triple(t.triple))
    return t


def _canonicalize(s: Sentence, resolver: Resolver | None, *, antecedent: bool) -> Sentence:
    """Rewrite every quoted atom in *s* to its canonical name.

    Polarity is tracked so that blank nodes are Skolemized exactly in
    antecedent position: the left operand of an implication and the operand
    of a negation flip polarity.
    """
    if s.type == ATOM:
        assert s.name is not None
        return Sentence(type=ATOM, name=_coerce_atom(s.name, resolver, antecedent=antecedent))
    if s.type == NEG:
        assert s.sub is not None
        return Sentence(type=NEG, sub=_canonicalize(s.sub, resolver, antecedent=not antecedent))
    assert s.left is not None and s.right is not None
    left_pol = not antecedent if s.type == IMPL else antecedent
    return Sentence(
        type=s.type,
        left=_canonicalize(s.left, resolver, antecedent=left_pol),
        right=_canonicalize(s.right, resolver, antecedent=antecedent),
    )


class RDFBase(MaterialBase):
    """A material base over ground triples with a backend-resident graph."""

    def __init__(
        self,
        backend: GraphBackend | None = None,
        *,
        consequences: set[BasePair] | None = None,
        robustness: dict[BasePair, Robustness] | None = None,
    ) -> None:
        self.backend: GraphBackend = backend if backend is not None else MemoryBackend()
        super().__init__(consequences=consequences, robustness=robustness)

    # --- Atoms ---

    @property
    def resolver(self) -> Resolver:
        return self.backend.resolver

    def _validate_atom(self, s: str, context: str) -> str:
        t = TripleAtom.coerce(s, self.resolver)
        if t is None:
            raise ValueError(f"{context}: {s!r} is not a triple atom <s p o>")
        return TripleAtom(*skolemize_triple(t.triple))

    @property
    def generation(self) -> int:
        return self._generation * 1_000_003 + self.backend.generation

    # --- Sequents over the stored graph ---

    def view(self) -> GraphView:
        """Γ = G: the stored graph as an antecedent."""
        return GraphView(self.backend)

    def parse(self, text: str, *, antecedent: bool = False) -> Sentence:
        """Parse a sentence whose atoms are ``<s p o>`` (prefixes resolved)."""
        from pynmms.syntax import parse_sentence

        return _canonicalize(parse_sentence(text), self.resolver, antecedent=antecedent)

    def sequent(
        self,
        antecedent: Iterable[str] = (),
        consequent: Iterable[str] = (),
        *,
        include_graph: bool = True,
    ) -> Sequent:
        """Build ``G, antecedent ⇒ consequent`` (or just ``antecedent ⇒ consequent``)."""
        ga, gc = _partition_canonical(antecedent, self.resolver, antecedent=True)
        da, dc = _partition_canonical(consequent, self.resolver, antecedent=False)
        if include_graph:
            return Sequent(self.view().with_added_all(ga), gc, AtomSet(da), dc)
        return Sequent(AtomSet(ga), gc, AtomSet(da), dc)

    def position(
        self,
        accept: Iterable[GraphLike] = (),
        reject: Iterable[GraphLike] = (),
        *,
        include_graph: bool = True,
    ) -> Sequent:
        """The sequent whose derivability says a position is out of bounds.

        A position ⟨𝔊, 𝔇⟩ is a set of accepted graphs and a set of rejected
        graphs (Definition 14 of the paper); it is out of bounds iff 𝔊
        entails 𝔇, which by Proposition 16 is ``Γ ⇒ Δ`` over the bearers:

        * the accepted graphs are read conjunctively and their positive
          roles adjoin to that of their union, so they become antecedent
          atoms (blank nodes Skolemized per graph, Lemma 30);
        * each rejected ground graph is denied "severally and in every
          joint combination" (Lemma 24), which is the conjunction of its
          triples under the Ketonen ``R∧`` rule, so it becomes one
          conjunctive sentence in the succedent;
        * a rejected graph with blank nodes becomes a pattern atom (the
          witness search of Lemma 33).

        Several rejected graphs are several succedent sentences (their
        disjunction). No rejected graph asks whether the accepted graphs
        are incoherent (Proposition 34). Each element may be an rdflib
        ``Graph``, a path to an RDF file, or an iterable of triples.
        """
        antecedent: set[str] = set()
        for g in accept:
            for t in _load_graph(g, skolemize=True):
                antecedent.add(TripleAtom(*t))
        consequent: list[str] = []
        for g in reject:
            triples = list(_load_graph(g, skolemize=False))
            if not triples:
                raise ValueError("A rejected graph must contain at least one triple")
            if any(isinstance(n, BNode) for t in triples for n in t):
                consequent.append(PatternAtom(triples))
            else:
                consequent.append(_conjunction(triples))
        return self.sequent(antecedent, consequent, include_graph=include_graph)


GraphLike = Union[Graph, str, Path, Iterable[Triple]]
"""An accepted or rejected graph: an rdflib Graph, an RDF file path, or triples."""


def _load_graph(g: GraphLike, *, skolemize: bool) -> list[Triple]:
    """Triples of *g*: an rdflib Graph, a file path, or an iterable of triples."""
    if isinstance(g, (str, Path)):
        graph = Graph()
        graph.parse(str(g))
    elif isinstance(g, Graph):
        graph = g
    else:
        triples = [(s, p, o) for s, p, o in g]
        if skolemize:
            tag = f"g{id(triples)}"
            return [
                (_skolem_bnode(s, tag), _skolem_bnode(p, tag), _skolem_bnode(o, tag))
                for s, p, o in triples
            ]
        return triples
    if skolemize:
        from pynmms.rdf.backends.memory import _skolemized

        graph = _skolemized(graph)
    return [(s, p, o) for s, p, o in graph]


def _skolem_bnode(n: Node, tag: str) -> Node:
    from pynmms.rdf.atoms import skolem

    return skolem(f"{tag}-{n}") if isinstance(n, BNode) else n


def _conjunction(triples: list[Triple]) -> str:
    """``<t1> & <t2> & ...`` as text, one atom when there is a single triple."""
    atoms = sorted(TripleAtom(*t) for t in triples)
    return " & ".join(atoms) if len(atoms) > 1 else atoms[0]


def _partition_canonical(
    sentences: Iterable[str], resolver: Resolver | None, *, antecedent: bool
) -> tuple[frozenset[str], frozenset[Sentence]]:
    atoms, complex_ = _partition(sentences)
    canon_atoms = frozenset(_coerce_atom(a, resolver, antecedent=antecedent) for a in atoms)
    canon_complex = frozenset(
        _canonicalize(c, resolver, antecedent=antecedent) for c in complex_
    )
    return canon_atoms, canon_complex


class RegimeBase(RDFBase):
    """The base ``B_R`` of an entailment regime (Definition 25, Theorem 35)."""

    def __init__(
        self,
        backend: GraphBackend | None = None,
        *,
        regime: Regime | None = None,
        consequences: set[BasePair] | None = None,
        robustness: dict[BasePair, Robustness] | None = None,
    ) -> None:
        super().__init__(backend, consequences=consequences, robustness=robustness)
        self.regime: Regime = regime or self.backend.regime or SIMPLE
        if self.backend.regime is not None and self.backend.regime is not self.regime:
            logger.warning(
                "RegimeBase regime %s differs from backend regime %s",
                self.regime, self.backend.regime,
            )
        self._engine = ClosureEngine(self.regime)
        self._extras_cache: dict[tuple[int, int, frozenset[str]], tuple[set[Triple], bool]] = {}
        # Hand store-side premises to the backend's join() in one call per
        # rule firing (one round trip on a remote store) rather than one
        # lookup per premise per candidate.
        self.batched: bool = True

    # --- Axiom check ---

    def is_axiom(self, gamma: AtomsView, delta: AtomsView) -> bool:
        if super().is_axiom(gamma, delta):
            return True
        return self._regime_check(gamma, delta)

    def _regime_check(self, gamma: AtomsView, delta: AtomsView) -> bool:
        view = gamma if isinstance(gamma, GraphView) and gamma.backend is self.backend else None
        over_graph = view is not None
        if view is not None:
            if view.removed:
                logger.debug("regime check with removed atoms: %d", len(view.removed))
            extras = frozenset(view.added)
            store_inconsistent = self.backend.is_inconsistent()
        else:
            extras = frozenset(gamma)
            store_inconsistent = False

        derived, bottom = self._closure_of_extras(extras, over_graph)
        if store_inconsistent or bottom:
            logger.debug("regime %s: Γ is inconsistent", self.regime)
            return True

        def in_closure(t: Triple) -> bool:
            return t in derived or (over_graph and self.backend.closure_contains(t))

        for d in delta:
            t = TripleAtom.coerce(d)
            if t is not None:
                if in_closure(t.triple):
                    logger.debug("regime %s: %s in cl(Γ)", self.regime, t)
                    return True
                continue
            pat = PatternAtom.coerce(d)
            if pat is not None and self._matches(pat, derived, over_graph):
                logger.debug("regime %s: pattern %s has a witness in cl(Γ)", self.regime, pat)
                return True
        return False

    def _matches(self, pat: PatternAtom, derived: set[Triple], over_graph: bool) -> bool:
        """Lemma 33 witness search for a succedent pattern (blank nodes as variables)."""
        index = _TripleIndex()
        for t in derived:
            index.add(t)

        def lookup(pattern: tuple[Node | None, Node | None, Node | None]) -> Iterator[Triple]:
            if over_graph:
                yield from self.backend.closure_triples(pattern)
            yield from index.match(pattern)

        bnode_vars: dict[BNode, Var] = {
            b: Var(f"_b{i}") for i, b in enumerate(sorted(pat.bnodes))
        }
        def var(n: Node) -> Node | Var:
            return bnode_vars[n] if isinstance(n, BNode) else n

        patterns = [(var(s), var(p), var(o)) for s, p, o in pat.triples]
        if over_graph and self.batched:
            # A witness entirely inside the store's closure is the common case
            # and costs one query; only otherwise search store ∪ extras.
            if next(iter(self.backend.join(patterns, {})), None) is not None:
                return True
            if not derived:
                return False
        return match_patterns(patterns, lookup) is not None

    def _closure_of_extras(
        self, extras: frozenset[str], over_graph: bool
    ) -> tuple[set[Triple], bool]:
        key = (id(self.backend), self.backend.generation if over_graph else -1, extras)
        hit = self._extras_cache.get(key)
        if hit is not None:
            return hit
        triples = [t.triple for t in (TripleAtom.coerce(a) for a in extras) if t is not None]
        if over_graph:
            new, bottom = self._engine.extend(
                triples, self.backend.closure_triples, self.backend.closure_contains,
                store_join=self.backend.join if self.batched else None,
            )
            result = (new.triples, bottom)
        else:
            closed, bottom = self._engine.close(triples)
            result = (closed, bottom)
        if len(self._extras_cache) >= 256:
            self._extras_cache.clear()
        self._extras_cache[key] = result
        return result

    def is_inconsistent(self, extras: Iterable[str] = ()) -> bool:
        """Is ``G ∪ extras`` R-inconsistent? (Proposition 34)"""
        atoms = frozenset(self._validate_atom(s, "is_inconsistent") for s in extras)
        _, bottom = self._closure_of_extras(atoms, True)
        return self.backend.is_inconsistent() or bottom


__all__ = ["RDFBase", "RegimeBase"]
