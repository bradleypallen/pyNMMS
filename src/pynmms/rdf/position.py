"""Positions as speech acts (PLAN.md workstream H).

A :class:`Position` is what a holder has said: the atoms they have asserted,
the graphs they have denied, and the order in which they did so. It is
checked over the store as *background*, the sediment of past speech acts
that a conversation takes for granted, and it speaks for the subjects it
asserts about, so those subjects' stored records are set aside while it is
checked (a record is nobody's position until someone reads it aloud, which
is :meth:`Position.of`).

The three questions a scorekeeper asks of a position:

* :meth:`Position.coherent` -- is ⟨accepted, rejected⟩ in bounds? It is out
  of bounds iff the accepted graphs entail a rejected one
  (``def:contententailment``, ``prop:positional``), or, with nothing
  rejected, iff the accepted graphs are incoherent (``prop:incoherence``).
  The verdict names the entry or rule responsible and the defeater that
  would rescue it.
* :meth:`Position.commits_to` -- does the position, over the background,
  entail this? (``ask`` as a challenge.)
* :meth:`Position.precludes` -- is the position incompatible with this?
  (``Γ, A ⇒ ∅``.)

Human scale is the normal scale: a position built in dialogue is tens of
triples, so the per-query cost is the extras closure of those triples, and
the store, however large, matters only as background.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rdflib import BNode, URIRef
from rdflib.term import Node

from pynmms.rdf.atoms import SKOLEM_NS, PatternAtom, TripleAtom
from pynmms.rdf.base import GraphLike, _conjunction, _load_graph
from pynmms.reasoner import NMMSReasoner

if TYPE_CHECKING:
    from pynmms.rdf.base import RegimeBase
    from pynmms.reasoner import ProofResult
    from pynmms.sequent import Sequent

logger = logging.getLogger(__name__)

Triple = tuple[Node, Node, Node]


@dataclass(frozen=True)
class Move:
    """One speech act in a position's history."""

    kind: str  # "assert", "deny", "withdraw", "commit"
    atoms: frozenset[str] = frozenset()
    note: str = ""


@dataclass(frozen=True)
class Verdict:
    """The answer to a question about a position, with its grounds.

    ``bool(verdict)`` is the answer. *reason* is the axiom that decided the
    proof (the last one that succeeded, as the reasoner reports it), and
    *rescue* the defeaters of the entry responsible, which is what the
    holder would have to establish to answer the challenge.
    """

    value: bool
    reason: str | None = None
    rescue: tuple[str, ...] = ()
    result: Any = field(default=None, compare=False, repr=False)

    def __bool__(self) -> bool:
        return self.value


