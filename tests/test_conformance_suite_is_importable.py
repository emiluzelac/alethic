"""The store_conformance suite must ship as public API, or a third-party
backend author has no way to prove they honour StoreProtocol.
"""
from __future__ import annotations

from itertools import count
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from alethic import MemoryStore, SqliteStore
from alethic.schema import Record, Slot
from alethic.store_protocol import StoreProtocol
from alethic.testing import store_conformance

from tests.helpers import make_record


def _sqlite_factory(tmp_path: Path) -> Callable[[], SqliteStore]:
    """The factory this repo hands to `store_conformance` for SqliteStore.

    A new database file per call: `store_conformance` calls its factory more
    than once and documents each result as a fresh, empty store. Reusing one
    path returns a second connection to a database the suite has already
    written to.
    """
    counter = count()
    return lambda: SqliteStore(str(tmp_path / f"conf_{next(counter)}.db"))


def test_shipped_stores_pass_their_own_conformance_suite() -> None:
    store_conformance(MemoryStore)


def test_sqlite_store_passes(tmp_path: Path) -> None:
    store_conformance(_sqlite_factory(tmp_path))


def _assert_factory_is_empty_every_call(
    factory: Callable[[], StoreProtocol],
) -> None:
    """`store_conformance` documents its factory as producing "a fresh, empty
    store instance" and calls it more than once, with later steps assuming
    the ids they use are free. A factory that hands back another connection
    to a database the suite has already written to breaks that, and passes
    only for as long as those ids happen not to collide.
    """
    first = factory()
    try:
        first.append(make_record(rec_id="percepts:factory:1", slot="percepts"))
    finally:
        first.close()

    second = factory()
    try:
        assert second.list_slot("percepts") == [], (
            "the factory returned a store still holding an earlier instance's "
            "records; store_conformance requires a fresh, empty store per call"
        )
    finally:
        second.close()


def test_the_sqlite_conformance_factory_is_empty_every_call(tmp_path: Path) -> None:
    _assert_factory_is_empty_every_call(_sqlite_factory(tmp_path))


def test_the_shared_store_factory_fixture_is_empty_every_call(
    store_factory: Callable[[], StoreProtocol],
) -> None:
    _assert_factory_is_empty_every_call(store_factory)


def test_a_store_that_overwrites_ids_is_caught() -> None:
    """The exact divergence that shipped once: MemoryStore silently
    overwrote an existing id while SqliteStore raised."""
    class Overwriting(MemoryStore):
        def append(self, rec: Record) -> None:  # StoreProtocol.append returns None
            self._records[rec.id] = rec  # never raises RecordIdConflict

    with pytest.raises(AssertionError, match="RecordIdConflict"):
        store_conformance(Overwriting)


def test_every_created_store_is_closed_even_when_conformance_fails() -> None:
    """A DB-backed store must not leak a connection or file handle when a
    later conformance assertion fails -- exactly the scenario this suite
    exists for: a non-conformant third-party store failing partway through.
    `store_conformance` creates more than one store instance (one per
    ``store_factory()`` call); every one of them must be closed, not just
    the first."""
    closed_ids: List[int] = []
    created: List["BrokenStore"] = []

    class BrokenStore(MemoryStore):
        def find_active_by_kind(self, slot: Slot, kind: str, trace_id: str) -> Optional[Record]:
            # Never finds anything active, so it fails the suite's step-4
            # assertion on the *second* store instance the suite creates,
            # after a first instance has already been created and used.
            return None

        def close(self) -> None:
            closed_ids.append(id(self))
            super().close()

    def factory() -> BrokenStore:
        s = BrokenStore()
        created.append(s)
        return s

    with pytest.raises(AssertionError, match="find_active_by_kind"):
        store_conformance(factory)

    assert len(created) >= 2, (
        "expected store_conformance to have created at least 2 store "
        f"instances before failing, got {len(created)}"
    )
    assert len(closed_ids) == len(created), (
        f"expected every created store to be closed, but only "
        f"{len(closed_ids)} of {len(created)} instances were"
    )


def test_a_store_that_returns_list_slot_in_the_wrong_order_is_caught() -> None:
    """The suite publishes insertion-ordered `list_slot` as a contract, so it
    has to be able to fail a store that supplies some other order.

    `Kernel.current_view()` folds the sequence into a dict keyed by `kind`, so
    a later COMMIT supersedes an earlier one only if it arrives later. Kind
    order is the specific wrong answer a SQL backend gives when the planner
    picks an index keyed on `kind` -- which is legal for the shipped schema.
    """
    class KindOrdered(MemoryStore):
        def list_slot(self, slot: Slot) -> List[Record]:
            return sorted(super().list_slot(slot), key=lambda r: r.kind)

    with pytest.raises(AssertionError, match="append order"):
        store_conformance(KindOrdered)
