"""Guards over values: comparisons on the literals a rule binds.

A rule of ``def:entailmentregime`` is uniform, closed under substituting any
term for any term. Real data reasons about values too: a production date
after a maker's death, evidence weaker than a threshold, a qualifier in one
language. A :class:`Guard` is a side condition on a rule's bindings written
in a small expression language and evaluated two ways that must agree:
as a SPARQL ``FILTER`` when the store materialises the closure
(:mod:`pynmms.rdf.sparql_rules`), and in Python when the in-process closure
runs (:class:`~pynmms.rdf.closure.ClosureEngine`). A guard is not uniform,
so a guarded rule is an admitted exception to `def:entailmentregime` that
the second paper has to state.

Grammar (``?x`` a rule variable; literals as in Turtle, ``"1712"``,
``"naar"@nl``, ``"1712-04-05"^^http://www.w3.org/2001/XMLSchema#date``,
numbers bare)::

    guard  := or
    or     := and ("||" and)*
    and    := not ("&&" not)*
    not    := "!" not | cmp
    cmp    := term (("<" | "<=" | ">" | ">=" | "=" | "!=") term)?
            | term "in" "(" term ("," term)* ")"
    term   := func "(" args ")" | ?var | literal | number | IRI | "(" or ")"
    func   := num | year | str | lang | datatype | rank | isLiteral | isIRI | isBlank

Semantics follow SPARQL so the two evaluators agree: typed numerics and
dates compare as values, plain strings as strings, and a comparison across
kinds is false. ``num(x)`` reads a plain string as a number, ``year(x)`` takes
the first four digits of a date, year, or string, ``rank(name, x)`` is the
place of ``x`` in a declared ordering (:func:`declare_ordering`, or an
``ordering name: a < b < c`` line in a rules file), ``-1`` when absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from rdflib import BNode, Literal, URIRef
from rdflib.term import Node

from pynmms.rdf.rules import Var

ORDERINGS: dict[str, tuple[str, ...]] = {}


def declare_ordering(name: str, values: list[str] | tuple[str, ...]) -> None:
    """Declare ``name`` as an ordering, weakest first, for ``rank(name, x)``."""
    ORDERINGS[name] = tuple(values)


def parse_ordering_line(line: str) -> bool:
    """``ordering evidence: IEA < ISS < IDA`` declares an ordering; returns True if it did."""
    m = re.match(r"^\s*ordering\s+([A-Za-z_][\w-]*)\s*:\s*(.+)$", line)
    if not m:
        return False
    declare_ordering(m.group(1), [x.strip().strip('"') for x in m.group(2).split("<")])
    return True


# --- AST ---------------------------------------------------------------------


@dataclass(frozen=True)
class Guard:
    """A parsed guard: ``evaluate`` in Python, ``to_sparql`` for the store."""

    node: Any
    text: str

    @property
    def variables(self) -> frozenset[Var]:
        out: set[Var] = set()
        _collect_vars(self.node, out)
        return frozenset(out)

    def evaluate(self, bindings: dict[Var, Node]) -> bool:
        try:
            return bool(_eval(self.node, bindings))
        except _Error:
            return False

    def to_sparql(self) -> str | None:
        try:
            return _sparql(self.node)
        except _Error:
            return None

    def __str__(self) -> str:
        return self.text


class _Error(Exception):
    pass


FUNCS = ("num", "year", "str", "lang", "datatype", "rank", "isLiteral", "isIRI", "isBlank")
OPS = ("<=", ">=", "!=", "<", ">", "=")

_TOKEN = re.compile(
    r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*"(?:@[A-Za-z0-9-]+|\^\^\S+)?)'
    r"|(?P<num>-?\d+(?:\.\d+)?)"
    r"|(?P<var>\?[A-Za-z_]\w*)"
    r"|(?P<op><=|>=|!=|<|>|=|&&|\|\||!|\(|\)|,)"
    r"|(?P<iri>[A-Za-z][A-Za-z0-9+.-]*:[^\s(),<>]+)"
    r"|(?P<word>[A-Za-z_][\w]*))"
)


def _tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            raise ValueError(f"cannot read guard at {text[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        out.append((kind, m.group(kind)))
    return out


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = _tokens(text)
        self.i = 0

    def peek(self, kind: str | None = None, val: str | None = None) -> bool:
        if self.i >= len(self.toks):
            return False
        k, v = self.toks[self.i]
        return (kind is None or k == kind) and (val is None or v == val)

    def take(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, kind: str, val: str | None = None) -> str:
        if not self.peek(kind, val):
            raise ValueError(f"guard: expected {val or kind} at token {self.i}")
        return self.take()[1]

    def parse(self) -> Any:
        node = self.parse_or()
        if self.i != len(self.toks):
            raise ValueError(f"guard: trailing tokens {self.toks[self.i:]}")
        return node

    def parse_or(self) -> Any:
        left = self.parse_and()
        while self.peek("op", "||"):
            self.take()
            left = ("or", left, self.parse_and())
        return left

    def parse_and(self) -> Any:
        left = self.parse_not()
        while self.peek("op", "&&"):
            self.take()
            left = ("and", left, self.parse_not())
        return left

    def parse_not(self) -> Any:
        if self.peek("op", "!"):
            self.take()
            return ("not", self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self) -> Any:
        left = self.parse_term()
        if self.peek("op") and self.toks[self.i][1] in OPS:
            op = self.take()[1]
            return ("cmp", op, left, self.parse_term())
        if self.peek("word", "in"):
            self.take()
            self.expect("op", "(")
            items = [self.parse_term()]
            while self.peek("op", ","):
                self.take()
                items.append(self.parse_term())
            self.expect("op", ")")
            return ("in", left, tuple(items))
        return left

    def parse_term(self) -> Any:
        if self.peek("op", "("):
            self.take()
            node = self.parse_or()
            self.expect("op", ")")
            return node
        kind, val = self.take()
        if kind == "var":
            return ("var", Var(val[1:]))
        if kind == "num":
            return ("lit", Literal(Decimal(val)) if "." in val else Literal(int(val)))
        if kind == "str":
            return ("lit", _literal(val))
        if kind == "iri":
            return ("lit", URIRef(val))
        if kind == "word":
            if val in ("true", "false"):
                return ("lit", Literal(val == "true"))
            if val not in FUNCS:
                raise ValueError(f"guard: unknown function {val!r}")
            self.expect("op", "(")
            if val == "rank":
                name = self.expect("word")
                self.expect("op", ",")
                arg = self.parse_term()
                self.expect("op", ")")
                return ("rank", name, arg)
            args = [self.parse_term()]
            while self.peek("op", ","):
                self.take()
                args.append(self.parse_term())
            self.expect("op", ")")
            if len(args) != 1:
                raise ValueError(f"guard: {val}() takes one argument")
            return ("fn", val, args[0])
        raise ValueError(f"guard: unexpected {val!r}")


def _literal(tok: str) -> Literal:
    m = re.match(r'^"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^(\S+))?$', tok)
    assert m is not None
    text = m.group(1).encode().decode("unicode_escape")
    if m.group(2):
        return Literal(text, lang=m.group(2))
    if m.group(3):
        return Literal(text, datatype=URIRef(m.group(3).strip("<>")))
    return Literal(text)


def parse_guard(text: str) -> Guard:
    """Parse a guard expression (without its enclosing ``[`` ``]``)."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    return Guard(_Parser(text).parse(), text)


