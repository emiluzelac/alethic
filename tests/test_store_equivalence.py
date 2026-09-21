"""The two stores must agree.

Which store is configured is a deployment choice. It must never change whether
a proposal is committed or refused — a governance decision that depends on the
backend is not a governance decision.

These tests run against both implementations via the parametrized `store` and
`kernel` fixtures in conftest.
"""
from __future__ import annotations

import time
from typing import Callable

import pytest

from alethic.kernel import Kernel
from alethic.schema import Provenance, Record
from alethic.store_protocol import StoreProtocol
from alethic.testing import store_conformance


def _record(rec_id: str, kind: str, ts_ms: int, ttl_ms: int | None,
            trace_id: str = "t1", slot: str = "percepts") -> Record:
    return Record(
        id=rec_id, slot=slot, mode="COMMIT", kind=kind, payload={"value": True},
        prov=Provenance(writer_id="tool", trace_id=trace_id, ts_ms=ts_ms,
                        input_refs=[], confidence=None, ttl_ms=ttl_ms),
        scope="episode",
    )


class TestFindActiveByKindSkipsExpired:
    def test_expired_record_does_not_shadow_a_live_one(
        self, store_factory: Callable[[], StoreProtocol]
    ) -> None:
        """An expired record must not hide a fresh record of the same kind.

        The SQL path selected the oldest ACTIVE row, TTL-checked that single
        row, and returned None when it had expired — never looking at the live
        record behind it. The in-memory path kept scanning. Same inputs, two
        different answers.

        store_conformance now carries this exact assertion (and the rest of
        the StoreProtocol contract), so this test calls it rather than
        re-asserting the same check inline — keeping one copy of the
        assertion instead of two that could drift apart.
        """
        store_conformance(store_factory)

    def test_all_expired_returns_none(self, store):
        now = int(time.time() * 1000)
        store.append(_record("percepts:t1:1", "charge", ts_ms=now - 10_000, ttl_ms=1))
        store.append(_record("percepts:t1:2", "charge", ts_ms=now - 9_000, ttl_ms=1))
        assert store.find_active_by_kind("percepts", "charge", "t1") is None

    def test_live_record_still_found(self, store):
        now = int(time.time() * 1000)
        store.append(_record("percepts:t1:1", "charge", ts_ms=now, ttl_ms=None))
        found = store.find_active_by_kind("percepts", "charge", "t1")
        assert found is not None and found.id == "percepts:t1:1"

    def test_oldest_live_record_wins(self, store):
        """Ordering is unchanged for live records: oldest ACTIVE still wins."""
        now = int(time.time() * 1000)
        store.append(_record("percepts:t1:1", "charge", ts_ms=now - 5_000, ttl_ms=None))
        store.append(_record("percepts:t1:2", "charge", ts_ms=now, ttl_ms=None))
        found = store.find_active_by_kind("percepts", "charge", "t1")
        assert found is not None and found.id == "percepts:t1:1"


class TestGovernanceDecisionsMatchAcrossStores:
    def test_expired_belief_does_not_block_a_prediction(self, kernel: Kernel):
        """The end-to-end shape of the divergence, through the kernel.

        A stale belief that has since been superseded by a fresh one must not
        cause the prediction gate to report the belief missing.
        """
        trace = "t-equiv"
        kernel.write("tool", "percepts", "COMMIT", "charge",
                     {"stale": False, "conflict": False}, trace, confidence=0.9)
        prop = kernel.write("planner", "beliefs", "PROPOSE", "refund_due",
                            {"value": True, "depends_on": ["charge"]}, trace)
        ok, code = kernel.commit_belief_from_proposal(prop.id, trace)
        assert (ok, code) == (True, "COMMITTED")

        pred = kernel.write("planner", "predictions", "PROPOSE", "refund_outcome",
                            {"expected_outcome": 1.0, "requires_beliefs": ["refund_due"]},
                            trace)
        assert kernel.commit_prediction(pred.id, trace) == (True, "COMMITTED")
