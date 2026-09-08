"""The Elenchus loop over a knowledge graph (PLAN.md step 6).

Allen's Elenchus protocol (AIAA4KE 2026) keeps a *dialectical state*
``<[C : D], T, I>``: a position of commitments ``C`` and denials ``D``, the
open *tensions* ``T``, sequents ``Γ |~ Δ`` with ``Γ ⊆ C`` and ``Δ ⊆ D`` that
the opponent claims incoherent, and the *material implications* ``I`` from
tensions the respondent accepted. The respondent proposes a positum and
resolves tensions as they arise, by retracting a commitment or denial, by
refining one, or by contesting the claim; the opponent detects tensions,
keeps the record, and probes.

Here the position is a :class:`~pynmms.rdf.position.Position` over a
store as background, and the opponent is *computed* from the regime, the
material entries, and the position's denials, so every tension it raises
is one the base licenses and its refutations are exact. That inverts the
paper's oracle: accepting a computed tension endorses what the base
already says, and *contesting* one is the move that revises the base, a
proposed exception to the responsible entry. A tension may also be
proposed from outside (:meth:`Dialogue.propose_tension`), an LLM oracle
or a colleague; accepting it adds the sequent to the base as a material
implication, contesting it drops it.

A positum cannot be withdrawn. The dialogue is in *aporia* when the
position is out of bounds and no open tension can be resolved: every
tension's own atoms lie in the positum and none has a rescue left.
State persists as JSON (:meth:`Dialogue.save`); commitments that held are
written to the store by :meth:`Dialogue.commit_to_store`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pynmms.rdf.atoms import TripleAtom
from pynmms.rdf.position import Challenge, Ground, Position
from pynmms.robustness import Robustness

if TYPE_CHECKING:
    from pynmms.rdf.base import RegimeBase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tension:
    """A sequent ``Γ |~ Δ`` over the position's own atoms the opponent claims incoherent."""

    gamma: tuple[str, ...]
    delta: tuple[str, ...]
    source: str
    rescue: tuple[str, ...] = ()
    kind: str = "computed"  # computed | external

    @property
    def id(self) -> str:
        key = "|".join(sorted(self.gamma)) + " |~ " + "|".join(sorted(self.delta))
        return hashlib.sha1(key.encode()).hexdigest()[:8]

    def sequent(self) -> str:
        return f"{', '.join(sorted(self.gamma))} |~ {', '.join(sorted(self.delta))}".rstrip()


@dataclass(frozen=True)
class Proposal:
    """A contestation's proposed exception to the responsible entry."""

    tension: Tension
    exception: tuple[str, ...]
    applied: bool


@dataclass(frozen=True)
class Turn:
    """One move of the dialogue and what the opponent found afterwards."""

    n: int
    actor: str
    move: str
    args: tuple[str, ...]
    tensions: tuple[Tension, ...] = ()
    probes: tuple[Challenge, ...] = ()
    status: str = ""
    ms: float = 0.0


@dataclass(frozen=True)
class Outcome:
    """The result of :meth:`Dialogue.play`: predictions checked against answers."""

    answers: tuple[tuple[str, Any, Any, bool | None], ...]

    @property
    def predicted(self) -> str:
        checked = [a for a in self.answers if a[3] is not None]
        return f"{sum(1 for a in checked if a[3])}/{len(checked)}"

    @property
    def failures(self) -> list[tuple[str, Any, Any, bool | None]]:
        return [a for a in self.answers if a[3] is False]