def _collect_vars(node: Any, out: set[Var]) -> None:
    if not isinstance(node, tuple):
        return
    if node[0] == "var":
        out.add(node[1])
        return
    for x in node[1:]:
        if isinstance(x, tuple):
            if x and isinstance(x[0], str):
                _collect_vars(x, out)
            else:
                for y in x:
                    _collect_vars(y, out)


# --- Python evaluation --------------------------------------------------------


def _value(n: Any) -> Any:
    """A comparable Python value for a term, following SPARQL's kinds."""
    if isinstance(n, Literal):
        if n.language:
            return ("str", str(n))
        if n.datatype is None:
            return ("str", str(n))
        v = n.toPython()
        if isinstance(v, bool):
            return ("bool", v)
        if isinstance(v, (int, float, Decimal)):
            return ("num", v)
        if isinstance(v, datetime):
            return ("date", v.date())
        if isinstance(v, date):
            return ("date", v)
        return ("str", str(n))
    if isinstance(n, (URIRef, BNode)):
        return ("node", n)
    if isinstance(n, tuple):
        return n
    return ("str", str(n))


def _eval(node: Any, b: dict[Var, Node]) -> Any:
    kind = node[0]
    if kind == "var":
        if node[1] not in b:
            raise _Error("unbound")
        return b[node[1]]
    if kind == "lit":
        return node[1]
    if kind == "or":
        return bool(_eval(node[1], b)) or bool(_eval(node[2], b))
    if kind == "and":
        return bool(_eval(node[1], b)) and bool(_eval(node[2], b))
    if kind == "not":
        return not bool(_eval(node[1], b))
    if kind == "cmp":
        return _compare(node[1], _value(_eval(node[2], b)), _value(_eval(node[3], b)))
    if kind == "in":
        left = _value(_eval(node[1], b))
        return any(_compare("=", left, _value(_eval(x, b))) for x in node[2])
    if kind == "rank":
        order = ORDERINGS.get(node[1])
        if order is None:
            raise _Error(f"no ordering {node[1]!r}")
        x = _eval(node[2], b)
        s = str(x)
        return ("num", order.index(s) if s in order else -1)
    if kind == "fn":
        return _fn(node[1], _eval(node[2], b))
    raise _Error(f"bad node {kind}")


