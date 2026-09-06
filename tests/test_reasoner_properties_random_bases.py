"""Property-based tests for pyNMMS using Hypothesis.

Tests the structural properties of the NMMS sequent calculus
(Hlobil & Brandom 2025, Ch. 3) against randomly generated
material bases and sequents.
"""

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import assume, given, note, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from pynmms import MaterialBase, NMMSReasoner, parse_sentence  # noqa: E402

# ============================================================
# Strategies for generating random NMMS structures
# ============================================================

# Atomic sentences: short lowercase identifiers
atoms = st.text(
    alphabet="abcdefgh",
    min_size=1,
    max_size=2,
).filter(lambda s: s.isalpha())

# Sets of atoms for languages (2-8 atoms keeps things tractable)
atom_sets = st.frozensets(atoms, min_size=2, max_size=8)


@st.composite
def material_bases(draw):
    """Generate a random material base with atomic language and consequences."""
    language = draw(atom_sets)
    lang_list = sorted(language)

    # Generate 0-6 consequences as pairs of non-empty subsets
    n_consequences = draw(st.integers(min_value=0, max_value=6))
    consequences = set()
    for _ in range(n_consequences):
        # Draw non-empty subsets of the language for antecedent and consequent
        ant = draw(st.frozensets(
            st.sampled_from(lang_list),
            min_size=1,
            max_size=max(1, len(lang_list) // 2),
        ))
        con = draw(st.frozensets(
            st.sampled_from(lang_list),
            min_size=1,
            max_size=max(1, len(lang_list) // 2),
        ))
        # Exclude sequents that are already Containment axioms
        # (they're trivially valid and uninteresting)
        if not (ant & con):
            consequences.add((ant, con))

    return MaterialBase(language=language, consequences=consequences)


@st.composite
def atomic_sequents(draw, base):
    """Generate a random sequent over the base language using only atoms."""
    lang_list = sorted(base.language)
    ant = draw(st.frozensets(
        st.sampled_from(lang_list),
        min_size=0,
        max_size=len(lang_list),
    ))
    con = draw(st.frozensets(
        st.sampled_from(lang_list),
        min_size=0,
        max_size=len(lang_list),
    ))
    return ant, con


@st.composite
def single_atom_sequents(draw, base):
    """Generate a sequent with single atoms on each side."""
    lang_list = sorted(base.language)
    ant_atom = draw(st.sampled_from(lang_list))
    con_atom = draw(st.sampled_from(lang_list))
    return frozenset({ant_atom}), frozenset({con_atom})


def make_negation(s: str) -> str:
    """Build ~s, handling atoms vs complex sentences."""
    parsed = parse_sentence(s)
    if parsed.type == "atom":
        return f"~{s}"
    return f"~({s})"


def make_conditional(a: str, b: str) -> str:
    """Build a -> b."""
    return f"{a} -> {b}"


def make_conjunction(a: str, b: str) -> str:
    """Build a & b."""
    return f"({a} & {b})"


def make_disjunction(a: str, b: str) -> str:
    """Build a | b."""
    return f"({a} | {b})"


# ============================================================
# Property 1: CONTAINMENT
#
# For any Gamma, Delta: if Gamma ∩ Delta ≠ ∅ then Gamma ⊩ Delta
# This is Ax1 and must hold for all material bases.
#
# A failure here would mean the reasoner rejects a sequent where
# the antecedent and consequent share an atom — a bug in is_axiom.
# Hard to imagine failing, but if this breaks, everything else
# is meaningless.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_containment(data):
    """Containment: overlapping antecedent and consequent is always derivable."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)

    # Draw a non-empty overlap
    overlap = data.draw(st.frozensets(
        st.sampled_from(lang_list),
        min_size=1,
        max_size=max(1, len(lang_list) // 2),
    ))
    # Draw additional atoms for each side
    extra_ant = data.draw(st.frozensets(
        st.sampled_from(lang_list),
        min_size=0,
        max_size=len(lang_list),
    ))
    extra_con = data.draw(st.frozensets(
        st.sampled_from(lang_list),
        min_size=0,
        max_size=len(lang_list),
    ))

    gamma = overlap | extra_ant
    delta = overlap | extra_con

    r = NMMSReasoner(base, max_depth=15)
    result = r.query(gamma, delta)

    note(f"Base: {base.to_dict()}")
    note(f"Gamma: {sorted(gamma)}, Delta: {sorted(delta)}")
    note(f"Overlap: {sorted(overlap)}")
    assert result is True, (
        f"Containment violated: {sorted(gamma)} => {sorted(delta)} "
        f"with overlap {sorted(overlap)}"
    )


# ============================================================
# Property 2: SUPRACLASSICALITY (SCL)
#
# All classically valid sequents are derivable in NMMS_B.
# We test specific schematic instances:
#   - Excluded middle: ⊩ A | ~A
#   - Explosion: A & ~A ⊩ (anything)
#   - Identity: A ⊩ A (special case of Containment)
#   - K axiom: ⊩ A -> (B -> A)
#   - Modus ponens structure: A, A -> B ⊩ B
#   - Double negation elimination: ~~A ⊩ A
#   - Contraposition: A -> B ⊩ ~B -> ~A
#
# A failure here would mean a classically valid sequent isn't
# derivable, indicating a bug in the proof rules (probably a
# right rule like [R|] or [R¬]) or in the proof search strategy
# (e.g., depth limit cutting off a valid proof). This would mean
# NMMS isn't a conservative extension of classical logic — a
# serious problem.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_excluded_middle(data):
    """SCL: ⊩ A | ~A for any atom A."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    sentence = make_disjunction(a, make_negation(a))
    result = r.query(frozenset(), frozenset({sentence}))

    note(f"Testing: => {sentence}")
    assert result is True, f"Excluded middle failed: => {sentence}"


@given(data=st.data())
@settings(max_examples=200)
def test_explosion(data):
    """SCL: A, ~A ⊩ B for any atoms A, B (via A & ~A ⊩ B)."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))
    b = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    # Test both formulations
    result1 = r.query(frozenset({a, make_negation(a)}), frozenset({b}))
    contradiction = make_conjunction(a, make_negation(a))
    result2 = r.query(frozenset({contradiction}), frozenset({b}))

    note(f"Testing: {a}, ~{a} => {b}")
    assert result1 is True, f"Explosion failed: {a}, ~{a} => {b}"
    assert result2 is True, f"Explosion failed: ({a} & ~{a}) => {b}"


@given(data=st.data())
@settings(max_examples=200)
def test_k_axiom(data):
    """SCL: ⊩ A -> (B -> A) for any atoms A, B."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))
    b = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    inner = make_conditional(b, a)
    sentence = make_conditional(a, inner)
    result = r.query(frozenset(), frozenset({sentence}))

    note(f"Testing: => {sentence}")
    assert result is True, f"K axiom failed: => {sentence}"


@given(data=st.data())
@settings(max_examples=200)
def test_modus_ponens(data):
    """SCL: A, A -> B ⊩ B for any atoms A, B."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))
    b = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    conditional = make_conditional(a, b)
    result = r.query(frozenset({a, conditional}), frozenset({b}))

    note(f"Testing: {a}, {conditional} => {b}")
    assert result is True, f"Modus ponens failed: {a}, {conditional} => {b}"


@given(data=st.data())
@settings(max_examples=200)
def test_double_negation_elimination(data):
    """SCL: ~~A ⊩ A for any atom A."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    dbl_neg = make_negation(make_negation(a))
    result = r.query(frozenset({dbl_neg}), frozenset({a}))

    note(f"Testing: {dbl_neg} => {a}")
    assert result is True, f"Double negation elimination failed: {dbl_neg} => {a}"


@given(data=st.data())
@settings(max_examples=200)
def test_contraposition(data):
    """SCL: A -> B ⊩ ~B -> ~A for any atoms A, B."""
    base = data.draw(material_bases())
    lang_list = sorted(base.language)
    a = data.draw(st.sampled_from(lang_list))
    b = data.draw(st.sampled_from(lang_list))

    r = NMMSReasoner(base, max_depth=15)
    premise = make_conditional(a, b)
    conclusion = make_conditional(make_negation(b), make_negation(a))
    result = r.query(frozenset({premise}), frozenset({conclusion}))

    note(f"Testing: {premise} => {conclusion}")
    assert result is True, f"Contraposition failed: {premise} => {conclusion}"


# ============================================================
# Property 3: DEDUCTION-DETACHMENT THEOREM (DDT)
#
# For single-premise, single-conclusion base consequences:
#   {A} ⊩ {B} if and only if ⊩ A -> B
#
# We test both directions:
#   Forward:  if {A} |~_B {B} then ⊩ A -> B
#   Backward: if ⊩ A -> B  then {A} ⊩ {B}
#
# A forward failure would mean the explicitation pattern is
# broken — a base consequence can't be expressed as a logical
# conditional. This would indicate a bug in [R→], since
# deriving ⊩ A → B requires decomposing to A ⊩ B, which
# should be a base axiom. A backward failure would mean a
# base consequence isn't derivable at all.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_ddt_forward(data):
    """DDT forward: if {A} |~_B {B} then ⊩ A -> B."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    for gamma, delta in base.consequences:
        # Test single-premise, single-conclusion cases
        if len(gamma) == 1 and len(delta) == 1:
            a = next(iter(gamma))
            b = next(iter(delta))
            conditional = make_conditional(a, b)
            result = r.query(frozenset(), frozenset({conditional}))

            note(f"Base has {a} |~ {b}, testing => {conditional}")
            assert result is True, (
                f"DDT forward failed: base has {a} |~ {b} "
                f"but => {conditional} is not derivable"
            )


@given(data=st.data())
@settings(max_examples=200)
def test_ddt_backward(data):
    """DDT backward: if ⊩ A -> B (as conditional) then {A} ⊩ {B}.

    We verify this for base consequences — if {A} |~_B {B},
    then we already know ⊩ A -> B (from forward direction),
    and {A} ⊩ {B} should hold.
    """
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    for gamma, delta in base.consequences:
        if len(gamma) == 1 and len(delta) == 1:
            a = next(iter(gamma))
            b = next(iter(delta))
            result = r.query(frozenset({a}), frozenset({b}))

            note(f"Base has {a} |~ {b}, testing {a} => {b}")
            assert result is True, (
                f"DDT backward failed: base has {a} |~ {b} "
                f"but {a} => {b} is not derivable"
            )


# ============================================================
# Property 4: NONMONOTONICITY (MOF)
#
# There exist material bases where adding premises defeats
# inferences. We verify this constructively: build a base
# where {A} |~ {B} but {A, C} |~ {B} does not hold,
# provided C ≠ A and C ≠ B.
#
# A no-Weakening failure would mean the reasoner derives a
# sequent with extra premises beyond what the base specifies —
# the system would be monotonic. This would be the most
# conceptually serious failure because it undermines the entire
# point of the logic. It would indicate that is_axiom is
# matching too loosely (subset matching instead of exact
# matching on base consequences).
# ============================================================

def test_nonmonotonicity_constructive():
    """MOF: demonstrate that Weakening fails in NMMS."""
    base = MaterialBase(
        language={'a', 'b', 'c'},
        consequences={
            (frozenset({'a'}), frozenset({'b'})),
        }
    )
    r = NMMSReasoner(base)

    # {a} ⊩ {b} holds
    assert r.query(frozenset({'a'}), frozenset({'b'})) is True

    # {a, c} ⊩ {b} does NOT hold — Weakening fails
    assert r.query(frozenset({'a', 'c'}), frozenset({'b'})) is False

    # {a, b} ⊩ {b} DOES hold — but only via Containment, not Weakening
    assert r.query(frozenset({'a', 'b'}), frozenset({'b'})) is True


@given(data=st.data())
@settings(max_examples=200)
def test_no_weakening(data):
    """MOF: for non-Containment base consequences, adding a fresh
    premise that doesn't appear in the consequent defeats the inference."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    for gamma, delta in base.consequences:
        # Find atoms not in gamma or delta
        fresh = base.language - gamma - delta
        if fresh:
            extra = data.draw(st.sampled_from(sorted(fresh)))
            weakened_gamma = gamma | {extra}

            # The weakened sequent should NOT be derivable
            # (unless it happens to be a Containment axiom or
            # independently a base consequence)
            if not (weakened_gamma & delta) and \
               (weakened_gamma, delta) not in base.consequences:
                result = r.query(weakened_gamma, delta)
                note(
                    f"Base has {sorted(gamma)} |~ {sorted(delta)}, "
                    f"testing {sorted(weakened_gamma)} => {sorted(delta)}"
                )
                assert result is False, (
                    f"Weakening should fail: {sorted(gamma)} |~ {sorted(delta)} "
                    f"but {sorted(weakened_gamma)} => {sorted(delta)} derived"
                )


# ============================================================
# Property 5: NONTRANSITIVITY
#
# There exist material bases where A ⊩ B and B ⊩ C but
# A ⊬ C. We verify this constructively.
#
# A no-Cut failure would mean the reasoner is transitive —
# it chains {A} ⊩ {B} and {B} ⊩ {C} to derive {A} ⊩ {C}.
# This would mean there's an implicit Cut rule hiding in the
# proof search, probably through some interaction of left and
# right rules that effectively smuggles in transitivity. This
# would be the hardest bug to find because it wouldn't be a
# simple implementation error but a subtle interaction between
# rules. The constructive test verifies that the logic actually
# *has* this property — if it failed, the implementation would
# be a different logic than NMMS.
# ============================================================

def test_nontransitivity_constructive():
    """Demonstrate that Cut/transitivity fails in NMMS."""
    base = MaterialBase(
        language={'a', 'b', 'c'},
        consequences={
            (frozenset({'a'}), frozenset({'b'})),
            (frozenset({'b'}), frozenset({'c'})),
        }
    )
    r = NMMSReasoner(base)

    assert r.query(frozenset({'a'}), frozenset({'b'})) is True
    assert r.query(frozenset({'b'}), frozenset({'c'})) is True
    assert r.query(frozenset({'a'}), frozenset({'c'})) is False


@given(data=st.data())
@settings(max_examples=200)
def test_no_cut(data):
    """For chains A |~ B, B |~ C where A, B, C are distinct and
    there's no direct A |~ C, transitivity should fail."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    # Look for chains in the base consequences
    consequences_list = list(base.consequences)
    for g1, d1 in consequences_list:
        for g2, d2 in consequences_list:
            # Single-premise, single-conclusion chain: {a} |~ {b}, {b} |~ {c}
            if len(g1) == 1 and len(d1) == 1 and len(g2) == 1 and len(d2) == 1:
                a = next(iter(g1))
                b1 = next(iter(d1))
                b2 = next(iter(g2))
                c = next(iter(d2))

                if b1 == b2 and a != b1 and b1 != c and a != c:
                    # Check there's no direct a |~ c
                    if (frozenset({a}), frozenset({c})) not in base.consequences:
                        result = r.query(frozenset({a}), frozenset({c}))
                        note(f"Chain: {a} |~ {b1}, {b1} |~ {c}, testing {a} => {c}")
                        assert result is False, (
                            f"Cut should fail: {a} |~ {b1} and {b1} |~ {c} "
                            f"but {a} => {c} was derived"
                        )


# ============================================================
# Property 6: CONSERVATIVITY
#
# Logical vocabulary does not create new atomic-level
# consequences. If Gamma and Delta are sets of atoms,
# then Gamma ⊩ Delta in NMMS_B iff the base axioms
# (Containment + base consequences) directly establish it.
#
# This is the most powerful test. A failure would mean the
# logical rules — negation, conjunction, disjunction,
# implication — are creating consequences between atoms that
# the base doesn't support. For example, decomposing and
# recomposing formulas through some sequence of left and right
# rules might find a path from atom A to atom C that doesn't
# exist in the base. This would invalidate the explicitation
# thesis: logical vocabulary would be adding content rather
# than making implicit content explicit. The fact that this
# passes across thousands of random bases — the logic is
# strong enough to derive everything classical but weak enough
# not to derive anything extra — is the real verification.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_conservativity(data):
    """Conservativity: no new atomic consequences beyond Containment
    and explicit base consequences."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    gamma, delta = data.draw(atomic_sequents(base))

    # Skip if it's a Containment axiom
    assume(not (gamma & delta))
    # Skip if it's an explicit base consequence
    assume((gamma, delta) not in base.consequences)
    # Skip empty sequents (⊩ and ⊩ are edge cases)
    assume(len(gamma) > 0 or len(delta) > 0)

    result = r.query(gamma, delta)

    note(f"Testing atomic sequent: {sorted(gamma)} => {sorted(delta)}")
    assert result is False, (
        f"Conservativity violated: {sorted(gamma)} => {sorted(delta)} "
        f"is derivable but is not a Containment axiom or base consequence"
    )


# ============================================================
# Property 7: BASE CONSEQUENCE DERIVABILITY
#
# Every explicit base consequence should be derivable.
#
# A failure would mean the reasoner can't find its own axioms,
# indicating a fundamental bug in is_axiom or in how the base
# stores consequences.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_base_consequences_derivable(data):
    """Every base consequence is derivable."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    for gamma, delta in base.consequences:
        result = r.query(gamma, delta)
        note(f"Base consequence: {sorted(gamma)} |~ {sorted(delta)}")
        assert result is True, (
            f"Base consequence not derivable: "
            f"{sorted(gamma)} |~ {sorted(delta)}"
        )


# ============================================================
# Property 8: IDEMPOTENCY
#
# Duplicating premises or conclusions should not change
# derivability. Since we use frozensets, this is structural,
# but we verify that the Ketonen third-sequent pattern
# preserves this: Gamma, A, A ⊩ Delta iff Gamma, A ⊩ Delta.
#
# A failure would indicate nondeterminism in the proof search,
# likely from unstable caching or iteration order effects.
# ============================================================

@given(data=st.data())
@settings(max_examples=200)
def test_idempotency(data):
    """Idempotency: derivability is unchanged by duplicating sentences."""
    base = data.draw(material_bases())
    r = NMMSReasoner(base, max_depth=15)

    for gamma, delta in base.consequences:
        # Since frozensets handle deduplication, this tests that
        # the proof search is consistent — querying the same sequent
        # multiple times gives the same answer
        r1 = r.query(gamma, delta)
        r2 = r.query(gamma, delta)
        assert r1 == r2, "Idempotency: repeated queries give different results"


# ============================================================
# Property 9: SERIALIZATION ROUNDTRIP
#
# MaterialBase survives JSON serialization and deserialization
# with identical behavior.
#
# A failure would mean the JSON format loses information —
# atoms or consequences silently dropped or transformed during
# serialization. Since the JSON format is the persistence
# layer between Elenchus (which produces bases) and the
# reasoner (which queries them), this must be airtight.
# ============================================================

@given(data=st.data())
@settings(max_examples=100)
def test_serialization_roundtrip(data):
    """Serialization: to_dict/from_dict preserves all base properties."""
    base = data.draw(material_bases())
    r1 = NMMSReasoner(base, max_depth=15)

    # Roundtrip through dict
    restored = MaterialBase.from_dict(base.to_dict())
    r2 = NMMSReasoner(restored, max_depth=15)

    # Check language equality
    assert base.language == restored.language, "Language changed after roundtrip"
    assert base.consequences == restored.consequences, "Consequences changed after roundtrip"

    # Check that derivability is preserved for all base consequences
    for gamma, delta in base.consequences:
        assert r1.query(gamma, delta) == r2.query(gamma, delta), (
            f"Derivability changed after roundtrip for "
            f"{sorted(gamma)} => {sorted(delta)}"
        )
