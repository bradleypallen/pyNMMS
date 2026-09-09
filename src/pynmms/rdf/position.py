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
* :meth:`Position.propose` -- the curation loop's report: everything the
  holder needs before writing (in bounds or not, refutation and rescue, the
  opponent's probes, commitments and preclusions, the score, the trace).
* :meth:`Position.challenges` -- the probes an opponent can put to it,
  generated from the base: incompatibilities and ⊥ rules the position's
  commitments partly satisfy (asking for the rest), and defaults it is
  committed to but has not acknowledged (asking whether it accepts them).

Human scale is the normal scale: a position built in dialogue is tens of
triples, so the per-query cost is the extras closure of those triples, and
the store, however large, matters only as background.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rdflib import BNode, URIRef
from rdflib.term import Node

from pynmms.rdf.atoms import SKOLEM_NS, PatternAtom, TripleAtom
from pynmms.rdf.base import GraphLike, _conjunction, _load_graph
from pynmms.rdf.closure import apply as _apply
from pynmms.rdf.closure import unify as _unify
from pynmms.rdf.provenance import Ground, attribution_triple, holder_graph, provenance_of
from pynmms.rdf.rules import Rule, Var
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
class Round:
    """The outcome of a round of the opponent's probes (:meth:`Position.defend`)."""

    stood: bool
    refutations: int
    open: int
    challenges: tuple[Any, ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True)
class Report:
    """What :meth:`Position.propose` returns: the position assessed, nothing written."""

    coherent: Any  # Verdict
    challenges: tuple[Any, ...]
    commitments: dict[str, Ground]
    precluded: tuple[str, ...]
    defaults: tuple[str, ...]
    rescue: tuple[str, ...]
    score: dict[str, int]
    trace: tuple[str, ...]
    ms: float

    def summary(self) -> str:
        lines = []
        if self.coherent:
            lines.append(f"Position is in bounds; score {self.score}.")
        else:
            why = self.coherent.reason or "⊥ from the regime"
            lines.append(f"Position is out of bounds: {why}.")
            if self.rescue:
                lines.append("It would be rescued by: " + ", ".join(self.rescue) + ".")
        if self.defaults:
            lines.append("Committed by default to: " + ", ".join(self.defaults) + ".")
        if self.precluded:
            lines.append("Precluded from accepting: " + ", ".join(self.precluded) + ".")
        open_probes = [c for c in self.challenges if c.kind != "refutation"]
        if open_probes:
            lines.append(f"{len(open_probes)} open probe(s).")
        return "\n".join(lines)


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


@dataclass(frozen=True)
class Challenge:
    """A probe an opponent can put to a position.

    *kind* is ``"refutation"`` (the position is already out of bounds),
    ``"incompatibility"`` (a material incompatibility it partly satisfies),
    ``"incoherence"`` (a ⊥ rule of the regime it partly matches), or
    ``"default"`` (a material inference it is committed to and has not
    acknowledged). *asks* are the atoms, or a pattern with blank nodes for the
    unbound variables, the holder is asked to accept; *source* the entry or
    rule; *rescue* the defeaters that would answer the challenge.
    """

    kind: str
    asks: tuple[str, ...]
    source: str
    rescue: tuple[str, ...] = ()

    def question(self) -> str:
        what = ", ".join(self.asks)
        if self.kind == "refutation":
            q = f"Your position is out of bounds: {self.source}."
        elif self.kind == "default":
            q = f"You are committed to {what} by {self.source}. Do you accept it?"
        else:
            q = f"Do you also accept {what}? Then {self.source} puts you out of bounds."
        if self.rescue:
            q += " Unless: " + ", ".join(self.rescue) + "."
        return q


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
        self._grounds: dict[str, Ground] = {}
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

    def assert_(self, *triples: Any, ground: Ground | None = None) -> Position:
        """Undertake commitment to these triples (atoms, names, or rdflib triples).

        The commitment's ground is ``asserted`` (undefended) unless *ground*
        says otherwise; :meth:`of` passes the inherited provenance.
        """
        atoms = self._atoms(triples)
        self._accepted |= atoms
        for a in atoms:
            if a not in self._grounds or self._grounds[a].kind == "asserted":
                self._grounds[a] = ground or Ground("asserted")
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
        for a in atoms:
            self._grounds.pop(a, None)
        self.log.append(Move("withdraw", atoms))
        return self

    def commit(self) -> int:
        """Write the accepted triples to the store (a ``TELL``); they become background.

        With a holder, the triples are also recorded in the holder's named
        graph, attributed with ``prov:wasAttributedTo``, so later readers
        inherit them from this holder.
        """
        triples = [t.triple for t in (TripleAtom.coerce(a) for a in self._accepted) if t]
        add = getattr(self.base.backend, "add", None)
        if add is None:
            raise TypeError("the backend cannot be written to")
        if self.holder and triples:
            graph = holder_graph(self.holder)
            n = int(add(triples, source=graph))
            if not self.base.backend.contains(attribution_triple(graph, self.holder)):
                add([attribution_triple(graph, self.holder)])
        else:
            n = int(add(triples))
        self.log.append(Move("commit", frozenset(self._accepted), f"{n} new"))
        self._accepted.clear()
        self._grounds.clear()
        self.base.clear_caches()
        return n

    @classmethod
    def of(cls, base: RegimeBase, subject: Node | str, *, holder: str = "",
           source: URIRef | None = None) -> Position:
        """Read a stored record aloud: its concise description as a position.

        The subject's asserted triples, following blank nodes and Skolem
        nodes into their own records (a maker record, an annotation). Each
        commitment is inherited, with its source graph and its record's
        evidence (``base.provenance``). With *source*, only that named
        graph's account of the subject is read: one catalogue's position.
        """
        s = subject if isinstance(subject, Node) else base.resolver.expand(subject)
        pos = cls(base, holder=holder)
        seen: set[Node] = set()
        frontier: list[Node] = [s]
        graphs_of = getattr(base.backend, "graphs_of", None)
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            for t in base.backend.triples((node, None, None)):
                if source is not None and (graphs_of is None or source not in graphs_of(t)):
                    continue
                pos.assert_(TripleAtom(*t), ground=provenance_of(base, t, prefer_source=source))
                o = t[2]
                if isinstance(o, BNode) or (
                    isinstance(o, URIRef) and str(o).startswith(SKOLEM_NS)
                ):
                    frontier.append(o)
        return pos

    # --- Entitlement ---

    def grounds(self, *, derived: bool = False) -> dict[str, Ground]:
        """Why the position holds each commitment; with *derived*, the defaults it is
        committed to but has not acknowledged, via their entries."""
        out = {a: self._grounds.get(a, Ground("asserted")) for a in sorted(self._accepted)}
        if derived:
            for c in self.challenges():
                if c.kind == "default":
                    for a in c.asks:
                        out.setdefault(a, Ground("derived", via=c.source))
        return out

    def defend(self) -> Round:
        """A round of the opponent's probes. If none refutes the position, every
        asserted commitment becomes defended; otherwise standings are unchanged."""
        cs = self.challenges()
        refutations = sum(1 for c in cs if c.kind == "refutation")
        open_ = len(cs) - refutations
        stood = refutations == 0
        if stood:
            for a in self._accepted:
                if self._grounds.get(a, Ground("asserted")).kind == "asserted":
                    self._grounds[a] = Ground("defended")
        self.log.append(Move("defend", frozenset(self._accepted),
                             f"{'stood' if stood else 'refuted'}, {open_} open"))
        return Round(stood, refutations, open_, tuple(cs))

    def score(self) -> dict[str, int]:
        """Committed, entitled (defended or inherited), and open (asserted, undefended)."""
        g = self.grounds()
        entitled = sum(1 for x in g.values() if x.entitled)
        return {"committed": len(g), "entitled": entitled, "open": len(g) - entitled}

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

    # --- The curation loop ---

    def propose(self) -> Report:
        """Assess the position as a proposal, writing nothing.

        Returns whether it is in bounds with the refutation and rescue, the
        opponent's probes, its commitments (asserted, inherited, and the
        defaults it is committed to), what it is precluded from accepting
        (the atoms incompatibility and incoherence probes ask for), its
        entitlement score, and the proof trace of the coherence check.
        """
        t0 = time.perf_counter()
        v = self.coherent()
        cs = tuple(self.challenges())
        commitments = {a: self._grounds.get(a, Ground("asserted")) for a in sorted(self._accepted)}
        defaults: list[str] = []
        precluded: list[str] = []
        for c in cs:
            if c.kind == "default":
                for a in c.asks:
                    commitments.setdefault(a, Ground("derived", via=c.source))
                    defaults.append(a)
            elif c.kind in ("incompatibility", "incoherence"):
                precluded.extend(c.asks)
        trace = tuple(str(e) for e in getattr(v.result, "entries", ()) or ())
        g = commitments
        entitled = sum(1 for a in self._accepted if g[a].entitled)
        score = {"committed": len(self._accepted), "entitled": entitled,
                 "open": len(self._accepted) - entitled}
        return Report(v, cs, commitments, tuple(dict.fromkeys(precluded)),
                      tuple(dict.fromkeys(defaults)), v.rescue, score, trace,
                      (time.perf_counter() - t0) * 1000)

    # --- The opponent's probes ---

    def challenges(self) -> list[Challenge]:
        """The probes an opponent can generate from the base for this position.

        Refutations first, then incompatibilities and ⊥ rules by how few atoms
        they still need, then unacknowledged defaults. Only what the position's
        own commitments take part in is asked (attribution), and what the store
        holds about the position's subjects counts as set aside, so the record's
        other facts are asked rather than assumed.
        """
        base = self.base
        aside = self.aside()
        accepted = frozenset(self._accepted)
        derived, bottom = base._closure_of_extras(accepted, True)
        hidden = aside - accepted
        own_triples: set[Triple] = set(derived)
        for a in accepted:
            t = TripleAtom.coerce(a, base.resolver)
            if t is not None:
                own_triples.add(t.triple)
        own_atoms = {str(TripleAtom(*t)) for t in own_triples}

        def in_cl(atom: str) -> bool:
            t = TripleAtom.coerce(atom, base.resolver)
            if t is None:
                return False
            if t.triple in own_triples:
                return True
            return str(t) not in hidden and base.backend.closure_contains(t.triple)

        def defeated(rob: Any) -> bool:
            return any(in_cl(x) for x in rob.left)

        out: list[Challenge] = []
        v = self.coherent()
        if not v:
            out.append(Challenge("refutation", (), v.reason or "incoherent", v.rescue))
        elif bottom:
            out.append(Challenge("refutation", (), f"⊥ from the regime {base.regime.name}"))

        # Material entries: incompatibilities partly satisfied, defaults unacknowledged.
        for a_set, d_set, rob in base.material_entries:
            have = [a for a in a_set if a in own_atoms]
            if not have:
                continue  # background only: not this position's
            if defeated(rob):
                continue
            rest = [a for a in a_set if a not in own_atoms]
            missing = tuple(sorted(a for a in rest if not in_cl(a)))
            source = (f"{', '.join(sorted(map(str, a_set)))} |~ "
                      f"{', '.join(sorted(map(str, d_set))) if d_set else '∅'} [{rob.kind}]")
            rescue = tuple(sorted(rob.left))
            if not d_set:
                if missing:
                    out.append(Challenge("incompatibility", missing, source, rescue))
                elif not v.value:
                    pass  # already reported as the refutation
                else:
                    out.append(Challenge("refutation", (), source, rescue))
            elif not missing:
                unacknowledged = tuple(sorted(d for d in d_set if not in_cl(d)))
                if unacknowledged:
                    out.append(Challenge("default", unacknowledged, source, rescue))

        # ⊥ rules of the regime, anchored on one of the position's own triples.
        for rule in base.regime.rules:
            if not isinstance(rule, Rule) or rule.conclusion is not None or rule.guard:
                continue
            for i, premise in enumerate(rule.premises):
                for tr in own_triples:
                    b = _unify(premise, tr)
                    if b is None:
                        continue
                    rest_p = [_apply(p, b) for j, p in enumerate(rule.premises) if j != i]
                    ground = [p for p in rest_p if not any(isinstance(x, Var) for x in p)]
                    open_ = [p for p in rest_p if any(isinstance(x, Var) for x in p)]
                    asks: list[str] = [str(TripleAtom(*p)) for p in ground  # type: ignore[misc]
                                       if not in_cl(str(TripleAtom(*p)))]  # type: ignore[misc]
                    if open_:
                        with_blanks: list[Triple] = [
                            tuple(BNode(x.name) if isinstance(x, Var) else x for x in p)  # type: ignore[misc]
                            for p in open_
                        ]
                        asks.append(str(PatternAtom(with_blanks)))
                    if not asks:
                        continue  # fully satisfied: ⊥ already, reported as the refutation
                    out.append(Challenge("incoherence", tuple(asks), str(rule)))

        # Pattern entries, anchored on the position's own triples.
        if base.pattern_rules:
            from pynmms.rdf.defeasible import Matcher, apply, as_atom

            matcher = Matcher(base.pattern_rules, base._lookup(derived, True, hidden))
            for rule in base.pattern_rules:
                for b0 in matcher.anchored(rule, own_triples):
                    complete = [b for b in matcher.complete(rule, b0)]
                    if complete:
                        for b in complete:
                            if matcher.defeated(rule, b) is not None:
                                continue
                            if rule.is_incompatibility:
                                if v.value:
                                    out.append(Challenge("refutation", (), f"{rule}",
                                                         matcher.rescue(rule, b)))
                            else:
                                concl = apply(rule.conclusion, b)  # type: ignore[arg-type]
                                atom = as_atom(concl)
                                if not in_cl(atom):
                                    out.append(Challenge("default", (atom,), f"{rule}",
                                                         matcher.rescue(rule, b)))
                    elif rule.is_incompatibility:
                        missing = tuple(matcher.missing(rule, b0))
                        if missing and matcher.defeated(rule, b0) is None:
                            out.append(Challenge("incompatibility", missing, f"{rule}",
                                                 matcher.rescue(rule, b0)))

        order = {"refutation": 0, "incompatibility": 1, "incoherence": 1, "default": 2}
        seen: set[tuple[str, tuple[str, ...], str]] = set()
        unique: list[Challenge] = []
        for c in sorted(out, key=lambda c: (order[c.kind], len(c.asks))):
            key = (c.kind, c.asks, c.source)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def __repr__(self) -> str:
        who = f"{self.holder!r}, " if self.holder else ""
        return (f"Position({who}{len(self._accepted)} accepted, {len(self._rejected)} rejected, "
                f"{len(self.log)} moves)")

