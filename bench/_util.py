"""Shared helpers for the benchmark sections."""

from __future__ import annotations

import json
import logging
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("bench")


def timeit(fn: Callable[[], Any], reps: int) -> float:
    """Median wall-clock time of *fn* over *reps* runs, in milliseconds."""
    ts: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return statistics.median(ts) * 1000.0


def git_sha() -> str:
    """Short git SHA of HEAD, suffixed with ``-dirty`` if the tree has changes."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], stderr=subprocess.DEVNULL
        ).returncode != 0
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def env_info() -> dict[str, str]:
    from pynmms._version import __version__

    return {
        "pynmms": __version__,
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


@dataclass
class Section:
    """One benchmark table."""

    name: str
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    notes: str = ""

    def add(self, *values: Any) -> None:
        self.rows.append(list(values))
        logger.info("%s: %s", self.name, dict(zip(self.columns, values)))

    def render(self) -> str:
        widths = [len(c) for c in self.columns]
        cells = [[_fmt(v) for v in r] for r in self.rows]
        for r in cells:
            for i, c in enumerate(r):
                widths[i] = max(widths[i], len(c))
        head = " | ".join(c.rjust(w) for c, w in zip(self.columns, widths))
        sep = "-+-".join("-" * w for w in widths)
        body = "\n".join(" | ".join(c.rjust(w) for c, w in zip(r, widths)) for r in cells)
        out = f"=== {self.name} ===\n{head}\n{sep}\n{body}"
        if self.notes:
            out += f"\n({self.notes})"
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "columns": self.columns, "rows": self.rows,
                "notes": self.notes}


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def write_record(sections: list[Section], out_dir: Path, quick: bool) -> Path:
    """Write a JSON record of this run and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    sha = git_sha()
    record = {
        "timestamp": now.isoformat(timespec="seconds"),
        "git_sha": sha,
        "quick": quick,
        "env": env_info(),
        "sections": [s.to_dict() for s in sections],
    }
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{sha}{'-quick' if quick else ''}.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    logger.info("wrote %s", path)
    return path
