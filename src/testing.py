"""Public conformance suite for StoreProtocol implementations.

A third-party backend author has no other way to prove their store honours
the subtle parts of the contract: lazy TTL expiry, walking candidates past an
expired one rather than judging only the oldest, and re-entrant transactions.
Those exact subtleties once produced a real divergence between the two
shipped stores, where ``MemoryStore`` silently overwrote a record that
``SqliteStore`` refused.
"""
from __future__ import annotations

import time
from typing import Callable

from .schema import Provenance, Record, RecordIdConflict
from .store_protocol import StoreProtocol


def _rec(rec_id: str, kind: str, trace_id: str = "conf", ttl_ms: int | None = None,
         ts_ms: int | None = None) -> Record:
    return Record(
        id=rec_id, slot="percepts", mode="COMMIT", kind=kind, payload={"v": rec_id},
        prov=Provenance(writer_id="conformance", trace_id=trace_id,
                        ts_ms=ts_ms if ts_ms is not None else int(time.time() * 1000),
                        ttl_ms=ttl_ms),
    )


def store_conformance(store_factory: Callable[[], StoreProtocol]) -> None:
    """Assert a StoreProtocol implementation honours the whole contract.

    ``store_factory`` is called more than once and must return a *fresh,
    empty* store every time -- a new database file or directory per call, not
    another handle on the one before. Later steps assume the ids they use are
    free, so a factory that hands back a store the suite has already written
    to passes only for as long as those ids happen not to collide. Every
    instance it returns is closed, including when an assertion fails.

    Raises AssertionError on the first violation, naming what failed. A
    backend that passes this agrees with the shipped stores on every
    behaviour the kernel's governance decisions depend on.
    """
    store = store_factory()
    try:
        # 1. round trip
        store.append(_rec("percepts:conf:1", "obs"))
        got = store.get("percepts:conf:1")
        assert got is not None, "get() returned None for a record just appended"
        assert got.kind == "obs", f"get() returned kind {got.kind!r}, expected 'obs'"

        # 2. duplicate ids are refused
        try:
            store.append(_rec("percepts:conf:1", "obs"))
        except RecordIdConflict:
            pass
        else:
            raise AssertionError(
                "append() accepted a duplicate id; it must raise RecordIdConflict. "
                "Records are an append-only audit trail, so silently overwriting "
                "destroys history."
            )

        # 3. list_slot returns records in append order
        #
        # NOTE: this does not mean ts_ms-sorted -- neither shipped store sorts
        # by ts_ms, both return append (insertion) order. Kernel.current_view()
        # relies on this: it folds list_slot() into a dict keyed by kind, so a
        # later COMMIT for the same kind must appear later in the sequence to
        # correctly supersede an earlier one, regardless of what ts_ms it
        # carries.
        #
        # The three records deliberately differ in `kind` ("obs", "zeta",
        # "alpha") and in `ts_ms`, so append order matches neither. Records
        # sharing one kind would make this assertion unfalsifiable against a
        # store that returns kind order -- the wrong answer a SQL backend
        # gives when its planner picks an index keyed on kind.
        store.append(_rec("percepts:conf:3", "zeta", ts_ms=3000))
        store.append(_rec("percepts:conf:2", "alpha", ts_ms=2000))
        ids = [r.id for r in store.list_slot("percepts")]
        expected = ["percepts:conf:1", "percepts:conf:3", "percepts:conf:2"]
        assert ids == expected, f"list_slot() returned {ids}, expected append order {expected}"

        # 4. an expired candidate must not hide a live one
        store2 = store_factory()
        try:
            store2.append(_rec("percepts:t:1", "reading", trace_id="t", ttl_ms=1, ts_ms=1))
            store2.append(_rec("percepts:t:2", "reading", trace_id="t"))
            found = store2.find_active_by_kind("percepts", "reading", "t")
            assert found is not None, (
                "find_active_by_kind() returned None while a live record exists; it must "
                "walk past expired candidates rather than judging only the oldest"
            )
            assert found.id == "percepts:t:2", f"found {found.id!r}, expected the live record"
        finally:
            store2.close()

        # 5. invalidate records status and reason
        store.invalidate("percepts:conf:2", "because")
        invalidated = store.get("percepts:conf:2")
        assert invalidated is not None and invalidated.status == "INVALIDATED", \
            "invalidate() did not set status to INVALIDATED"
        assert invalidated.reason == "because", "invalidate() did not record the reason"

        # 6. a transaction rolls back on exception
        store3 = store_factory()
        try:
            try:
                with store3.transaction():
                    store3.append(_rec("percepts:tx:1", "obs", trace_id="tx"))
                    raise RuntimeError("abort")
            except RuntimeError:
                pass
            assert store3.get("percepts:tx:1") is None, \
                "transaction() did not roll back a write when the block raised"

            # 7. transactions are re-entrant: only the outermost commits
            with store3.transaction():
                with store3.transaction():
                    store3.append(_rec("percepts:tx:2", "obs", trace_id="tx"))
            assert store3.get("percepts:tx:2") is not None, \
                "a nested transaction() lost a write the outer block completed"
        finally:
            store3.close()
    finally:
        store.close()
