"""Implements the merchant/PA-side evidence store (§2 node C, §4).

Stores delivery OTP, courier POD, geotag, redemption timestamp, buyer dispute history,
and fulfillment records indexed by order_id.
"""

import json
import os
import sqlite3
from typing import Any, Dict, Optional


class EvidenceStore:
    """Merchant/PA-side evidence store backed by SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "evidence.db")
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
                CREATE TABLE IF NOT EXISTS evidence (
                    order_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def save_evidence(self, evidence: Dict[str, Any]) -> None:
        """Save or update an evidence record keyed by order_id."""
        order_id = evidence.get("order_id")
        if not order_id:
            raise ValueError("Evidence record must contain an 'order_id'")
        payload_json = json.dumps(evidence)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO evidence (order_id, payload)
                VALUES (?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    payload = excluded.payload
                """,
                (order_id, payload_json),
            )
            conn.commit()

    def get_evidence(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve evidence record by order_id, returning None if not found."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM evidence WHERE order_id = ?", (order_id,)
            ).fetchone()
            if row:
                return json.loads(row["payload"])
        return None

    def clear(self) -> None:
        """Clear all records in the evidence store."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM evidence")
            conn.commit()
