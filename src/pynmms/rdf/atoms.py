"""RDF triples as atomic sentences.

Definition 19 of the paper encodes a ground triple ``(s, p, o)`` as the bearer
``T<s, p, o>`` of a single ternary property. In pyNMMS that bearer is a
:class:`TripleAtom`: a ``str`` subclass whose value is the *canonical quoted
atom name* ``<s p o>`` accepted by the propositional parser, and which also
carries the three rdflib terms. Being a ``str`` lets a triple flow through
every string-typed part of the core (atom sets, bases, traces, JSON) with no
special cases; being canonical (full IRIs, escaped literals) makes two names
equal exactly when the triples are.

Content grammar (what goes between ``<`` and ``>``)::

    content ::= term ' ' term ' ' term
    term    ::= IRI | '_:' label | literal | 'a'          ('a' = rdf:type, predicate only)
    literal ::= '"' escaped '"' ( '@' lang | '^^' IRI )?

In the canonical form IRIs are written in full. On input, ``prefix:local``
is expanded through a :class:`Resolver` (an rdflib ``NamespaceManager``).
Literal escapes are the N-Triples ones plus ``\\u003C`` / ``\\u003E`` for the
angle brackets, so no content ever contains ``<`` or ``>``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, NamespaceManager
from rdflib.term import Node

logger = logging.getLogger(__name__)

Triple = tuple[Node, Node, Node]

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t",
            "<": "\\u003C", ">": "\\u003E"}
_UNESCAPE_RE = re.compile(r'\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|[\\"nrt])')
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _escape(s: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in s)


def _unescape(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        code = m.group(1)
        if code[0] in "uU":
            return chr(int(code[1:], 16))
        return {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}[code]
    return _UNESCAPE_RE.sub(repl, s)


class Resolver:
    """Expands ``prefix:local`` names and ``a`` when parsing atom content.

    Wraps an rdflib ``NamespaceManager``; a bare ``Graph`` or ``None`` is
    accepted for convenience (``None`` means no prefixes: every name is a
    full IRI).
    """

    def __init__(self, nsm: NamespaceManager | Graph | None = None) -> None:
        if isinstance(nsm, Graph):
            nsm = nsm.namespace_manager
        self.nsm = nsm

    def bind(self, prefix: str, namespace: str) -> None:
        if self.nsm is None:
            self.nsm = NamespaceManager(Graph())
        self.nsm.bind(prefix, URIRef(namespace), replace=True)

    def expand(self, token: str) -> URIRef:
        """Expand a prefixed name, or accept an absolute IRI; else ValueError."""
        if self.nsm is not None and ":" in token:
            prefix = token.split(":", 1)[0]
            if self.nsm.store.namespace(prefix) is not None:
                return URIRef(self.nsm.expand_curie(token))
        if _SCHEME_RE.match(token):
            return URIRef(token)
        raise ValueError(
            f"{token!r} is neither an absolute IRI nor a prefixed name with a bound prefix"
        )

    def compact(self, iri: URIRef) -> str:
        """Prefixed form for display, if a prefix is bound; else the full IRI."""
        if self.nsm is None:
            return str(iri)
        try:
            return self.nsm.normalizeUri(iri)
        except Exception:  # pragma: no cover - rdflib raises on odd IRIs
            return str(iri)


def term_to_content(t: Node) -> str:
    """Canonical content form of an rdflib term."""
    if isinstance(t, URIRef):
        s = str(t)
        if " " in s or "<" in s or ">" in s:
            raise ValueError(f"IRI contains a forbidden character: {s!r}")
        return s
    if isinstance(t, BNode):
        return f"_:{t}"
    if isinstance(t, Literal):
        out = f'"{_escape(str(t))}"'
        if t.language:
            out += f"@{t.language}"
        elif t.datatype:
            out += f"^^{t.datatype}"
        return out
    raise TypeError(f"Unsupported RDF term: {t!r}")


def _tokens(content: str) -> Iterator[str]:
    i, n = 0, len(content)
    while i < n:
        if content[i].isspace():
            i += 1
            continue
        if content[i] == '"':
            j = i + 1
            while j < n:
                if content[j] == "\\":
                    j += 2
                    continue
                if content[j] == '"':
                    break
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated literal in {content!r}")
            j += 1
            while j < n and not content[j].isspace():
                j += 1
            yield content[i:j]
            i = j
        else:
            j = i
            while j < n and not content[j].isspace():
                j += 1
            yield content[i:j]
            i = j


def content_to_term(token: str, resolver: Resolver | None, *, predicate: bool = False) -> Node:
    if token.startswith('"'):
        end = token.rfind('"')
        lexical = _unescape(token[1:end])
        suffix = token[end + 1:]
        if suffix.startswith("@"):
            return Literal(lexical, lang=suffix[1:])
        if suffix.startswith("^^"):
            dtype = (resolver or _NO_PREFIXES).expand(suffix[2:])
            return Literal(lexical, datatype=dtype)
        if suffix:
            raise ValueError(f"Malformed literal {token!r}")
        return Literal(lexical)
    if token.startswith("_:"):
        return BNode(token[2:])
    if predicate and token == "a":
        return RDF.type
    return (resolver or _NO_PREFIXES).expand(token)


_NO_PREFIXES = Resolver(None)


def content_to_triple(content: str, resolver: Resolver | None = None) -> Triple:
    toks = list(_tokens(content))
    if len(toks) != 3:
        raise ValueError(f"A triple atom needs exactly three terms, got {len(toks)}: {content!r}")
    return (
        content_to_term(toks[0], resolver),
        content_to_term(toks[1], resolver, predicate=True),
        content_to_term(toks[2], resolver),
    )


class TripleAtom(str):
    """An RDF triple as an atomic sentence.

    ``TripleAtom(s, p, o)`` is the string ``"<s p o>"`` in canonical form and
    exposes ``.s``, ``.p``, ``.o`` and ``.triple``. Two atoms are equal iff
    their triples are.
    """

    s: Node
    p: Node
    o: Node

    def __new__(cls, s: Node, p: Node, o: Node) -> TripleAtom:
        name = f"<{term_to_content(s)} {term_to_content(p)} {term_to_content(o)}>"
        obj = super().__new__(cls, name)
        obj.s, obj.p, obj.o = s, p, o
        return obj

    @property
    def triple(self) -> Triple:
        return (self.s, self.p, self.o)

    @classmethod
    def from_triple(cls, t: Triple) -> TripleAtom:
        return cls(*t)

    @classmethod
    def from_name(cls, name: str, resolver: Resolver | None = None) -> TripleAtom:
        """Parse a quoted atom name ``<s p o>`` (prefixes via *resolver*)."""
        name = name.strip()
        if not (name.startswith("<") and name.endswith(">")):
            raise ValueError(f"Not a quoted triple atom: {name!r}")
        return cls(*content_to_triple(name[1:-1], resolver))

    @classmethod
    def coerce(cls, x: object, resolver: Resolver | None = None) -> TripleAtom | None:
        """Return *x* as a TripleAtom if it is one or names one, else ``None``."""
        if isinstance(x, TripleAtom):
            return x
        if isinstance(x, str) and x.startswith("<") and x.endswith(">"):
            try:
                return cls.from_name(x, resolver)
            except ValueError:
                return None
        if isinstance(x, tuple) and len(x) == 3:
            return cls(*x)
        return None

    def display(self, resolver: Resolver | None = None) -> str:
        """Compact form for humans: prefixed names, ``a`` for rdf:type."""
        r = resolver or _NO_PREFIXES

        def show(t: Node, pred: bool = False) -> str:
            if pred and t == RDF.type:
                return "a"
            if isinstance(t, URIRef):
                return r.compact(t)
            return term_to_content(t)

        return f"<{show(self.s)} {show(self.p, True)} {show(self.o)}>"

    def __repr__(self) -> str:
        return f"TripleAtom({str(self)!r})"

    def __reduce__(self) -> Any:
        return (TripleAtom, (self.s, self.p, self.o))
