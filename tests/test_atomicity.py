"""Commit must be all-or-nothing, and record ids must not collide.

Both properties concern what survives a failure. The framework's deliverable is
its audit trail, so a half-written commit is worse than a refused one: it leaves
a record asserting that validation passed for a belief that does not exist.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from alethic.kernel import Kernel
from alethic.store import MemoryStore
from alethic.sqlite_store import SqliteStore


def _percept_and_proposal(k: Kernel, trace: str):
    k.write("tool", "percepts", "COMMIT", "charge",
            {"stale": False, "conflict": False}, trace, confidence=0.9)
    return k.write("planner", "beliefs", "PROPOSE", "refund_due",
                   {"value": True, "depends_on": ["charge"]}, trace)


class TestCommitIsAtomic:
    """P0-4: the evidence artifact, the invalidation and the record are one unit."""

    def test_failed_belief_commit_leaves_no_evidence_behind(self, kernel: Kernel):
        """If the belief write fails, its evidence artifact must not survive.

        The evidence record says "result: pass" for a belief. If the belief is
        never written but the evidence is, the trail asserts a validation that
        governs nothing -- and the proposal is already invalidated, so it cannot
        be retried. That is the state a crash used to leave behind.
        """
        trace = "t-atomic"
        prop = _percept_and_proposal(kernel, trace)

        real_write = kernel.write
        calls = {"n": 0}

        def exploding_write(role, slot, *args, **kwargs):
            # let the evidence artifact through, blow up on the belief commit
            if slot == "beliefs" and args and args[0] == "COMMIT":
                calls["n"] += 1
                raise RuntimeError("simulated failure mid-commit")
            return real_write(role, slot, *args, **kwargs)

        kernel.write = exploding_write  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            kernel.commit_belief_from_proposal(prop.id, trace)
        kernel.write = real_write  # type: ignore[method-assign]

        assert calls["n"] == 1, "the belief commit should have been attempted"

        view = kernel.current_view(trace)
        assert view["beliefs"].get("refund_due") is None, "belief must not exist"
        assert view["evidence"] == {}, (
            "evidence artifact survived a commit that never completed -- "
            "the audit trail is asserting a validation that governs nothing"
        )
        still = kernel.store.get(prop.id)
        assert still is not None and still.status == "ACTIVE", (
            "proposal was invalidated by a commit that failed, so it can never "
            "be retried"
        )

    def test_successful_commit_still_writes_everything(self, kernel: Kernel):
        trace = "t-atomic-ok"
        prop = _percept_and_proposal(kernel, trace)
        assert kernel.commit_belief_from_proposal(prop.id, trace) == (True, "COMMITTED")
        view = kernel.current_view(trace)
        assert view["beliefs"]["refund_due"] == {"value": True, "depends_on": ["charge"]}
        assert view["evidence"]["validation_refund_due"]["result"] == "pass"
        assert kernel.store.get(prop.id).status == "INVALIDATED"

    def test_failed_action_rejection_leaves_no_evidence_behind(self, kernel: Kernel) -> None:
        """The same P0-4 invariant, now on the action-rejection path.

        `_reject_action` writes an evidence artifact recording *why* an
        action was refused, then invalidates the proposal, under one
        transaction. If the evidence write survives a rejection that never
        completed, the trail asserts a validation outcome for a proposal
        that is still live and retryable -- the mirror image of the belief
        case above.
        """
        trace = "t-atomic-action"
        action = kernel.write("planner", "actions", "PROPOSE", "send",
                              {"type": "send", "requires_beliefs": ["refund_due"]},
                              trace)

        real_write = kernel.write
        calls = {"n": 0}

        def exploding_write(role, slot, *args, **kwargs):
            # let the rejection reach its evidence write, then blow up there
            if slot == "evidence" and args and args[0] == "COMMIT":
                calls["n"] += 1
                raise RuntimeError("simulated failure mid-rejection")
            return real_write(role, slot, *args, **kwargs)

        kernel.write = exploding_write  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            kernel.decide_action(action.id, trace)
        kernel.write = real_write  # type: ignore[method-assign]

        assert calls["n"] == 1, "the rejection evidence write should have been attempted"

        view = kernel.current_view(trace)
        assert view["evidence"] == {}, (
            "evidence artifact survived a rejection that never completed -- "
            "the audit trail is asserting a validation outcome for nothing"
        )
        still = kernel.store.get(action.id)
        assert still is not None and still.status == "ACTIVE", (
            "proposal was invalidated by a rejection that failed, so it can "
            "never be retried"
        )


CRASH_CHILD = '''
import os, sys
from alethic.kernel import Kernel
from alethic.sqlite_store import SqliteStore

k = Kernel(store=SqliteStore(sys.argv[1]))
k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": False}, "t-crash", confidence=0.9)
prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
               {"value": True, "depends_on": ["charge"]}, "t-crash")
real = k.write
def crashing(role, slot, mode, *a, **kw):
    if slot == "beliefs" and mode == "COMMIT":
        os._exit(9)                    # hard kill inside the open transaction
    return real(role, slot, mode, *a, **kw)
k.write = crashing
k.commit_belief_from_proposal(prop.id, "t-crash")
'''


class TestCommitSurvivesAProcessCrash:
    """The failure P0-4 was actually about: not an exception, a dead process.

    An exception unwinds Python and runs cleanup; os._exit does neither. Only a
    real transaction protects against this, which is why it gets its own test.
    """

    def test_crash_mid_commit_leaves_a_retryable_episode(self, tmp_path):
        import subprocess
        import sys

        child = tmp_path / "child.py"
        child.write_text(CRASH_CHILD)
        db = str(tmp_path / "crash.db")

        proc = subprocess.run([sys.executable, str(child), db],
                              capture_output=True, timeout=60)
        assert proc.returncode == 9, (
            f"child did not crash in the commit window (rc={proc.returncode}): "
            f"{proc.stderr.decode()[:400]}"
        )

        store = SqliteStore(db)
        try:
            k = Kernel(store=store)
            view = k.current_view("t-crash")
            prop = store.get("beliefs:t-crash:1")

            assert view["evidence"] == {}, (
                "evidence survived a commit that never completed: the trail "
                "asserts a validation for a belief that does not exist"
            )
            assert view["beliefs"].get("refund_due") is None
            assert prop is not None and prop.status == "ACTIVE", (
                "proposal was superseded by a commit that never happened, so "
                "the episode can never be retried"
            )
            # the whole point of staying ACTIVE: it can be driven to completion
            assert k.commit_belief_from_proposal(prop.id, "t-crash") == (True, "COMMITTED")
        finally:
            store.close()


class TestRecordIdsSurviveRestart:
    """P0-5: ids come from a per-process counter against a durable store."""

    def test_reused_trace_id_after_restart_does_not_collide(self):
        """A client reusing a trace_id (e.g. an order number) after a restart.

        The counter restarts at 1 while the database still holds
        `percepts:order-123:1`, so the write collided on the primary key.
        """
        d = tempfile.mkdtemp()
        path = os.path.join(d, "restart.db")
        trace = "order-123"

        s1 = SqliteStore(path)
        k1 = Kernel(store=s1)
        k1.write("tool", "percepts", "COMMIT", "charge", {"v": 1}, trace)
        s1.close()

        # process restarts; same database, same trace_id
        s2 = SqliteStore(path)
        k2 = Kernel(store=s2)
        rec = k2.write("tool", "percepts", "COMMIT", "charge", {"v": 2}, trace)
        ids = [r.id for r in s2.list_slot("percepts")]
        s2.close()

        assert len(ids) == len(set(ids)), f"duplicate record ids: {ids}"
        assert len(ids) == 2, f"expected both records to survive, got {ids}"
        assert rec.payload == {"v": 2}

    def test_two_kernels_over_one_store_do_not_collide(self):
        """`uvicorn --workers 4` with a shared sqlite store, in miniature."""
        d = tempfile.mkdtemp()
        store = SqliteStore(os.path.join(d, "shared.db"))
        trace = "shared-trace"

        ka, kb = Kernel(store=store), Kernel(store=store)
        ka.write("tool", "percepts", "COMMIT", "charge", {"by": "a"}, trace)
        kb.write("tool", "percepts", "COMMIT", "charge", {"by": "b"}, trace)

        ids = [r.id for r in store.list_slot("percepts")]
        store.close()
        assert len(ids) == len(set(ids)), f"duplicate record ids: {ids}"
        assert len(ids) == 2, f"a record was lost: {ids}"


class TestDuplicateIdsAreRejectedByBothStores:
    def test_append_of_duplicate_id_is_refused(self, store):
        """MemoryStore silently overwrote; SqliteStore raised. Neither is right.

        Records are an append-only audit trail: a write that replaces an
        existing record destroys history, and the two stores must agree on what
        happens.
        """
        from tests.helpers import make_record
        store.append(make_record(rec_id="percepts:t:1", payload={"v": 1}))
        with pytest.raises(Exception):
            store.append(make_record(rec_id="percepts:t:1", payload={"v": 2}))
        kept = store.get("percepts:t:1")
        assert kept is not None and kept.payload == {"v": 1}, "history was overwritten"
