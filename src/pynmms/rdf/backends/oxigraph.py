"""Oxigraph backend: a fast local store through the ``oxrdflib`` rdflib plugin.

Same behaviour as :class:`~pynmms.rdf.backends.memory.MemoryBackend` (closure
computed in process), but the asserted graph lives in Oxigraph, either in
memory or on disk. Requires ``pip install oxrdflib``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rdflib import Graph

from pynmms.rdf.backends.memory import MemoryBackend

if TYPE_CHECKING:
    from pynmms.rdf.rules import Regime


class OxigraphBackend(MemoryBackend):
    """``MemoryBackend`` whose asserted graph is an Oxigraph store."""

    def __init__(
        self,
        path: str | None = None,
        *,
        regime: Regime | None = None,
        skolemize: bool = True,
    ) -> None:
        try:
            graph = Graph(store="Oxigraph")
        except Exception as e:  # pragma: no cover - depends on environment
            raise ImportError("OxigraphBackend needs the oxrdflib package") from e
        if path is not None:
            graph.open(path, create=True)
        super().__init__(graph, regime=regime, skolemize=skolemize)
