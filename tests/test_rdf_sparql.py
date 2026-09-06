"""Live test of SPARQLBackend against a local rdflib-endpoint server.

Skipped unless ``rdflib_endpoint`` and ``uvicorn`` are importable. The server
runs in a background thread on an ephemeral port for the duration of the
module.
"""

# ruff: noqa: E402

from __future__ import annotations

import importlib.util
import socket
import threading
import time

import pytest

_missing = [m for m in ("rdflib_endpoint", "uvicorn") if importlib.util.find_spec(m) is None]
if _missing:
    pytest.skip("rdflib-endpoint / uvicorn not installed", allow_module_level=True)
pytest.importorskip("rdflib")

import uvicorn
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS
from rdflib_endpoint import SparqlEndpoint

from pynmms import NMMSReasoner
from pynmms.rdf import RDFS as RDFS_REGIME
from pynmms.rdf import RegimeBase, TripleAtom
from pynmms.rdf.backends import SPARQLBackend
from pynmms.rdf.closure import ClosureEngine

EX = Namespace("http://ex.org/")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def endpoint():
    g = Graph()
    g.bind("ex", EX)
    g.add((EX.Bird, RDFS.subClassOf, EX.Animal))
    g.add((EX.tweety, RDF.type, EX.Bird))
    g.add((EX.hasChild, RDFS.range, EX.Person))
    # Materialise RDFS in the "store" so the endpoint behaves like a
    # regime-materialising server.
    closed, _ = ClosureEngine(RDFS_REGIME).close(iter(g))
    for t in closed:
        g.add(t)
    port = _free_port()
    app = SparqlEndpoint(graph=g, enable_update=True)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "endpoint did not start"
    yield f"http://127.0.0.1:{port}/", g
    server.should_exit = True
    thread.join(timeout=5)


def test_membership_and_regime_over_endpoint(endpoint):
    url, _ = endpoint
    backend = SPARQLBackend(url, regime=RDFS_REGIME, prefixes={"ex": str(EX)},
                            probe=((EX.tweety, RDF.type, EX.Animal),))
    assert backend.size() >= 3
    assert backend.contains((EX.tweety, RDF.type, EX.Bird))
    assert not backend.contains((EX.tweety, RDF.type, EX.Fish))
    base = RegimeBase(backend)
    r = NMMSReasoner(base, persistent_cache=True)
    # closure hit served by the store
    assert r.derives_sequent(base.sequent([], ["<ex:tweety a ex:Animal>"])).derivable
    # extras closed in process against the store's closure
    seq = base.sequent(["<ex:bob ex:hasChild ex:kim>"], ["<ex:kim a ex:Person>"])
    assert r.derives_sequent(seq).derivable
    assert not r.derives_sequent(base.sequent([], ["<ex:kim a ex:Person>"])).derivable
    stats = backend.stats
    assert stats["calls"] > 0 and stats["latency_ms"] >= 0


def test_probe_mismatch_raises(endpoint):
    url, _ = endpoint
    with pytest.raises(ValueError, match="does not entail"):
        SPARQLBackend(url, regime=RDFS_REGIME, probe=((EX.tweety, RDF.type, EX.Fish),))


def test_add_through_update_endpoint(endpoint):
    url, g = endpoint
    backend = SPARQLBackend(url, regime=RDFS_REGIME, update_endpoint=url,
                            prefixes={"ex": str(EX)})
    gen = backend.generation
    n = backend.add([(EX.kim, RDF.type, EX.Fish)])
    assert n == 1 and backend.generation == gen + 1
    assert (EX.kim, RDF.type, EX.Fish) in g
    base = RegimeBase(backend)
    r = NMMSReasoner(base)
    assert r.derives_sequent(base.sequent([], [TripleAtom(EX.kim, RDF.type, EX.Fish)])).derivable


def test_join_batches_round_trips(endpoint):
    """A firing with several store-side premises is one query when batched."""
    from pynmms.rdf import Resolver, parse_rule
    from pynmms.rdf.rules import custom

    url, g = endpoint
    # bob -> kim -> pat0..pat5 (all Persons): the grandparent rule has two
    # remaining premises to answer from the store once (bob hasChild kim) is new.
    g.add((EX.kim, RDF.type, EX.Person))
    for i in range(6):
        g.add((EX.kim, EX.hasChild, EX[f"pat{i}"]))
        g.add((EX[f"pat{i}"], RDF.type, EX.Person))
    rule = parse_rule(
        "?x ex:hasChild ?y, ?y ex:hasChild ?z, ?z a ex:Person -> ?x a ex:Grandparent",
        Resolver(g),
    )
    regime = custom("gp", [rule])
    engine = ClosureEngine(regime)
    extras = [(EX.bob, EX.hasChild, EX.kim)]

    plain_backend = SPARQLBackend(url, regime=regime, prefixes={"ex": str(EX)})
    plain, _ = engine.extend(extras, plain_backend.closure_triples,
                             plain_backend.closure_contains)
    calls_plain = plain_backend.stats["calls"]

    batched_backend = SPARQLBackend(url, regime=regime, prefixes={"ex": str(EX)})
    batched, _ = engine.extend(extras, batched_backend.closure_triples,
                               batched_backend.closure_contains,
                               store_join=batched_backend.join)
    calls_batched = batched_backend.stats["calls"]

    assert plain.triples == batched.triples
    assert (EX.bob, RDF.type, EX.Grandparent) in batched
    # plain: one lookup for ?z, then one per pat_i for the Person check;
    # batched: a single SELECT for the conjunction (plus the contains checks).
    assert calls_batched < calls_plain, (calls_batched, calls_plain)


def test_bulk_insert_in_chunks(endpoint):
    url, g = endpoint
    backend = SPARQLBackend(url, regime=RDFS_REGIME, update_endpoint=url,
                            prefixes={"ex": str(EX)})
    backend.BULK_CHUNK = 7
    before = backend.stats["calls"]
    triples = [(EX[f"n{i}"], EX.p, EX[f"m{i}"]) for i in range(20)]
    assert backend.add(triples) == 20
    assert backend.stats["calls"] - before == 3  # ceil(20 / 7) updates
    assert all(t in g for t in triples)
    with pytest.raises(ValueError, match="blank"):
        from rdflib import BNode

        backend.add([(BNode(), EX.p, EX.x)])
