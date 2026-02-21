"""pyNMMS — Non-Monotonic Multi-Succedent sequent calculus.

Propositional NMMS from Hlobil & Brandom 2025, Ch. 3.

Public API::

    from pynmms import MaterialBase, NMMSReasoner, ProofResult
    from pynmms import parse_sentence, is_atomic, all_atomic, Sentence
"""

from pynmms._version import __version__
from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner, ProofResult
from pynmms.syntax import Sentence, all_atomic, is_atomic, parse_sentence

__all__ = [
    "__version__",
    "MaterialBase",
    "NMMSReasoner",
    "ProofResult",
    "Sentence",
    "parse_sentence",
    "is_atomic",
    "all_atomic",
]
