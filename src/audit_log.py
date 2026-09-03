"""Implements the immutable audit log: features, SHAP, action, evidence payload, cumulative counters (§2, node L)."""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


class AuditLog:
    """Immutable SQLite audit log for all dispute decisions and confirmations."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "audit_log.db")
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
                CREATE TABLE IF NOT EXISTS audit_trail (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispute_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rule_fired TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    features TEXT,
                    shap_values TEXT,
                    evidence TEXT,
                    exposure_counter TEXT,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_dispute
                ON audit_trail (dispute_id, timestamp)
                """
            )
            conn.commit()

    def record(
        self,
        dispute_id: str,
        decision: str,
        rule_fired: str,
        actor: str = "system",
        features: Optional[Dict[str, Any]] = None,
        shap_values: Optional[Any] = None,
        evidence: Optional[Dict[str, Any]] = None,
        exposure_counter: Optional[Any] = None,
        timestamp: Optional[int] = None,
    ) -> int:
        """Append an entry to the immutable audit log."""
        if timestamp is None:
            timestamp = int(time.time())

        features_json = json.dumps(features) if features is not None else None
        shap_json = json.dumps(shap_values) if shap_values is not None else None
        evidence_json = json.dumps(evidence) if evidence is not None else None
        exposure_json = json.dumps(exposure_counter) if exposure_counter is not None else None

        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_trail
                (dispute_id, decision, rule_fired, actor, features, shap_values, evidence, exposure_counter, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dispute_id,
                    decision,
                    rule_fired,
                    actor,
                    features_json,
                    shap_json,
                    evidence_json,
                    exposure_json,
                    timestamp,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_entries(
        self, dispute_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve audit entries, optionally filtered by dispute_id and capped by limit.

        When limit is provided, retrieves the latest entries ordered by id DESC.
        Otherwise preserves chronological id ASC ordering.
        """
        with self._get_conn() as conn:
            if dispute_id and limit:
                rows = conn.execute(
                    "SELECT * FROM audit_trail WHERE dispute_id = ? ORDER BY id DESC LIMIT ?",
                    (dispute_id, limit),
                ).fetchall()
            elif dispute_id:
                rows = conn.execute(
                    "SELECT * FROM audit_trail WHERE dispute_id = ? ORDER BY id ASC",
                    (dispute_id,),
                ).fetchall()
            elif limit:
                rows = conn.execute(
                    "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM audit_trail ORDER BY id ASC").fetchall()

            entries = []
            for r in rows:
                entries.append({
                    "id": r["id"],
                    "dispute_id": r["dispute_id"],
                    "decision": r["decision"],
                    "rule_fired": r["rule_fired"],
                    "actor": r["actor"],
                    "features": json.loads(r["features"]) if r["features"] else None,
                    "shap_values": json.loads(r["shap_values"]) if r["shap_values"] else None,
                    "evidence": json.loads(r["evidence"]) if r["evidence"] else None,
                    "exposure_counter": json.loads(r["exposure_counter"]) if r["exposure_counter"] else None,
                    "timestamp": r["timestamp"],
                })
            return entries

    def clear(self) -> None:
        """Clear all audit entries."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM audit_trail")
            conn.commit()
