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
from collections.abc import Iterable

from pynmms.base import MaterialBase
from pynmms.base import Sequent as BasePair
from pynmms.rdf.atoms import Resolver, Triple, TripleAtom
from pynmms.rdf.backends import GraphBackend, MemoryBackend
from pynmms.rdf.closure import ClosureEngine
from pynmms.rdf.rules import SIMPLE, Regime
from pynmms.rdf.view import GraphView
from pynmms.robustness import Robustness
from pynmms.sequent import AtomSet, AtomsView, Sequent, _partition
from pynmms.syntax import ATOM, Sentence

logger = logging.getLogger(__name__)


def _canonicalize(s: Sentence, resolver: Resolver | None) -> Sentence:
    """Rewrite every quoted atom in *s* to its canonical TripleAtom name."""
    if s.type == ATOM:
        assert s.name is not None
        t = TripleAtom.coerce(s.name, resolver)
        if t is None:
            raise ValueError(f"{s.name!r} is not a triple atom <s p o>")
        return Sentence(type=ATOM, name=t)
    if s.sub is not None:
        return Sentence(type=s.type, sub=_canonicalize(s.sub, resolver))
    assert s.left is not None and s.right is not None
    return Sentence(
        type=s.type,
        left=_canonicalize(s.left, resolver),
        right=_canonicalize(s.right, resolver),
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
        return t

    @property
    def generation(self) -> int:
        return self._generation * 1_000_003 + self.backend.generation

    # --- Sequents over the stored graph ---

    def view(self) -> GraphView:
        """Γ = G: the stored graph as an antecedent."""
        return GraphView(self.backend)

    def parse(self, text: str) -> Sentence:
        """Parse a sentence whose atoms are ``<s p o>`` (prefixes resolved)."""
        from pynmms.syntax import parse_sentence

        return _canonicalize(parse_sentence(text), self.resolver)

    def sequent(
        self,
        antecedent: Iterable[str] = (),
        consequent: Iterable[str] = (),
        *,
        include_graph: bool = True,
    ) -> Sequent:
        """Build ``G, antecedent ⇒ consequent`` (or just ``antecedent ⇒ consequent``)."""
        ga, gc = _partition_canonical(antecedent, self.resolver)
        da, dc = _partition_canonical(consequent, self.resolver)
        if include_graph:
            return Sequent(self.view().with_added_all(ga), gc, AtomSet(da), dc)
        return Sequent(AtomSet(ga), gc, AtomSet(da), dc)


def _coerce_atom(name: str, resolver: Resolver | None) -> str:
    t = TripleAtom.coerce(name, resolver)
    if t is None:
        raise ValueError(f"{name!r} is not a triple atom <s p o>")
    return t


def _partition_canonical(
    sentences: Iterable[str], resolver: Resolver | None
) -> tuple[frozenset[str], frozenset[Sentence]]:
    atoms, complex_ = _partition(sentences)
    canon_atoms = frozenset(_coerce_atom(a, resolver) for a in atoms)
    canon_complex = frozenset(_canonicalize(c, resolver) for c in complex_)
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
        for d in delta:
            t = TripleAtom.coerce(d)
            if t is None:
                continue
            if t.triple in derived or (over_graph and self.backend.closure_contains(t.triple)):
                logger.debug("regime %s: %s in cl(Γ)", self.regime, t)
                return True
        return False

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
                triples, self.backend.closure_triples, self.backend.closure_contains
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
