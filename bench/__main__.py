"""Run the pyNMMS benchmark suite: ``python -m bench [--quick] [--only NAME]``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import antecedent_scaling, query_complexity, schema_scaling
from ._util import Section, env_info, git_sha, write_record

SECTIONS = {
    "antecedent_scaling": antecedent_scaling.run,
    "schema_scaling": schema_scaling.run,
    "query_complexity": query_complexity.run,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench", description=__doc__)
    parser.add_argument("--quick", action="store_true", help="reduced sizes")
    parser.add_argument("--only", choices=sorted(SECTIONS), action="append",
                        help="run only this section (repeatable)")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "results",
                        help="directory for the JSON record")
    parser.add_argument("--no-write", action="store_true", help="do not write a record")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    # The reasoner's DEBUG trace would dominate timings; keep it off.
    logging.getLogger("pynmms").setLevel(logging.WARNING)

    print(f"pyNMMS bench  sha={git_sha()}  {env_info()}  quick={args.quick}\n")
    sections: list[Section] = []
    for name in args.only or sorted(SECTIONS):
        result = SECTIONS[name](quick=args.quick)
        for section in result if isinstance(result, list) else [result]:
            sections.append(section)
            print(section.render(), end="\n\n")

    if not args.no_write:
        path = write_record(sections, args.out, args.quick)
        print(f"record: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
