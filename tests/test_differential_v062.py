"""Differential test: the rewritten reasoner against a frozen copy of v0.6.2.

v0.6.2 is the last release before the Phase 1 rewrite (parsed sentences,
diff-based atom sets, structural memo keys) and the Phase 2 base changes
(indexed exact matching, robustness policies, schema index). With every
entry EXACT, the two must agree on every sequent. Random bases and sequents
are drawn with Hypothesis so that the atom-set equality, the memo cache, and
the index paths are exercised far beyond the hand-written suite.

The legacy modules live under ``tests/legacy_v062`` so the test needs no git
history (CI checkouts are shallow).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from legacy_v062.base import MaterialBase as OldBase  # noqa: E402
from legacy_v062.onto_base import OntoMaterialBase as OldOnto  # noqa: E402
from legacy_v062.reasoner import NMMSReasoner as OldReasoner  # noqa: E402

from pynmms import MaterialBase, NMMSReasoner  # noqa: E402
from pynmms.onto.base import OntoMaterialBase  # noqa: E402

F = frozenset
ATOMS = ["a", "b", "c", "d", "e"]

atom = st.sampled_from(ATOMS)
atom_set = st.frozensets(atom, max_size=3)


@st.composite
def sentences(draw, depth: int = 0):
    if depth >= 2 or draw(st.booleans()):
        return draw(atom)
    kind = draw(st.sampled_from(["~", "&", "|", "->"]))
    if kind == "~":
        return f"~{draw(sentences(depth + 1))}"
    left, right = draw(sentences(depth + 1)), draw(sentences(depth + 1))
    return f"({left} {kind} {right})"


@st.composite
def bases(draw):
    consequences = set()
    for _ in range(draw(st.integers(0, 5))):
        consequences.add((draw(atom_set), draw(atom_set)))
    return consequences


@st.composite
def sequents(draw):
    gamma = draw(st.frozensets(sentences(), max_size=3))
    delta = draw(st.frozensets(sentences(), max_size=2))
    return gamma, delta


@settings(max_examples=300, deadline=None)
@given(bases(), sequents())
def test_propositional_agrees_with_v062(consequences, sequent):
    gamma, delta = sequent
    old = OldReasoner(OldBase(language=set(ATOMS), consequences=set(consequences)),
                      max_depth=50)
    new = NMMSReasoner(MaterialBase(language=set(ATOMS), consequences=set(consequences)))
    expected = old.derives(gamma, delta)
    actual = new.derives(gamma, delta)
    assert not expected.derivable or expected.depth_reached < 50
    assert actual.derivable == expected.derivable, (consequences, gamma, delta)
    assert not actual.depth_limited


# --- ontology layer: every schema EXACT, as in v0.6.2 ---

CONCEPTS = ["Man", "Mortal", "Bird", "Flies"]
ROLES = ["hasChild", "knows"]
INDS = ["x", "y"]


@st.composite
def onto_atoms(draw):
    if draw(st.booleans()):
        return f"{draw(st.sampled_from(CONCEPTS))}({draw(st.sampled_from(INDS))})"
    r, i, j = (draw(st.sampled_from(ROLES)), draw(st.sampled_from(INDS)),
               draw(st.sampled_from(INDS)))
    return f"{r}({i},{j})"


@st.composite
def onto_sentences(draw, depth: int = 0):
    if depth >= 2 or draw(st.booleans()):
        return draw(onto_atoms())
    kind = draw(st.sampled_from(["~", "&", "|", "->"]))
    if kind == "~":
        return f"~{draw(onto_sentences(depth + 1))}"
    return f"({draw(onto_sentences(depth + 1))} {kind} {draw(onto_sentences(depth + 1))})"


@st.composite
def schema_sets(draw):
    out = []
    for _ in range(draw(st.integers(0, 4))):
        kind = draw(st.sampled_from(
            ["subClassOf", "range", "domain", "subPropertyOf", "disjointWith",
             "disjointProperties", "jointCommitment"]))
        c1, c2 = draw(st.sampled_from(CONCEPTS)), draw(st.sampled_from(CONCEPTS))
        r1, r2 = draw(st.sampled_from(ROLES)), draw(st.sampled_from(ROLES))
        if kind in ("subClassOf", "disjointWith"):
            out.append((kind, c1, c2))
        elif kind in ("range", "domain"):
            out.append((kind, r1, c1))
        elif kind in ("subPropertyOf", "disjointProperties"):
            out.append((kind, r1, r2))
        else:
            out.append((kind, f"{c1},{c2}" if c1 != c2 else f"{c1},Bird", draw(
                st.sampled_from(CONCEPTS))))
    return out


def _register(base, schemas):
    for kind, a1, a2 in schemas:
        {
            "subClassOf": base.register_subclass,
            "range": base.register_range,
            "domain": base.register_domain,
            "subPropertyOf": base.register_subproperty,
            "disjointWith": base.register_disjoint,
            "disjointProperties": base.register_disjoint_properties,
        }.get(kind, lambda x, y: base.register_joint_commitment(x.split(","), y))(a1, a2)


@settings(max_examples=300, deadline=None)
@given(schema_sets(), st.frozensets(onto_atoms(), max_size=2),
       st.frozensets(onto_sentences(), max_size=3), st.frozensets(onto_sentences(), max_size=2))
def test_onto_exact_agrees_with_v062(schemas, ground, gamma, delta):
    old_base, new_base = OldOnto(), OntoMaterialBase()
    _register(old_base, schemas)
    _register(new_base, schemas)
    if ground:
        g = frozenset(sorted(ground)[:1])
        d = frozenset(sorted(ground)[1:]) or F({"Mortal(x)"})
        old_base.add_consequence(g, d)
        new_base.add_consequence(g, d)
    expected = OldReasoner(old_base, max_depth=50).derives(gamma, delta)
    actual = NMMSReasoner(new_base).derives(gamma, delta)
    assert actual.derivable == expected.derivable, (schemas, ground, gamma, delta)
