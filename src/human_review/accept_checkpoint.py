"""Implements §6b human review checkpoint on the accept path: one-line reasoning card + expand-for-full-log + single Accept tap.

Includes SQLite-backed AcceptCheckpointStore with WAL mode for process durability across restarts.
"""

import json
import os
import sqlite3
from typing import Any, Callable, Dict, Iterator, List, Optional


class AcceptCheckpoint:
    """Single-tap human review card for auto-accept candidates (§6b).

    Holds recommendation details, dispute deadline, SHAP explanations,
    and handles idempotent confirmation by either a human reviewer or
    the deadline watchdog fallback.
    """

    def __init__(
        self,
        dispute_id: str,
        amount: int,
        p: float,
        v_cum: int,
        rule_fired: str,
        respond_by: Optional[int] = None,
        features: Optional[Dict[str, Any]] = None,
        shap_values: Optional[Any] = None,
        evidence: Optional[Dict[str, Any]] = None,
        buyer_dispute_history: Optional[Dict[str, Any]] = None,
        exposure_counters: Optional[Any] = None,
        on_confirm: Optional[Callable[["AcceptCheckpoint"], None]] = None,
    ):
        self.dispute_id = dispute_id
        self.amount = amount
        self.p = p
        self.v_cum = v_cum
        self.rule_fired = rule_fired
        self.respond_by = respond_by
        self.features = features or {}
        self.shap_values = shap_values
        self.evidence = evidence or {}
        self.buyer_dispute_history = buyer_dispute_history or {}
        self.exposure_counters = exposure_counters
        self.on_confirm = on_confirm

        self.confirmed = False
        self.confirmed_by: Optional[str] = None

    def render_one_liner(self) -> str:
        """Render one-line reasoning card per §6b."""
        v_rupees = self.amount / 100.0
        v_cum_rupees = self.v_cum / 100.0
        return (
            f"p={self.p:.2f}, V=₹{v_rupees:.0f}, V_cum(30d)=₹{v_cum_rupees:.0f}, "
            f"rule: {self.rule_fired} — recommend Accept"
        )

    def expand(self) -> Dict[str, Any]:
        """Expand card for full reasoning breakdown, SHAP, and evidence records."""
        return {
            "dispute_id": self.dispute_id,
            "amount": self.amount,
            "p": self.p,
            "v_cum": self.v_cum,
            "rule_fired": self.rule_fired,
            "respond_by": self.respond_by,
            "features": self.features,
            "shap_values": self.shap_values,
            "evidence": self.evidence,
            "buyer_dispute_history": self.buyer_dispute_history,
            "exposure_counters": self.exposure_counters,
            "confirmed": self.confirmed,
            "confirmed_by": self.confirmed_by,
        }

    def confirm(self, actor: str = "human") -> bool:
        """Confirm the accept action. Idempotent: subsequent calls are no-ops."""
        if self.confirmed:
            return False

        self.confirmed = True
        self.confirmed_by = actor

        if self.on_confirm is not None:
            self.on_confirm(self)
        return True


