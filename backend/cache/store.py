"""SQLite cache for external API responses.

Every outbound call to FortyGuard, OpenRouteService, and Overpass goes through
here. Overpass rate-limits hard and FortyGuard is async with a poll loop, so a
cache miss during the demo is a stall in front of judges. Caching is wired in
from the first service rather than bolted on at the end.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.config import CACHE_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    namespace  TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_cache_created ON cache(created_at);
"""


# Paths whose schema this process has already created. Guards against paying for
# executescript on every connection while keeping every entry point self-healing:
# a missing cache table mid-demo is not a failure mode worth risking.
_initialised: set[Path] = set()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else CACHE_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if path not in _initialised:
        conn.executescript(_SCHEMA)
        conn.commit()
        _initialised.add(path)
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create the schema eagerly. _connect does this lazily too."""
    _connect(db_path).close()


def get(namespace: str, key: str, max_age_s: float | None = None,
        db_path: Path | None = None) -> Any | None:
    """Return the cached value, or None on miss or expiry."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT value, created_at FROM cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
    if row is None:
        return None
    if max_age_s is not None and time.time() - row["created_at"] > max_age_s:
        return None
    return json.loads(row["value"])


def put(namespace: str, key: str, value: Any, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (namespace, key, value, created_at) "
            "VALUES (?, ?, ?, ?)",
            (namespace, key, json.dumps(value), time.time()),
        )


def stats(db_path: Path | None = None) -> dict[str, int]:
    """Rows per namespace. Used to confirm demo runs are pre-cached."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT namespace, COUNT(*) AS n FROM cache GROUP BY namespace"
        ).fetchall()
    return {r["namespace"]: r["n"] for r in rows}
