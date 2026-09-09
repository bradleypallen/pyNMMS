"""Guards over values: one expression, two evaluators that must agree.

Predictions written before the implementation was run.
"""

# ruff: noqa: E402

from __future__ import annotations

import pytest

pytest.importorskip("rdflib")
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from pynmms.rdf import Resolver, parse_rule
from pynmms.rdf.closure import ClosureEngine
from pynmms.rdf.rules import Var, custom, parse_rules_text
from pynmms.rdf.sparql_rules import rule_to_ask, rule_to_update, translatable
from pynmms.rdf.values import ORDERINGS, declare_ordering, parse_guard

EX = Namespace("http://ex.org/")
X, D, S, E = Var("x"), Var("d"), Var("s"), Var("e")


def ev(text: str, **b) -> bool:
    return parse_guard(text).evaluate({Var(k): v for k, v in b.items()})


class TestEvaluate:
    def test_numbers_dates_and_strings_follow_sparql_kinds(self):
        assert ev("?a > ?b", a=Literal(1780), b=Literal(1632))
        assert ev("?a > ?b", a=Literal("1780"), b=Literal("1632"))      # plain: string order
        assert ev("?a > ?b", a=Literal("999"), b=Literal("1000"))       # ... which misleads
        assert ev("num(?a) < num(?b)", a=Literal("999"), b=Literal("1000"))
        assert not ev("?a > ?b", a=Literal("1780"), b=Literal(1632))    # kinds differ: false
        assert ev("?a > ?b", a=Literal("1712-04-05", datatype=XSD.date),
                  b=Literal("1711-01-01", datatype=XSD.date))
        assert ev("?a = ?b", a=URIRef(EX.p), b=URIRef(EX.p))

    def test_year_reads_dates_years_and_leading_digits(self):
        assert ev("year(?s) > year(?d)", s=Literal("1727"), d=Literal("1712-04-05"))
        assert ev("year(?s) > year(?d)", s=Literal("1727", datatype=XSD.gYear),
                  d=Literal("1712-04-05", datatype=XSD.date))
        assert not ev("year(?s) > year(?d)", s=Literal("1700"), d=Literal("1712"))
        assert not ev("year(?s) > year(?d)", s=Literal("unknown"), d=Literal("1712"))  # error

    def test_lang_datatype_and_membership(self):
        assert ev('lang(?q) = "nl"', q=Literal("naar", lang="nl"))
        assert ev('lang(?q) = ""', q=Literal("naar"))
        assert ev("datatype(?d) = http://www.w3.org/2001/XMLSchema#date",
                  d=Literal("1712-04-05", datatype=XSD.date))
        assert ev('?e in ("IDA", "IMP")', e=Literal("IDA"))
        assert not ev('?e in ("IDA", "IMP")', e=Literal("IEA"))
        assert ev('!(?e in ("IDA")) && isLiteral(?e)', e=Literal("IEA"))

    def test_rank_over_a_declared_ordering(self):
        declare_ordering("evidence", ["IEA", "ISS", "IMP", "IDA"])
        assert ev('rank(evidence, ?e) >= rank(evidence, "IMP")', e=Literal("IDA"))
        assert not ev('rank(evidence, ?e) >= rank(evidence, "IMP")', e=Literal("ISS"))
        assert ev("rank(evidence, ?e) < 0", e=Literal("XXX"))            # absent: -1
        assert parse_guard("[?a > 1]").variables == frozenset({Var("a")})


class TestSparql:
    def test_translation_forms(self):
        assert parse_guard("year(?s) > year(?d)").to_sparql() == \
            "(xsd:integer(SUBSTR(STR(?s), 1, 4)) > xsd:integer(SUBSTR(STR(?d), 1, 4)))"
        assert parse_guard('lang(?q) = "nl" || !isLiteral(?q)').to_sparql() == \
            '((LANG(?q) = "nl") || (!isLiteral(?q)))'
        declare_ordering("ev", ["IEA", "IDA"])
        assert parse_guard('rank(ev, ?e) >= 1').to_sparql() == \
            '(IF(STR(?e) = "IEA", 0, IF(STR(?e) = "IDA", 1, -1)) >= 1)'
        assert parse_guard('?e in ("a", 2)').to_sparql() == '(?e IN ("a", 2))'


