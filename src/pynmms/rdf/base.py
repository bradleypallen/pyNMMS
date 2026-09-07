"""Material bases over RDF triples.

:class:`RDFBase` is a base in the sense of the paper's ``def:fitness``: its lexicon is the
ground triples over a vocabulary and whose relation satisfies Containment.
The lexicon is intensional (any well-formed triple is a sentence), explicit
entries with robustness policies come from :class:`~pynmms.base.MaterialBase`,
and the stored graph is reached through a backend.

:class:`RegimeBase` is the *regime-relative material base* ``B_{R,I}``: a
regime ``R`` together with a set ``I`` of material entries ``<A, D; E>``
(antecedent, consequent, defeaters). A pair ``(Γ, Δ)`` is good iff

(i)   Γ is R-inconsistent, or
(ii)  ``Δ ∩ cl_R(Γ) ≠ ∅``                                    (the regime layer), or
(iii) some entry ``<A, D; E>`` has ``A ⊆ cl_R(Γ)`` (antecedent derivable, not
      merely present), no ``e ∈ E`` with ``e ⊆ cl_R(Γ)`` (no defeater
      derivable), and ``Δ ∩ cl_R(Γ ∪ D) ≠ ∅`` (consequent elaborated by the
      regime; with ``elaborate_consequent = False``, ``Δ ∩ D ≠ ∅``).

Robustness policies map onto (iii): ``monotone`` has ``E = ∅``; ``guarded``
has ``E`` as given (singleton defeaters as singleton sets, conjunctive
exclusions as sets); ``exact`` additionally requires ``Γ ⊆ cl_R(A)``, i.e.
an antecedent R-equivalent to ``A``. There is still no Cut between material
entries: (iii) uses one entry. Containment holds through (ii) since
``Γ ⊆ cl_R(Γ)``. With ``I`` empty this is the base a regime specifies (the
paper's ``def:fitness``); ``B_{R,I}`` itself is a proposal, see the theory
page. With Γ a :class:`~pynmms.rdf.view.GraphView` over the backend,
``cl_R(Γ)`` is the backend's materialised closure of G extended by the
per-node extras, and ``cl_R(Γ ∪ D)`` is that extended once more by ``D``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
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
        graphs (``def:contententailment``); it is out of bounds iff 𝔊
        entails 𝔇, which by ``prop:positional`` is ``Γ ⇒ Δ`` over the bearers:

        * the accepted graphs are read conjunctively and their positive
          roles adjoin to that of their union, so they become antecedent
          atoms (blank nodes Skolemized per graph, ``lem:skolem``);
        * each rejected ground graph is denied "severally and in every
          joint combination" (``lem:shapes``), which is the conjunction of its
          triples under the Ketonen ``R∧`` rule, so it becomes one
          conjunctive sentence in the succedent;
        * a rejected graph with blank nodes becomes a pattern atom (the
          witness search of ``lem:witnesschar``).

        Several rejected graphs are several succedent sentences (their
        disjunction). No rejected graph asks whether the accepted graphs
        are incoherent (``prop:incoherence``). Each element may be an rdflib
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
    """The regime-relative material base ``B_{R,I}`` (see the module docstring)."""

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
        # (iii)'s third conjunct: read the consequent D through the regime
        # (Δ ∩ cl_R(Γ ∪ D)) rather than literally (Δ ∩ D).
        self.elaborate_consequent: bool = True
        self._entry_closure_cache: dict[frozenset[str], set[Triple]] = {}

    def clear_caches(self) -> None:
        self._extras_cache.clear()
        self._entry_closure_cache.clear()

    @property
    def material_entries(self) -> list[tuple[frozenset[str], frozenset[str], Robustness]]:
        """The entries <A, D; E> of I with their policies."""
        return [(g, d, self.robustness_of(g, d)) for g, d in self._consequences]

    # --- Axiom check ---

    def is_axiom(self, gamma: AtomsView, delta: AtomsView) -> bool:
        """The B_{R,I} test: (i) inconsistency, (ii) the regime, (iii) one material entry.

        Containment is (ii) with Γ ⊆ cl_R(Γ), so the propositional base's
        literal-match paths are not consulted here.
        """
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
        if self._delta_meets(delta, derived, over_graph, "cl(Γ)"):
            return True
        if not self._consequences:
            return False

        def in_cl(t: Triple) -> bool:
            return t in derived or (over_graph and self.backend.closure_contains(t))

        return self._material_check(gamma, delta, extras, derived, over_graph, in_cl)

    def _delta_meets(
        self, delta: AtomsView, derived: set[Triple], over_graph: bool, what: str
    ) -> bool:
        """Δ ∩ closure ≠ ∅, where the closure is the store's plus *derived*."""
        for d in delta:
            t = TripleAtom.coerce(d)
            if t is not None:
                if t.triple in derived or (over_graph and self.backend.closure_contains(t.triple)):
                    logger.debug("regime %s: %s in %s", self.regime, t, what)
                    return True
                continue
            pat = PatternAtom.coerce(d)
            if pat is not None and self._matches(pat, derived, over_graph):
                logger.debug("regime %s: pattern %s has a witness in %s", self.regime, pat, what)
                return True
        return False

    def _material_check(
        self,
        gamma: AtomsView,
        delta: AtomsView,
        extras: frozenset[str],
        derived: set[Triple],
        over_graph: bool,
        in_cl: Callable[[Triple], bool],
    ) -> bool:
        """Clause (iii): one entry whose antecedent is derivable, whose defeaters are
        not, and whose consequent, elaborated by the regime, meets Δ."""

        def atoms_in_cl(atoms: Iterable[str]) -> bool:
            for a in atoms:
                t = TripleAtom.coerce(a)
                if t is None or not in_cl(t.triple):
                    return False
            return True

        for a_set, d_set, rob in self.material_entries:
            if not atoms_in_cl(a_set):
                continue
            # Antecedent-side defeaters (singletons and the left parts of
            # exclusions) are read through the closure; succedent-side ones
            # against Δ literally.
            if any(atoms_in_cl([x]) for x in rob.left):
                logger.debug("entry %s |~ %s: a defeater is derivable", set(a_set), set(d_set))
                continue
            defeated = False
            for x_, y in rob.exclusions:
                left_ok = atoms_in_cl(x_) if x_ else True
                right_ok = all(x in delta for x in y) if y else True
                if left_ok and right_ok:
                    defeated = True
                    break
            if defeated or (rob.right and any(x in delta for x in rob.right)):
                logger.debug("entry %s |~ %s: a conjunctive or succedent defeater applies",
                             set(a_set), set(d_set))
                continue
            if rob.is_exact and not self._gamma_within_closure_of(gamma, a_set):
                logger.debug("entry %s |~ %s: exact, Γ not R-equivalent to A",
                             set(a_set), set(d_set))
                continue
            if self.elaborate_consequent:
                elaborated = self._closure_of_extras_plus(extras, derived, d_set, over_graph)
                if self._delta_meets(delta, elaborated, over_graph, "cl(Γ ∪ D)"):
                    logger.debug("entry %s |~ %s fires [%s]", set(a_set), set(d_set), rob)
                    return True
            elif any(x in delta for x in d_set):
                logger.debug("entry %s |~ %s fires literally [%s]", set(a_set), set(d_set), rob)
                return True
        return False

    def _closure_of_extras_plus(
        self, extras: frozenset[str], derived: set[Triple], d_set: frozenset[str],
        over_graph: bool,
    ) -> set[Triple]:
        """cl_R(Γ ∪ D) minus the store: cl_R(Γ)'s in-process part extended by D."""
        key = (id(self.backend), self.backend.generation if over_graph else -1, extras | d_set)
        hit = self._extras_cache.get(key)
        if hit is not None:
            return hit[0]
        base_new = _TripleIndex()
        for t in derived:
            base_new.add(t)
        d_triples = [t.triple for t in (TripleAtom.coerce(a) for a in d_set) if t is not None]

        def lookup(pattern: tuple[Node | None, Node | None, Node | None]) -> Iterator[Triple]:
            if over_graph:
                yield from self.backend.closure_triples(pattern)
            yield from base_new.match(pattern)

        def contains(t: Triple) -> bool:
            return t in base_new or (over_graph and self.backend.closure_contains(t))

        more, _bottom = self._engine.extend(d_triples, lookup, contains)
        result = derived | more.triples
        if len(self._extras_cache) >= 256:
            self._extras_cache.clear()
        self._extras_cache[key] = (result, False)
        return result

    def _gamma_within_closure_of(self, gamma: AtomsView, a_set: frozenset[str]) -> bool:
        """Γ ⊆ cl_R(A), the extra condition of an exact entry."""
        closed = self._entry_closure_cache.get(a_set)
        if closed is None:
            triples = [t.triple for t in (TripleAtom.coerce(a) for a in a_set) if t is not None]
            closed, _ = self._engine.close(triples)
            self._entry_closure_cache[a_set] = closed
        if len(gamma) > len(closed):
            return False
        for g in gamma:
            t = TripleAtom.coerce(g)
            if t is None or t.triple not in closed:
                return False
        return True

    def _matches(self, pat: PatternAtom, derived: set[Triple], over_graph: bool) -> bool:
        """``lem:witnesschar`` witness search for a succedent pattern (blanks as variables)."""
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
        """Is ``G ∪ extras`` R-inconsistent? (``prop:incoherence``)"""
        atoms = frozenset(self._validate_atom(s, "is_inconsistent") for s in extras)
        _, bottom = self._closure_of_extras(atoms, True)
        return self.backend.is_inconsistent() or bottom


__all__ = ["RDFBase", "RegimeBase"]
