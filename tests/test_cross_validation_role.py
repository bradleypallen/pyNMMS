"""
Cross-validation test: pyNMMS against ROLE.jl ground truth.

The ground truth is loaded from role_ground_truth.json, generated
once by running cross_validate_role.jl with Kris Brown's ROLE.jl (https://github.com/kris-brown/ROLE).

The two implementations use fundamentally different algorithms:
  - ROLE.jl: exhaustive semantic enumeration (4^n implication frames)
  - pyNMMS: backward-chaining proof search (goal-directed)

Agreement across all sequents provides strong evidence that both
implementations correctly realize the NMMS sequent calculus.

To regenerate the fixture:
  1. julia --project=. cross_validate_role.jl
  2. Place role_ground_truth.json alongside this file
  3. pytest test_cross_validation_role.py -v

Source: Hlobil & Brandom (2025), Ch. 3; Brown, ROLE.jl
"""

import json
import os

import pytest

from pynmms import MaterialBase, NMMSReasoner

# ============================================================
# Fragment definitions
# ============================================================

FRAGMENTS = {
    "fragment_1": {
        "name": "Individuation chain",
        "bearers": ["p2", "p18", "p23"],
        "consequences": [
            (["p2"], ["p18"]),
            (["p18"], ["p23"]),
        ],
    },
    "fragment_2": {
        "name": "Delegation fork",
        "bearers": ["p9", "p25", "p26"],
        "consequences": [
            (["p9"], ["p25"]),
            (["p9"], ["p26"]),
        ],
    },
    "fragment_3": {
        "name": "Chain + fork combined",
        "bearers": ["p2", "p18", "p23", "p9", "p25", "p26"],
        "consequences": [
            (["p2"], ["p18"]),
            (["p18"], ["p23"]),
            (["p9"], ["p25"]),
            (["p9"], ["p26"]),
        ],
    },

}

# ============================================================
# Load ground truth
# ============================================================

GROUND_TRUTH_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "role_ground_truth.json",
)


def _load_ground_truth():
    """Load ROLE.jl ground truth from JSON, converting to (ant, con) -> bool."""
    with open(GROUND_TRUTH_PATH) as f:
        raw = json.load(f)

    truth = {}
    for frag_id, sequents in raw.items():
        frag_truth = {}
        for key, derivable in sequents.items():
            ant, con = key.split("|")
            frag_truth[(ant, con)] = derivable
        truth[frag_id] = frag_truth
    return truth


# Skip all tests if ground truth file doesn't exist
pytestmark = pytest.mark.skipif(
    not os.path.exists(GROUND_TRUTH_PATH),
    reason=f"ROLE ground truth not found at {GROUND_TRUTH_PATH}. "
           f"Run cross_validate_role.jl to generate it.",
)

# Load once at module level (only if file exists)
ROLE_GROUND_TRUTH = _load_ground_truth() if os.path.exists(GROUND_TRUTH_PATH) else {}


# ============================================================
# Test helpers
# ============================================================

def make_base(frag_id):
    """Build a MaterialBase from a fragment definition."""
    frag = FRAGMENTS[frag_id]
    return MaterialBase(
        language=set(frag["bearers"]),
        consequences={
            (frozenset(ant), frozenset(con))
            for ant, con in frag["consequences"]
        },
    )


# ============================================================
# Parametrized tests
# ============================================================

def _generate_test_cases():
    """Yield (frag_id, ant, con, expected) for all ground truth entries."""
    for frag_id, sequents in ROLE_GROUND_TRUTH.items():
        for (ant, con), expected in sequents.items():
            yield frag_id, ant, con, expected


ALL_CASES = list(_generate_test_cases())


@pytest.mark.parametrize(
    "frag_id, ant, con, expected",
    ALL_CASES,
    ids=[f"{frag}:{ant}=>{con}" for frag, ant, con, _ in ALL_CASES],
)
def test_cross_validation(frag_id, ant, con, expected):
    """pyNMMS agrees with ROLE.jl on every single-bearer sequent."""
    base = make_base(frag_id)
    r = NMMSReasoner(base, max_depth=15)
    result = r.query(frozenset({ant}), frozenset({con}))

    assert result == expected, (
        f"[{frag_id}] {ant} => {con}: "
        f"pyNMMS says {result}, ROLE.jl says {expected}"
    )


# ============================================================
# Structural tests
# ============================================================

def test_all_fragments_present():
    """Ground truth covers all three fragments."""
    for frag_id in FRAGMENTS:
        assert frag_id in ROLE_GROUND_TRUTH, f"Missing fragment: {frag_id}"


def test_sequent_counts():
    """Each fragment has n² sequents."""
    for frag_id, frag in FRAGMENTS.items():
        if frag_id in ROLE_GROUND_TRUTH:
            n = len(frag["bearers"])
            assert len(ROLE_GROUND_TRUTH[frag_id]) == n * n, (
                f"{frag_id}: expected {n*n} sequents, "
                f"got {len(ROLE_GROUND_TRUTH[frag_id])}"
            )


def test_no_cross_chain_leakage():
    """Fragment 3: no derivability between individuation and delegation chains."""
    if "fragment_3" not in ROLE_GROUND_TRUTH:
        pytest.skip("Fragment 3 not in ground truth")

    chain_bearers = {"p2", "p18", "p23"}
    fork_bearers = {"p9", "p25", "p26"}
    truth = ROLE_GROUND_TRUTH["fragment_3"]

    for ant in chain_bearers:
        for con in fork_bearers:
            assert truth[(ant, con)] is False, f"Cross-chain: {ant} => {con}"
    for ant in fork_bearers:
        for con in chain_bearers:
            assert truth[(ant, con)] is False, f"Cross-chain: {ant} => {con}"


def test_nontransitivity_in_ground_truth():
    """The individuation chain doesn't compose in ROLE.jl either."""
    if "fragment_1" not in ROLE_GROUND_TRUTH:
        pytest.skip("Fragment 1 not in ground truth")

    truth = ROLE_GROUND_TRUTH["fragment_1"]
    assert truth[("p2", "p18")] is True
    assert truth[("p18", "p23")] is True
    assert truth[("p2", "p23")] is False


def test_delegation_fork_asymmetry():
    """p9 implies p25 and p26, but neither implies the other or p9."""
    if "fragment_2" not in ROLE_GROUND_TRUTH:
        pytest.skip("Fragment 2 not in ground truth")

    truth = ROLE_GROUND_TRUTH["fragment_2"]
    assert truth[("p9", "p25")] is True
    assert truth[("p9", "p26")] is True
    assert truth[("p25", "p26")] is False
    assert truth[("p26", "p25")] is False
    assert truth[("p25", "p9")] is False
    assert truth[("p26", "p9")] is False