def _fn(name: str, x: Any) -> Any:
    if name == "str":
        return ("str", str(x))
    if name == "num":
        try:
            return ("num", Decimal(str(x)))
        except InvalidOperation as e:
            raise _Error("not a number") from e
    if name == "year":
        # SPARQL side: xsd:integer(SUBSTR(STR(x), 1, 4)); the same here.
        head = str(x)[:4]
        if not re.match(r"^[+-]?\d+$", head):
            raise _Error("no year")
        return ("num", int(head))
    if name == "lang":
        return ("str", x.language or "" if isinstance(x, Literal) else "")
    if name == "datatype":
        if not isinstance(x, Literal):
            raise _Error("not a literal")
        if x.language:
            return ("node", URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"))
        return ("node", x.datatype or URIRef("http://www.w3.org/2001/XMLSchema#string"))
    if name == "isLiteral":
        return ("bool", isinstance(x, Literal))
    if name == "isIRI":
        return ("bool", isinstance(x, URIRef))
    if name == "isBlank":
        return ("bool", isinstance(x, BNode))
    raise _Error(name)


def _compare(op: str, a: Any, b: Any) -> bool:
    ka, va = a
    kb, vb = b
    if ka != kb:
        return False
    if op == "=":
        return bool(va == vb)
    if op == "!=":
        return bool(va != vb)
    if ka in ("node", "bool"):
        return False
    try:
        return bool({"<": va < vb, "<=": va <= vb, ">": va > vb, ">=": va >= vb}[op])
    except TypeError:
        return False


# --- SPARQL translation -------------------------------------------------------


def _sparql(node: Any) -> str:
    kind = node[0]
    if kind == "var":
        return f"?{node[1].name}"
    if kind == "lit":
        lit = node[1]
        if isinstance(lit, Literal) and lit.datatype in _NUMERIC and not lit.language:
            return str(lit)
        return str(lit.n3())
    if kind == "or":
        return f"({_sparql(node[1])} || {_sparql(node[2])})"
    if kind == "and":
        return f"({_sparql(node[1])} && {_sparql(node[2])})"
    if kind == "not":
        return f"(!{_sparql(node[1])})"
    if kind == "cmp":
        return f"({_sparql(node[2])} {node[1]} {_sparql(node[3])})"
    if kind == "in":
        return f"({_sparql(node[1])} IN ({', '.join(_sparql(x) for x in node[2])}))"
    if kind == "rank":
        order = ORDERINGS.get(node[1])
        if order is None:
            raise _Error("no ordering")
        x = _sparql(node[2])
        expr = "-1"
        for i in range(len(order) - 1, -1, -1):
            expr = f'IF(STR({x}) = {Literal(order[i]).n3()}, {i}, {expr})'
        return expr
    if kind == "fn":
        x = _sparql(node[2])
        forms: dict[str, str] = {
            "str": f"STR({x})",
            "num": f"xsd:decimal(STR({x}))",
            "year": f"xsd:integer(SUBSTR(STR({x}), 1, 4))",
            "lang": f"LANG({x})",
            "datatype": f"DATATYPE({x})",
            "isLiteral": f"isLiteral({x})",
            "isIRI": f"isIRI({x})",
            "isBlank": f"isBlank({x})",
        }
        return forms[node[1]]
    raise _Error(kind)


_NUMERIC = {URIRef("http://www.w3.org/2001/XMLSchema#integer"),
            URIRef("http://www.w3.org/2001/XMLSchema#decimal"),
            URIRef("http://www.w3.org/2001/XMLSchema#double")}
