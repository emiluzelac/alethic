import dataclasses

import pytest

from alethic import MemoryStore, ValidationContext


def test_context_carries_store_trace_and_clock() -> None:
    store = MemoryStore()
    ctx = ValidationContext(store=store, trace_id="t-1", now_ms=1_700_000_000_000)
    assert ctx.store is store
    assert ctx.trace_id == "t-1"
    assert ctx.now_ms == 1_700_000_000_000


def test_context_is_frozen() -> None:
    """A validator must not be able to retarget the kernel's store mid-run."""
    ctx = ValidationContext(store=MemoryStore(), trace_id="t-1", now_ms=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.trace_id = "t-2"  # type: ignore[misc]
