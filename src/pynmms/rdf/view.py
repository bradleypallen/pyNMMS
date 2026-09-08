"""A graph in a backend, plus a small diff, as an antecedent.

:class:`GraphView` implements the same interface as
:class:`pynmms.sequent.AtomSet` (membership, size, iteration, structural
hash/equality, ``with_added``/``with_removed``, ``intersects``) but its base is
a :class:`~pynmms.rdf.backends.GraphBackend` rather than a ``frozenset``.
Membership is answered by the backend; hashing and equality use only the
backend identity and generation plus the diffs, so the memo key of a proof
node never touches the graph. Iterating a view streams the whole graph and
should only be used for display or diagnostics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from collections.abc import Set as AbstractSet

from pynmms.rdf.atoms import TripleAtom
from pynmms.rdf.backends import GraphBackend
from pynmms.sequent import AtomsView

logger = logging.getLogger(__name__)

_EMPTY: frozenset[str] = frozenset()


class GraphView(AbstractSet[str]):
    """Γ = G ∪ added \\ removed, with G living in a backend.

    With ``background=True`` the view is a *position over a background*: its
    members are the added atoms alone, while the backend is still the store
    a :class:`~pynmms.rdf.base.RegimeBase` closes the position against.
    """

    __slots__ = ("_backend", "_added", "_removed", "_generation", "_hashcode", "_background")

    def __init__(
        self,
        backend: GraphBackend,
        added: frozenset[str] = _EMPTY,
        removed: frozenset[str] = _EMPTY,
        background: bool = False,
    ) -> None:
        self._backend = backend
        self._added = added
        self._removed = removed
        self._background = background
        self._generation = backend.generation
        self._hashcode: int | None = None

    # --- Properties ---

    @property
    def backend(self) -> GraphBackend:
        return self._backend

    @property
    def added(self) -> frozenset[str]:
        return self._added

    @property
    def removed(self) -> frozenset[str]:
        return self._removed

    @property
    def background(self) -> bool:
        """Is the store a background rather than part of Γ?"""
        return self._background

    @property
    def diff_size(self) -> int:
        return len(self._added) + len(self._removed)

    def added_triples(self) -> list[TripleAtom]:
        out = []
        for a in self._added:
            t = TripleAtom.coerce(a)
            if t is not None:
                out.append(t)
        return out

    # --- Set protocol ---

    def _in_store(self, x: object) -> bool:
        t = TripleAtom.coerce(x)
        return t is not None and self._backend.contains(t.triple)

    def __contains__(self, x: object) -> bool:
        if x in self._added:
            return True
        if self._background or x in self._removed:
            return False
        return self._in_store(x)

    def __iter__(self) -> Iterator[str]:
        yield from self._added
        if self._background:
            return
        logger.debug("GraphView iterated: streaming %d triples from the backend", len(self))
        for t in self._backend.triples((None, None, None)):
            atom = TripleAtom.from_triple(t)
            if atom not in self._removed:
                yield atom

    def __len__(self) -> int:
        if self._background:
            return len(self._added)
        return self._backend.size() + len(self._added) - len(self._removed)

    def __hash__(self) -> int:
        if self._hashcode is None:
            self._hashcode = hash(
                (id(self._backend), self._generation, self._added, self._removed,
                 self._background)
            )
        return self._hashcode

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GraphView):
            return (
                self._backend is other._backend
                and self._generation == other._generation
                and self._added == other._added
                and self._removed == other._removed
                and self._background == other._background
            )
        if isinstance(other, AbstractSet):
            return len(self) == len(other) and all(x in self for x in other)
        return NotImplemented

    def __repr__(self) -> str:
        return (
            f"GraphView({self._backend!r}, +{len(self._added)}, -{len(self._removed)})"
        )

    # --- Persistent updates ---

    def with_added(self, x: str) -> GraphView:
        if x in self:
            return self
        if x in self._removed:
            if self._background:
                # Set aside from the background and now asserted: a commitment.
                return GraphView(self._backend, self._added | {x}, self._removed - {x}, True)
            return GraphView(self._backend, self._added, self._removed - {x}, self._background)
        return GraphView(self._backend, self._added | {x}, self._removed, self._background)

    def with_removed(self, x: str) -> GraphView:
        if x not in self:
            return self
        if x in self._added:
            return GraphView(self._backend, self._added - {x}, self._removed, self._background)
        return GraphView(self._backend, self._added, self._removed | {x}, self._background)

    def with_added_all(self, xs: Iterable[str]) -> GraphView:
        out = self
        for x in xs:
            out = out.with_added(x)
        return out

    # --- Convenience ---

    def intersects(self, other: AtomsView) -> bool:
        if isinstance(other, GraphView):
            if (other._backend is self._backend and other._generation == self._generation
                    and not self._background and not other._background):
                if self._backend.size() > len(self._removed | other._removed):
                    return True
            return any(x in self for x in other._added) or any(x in other for x in self._added)
        return any(x in self for x in other)

    def to_frozenset(self) -> frozenset[str]:
        """Materialise Γ (streams the whole graph; diagnostics only)."""
        return frozenset(self)
