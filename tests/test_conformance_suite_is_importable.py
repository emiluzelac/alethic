"""The store_conformance suite must ship as public API, or a third-party
backend author has no way to prove they honour StoreProtocol.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alethic import MemoryStore, SqliteStore
from alethic.schema import Record
from alethic.testing import store_conformance


def test_shipped_stores_pass_their_own_conformance_suite() -> None:
    store_conformance(MemoryStore)


def test_sqlite_store_passes(tmp_path: Path) -> None:
    store_conformance(lambda: SqliteStore(str(tmp_path / "conf.db")))


def test_a_store_that_overwrites_ids_is_caught() -> None:
    """The exact divergence that shipped once: MemoryStore silently
    overwrote an existing id while SqliteStore raised."""
    class Overwriting(MemoryStore):
        def append(self, rec: Record) -> None:  # StoreProtocol.append returns None
            self._records[rec.id] = rec  # never raises RecordIdConflict

    with pytest.raises(AssertionError, match="RecordIdConflict"):
        store_conformance(Overwriting)
