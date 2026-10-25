"""Tests for the SQLite routing cache (F-02)."""

from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from nedviga.routing_cache import _connect, put, stats


def test_connect_uses_wal_and_busy_timeout(tmp_path: Path):
    db = tmp_path / "routing_cache.sqlite"
    conn = _connect(db)
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal.lower() == "wal"
        assert busy == 5000
    finally:
        conn.close()


def _write_batch(args: tuple[Path, int, int]) -> int:
    """Worker used by the concurrent-write test; must be module-level."""
    db, offset, count = args
    for i in range(count):
        # Step by > 50 m of latitude (~0.00045°) to avoid cache-key collisions.
        put(
            55.0 + offset * 0.1 + i * 0.001,
            37.0 + offset * 0.1,
            "ВДНХ",
            meters=float(offset * 1000 + i),
            db_path=db,
        )
    return offset


def test_concurrent_process_writes_do_not_raise(tmp_path: Path):
    """Cross-process writers must not see 'database is locked' (F-02)."""
    db = tmp_path / "routing_cache.sqlite"
    # Initialise the DB in the parent so workers only contend on real writes.
    _connect(db).close()

    workers = 4
    per_worker = 25

    with multiprocessing.Pool(workers) as pool:
        pool.map(
            _write_batch,
            [(db, offset, per_worker) for offset in range(workers)],
        )

    assert stats(db_path=db)["entries"] == workers * per_worker
