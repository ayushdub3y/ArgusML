"""Implements the human escalation queue (§2 node K).

Stores mid-p, high-V, or low-confidence disputes awaiting manual review,
prioritizing them by response deadline. Persisted in SQLite with WAL mode.
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


class EscalationQueue:
    """SQLite-backed escalation queue sorted by impending respond_by deadline."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "escalations.db")
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS escalation_queue (
                    dispute_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    respond_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_escalation_respond_by
                ON escalation_queue (respond_by ASC)
                """
            )
            conn.commit()

    def add(self, item: Dict[str, Any]) -> None:
        """Add an item to the escalation queue."""
        dispute_id = item.get("dispute_id")
        if not dispute_id:
            raise ValueError("Item must contain 'dispute_id'")
        respond_by = int(item.get("respond_by") or 0)
        payload_json = json.dumps(item)

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO escalation_queue (dispute_id, payload, respond_by)
                VALUES (?, ?, ?)
                ON CONFLICT(dispute_id) DO UPDATE SET
                    payload = excluded.payload,
                    respond_by = excluded.respond_by
                """,
                (dispute_id, payload_json, respond_by),
            )
            conn.commit()

    def get(self, dispute_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an item by dispute_id without removing it."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM escalation_queue WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            if row:
                return json.loads(row["payload"])
        return None

    def pop(self, dispute_id: str) -> Optional[Dict[str, Any]]:
        """Remove and return an item from the queue."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM escalation_queue WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "DELETE FROM escalation_queue WHERE dispute_id = ?",
                    (dispute_id,),
                )
                conn.commit()
                return json.loads(row["payload"])
        return None

    def all_pending(self) -> List[Dict[str, Any]]:
        """Return all pending escalations sorted by respond_by ascending."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM escalation_queue ORDER BY respond_by ASC"
            ).fetchall()
            return [json.loads(r["payload"]) for r in rows]

    def seconds_remaining(self, dispute_id: str, now_ts: Optional[int] = None) -> int:
        """Calculate seconds remaining before respond_by. Never returns negative."""
        if now_ts is None:
            now_ts = int(time.time())
        item = self.get(dispute_id)
        if not item:
            raise KeyError(f"Dispute {dispute_id} not found in escalation queue")
        respond_by = item.get("respond_by") or now_ts
        return max(0, int(respond_by - now_ts))

    def clear(self) -> None:
        """Clear the queue."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM escalation_queue")
            conn.commit()
