"""CLI entry point for pyNMMS.

Usage::

    pynmms tell -b base.json --create "A |~ B"
    pynmms ask  -b base.json "A => B"
    pynmms repl [-b base.json]
"""

from __future__ import annotations

import argparse
import sys

from pynmms._version import __version__


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the ``pynmms`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pynmms",
        description="pyNMMS — Non-Monotonic Multi-Succedent sequent calculus",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- tell ---
    tell_parser = subparsers.add_parser("tell", help="Add atoms or consequences to a base")
    tell_parser.add_argument("-b", "--base", required=True, help="Path to JSON base file")
    tell_parser.add_argument("--create", action="store_true", help="Create the base file if it doesn't exist")
    tell_parser.add_argument("statement", help='Statement: "A |~ B" or "atom A"')

    # --- ask ---
    ask_parser = subparsers.add_parser("ask", help="Query derivability of a sequent")
    ask_parser.add_argument("-b", "--base", required=True, help="Path to JSON base file")
    ask_parser.add_argument("--trace", action="store_true", help="Print proof trace")
    ask_parser.add_argument("--max-depth", type=int, default=25, help="Max proof depth (default: 25)")
    ask_parser.add_argument("sequent", help='Sequent: "A => B" or "A, B => C, D"')

    # --- repl ---
    repl_parser = subparsers.add_parser("repl", help="Interactive REPL")
    repl_parser.add_argument("-b", "--base", default=None, help="Path to JSON base file to load")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "tell":
        from pynmms.cli.tell import run_tell
        return run_tell(args)
    elif args.command == "ask":
        from pynmms.cli.ask import run_ask
        return run_ask(args)
    elif args.command == "repl":
        from pynmms.cli.repl import run_repl
        return run_repl(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
