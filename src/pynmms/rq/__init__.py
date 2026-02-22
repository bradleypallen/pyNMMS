"""pyNMMS Restricted Quantifier extension.

Extends propositional NMMS with ALC-style restricted quantifiers
(ALL R.C, SOME R.C) following Hlobil (2025), "First-Order Implication-Space
Semantics."

Public API::

    from pynmms.rq import RQMaterialBase, NMMSRQReasoner
    from pynmms.rq import CommitmentStore, InferenceSchema
    from pynmms.rq import (
        RQSentence, parse_rq_sentence, is_rq_atomic, all_rq_atomic,
        make_concept_assertion, make_role_assertion,
    )
"""

from pynmms.rq.base import CommitmentStore, InferenceSchema, RQMaterialBase
from pynmms.rq.reasoner import NMMSRQReasoner
from pynmms.rq.syntax import (
    ALL_RESTRICT,
    ATOM_CONCEPT,
    ATOM_ROLE,
    SOME_RESTRICT,
    RQSentence,
    all_rq_atomic,
    is_rq_atomic,
    make_concept_assertion,
    make_role_assertion,
    parse_rq_sentence,
)

__all__ = [
    "ALL_RESTRICT",
    "ATOM_CONCEPT",
    "ATOM_ROLE",
    "CommitmentStore",
    "InferenceSchema",
    "NMMSRQReasoner",
    "RQMaterialBase",
    "RQSentence",
    "SOME_RESTRICT",
    "all_rq_atomic",
    "is_rq_atomic",
    "make_concept_assertion",
    "make_role_assertion",
    "parse_rq_sentence",
]
