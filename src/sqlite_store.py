from __future__ import annotations
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, cast

from .schema import Record, Provenance, RecordIdConflict, Slot, WriteMode
from .migrations import migrate


def _rec_to_row(rec: Record) -> tuple[Any, ...]:
    return (
        rec.id, rec.slot, rec.mode, rec.kind,
        json.dumps(rec.payload, separators=(",", ":")),
        rec.prov.writer_id, rec.prov.trace_id, rec.prov.ts_ms,
        json.dumps(rec.prov.input_refs, separators=(",", ":")),
        rec.prov.confidence, rec.prov.ttl_ms,
        json.dumps(rec.evidence_refs, separators=(",", ":")),
        rec.status, rec.reason, rec.scope,
    )


def _row_to_rec(row: tuple[Any, ...]) -> Record:
    return Record(
        id=row[0], slot=cast(Slot, row[1]), mode=cast(WriteMode, row[2]),
        kind=row[3], payload=json.loads(row[4]),
        prov=Provenance(
            writer_id=row[5], trace_id=row[6], ts_ms=row[7],
            input_refs=json.loads(row[8]),
            confidence=row[9], ttl_ms=row[10],
        ),
        evidence_refs=json.loads(row[11]),
        status=cast(str, row[12]),  # type: ignore[arg-type]
        reason=row[13],
        scope=cast(str, row[14]),  # type: ignore[arg-type]
    )


class SqliteStore:
    """StoreProtocol implementation backed by SQLite.

    Provides real persistence across process restarts.  Pass `":memory:"`
    for an in-process store that behaves identically to MemoryStore but
    with SQL query capabilities.
    """

    def __init__(self, path: str = "blackboard.db") -> None:
        self._path = path
        # Re-entrant: transaction() holds the lock across the writes inside it,
        # and each of those writes takes the lock again.
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        migrate(self._conn)

    # ── StoreProtocol ────────────────────────────────────────────────

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self._conn.rollback()
                raise
            else:
                self._tx_depth -= 1
                self._maybe_commit()

    def _maybe_commit(self) -> None:
        """Defer to the outermost transaction, so its writes land as one unit."""
        if self._tx_depth == 0:
            self._conn.commit()

    def append(self, rec: Record) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    _rec_to_row(rec),
                )
            except sqlite3.IntegrityError as e:
                raise RecordIdConflict(rec.id) from e
            self._maybe_commit()

    def get(self, rec_id: str) -> Optional[Record]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM records WHERE id=?", (rec_id,))
            row = cur.fetchone()
            if row is None:
                return None
            rec = _row_to_rec(row)
            self._check_ttl(rec)
            return rec

    def list_slot(self, slot: Slot) -> List[Record]:
        # ORDER BY rowid, not "whatever the planner returns". Append order is
        # part of StoreProtocol: Kernel.current_view() folds this sequence
        # into a dict keyed by kind, so a later COMMIT supersedes an earlier
        # one only if it arrives later. `WHERE slot=?` can be served by
        # idx_slot (rowid order) or by idx_slot_kind_trace (kind order), both
        # legal, and the two disagree -- so without this the record that wins
        # is a planner decision. rowid is append order here: the table is not
        # WITHOUT ROWID and records are never deleted.
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM records WHERE slot=? ORDER BY rowid", (slot,))
            recs = [_row_to_rec(r) for r in cur.fetchall()]
            for r in recs:
                self._check_ttl(r)
            return recs

    def find_active_by_kind(self, slot: Slot, kind: str,
                            trace_id: str) -> Optional[Record]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM records "
                "WHERE slot=? AND kind=? AND trace_id=? AND status='ACTIVE' "
                "ORDER BY ts_ms ASC",
                (slot, kind, trace_id),
            )
            # TTL is evaluated lazily on read, so a row still marked ACTIVE may
            # in fact have expired. Walk the candidates rather than judging only
            # the oldest, or an expired record hides the live one behind it.
            for row in cur.fetchall():
                rec = _row_to_rec(row)
                self._check_ttl(rec)
                if rec.status == "ACTIVE":
                    return rec
            return None

    def invalidate(self, rec_id: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE records SET status='INVALIDATED', reason=? WHERE id=?",
                (reason, rec_id),
            )
            self._maybe_commit()

    # ── Extended queries (beyond StoreProtocol) ──────────────────────

    # These two return records in append order for the same reason list_slot
    # does, and are ordered explicitly for the same reason: an append-only
    # audit trail read back in an order the planner chose is not an audit
    # trail. `list_persistent(slot=...)` has the identical exposure to
    # list_slot today; `list_by_status` does not yet, and the ORDER BY keeps
    # it that way the day an index on (status, ...) is added.

    def list_by_status(self, status: str) -> List[Record]:
        """Return all records with the given status, in append order."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM records WHERE status=? ORDER BY rowid", (status,))
            return [_row_to_rec(r) for r in cur.fetchall()]

    def list_persistent(self, slot: Optional[str] = None) -> List[Record]:
        """Return all persistent-scope records in append order, optionally
        filtered by slot."""
        with self._lock:
            if slot:
                cur = self._conn.execute(
                    "SELECT * FROM records WHERE scope='persistent' AND slot=? "
                    "ORDER BY rowid",
                    (slot,),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM records WHERE scope='persistent' ORDER BY rowid")
            recs = [_row_to_rec(r) for r in cur.fetchall()]
            for r in recs:
                self._check_ttl(r)
            return recs

    def count_invalidated_by_reason(self) -> Dict[str, int]:
        """Return {reason: count} for all invalidated records."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT reason, COUNT(*) FROM records "
                "WHERE status='INVALIDATED' AND reason IS NOT NULL "
                "GROUP BY reason")
            return {row[0]: row[1] for row in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()

    # ── Internal ─────────────────────────────────────────────────────

    def _check_ttl(self, rec: Record) -> None:
        if rec.status == "ACTIVE" and rec.prov.ttl_ms is not None:
            now = int(time.time() * 1000)
            if now >= rec.prov.ts_ms + rec.prov.ttl_ms:
                rec.status = "EXPIRED"
                rec.reason = "TTL_EXPIRED"
                self._conn.execute(
                    "UPDATE records SET status='EXPIRED', reason='TTL_EXPIRED' "
                    "WHERE id=?", (rec.id,))
                self._maybe_commit()
