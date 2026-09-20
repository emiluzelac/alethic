from __future__ import annotations

from typing import Callable

import pytest

from alethic.kernel import Kernel
from alethic.store import MemoryStore
from alethic.sqlite_store import SqliteStore
from alethic.store_protocol import StoreProtocol


@pytest.fixture(params=["memory", "sqlite"])
def kernel(request, tmp_path) -> Kernel:
    """Run every governance assertion against both stores.

    The two backends must agree: which store is configured is a deployment
    choice and must never change whether a proposal is committed or refused.
    """
    if request.param == "memory":
        yield Kernel()
        return
    store = SqliteStore(str(tmp_path / "kernel.db"))
    try:
        yield Kernel(store=store)
    finally:
        store.close()


@pytest.fixture
def memory_store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def sqlite_store(tmp_path) -> SqliteStore:
    store = SqliteStore(str(tmp_path / "test.db"))
    yield store
    store.close()


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    """Both StoreProtocol implementations, for tests that must hold on either."""
    if request.param == "memory":
        yield MemoryStore()
        return
    s = SqliteStore(str(tmp_path / "store.db"))
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(params=["memory", "sqlite"])
def store_factory(request, tmp_path) -> Callable[[], StoreProtocol]:
    """A factory for either StoreProtocol implementation.

    For tests that call store_conformance, which needs to create several
    independent store instances within a single call, rather than a single
    already-constructed store.
    """
    if request.param == "memory":
        return MemoryStore
    return lambda: SqliteStore(str(tmp_path / "store_factory.db"))


@pytest.fixture
def trace_id() -> str:
    return "test-trace-001"


# ── Charge fixtures ──────────────────────────────────────────────────

@pytest.fixture
def clean_charge() -> dict:
    return {
        "charge_id": "ch_clean",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": False,
        "conflict": False,
        "customer_id": "cus_clean",
    }


@pytest.fixture
def stale_charge() -> dict:
    return {
        "charge_id": "ch_stale",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": True,
        "conflict": False,
        "customer_id": "cus_stale",
    }


@pytest.fixture
def conflict_charge() -> dict:
    return {
        "charge_id": "ch_conflict",
        "amount": 100.00,
        "currency": "usd",
        "status": "disputed",
        "stale": False,
        "conflict": True,
        "customer_id": "cus_conflict",
    }