class ComputedOpponent:
    """Tensions and probes read off the base: exact, never spurious."""

    def tensions(self, d: Dialogue) -> list[Tension]:
        pos = d.position
        base = d.base
        accepted = pos.accepted
        out: list[Tension] = []
        # Denials the commitments entail: Γ = C, Δ = the denied graph.
        for r in pos.rejected:
            if pos._ask(pos.sequent(consequent=[r])).value:
                why = base.last_reason or "entailed"
                out.append(Tension(tuple(sorted(accepted)), (r,), why, tuple(base.last_rescue)))
        # Incoherence of the commitments themselves: which own atoms take part.
        verdict = pos._ask(pos.sequent())
        if verdict.value:
            gamma = self._participants(d, verdict.reason or "")
            out.append(Tension(tuple(sorted(gamma)), (), verdict.reason or "⊥",
                               tuple(verdict.rescue)))
        return out

    def _participants(self, d: Dialogue, reason: str) -> set[str]:
        """The position's own atoms that take part in the refutation.

        Those the refuting entry or instance names, and those whose withdrawal
        alone restores coherence (the atom a derived premise came from). Human
        scale keeps this at one coherence check per own atom.
        """
        pos = d.position
        own = set(pos.accepted)
        parts = {a for a in own if a in reason}
        grounds = pos.grounds()
        for a in sorted(own - parts):
            trial = Position(d.base, holder=pos.holder)
            for b in own - {a}:
                trial.assert_(b, ground=grounds.get(b))
            for g in pos._rejected_graphs:
                trial.deny(g)
            if trial.coherent():
                parts.add(a)
        return parts or own

    def probes(self, d: Dialogue) -> list[Challenge]:
        return [c for c in d.position.challenges() if c.kind != "refutation"]


