"""Structured JSON output for the pyNMMS CLI."""

from __future__ import annotations

import json
import logging
import sys

logger = logging.getLogger(__name__)


def emit_json(data: dict) -> None:
    """Print compact single-line JSON to stdout."""
    print(json.dumps(data, separators=(",", ":")))


def ask_response(
    derivable: bool,
    antecedent: frozenset[str],
    consequent: frozenset[str],
    depth_reached: int,
    cache_hits: int,
    trace: list[str] | None = None,
) -> dict:
    """Build an ask response dict."""
    d: dict = {
        "status": "DERIVABLE" if derivable else "NOT_DERIVABLE",
        "sequent": {
            "antecedent": sorted(antecedent),
            "consequent": sorted(consequent),
        },
        "depth_reached": depth_reached,
        "cache_hits": cache_hits,
    }
    if trace is not None:
        d["trace"] = trace
    return d


def tell_atom_response(atom: str, base_file: str, annotation: str | None = None) -> dict:
    """Build a tell-atom response dict."""
    d: dict = {
        "action": "added_atom",
        "atom": atom,
        "base_file": base_file,
    }
    if annotation is not None:
        d["annotation"] = annotation
    return d


def tell_consequence_response(
    antecedent: frozenset[str],
    consequent: frozenset[str],
    base_file: str,
) -> dict:
    """Build a tell-consequence response dict."""
    return {
        "action": "added_consequence",
        "consequence": {
            "antecedent": sorted(antecedent),
            "consequent": sorted(consequent),
        },
        "base_file": base_file,
    }


def tell_schema_response(
    schema_type: str,
    details: str,
    base_file: str,
    annotation: str | None = None,
) -> dict:
    """Build a tell-schema response dict."""
    d: dict = {
        "action": f"registered_{schema_type}_schema",
        "details": details,
        "base_file": base_file,
    }
    if annotation is not None:
        d["annotation"] = annotation
    return d


def error_response(message: str) -> dict:
    """Build an error response dict."""
    return {"error": message}


def emit_error(message: str, *, json_mode: bool = False, quiet: bool = False) -> None:
    """Print an error message to stderr, or as JSON to stdout."""
    if quiet:
        return
    if json_mode:
        emit_json(error_response(message))
    else:
        print(f"Error: {message}", file=sys.stderr)
