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
