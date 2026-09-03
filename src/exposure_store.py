"""Implements the rolling cumulative-exposure store keyed on compound identity (§4, §6b).

Maintains rolling window counts and cumulative values of auto-accepted disputes per identity
to close velocity abuse loopholes before the per-dispute EV routing rule.
"""

import os
import sqlite3
import time
from typing import Optional, Tuple


class ExposureStore:
    """Cumulative exposure store implementing the §6b velocity gate.

    Tracks rolling cumulative auto-accepted dispute volume and frequency
    using a compound key of vpa_hash + device_fingerprint_hash. Composing
    both identifiers together ensures accurate tracking across devices and VPAs,
    preventing low-value, high-frequency abuse where individual disputes remain
    under static thresholds while accumulating substantial unmonitored losses.
    """

    def __init__(self, db_path: Optional[str] = None, window_days: int = 30):
        self.window_days = window_days
        self.window_seconds = window_days * 86400
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "exposure.db")
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
                CREATE TABLE IF NOT EXISTS auto_accept_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    compound_key TEXT NOT NULL,
                    vpa_hash TEXT NOT NULL,
                    device_fingerprint_hash TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exposure_compound_ts
                ON auto_accept_events (compound_key, timestamp)
                """
            )
            conn.commit()

    @staticmethod
    def make_compound_key(vpa_hash: str, device_fingerprint_hash: str) -> str:
        """Compose vpa_hash and device_fingerprint_hash into a canonical compound key."""
        return f"{vpa_hash}:{device_fingerprint_hash}"

    def record_accept(
        self,
        vpa_hash: str,
        device_fingerprint_hash: str,
        amount: int,
        timestamp: Optional[int] = None,
    ) -> None:
        """Record an auto-accepted dispute event."""
        if timestamp is None:
            timestamp = int(time.time())
        compound_key = self.make_compound_key(vpa_hash, device_fingerprint_hash)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO auto_accept_events
                (compound_key, vpa_hash, device_fingerprint_hash, amount, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (compound_key, vpa_hash, device_fingerprint_hash, amount, timestamp),
            )
            conn.commit()

    def get_exposure(
        self,
        vpa_hash: str,
        device_fingerprint_hash: str,
        now_ts: Optional[int] = None,
    ) -> Tuple[int, int]:
        """Get rolling (count, cumulative_value_paise) for the given compound identity.

        Returns:
            Tuple of (auto_accepted_count_window, auto_accepted_value_window_paise).
        """
        if now_ts is None:
            now_ts = int(time.time())
        cutoff_ts = now_ts - self.window_seconds
        compound_key = self.make_compound_key(vpa_hash, device_fingerprint_hash)

        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total_val
                FROM auto_accept_events
                WHERE compound_key = ? AND timestamp >= ? AND timestamp <= ?
                """,
                (compound_key, cutoff_ts, now_ts),
            ).fetchone()
            if row:
                return int(row["cnt"]), int(row["total_val"])
        return 0, 0

    def clear(self) -> None:
        """Clear all exposure history."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM auto_accept_events")
            conn.commit()