class TestRules:
    def test_parse_rule_with_a_guard_and_its_string(self):
        r = parse_rule("?x ex:made ?s, ?x ex:died ?d, [year(?s) > year(?d)] -> false",
                       Resolver(Graph().namespace_manager) if False else _resolver())
        assert len(r.premises) == 2 and r.conclusion is None and r.guard is not None
        assert "[year(?s) > year(?d)]" in str(r)
        assert translatable(r)
        assert "FILTER((xsd:integer" in rule_to_ask(r)
        with pytest.raises(ValueError):
            parse_rule("?x ex:made ?s, [year(?z) > 1] -> false", _resolver())  # ?z unbound

    def test_two_guards_are_conjoined_and_python_guards_stay_in_process(self):
        r = parse_rule("?x ex:p ?s, [?s > 1], [?s < 9] -> ?x ex:q ?s", _resolver())
        assert r.guard({X: EX.a, S: Literal(5)}) and not r.guard({X: EX.a, S: Literal(10)})
        assert "FILTER(((?s > 1) && (?s < 9)))" in rule_to_update(r)

    def test_a_guard_containing_less_than_does_not_swallow_the_premises_after_it(self):
        # `<` used to open a quoted atom for the splitter, so a premise after the
        # guard was glued onto it; a guard is an opaque `[...]` bracket now.
        r = parse_rule("?a ex:p ?b, [?a < ?b], ?b ex:q ?c -> false", _resolver())
        assert len(r.premises) == 2 and r.premises[1] == (Var("b"), EX.q, Var("c"))
        assert r.conclusion is None and r.guard is not None
        assert r.guard({Var("a"): Literal(1), Var("b"): Literal(2), Var("c"): EX.c})
        assert not r.guard({Var("a"): Literal(3), Var("b"): Literal(2), Var("c"): EX.c})
        # A literal with a comma is one term, not two premises.
        r2 = parse_rule('?x ex:n "a, b", ?x ex:q ?y -> ?y ex:r ?x', _resolver())
        assert len(r2.premises) == 2 and r2.premises[0][2] == Literal("a, b")

    def test_rules_text_declares_orderings(self):
        rules = parse_rules_text("""# comment
ordering strength: IEA < ISS < IDA
?a ex:evidence ?e, [rank(strength, ?e) >= rank(strength, "ISS")] -> ?a ex:strong "yes"
""", _resolver())
        assert ORDERINGS["strength"] == ("IEA", "ISS", "IDA")
        assert len(rules) == 1 and rules[0].guard({Var("a"): EX.x, E: Literal("IDA")})
        assert not rules[0].guard({Var("a"): EX.x, E: Literal("IEA")})


def _resolver():
    g = Graph()
    g.bind("ex", EX)
    return Resolver(g)


def _museum() -> Graph:
    g = Graph()
    g.bind("ex", EX)
    for i, (made, died) in enumerate([("1727", "1712-04-05"), ("1700", "1712"),
                                      ("1725", "1711"), ("unknown", "1711")]):
        g.add((EX[f"obj{i}"], EX.made, Literal(made)))
        g.add((EX[f"obj{i}"], EX.maker, EX[f"p{i}"]))
        g.add((EX[f"p{i}"], EX.died, Literal(died)))
    return g


ANACHRONISM = ("?x ex:maker ?p, ?p ex:died ?d, ?x ex:made ?s, [year(?s) > year(?d)] "
               "-> ?x ex:anachronisticMaker ?p")


class TestClosure:
    def test_in_process_closure_applies_the_guard(self):
        from pynmms.rdf import RDFS as RDFS_REGIME

        regime = custom("rdfs+values", [parse_rule(ANACHRONISM, _resolver())], extends=RDFS_REGIME)
        closed, _ = ClosureEngine(regime).close(iter(_museum()))
        found = {t[0] for t in closed if t[1] == EX.anachronisticMaker}
        assert found == {EX.obj0, EX.obj2}

    def test_store_and_in_process_closures_agree(self):
        pytest.importorskip("pyoxigraph")
        from pynmms.rdf import RDFS as RDFS_REGIME
        from pynmms.rdf.backends import MemoryBackend, OxigraphBackend

        regime = custom("rdfs+values", [parse_rule(ANACHRONISM, _resolver())], extends=RDFS_REGIME)
        ox = OxigraphBackend(regime=regime, skolemize=False)
        ox.load_graph(_museum())
        mem = MemoryBackend(_museum(), regime=regime, skolemize=False)
        store_side = {t for t in ox.closure_triples((None, EX.anachronisticMaker, None))}
        in_process = {t for t in mem.closure.triples((None, EX.anachronisticMaker, None))}
        assert store_side == in_process == {(EX.obj0, EX.anachronisticMaker, EX.p0),
                                            (EX.obj2, EX.anachronisticMaker, EX.p2)}

    def test_a_guarded_bottom_rule_makes_a_position_incoherent_only_when_it_fires(self):
        from pynmms import NMMSReasoner
        from pynmms.rdf import RDFS as RDFS_REGIME
        from pynmms.rdf import RegimeBase, TripleAtom
        from pynmms.rdf.backends import MemoryBackend

        rule = parse_rule("?x ex:maker ?p, ?p ex:died ?d, ?x ex:made ?s, [year(?s) > year(?d)] "
                          "-> false", _resolver())
        g = Graph()
        g.add((EX.p, EX.died, Literal("1712-04-05")))
        b = RegimeBase(MemoryBackend(g, regime=custom("rdfs+anach", [rule], extends=RDFS_REGIME)))
        r = NMMSReasoner(b)
        pos = [TripleAtom(EX.o, EX.maker, EX.p), TripleAtom(EX.o, EX.made, Literal("1727"))]
        assert r.derives_sequent(b.sequent(pos, [])).derivable
        pos[1] = TripleAtom(EX.o, EX.made, Literal("1700"))
        assert not r.derives_sequent(b.sequent(pos, [])).derivable
        assert (EX.o, RDF.type, EX.Thing) not in g