class AcceptCheckpointStore:
    """SQLite-backed persistent store for pending accept checkpoints with dict-like interface."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        on_confirm_callback: Optional[Callable[[AcceptCheckpoint], None]] = None,
    ):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, "data", "checkpoints.db")
        self.db_path = db_path
        self._on_confirm_callback = on_confirm_callback

        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def set_on_confirm(self, callback: Optional[Callable[[AcceptCheckpoint], None]]) -> None:
        """Dynamically set or rebind the on_confirm callback."""
        self._on_confirm_callback = callback

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
                CREATE TABLE IF NOT EXISTS pending_checkpoints (
                    dispute_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    respond_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_checkpoint_respond_by
                ON pending_checkpoints (respond_by ASC)
                """
            )
            conn.commit()

    def _deserialize_checkpoint(self, payload_dict: Dict[str, Any]) -> AcceptCheckpoint:
        """Reconstruct AcceptCheckpoint instance and attach active on_confirm callback."""
        cp = AcceptCheckpoint(
            dispute_id=payload_dict["dispute_id"],
            amount=payload_dict["amount"],
            p=payload_dict["p"],
            v_cum=payload_dict["v_cum"],
            rule_fired=payload_dict["rule_fired"],
            respond_by=payload_dict.get("respond_by"),
            features=payload_dict.get("features"),
            shap_values=payload_dict.get("shap_values"),
            evidence=payload_dict.get("evidence"),
            buyer_dispute_history=payload_dict.get("buyer_dispute_history"),
            exposure_counters=payload_dict.get("exposure_counters"),
            on_confirm=self._on_confirm_callback,
        )
        cp.confirmed = bool(payload_dict.get("confirmed", False))
        cp.confirmed_by = payload_dict.get("confirmed_by")
        return cp

    def save(self, checkpoint: AcceptCheckpoint) -> None:
        """Persist checkpoint data fields to SQLite, omitting the live closure."""
        data = {
            "dispute_id": checkpoint.dispute_id,
            "amount": checkpoint.amount,
            "p": checkpoint.p,
            "v_cum": checkpoint.v_cum,
            "rule_fired": checkpoint.rule_fired,
            "respond_by": checkpoint.respond_by,
            "features": checkpoint.features,
            "shap_values": checkpoint.shap_values,
            "evidence": checkpoint.evidence,
            "buyer_dispute_history": checkpoint.buyer_dispute_history,
            "exposure_counters": checkpoint.exposure_counters,
            "confirmed": checkpoint.confirmed,
            "confirmed_by": checkpoint.confirmed_by,
        }
        payload_json = json.dumps(data)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_checkpoints (dispute_id, payload, respond_by)
                VALUES (?, ?, ?)
                ON CONFLICT(dispute_id) DO UPDATE SET
                    payload = excluded.payload,
                    respond_by = excluded.respond_by
                """,
                (checkpoint.dispute_id, payload_json, checkpoint.respond_by),
            )
            conn.commit()

    def get(self, dispute_id: str, default: Any = None) -> Any:
        """Retrieve checkpoint by dispute_id, returning reconstructed instance or default."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM pending_checkpoints WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            if row:
                return self._deserialize_checkpoint(json.loads(row["payload"]))
        return default

    def pop(self, dispute_id: str, default: Any = None) -> Any:
        """Remove and return checkpoint from store."""
        cp = self.get(dispute_id, default=None)
        if cp is not None:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM pending_checkpoints WHERE dispute_id = ?",
                    (dispute_id,),
                )
                conn.commit()
            return cp
        return default

    def values(self) -> List[AcceptCheckpoint]:
        """Return list of all active pending checkpoints."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT payload FROM pending_checkpoints ORDER BY respond_by ASC"
            ).fetchall()
            return [self._deserialize_checkpoint(json.loads(r["payload"])) for r in rows]

    def clear(self) -> None:
        """Clear all pending checkpoints."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM pending_checkpoints")
            conn.commit()

    def __getitem__(self, dispute_id: str) -> AcceptCheckpoint:
        cp = self.get(dispute_id)
        if cp is None:
            raise KeyError(dispute_id)
        return cp

    def __setitem__(self, dispute_id: str, checkpoint: AcceptCheckpoint) -> None:
        self.save(checkpoint)

    def __delitem__(self, dispute_id: str) -> None:
        if self.pop(dispute_id) is None:
            raise KeyError(dispute_id)

    def __contains__(self, dispute_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM pending_checkpoints WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            return row is not None

    def __len__(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM pending_checkpoints").fetchone()
            return int(row["cnt"]) if row else 0

    def __iter__(self) -> Iterator[str]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT dispute_id FROM pending_checkpoints").fetchall()
            return iter([r["dispute_id"] for r in rows])
