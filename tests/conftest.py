"""Shared fixtures for pyNMMS test suite."""

import pytest

from pynmms import MaterialBase, NMMSReasoner


@pytest.fixture
def empty_base():
    """An empty material base with no atoms or consequences."""
    return MaterialBase()


@pytest.fixture
def toy_base():
    """The toy base from Ch. 3 (adapted): A |~ B, B |~ C.

    This base exhibits both nontransitivity (A =/=> C) and
    nonmonotonicity (A, C =/=> B).
    """
    return MaterialBase(
        language={"A", "B", "C"},
        consequences={
            (frozenset({"A"}), frozenset({"B"})),
            (frozenset({"B"}), frozenset({"C"})),
        },
    )


@pytest.fixture
def toy_reasoner(toy_base):
    """An NMMSReasoner over the toy base with depth limit 15."""
    return NMMSReasoner(toy_base, max_depth=15)
