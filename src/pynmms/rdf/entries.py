"""Material entries in tell syntax, ground and pattern, from a file or text.

One entry per line, ``#`` comments::

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


def load_entries(source: str | Path, base: Any) -> tuple[int, int]:
    """Add the entries of *source* (a path, or text) to *base*; returns (ground, pattern)."""
    from pynmms.rdf.atoms import TripleAtom
    from pynmms.rdf.defeasible import is_pattern_entry, parse_defeasible_rule
    from pynmms.robustness import Robustness, split_robustness_clause
    from pynmms.syntax import split_top_level

    text = Path(source).read_text() if isinstance(source, Path) or (
        "\n" not in str(source) and Path(str(source)).exists()) else str(source)

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
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if is_pattern_entry(line):
            base.add_rule(parse_defeasible_rule(line, base.resolver))
            patterns += 1
            continue
        body, rob = split_robustness_clause(line)
        if "|~" not in body:
            raise ValueError(f"entry without |~: {line!r}")
        left, right = body.split("|~", 1)
        rob = Robustness(
            rob.kind,
            frozenset(canon(x) for x in rob.left),
            frozenset(canon(x) for x in rob.right),
            frozenset((frozenset(canon(x) for x in a), frozenset(canon(x) for x in b))
                      for a, b in rob.exclusions),
        )
        base.add_consequence(atoms(left), atoms(right), robustness=rob)
        ground += 1
    return ground, patterns
