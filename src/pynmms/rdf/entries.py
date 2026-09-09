"""Material entries in tell syntax, ground and pattern, from a file or text.

One entry per line, ``#`` comments, and ``ordering name: a < b < c`` lines
declaring an ordering for ``rank`` guards (:mod:`pynmms.rdf.values`)::

    <ex:tweety a ex:Bird> |~ <ex:tweety a ex:Flies> unless <ex:tweety a ex:Penguin>
    <ex:a ex:p ex:b>, <ex:b ex:q ex:c> |~ <ex:a ex:r ex:c> monotone
    ?x am:maker ?m, ?m rdf:value ?p |~ ?x am:madeBy ?p unless ?m am:creatorQualifier "naar"

A line with variables before ``|~`` is a pattern entry
(:mod:`pynmms.rdf.defeasible`); a ground line's robustness clause follows
:func:`pynmms.robustness.split_robustness_clause`, with defeaters as triple
atoms over the base's prefixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_source(source: str | Path) -> str:
    """The text of *source*, which is a file path or the entries text itself.

    A :class:`~pathlib.Path` is always read. A ``str`` is read as a file when
    it has no newline and names an existing file; otherwise it is the text
    (one entry is a line, so a single-line string naming no file is one entry).
    """
    if isinstance(source, Path):
        return source.read_text()
    if "\n" not in source and Path(source).exists():
        return Path(source).read_text()
    return source


def load_entries(source: str | Path, base: Any) -> tuple[int, int]:
    """Add the entries of *source* (a path, or text; :func:`read_source`) to *base*;
    returns (ground, pattern)."""
    from pynmms.rdf.atoms import TripleAtom
    from pynmms.rdf.defeasible import is_pattern_entry, parse_defeasible_rule
    from pynmms.rdf.rules import content_lines
    from pynmms.robustness import split_robustness_clause
    from pynmms.syntax import split_top_level

    text = read_source(source)

    def atoms(part: str) -> frozenset[str]:
        out = []
        for name in split_top_level(part, ","):
            if not name.strip():
                continue
            atom = TripleAtom.coerce(name.strip(), base.resolver)
            if atom is None:
                raise ValueError(f"{name!r} is not a triple atom")
            out.append(str(atom))
        return frozenset(out)

    def canon(name: str) -> str:
        atom = TripleAtom.coerce(name, base.resolver)
        return str(atom) if atom is not None else name

    ground = patterns = 0
    for line in content_lines(text):
        if is_pattern_entry(line):
            base.add_rule(parse_defeasible_rule(line, base.resolver))
            patterns += 1
            continue
        body, rob = split_robustness_clause(line)
        if "|~" not in body:
            raise ValueError(f"entry without |~: {line!r}")
        left, right = body.split("|~", 1)
        base.add_consequence(atoms(left), atoms(right), robustness=rob.map_atoms(canon))
        ground += 1
    return ground, patterns
