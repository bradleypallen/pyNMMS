"""Parsing and registration of ontology schema lines (shared by tell and the REPL).

A schema line has the form::

    schema <type> <arg1> <arg2> [unless C1, C2 | monotone] ["annotation"]

where ``<type>`` is one of the seven schema types and ``<arg1>`` for
``jointCommitment`` is a comma-separated list of concepts. The optional
robustness clause is parsed by :func:`pynmms.robustness.split_robustness_clause`;
its defeaters are concept names.
"""

from __future__ import annotations

from pynmms.onto.base import OntoMaterialBase
from pynmms.robustness import Robustness, split_robustness_clause

SCHEMA_TYPES = (
    "subClassOf",
    "range",
    "domain",
    "subPropertyOf",
    "disjointWith",
    "disjointProperties",
    "jointCommitment",
)

USAGE = (
    "Usage: schema subClassOf <sub> <super>\n"
    "       schema range <role> <concept>\n"
    "       schema domain <role> <concept>\n"
    "       schema subPropertyOf <sub_role> <super_role>\n"
    "       schema disjointWith <concept1> <concept2>\n"
    "       schema disjointProperties <role1> <role2>\n"
    "       schema jointCommitment <C1,C2,...> <D>\n"
    "  each optionally followed by 'unless <C1, C2, ...>' or 'monotone', "
    "and a quoted annotation"
)


def extract_trailing_annotation(text: str) -> tuple[str, str | None]:
    """Extract an optional trailing quoted annotation from *text*.

    Returns (remaining_text, annotation_or_None).
    """
    for quote_char in ('"', "'"):
        idx = text.find(quote_char)
        if idx != -1:
            end_idx = text.find(quote_char, idx + 1)
            if end_idx == -1:
                annotation = text[idx + 1:].strip()
            else:
                annotation = text[idx + 1:end_idx]
            remaining = text[:idx].strip()
            return remaining, annotation if annotation else None
    return text, None


def describe_schema(schema_type: str, arg1: str | list[str], arg2: str) -> str:
    """The ``{...} |~ {...}`` pattern a schema generates, for display."""
    if schema_type == "subClassOf":
        return f"{{{arg1}(x)}} |~ {{{arg2}(x)}}"
    if schema_type == "range":
        return f"{{{arg1}(x,y)}} |~ {{{arg2}(y)}}"
    if schema_type == "domain":
        return f"{{{arg1}(x,y)}} |~ {{{arg2}(x)}}"
    if schema_type == "subPropertyOf":
        return f"{{{arg1}(x,y)}} |~ {{{arg2}(x,y)}}"
    if schema_type == "disjointWith":
        return f"{{{arg1}(x), {arg2}(x)}} |~"
    if schema_type == "disjointProperties":
        return f"{{{arg1}(x,y), {arg2}(x,y)}} |~"
    if schema_type == "jointCommitment":
        concepts = arg1.split(",") if isinstance(arg1, str) else list(arg1)
        ant = ", ".join(f"{c}(x)" for c in concepts)
        return f"{{{ant}}} |~ {{{arg2}(x)}}"
    return f"{arg1} -> {arg2}"  # pragma: no cover


def register_schema_line(
    base: OntoMaterialBase, line: str
) -> tuple[str, str, Robustness, str | None]:
    """Parse *line* and register the schema on *base*.

    *line* may or may not start with the word ``schema``. Returns
    ``(schema_type, details, robustness, annotation)``. Raises ValueError on
    malformed input.
    """
    body, annotation = extract_trailing_annotation(line.strip())
    body, robustness = split_robustness_clause(body)
    parts = body.split()
    if parts and parts[0] == "schema":
        parts = parts[1:]
    if len(parts) != 3 or parts[0] not in SCHEMA_TYPES:
        raise ValueError(f"Invalid schema line: {line!r}\n{USAGE}")
    schema_type, arg1, arg2 = parts

    if schema_type == "subClassOf":
        base.register_subclass(arg1, arg2, annotation=annotation, robustness=robustness)
    elif schema_type == "range":
        base.register_range(arg1, arg2, annotation=annotation, robustness=robustness)
    elif schema_type == "domain":
        base.register_domain(arg1, arg2, annotation=annotation, robustness=robustness)
    elif schema_type == "subPropertyOf":
        base.register_subproperty(arg1, arg2, annotation=annotation, robustness=robustness)
    elif schema_type == "disjointWith":
        base.register_disjoint(arg1, arg2, annotation=annotation, robustness=robustness)
    elif schema_type == "disjointProperties":
        base.register_disjoint_properties(
            arg1, arg2, annotation=annotation, robustness=robustness
        )
    else:  # jointCommitment
        concepts = [c for c in arg1.split(",") if c]
        if len(concepts) < 2:
            raise ValueError(
                "jointCommitment requires at least 2 comma-separated antecedent concepts."
            )
        base.register_joint_commitment(
            concepts, arg2, annotation=annotation, robustness=robustness
        )

    return schema_type, describe_schema(schema_type, arg1, arg2), robustness, annotation


def format_registration(
    schema_type: str, details: str, robustness: Robustness, annotation: str | None
) -> str:
    """Human-readable confirmation line for a registered schema."""
    msg = f"Registered {schema_type} schema: {details}"
    if not robustness.is_exact:
        msg += f" [{robustness}]"
    if annotation:
        msg += f" — {annotation}"
    return msg