class Position:
    """A holder's commitments over a base whose store is the background."""

    def __init__(self, base: RegimeBase, *, holder: str = "",
                 speaks_for_subjects: bool = True) -> None:
        self.base = base
        self.holder = holder
        self.speaks_for_subjects = speaks_for_subjects
        self._accepted: set[str] = set()
        self._rejected: list[str] = []  # succedent sentences (conjunctions or patterns)
        self._rejected_graphs: list[list[Triple]] = []
        self.log: list[Move] = []
        self._reasoner = NMMSReasoner(base, persistent_cache=True)

    # --- What has been said ---

    @property
    def accepted(self) -> frozenset[str]:
        return frozenset(self._accepted)

    @property
    def rejected(self) -> tuple[str, ...]:
        return tuple(self._rejected)

    @property
    def subjects(self) -> frozenset[Node]:
        """The subjects the position speaks for."""
        out: set[Node] = set()
        for a in self._accepted:
            t = TripleAtom.coerce(a, self.base.resolver)
            if t is not None:
                out.add(t.s)
        return frozenset(out)

    def _atoms(self, items: Iterable[Any]) -> frozenset[str]:
        out: set[str] = set()
        for x in items:
            t = TripleAtom.coerce(x, self.base.resolver)
            if t is None:
                raise ValueError(f"{x!r} is not a triple atom")
            out.add(str(t))
        return frozenset(out)

    def assert_(self, *triples: Any) -> Position:
        """Undertake commitment to these triples (atoms, names, or rdflib triples)."""
        atoms = self._atoms(triples)
        self._accepted |= atoms
        self.log.append(Move("assert", atoms))
        return self

    def deny(self, graph: GraphLike) -> Position:
        """Reject a graph: a conjunction of ground triples, or a pattern with blank nodes."""
        triples = list(_load_graph(graph, skolemize=False))
        if not triples:
            raise ValueError("A rejected graph must contain at least one triple")
        sentence = (PatternAtom(triples) if any(isinstance(n, BNode) for t in triples for n in t)
                    else _conjunction(triples))
        self._rejected.append(str(sentence))
        self._rejected_graphs.append(triples)
        self.log.append(Move("deny", frozenset(TripleAtom(*t) for t in triples)))
        return self

    def withdraw(self, *triples: Any) -> Position:
        """Take back assertions."""
        atoms = self._atoms(triples)
        self._accepted -= atoms
        self.log.append(Move("withdraw", atoms))
        return self

    def commit(self) -> int:
        """Write the accepted triples to the store (a ``TELL``); they become background."""
        triples = [t.triple for t in (TripleAtom.coerce(a) for a in self._accepted) if t]
        add = getattr(self.base.backend, "add", None)
        if add is None:
            raise TypeError("the backend cannot be written to")
        n = int(add(triples))
        self.log.append(Move("commit", frozenset(self._accepted), f"{n} new"))
        self._accepted.clear()
        self.base.clear_caches()
        return n

    @classmethod
    def of(cls, base: RegimeBase, subject: Node | str, *, holder: str = "") -> Position:
        """Read a stored record aloud: its concise description as a position.

        The subject's asserted triples, following blank nodes and Skolem
        nodes into their own records (a maker record, an annotation).
        """
        s = subject if isinstance(subject, Node) else base.resolver.expand(subject)
        pos = cls(base, holder=holder)
        seen: set[Node] = set()
        frontier: list[Node] = [s]
        atoms: list[TripleAtom] = []
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            for t in base.backend.triples((node, None, None)):
                atoms.append(TripleAtom(*t))
                o = t[2]
                if isinstance(o, BNode) or (
                    isinstance(o, URIRef) and str(o).startswith(SKOLEM_NS)
                ):
                    frontier.append(o)
        if atoms:
            pos.assert_(*atoms)
        return pos

    # --- Checking ---

    def aside(self) -> frozenset[str]:
        """The stored triples of the subjects the position speaks for."""
        if not self.speaks_for_subjects:
            return frozenset()
        out: set[str] = set()
        for s in self.subjects:
            for t in self.base.backend.triples((s, None, None)):
                out.add(TripleAtom(*t))
        return frozenset(out)

    def sequent(self, antecedent: Iterable[Any] = (), consequent: Iterable[Any] = (),
                *, rejected: bool = False) -> Sequent:
        """``accepted, antecedent ⇒ consequent`` over the background (plus the
        rejected graphs in the succedent when *rejected*)."""
        ant = list(self._accepted) + [str(x) for x in antecedent]
        con = [str(x) for x in consequent] + (self._rejected if rejected else [])
        return self.base.sequent(ant, con, include_graph="background", aside=self.aside())

    def _ask(self, seq: Sequent) -> Verdict:
        self.base.last_reason = None
        self.base.last_rescue = ()
        result: ProofResult = self._reasoner.derives_sequent(seq)
        return Verdict(result.derivable, self.base.last_reason if result.derivable else None,
                       tuple(self.base.last_rescue) if result.derivable else (), result)

    def coherent(self) -> Verdict:
        """In bounds: the accepted graphs do not entail a rejected one, nor ∅."""
        v = self._ask(self.sequent(rejected=True))
        return Verdict(not v.value, v.reason, v.rescue, v.result)

    def commits_to(self, *consequent: Any) -> Verdict:
        return self._ask(self.sequent(consequent=consequent))

    def precludes(self, *atoms: Any) -> Verdict:
        return self._ask(self.sequent(antecedent=atoms))

    def __repr__(self) -> str:
        who = f"{self.holder!r}, " if self.holder else ""
        return (f"Position({who}{len(self._accepted)} accepted, {len(self._rejected)} rejected, "
                f"{len(self.log)} moves)")
