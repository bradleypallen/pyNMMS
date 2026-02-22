"""``pynmms ask`` subcommand — query derivability of a sequent."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pynmms.base import MaterialBase
from pynmms.reasoner import NMMSReasoner

logger = logging.getLogger(__name__)


def _parse_sequent(sequent_str: str) -> tuple[frozenset[str], frozenset[str]]:
    """Parse a sequent string like ``A, B => C, D``.

    Returns (antecedent, consequent) as frozensets of sentence strings.
    """
    sequent_str = sequent_str.strip()

    if "=>" not in sequent_str:
        raise ValueError(
            f"Invalid sequent: {sequent_str!r}. Expected 'A, B => C, D'."
        )

    parts = sequent_str.split("=>", 1)
    ant_str = parts[0].strip()
    con_str = parts[1].strip()

    antecedent = frozenset(s.strip() for s in ant_str.split(",") if s.strip())
    consequent = frozenset(s.strip() for s in con_str.split(",") if s.strip())

    return antecedent, consequent


def run_ask(args: argparse.Namespace) -> int:
    """Execute the ``ask`` subcommand."""
    base_path = Path(args.base)
    rq_mode = getattr(args, "rq", False)

    if not base_path.exists():
        print(f"Error: Base file {base_path} does not exist.", file=sys.stderr)
        return 1

    base: MaterialBase
    reasoner: NMMSReasoner

    if rq_mode:
        from pynmms.rq.base import RQMaterialBase
        from pynmms.rq.reasoner import NMMSRQReasoner

        base = RQMaterialBase.from_file(base_path)
        reasoner = NMMSRQReasoner(base, max_depth=args.max_depth)
    else:
        base = MaterialBase.from_file(base_path)
        reasoner = NMMSReasoner(base, max_depth=args.max_depth)

    try:
        antecedent, consequent = _parse_sequent(args.sequent)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    result = reasoner.derives(antecedent, consequent)

    if result.derivable:
        print("DERIVABLE")
    else:
        print("NOT DERIVABLE")

    if args.trace:
        print("\nProof trace:")
        for line in result.trace:
            print(f"  {line}")
        print(f"\nDepth reached: {result.depth_reached}")
        print(f"Cache hits: {result.cache_hits}")

    logger.info(
        "Query %s => %s: %s (depth %d)",
        set(antecedent), set(consequent),
        "DERIVABLE" if result.derivable else "NOT DERIVABLE",
        result.depth_reached,
    )
    return 0
