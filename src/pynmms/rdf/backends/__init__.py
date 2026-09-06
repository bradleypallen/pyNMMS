"""Graph backends: where the stored graph G and its closure live.

A backend answers membership and pattern queries against the *asserted*
graph and against its *closure* under the backend's regime (the same graph
when no regime is configured). The reasoner never iterates a backend during
proof search; it asks for membership of a handful of triples per node.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rdflib.term import Node

if TYPE_CHECKING:
    from pynmms.rdf.atoms import Resolver
    from pynmms.rdf.rules import Regime

Triple = tuple[Node, Node, Node]
Pattern = tuple[Node | None, Node | None, Node | None]


@runtime_checkable
class GraphBackend(Protocol):
    """What a store must provide to serve as the base of a :class:`GraphView`."""

    @property
    def generation(self) -> int:
        """Bumped whenever the asserted graph or the closure changes."""
        ...

    @property
    def regime(self) -> Regime | None:
        """The entailment regime whose closure this backend maintains, if any."""
        ...

    @property
    def resolver(self) -> Resolver:
        """Prefix resolver for parsing and display."""
        ...

    def size(self) -> int:
        """Number of asserted triples."""
        ...

    def contains(self, t: Triple) -> bool:
        """Is *t* asserted?"""
        ...

    def triples(self, pattern: Pattern) -> Iterator[Triple]:
        """Asserted triples matching *pattern* (``None`` = wildcard)."""
        ...

    def closure_contains(self, t: Triple) -> bool:
        """Is *t* in cl_R(G)? (Equals ``contains`` when there is no regime.)"""
        ...

    def closure_triples(self, pattern: Pattern) -> Iterator[Triple]:
        """Closure triples matching *pattern*."""
        ...

    def is_inconsistent(self) -> bool:
        """Does the regime derive ⊥ from G alone?"""
        ...


from pynmms.rdf.backends.memory import MemoryBackend  # noqa: E402
from pynmms.rdf.backends.sparql import SPARQLBackend  # noqa: E402

__all__ = ["GraphBackend", "MemoryBackend", "SPARQLBackend", "Triple", "Pattern"]