class Dialogue:
    """The dialectical state and the moves of the Elenchus loop."""

    def __init__(self, base: RegimeBase, *, holder: str = "", positum: Iterable[Any] = (),
                 opponent: Any = None) -> None:
        self.base = base
        self.position = Position(base, holder=holder)
        self.opponent = opponent or ComputedOpponent()
        self.open: dict[str, Tension] = {}
        self.accepted: list[Tension] = []
        self.contested: list[Tension] = []
        self.proposals: list[Proposal] = []
        self.transcript: list[Turn] = []
        self.positum: frozenset[str] = frozenset()
        atoms = [self._atom(x) for x in positum]
        if atoms:
            self.positum = frozenset(atoms)
            self.commit(*atoms)

    # --- helpers ---

    def _atom(self, x: Any) -> str:
        t = TripleAtom.coerce(x, self.base.resolver)
        if t is None:
            raise ValueError(f"{x!r} is not a triple atom")
        return str(t)

    def _after(self, actor: str, move: str, args: tuple[str, ...], t0: float) -> Turn:
        found = self.opponent.tensions(self)
        new: list[Tension] = []
        contested = {t.id for t in self.contested}
        for t in found:
            if t.id in self.open or t.id in contested:
                continue
            self.open[t.id] = t
            new.append(t)
        # Tensions that no longer hold have been dissolved by the move.
        current = {t.id for t in found}
        for tid in list(self.open):
            if tid not in current and self.open[tid].kind == "computed":
                del self.open[tid]
        probes = tuple(self.opponent.probes(self))
        turn = Turn(len(self.transcript) + 1, actor, move, args, tuple(new), probes,
                    self.status(), (time.perf_counter() - t0) * 1000)
        self.transcript.append(turn)
        return turn

    # --- the respondent's moves ---

    def commit(self, *atoms: Any) -> Turn:
        t0 = time.perf_counter()
        names = tuple(self._atom(a) for a in atoms)
        self.position.assert_(*names)
        return self._after("respondent", "commit", names, t0)

    def deny(self, graph: Any) -> Turn:
        t0 = time.perf_counter()
        before = set(self.position.rejected)
        self.position.deny(graph)
        added = tuple(sorted(set(self.position.rejected) - before))
        return self._after("respondent", "deny", added, t0)

    def withdraw(self, *atoms: Any) -> Turn:
        t0 = time.perf_counter()
        names = tuple(self._atom(a) for a in atoms)
        kept = [a for a in names if a in self.positum]
        if kept:
            raise ValueError(f"the positum cannot be withdrawn: {kept}")
        self.position.withdraw(*names)
        return self._after("respondent", "withdraw", names, t0)

    def propose_tension(self, gamma: Iterable[Any], delta: Iterable[Any], *,
                        source: str = "external") -> Tension:
        """An opponent outside the base (an oracle, a colleague) proposes a tension."""
        t = Tension(tuple(sorted(self._atom(a) for a in gamma)),
                    tuple(sorted(str(x) for x in delta)), source, (), "external")
        self.open[t.id] = t
        self.transcript.append(Turn(len(self.transcript) + 1, "opponent", "propose",
                                    (t.sequent(),), (t,), (), self.status()))
        return t

    def accept(self, tension_id: str, *, retract: Iterable[Any] = (),
               refine: tuple[Iterable[Any], Iterable[Any]] | None = None) -> Turn:
        """Endorse a tension: resolve it by retraction or refinement; it joins I.

        An external tension becomes a material implication of the base itself
        (an exact entry), so it is raised from the base from now on.
        """
        t0 = time.perf_counter()
        t = self.open.pop(tension_id, None)
        if t is None:
            raise ValueError(f"no open tension {tension_id}")
        moves: list[str] = []
        for a in retract:
            name = self._atom(a)
            if name in self.positum:
                raise ValueError(f"the positum cannot be retracted: {name}")
            if name in self.position.accepted:
                self.position.withdraw(name)
            elif name in self.position.rejected:
                self.position._rejected.remove(name)
            moves.append(f"-{name}")
        if refine is not None:
            old, new = refine
            self.position.withdraw(*[self._atom(a) for a in old])
            self.position.assert_(*[self._atom(a) for a in new])
            moves.append("refine")
        if t.kind == "external":
            self.base.add_consequence(frozenset(t.gamma), frozenset(t.delta))
        self.accepted.append(t)
        return self._after("respondent", "accept", (t.id, *moves), t0)

    def contest(self, tension_id: str, *, exception: Iterable[Any] = (),
                apply: bool = True) -> Turn:
        """Reject a tension. With *exception*, propose it as a defeater of the
        responsible entry, and apply it to a ground or pattern entry of the base."""
        t0 = time.perf_counter()
        t = self.open.pop(tension_id, None)
        if t is None:
            raise ValueError(f"no open tension {tension_id}")
        exc = tuple(self._atom(a) for a in exception)
        applied = False
        if exc and t.kind == "computed":
            applied = self._add_exception(t, exc) if apply else False
        self.contested.append(t)
        if exc or t.kind == "computed":
            self.proposals.append(Proposal(t, exc, applied))
        return self._after("respondent", "contest", (t.id, *exc), t0)

    def _add_exception(self, t: Tension, exc: tuple[str, ...]) -> bool:
        """Give the entry named in the tension's source the exception as a defeater."""
        base = self.base
        # Ground entries: the reason names them as "incompatibility A, B |~ ∅ [kind]".
        for gamma, delta in list(base.consequences):
            names = ", ".join(sorted(str(a) for a in gamma))
            if names and names in t.source:
                rob = base.robustness_of(gamma, delta)
                new = Robustness("guarded", rob.left | frozenset(exc), rob.right, rob.exclusions)
                base.add_consequence(gamma, delta, robustness=new)
                base.clear_caches()
                return True
        # Pattern entries: the reason names the rule text.
        from pynmms.rdf.defeasible import DefeasibleRule, Defeater

        for rule in base.pattern_rules:
            if str(rule) in t.source:
                patterns = tuple(TripleAtom.coerce(a).triple for a in exc)  # type: ignore[union-attr]
                revised = DefeasibleRule(rule.name, rule.premises, rule.conclusion,
                                         rule.defeaters + (Defeater(patterns),), "guarded",
                                         rule.guard_expr)
                base._pattern_rules[base._pattern_rules.index(rule)] = revised
                base.clear_caches()
                return True
        return False

    # --- the opponent's side and the scorekeeper ---

    def probes(self) -> list[Challenge]:
        return list(self.opponent.probes(self))

    def status(self) -> str:
        """``coherent``, ``tensions open``, or ``aporia``."""
        if not self.open:
            return "coherent" if self.position.coherent() else "tensions open"
        if self.position.coherent():
            return "tensions open"
        for t in self.open.values():
            if t.rescue:
                return "tensions open"
            if any(a not in self.positum for a in t.gamma) or t.delta:
                return "tensions open"
        return "aporia"

    def commit_to_store(self) -> int:
        """Write the commitments that held to the store (the holder's graph)."""
        return self.position.commit()

    # --- persistence ---

    def to_dict(self) -> dict[str, Any]:
        def tension(t: Tension) -> dict[str, Any]:
            return {"gamma": list(t.gamma), "delta": list(t.delta), "source": t.source,
                    "rescue": list(t.rescue), "kind": t.kind}

        return {
            "holder": self.position.holder,
            "positum": sorted(self.positum),
            "accepted_atoms": sorted(self.position.accepted),
            "grounds": {a: vars(g) for a, g in self.position.grounds().items()},
            "rejected": [[list(map(str, t)) for t in g] for g in self.position._rejected_graphs],
            "open": [tension(t) for t in self.open.values()],
            "accepted": [tension(t) for t in self.accepted],
            "contested": [tension(t) for t in self.contested],
            "proposals": [{"tension": tension(p.tension), "exception": list(p.exception),
                           "applied": p.applied} for p in self.proposals],
            "transcript": [{"n": x.n, "actor": x.actor, "move": x.move, "args": list(x.args),
                            "status": x.status, "ms": x.ms} for x in self.transcript],
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path, base: RegimeBase, *, opponent: Any = None) -> Dialogue:
        from rdflib import Literal, URIRef

        data = json.loads(Path(path).read_text())
        d = cls(base, holder=data["holder"], opponent=opponent)
        d.positum = frozenset(data["positum"])
        for a in data["accepted_atoms"]:
            g = data["grounds"].get(a)
            d.position.assert_(a, ground=Ground(**g) if g else None)

        def term(s: str) -> Any:
            return Literal(s) if not s.startswith(("http", "urn:", "_:")) else URIRef(s)

        for g in data["rejected"]:
            d.position.deny([tuple(term(x) for x in t) for t in g])

        def tension(x: dict[str, Any]) -> Tension:
            return Tension(tuple(x["gamma"]), tuple(x["delta"]), x["source"],
                           tuple(x["rescue"]), x["kind"])

        d.open = {tension(x).id: tension(x) for x in data["open"]}
        d.accepted = [tension(x) for x in data["accepted"]]
        d.contested = [tension(x) for x in data["contested"]]
        d.proposals = [Proposal(tension(p["tension"]), tuple(p["exception"]), p["applied"])
                       for p in data["proposals"]]
        d.transcript = [Turn(x["n"], x["actor"], x["move"], tuple(x["args"]), (), (),
                             x["status"], x["ms"]) for x in data["transcript"]]
        return d

    # --- a scripted respondent ---

    def play(self, script: str) -> Outcome:
        """Run a move script with predictions: one move per line, ``#`` comments.

        Moves: ``commit <atoms>``, ``deny <atoms>``, ``withdraw <atoms>``,
        ``accept N [retract <atoms> | refine <old> => <new>]``, ``contest N
        [unless <atoms>]`` (``N`` the 1-based index into the open tensions in
        the order raised), ``propose <atoms> |~ <atoms>``; questions
        ``status? ## coherent``, ``tensions? ## 1``, ``probes? ## 2``.
        """
        from pynmms.syntax import split_top_level

        answers: list[tuple[str, Any, Any, bool | None]] = []

        def atoms(text: str) -> list[str]:
            return [x.strip() for x in split_top_level(text, ",") if x.strip()]

        for raw in script.splitlines():
            line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
            if not line:
                continue
            expect = raw.split("##", 1)[1].strip() if "##" in raw else None
            kind, _, rest = line.partition(" ")
            rest = rest.strip()
            answer: Any = None
            if kind == "commit":
                self.commit(*atoms(rest))
            elif kind == "deny":
                self.deny([TripleAtom.from_name(a, self.base.resolver).triple
                           for a in atoms(rest)])
            elif kind == "withdraw":
                self.withdraw(*atoms(rest))
            elif kind in ("accept", "contest"):
                idx, _, how = rest.partition(" ")
                tid = list(self.open)[int(idx) - 1]
                if kind == "accept":
                    if how.startswith("retract "):
                        self.accept(tid, retract=atoms(how[8:]))
                    elif how.startswith("refine "):
                        old, new = how[7:].split("=>", 1)
                        self.accept(tid, refine=(atoms(old), atoms(new)))
                    else:
                        self.accept(tid)
                else:
                    exc = atoms(how[7:]) if how.startswith("unless ") else []
                    self.contest(tid, exception=exc)
            elif kind == "propose":
                left, _, right = rest.partition("|~")
                self.propose_tension(atoms(left), atoms(right), source="script")
            elif kind == "status?":
                answer = self.status()
            elif kind == "tensions?":
                answer = len(self.open)
            elif kind == "probes?":
                answer = len(self.probes())
            else:
                raise ValueError(f"unknown move {kind!r}")
            ok: bool | None = None
            if expect is not None and answer is not None:
                ok = str(answer) == expect
            answers.append((line, answer, expect, ok))
        return Outcome(tuple(answers))
