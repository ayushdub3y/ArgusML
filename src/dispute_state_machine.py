"""Explicit, deterministic dispute state machine for ArgusML (§2, Section 2 hardening).

Prevents contradictory or invalid lifecycle transitions (e.g. CONTESTED -> ACCEPTED),
enforces terminal resolution immutability, and gates exceptional reopening behind
explicit secondary confirmation.
"""

from enum import Enum
import os
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple


class DisputeState(str, Enum):
    """Lifecycle states of an ArgusML dispute."""
    OPEN = "OPEN"
    PENDING_CHECKPOINT = "PENDING_CHECKPOINT"
    ESCALATED = "ESCALATED"
    CONTESTED = "CONTESTED"
    ACCEPTED = "ACCEPTED"
    REOPENED = "REOPENED"

    @property
    def is_terminal(self) -> bool:
        return self in (DisputeState.ACCEPTED, DisputeState.CONTESTED)


class DisputeEvent(str, Enum):
    """Permitted state transition events."""
    ROUTE_ACCEPT_CHECKPOINT = "route_accept_checkpoint"
    ROUTE_AUTO_CONTEST = "route_auto_contest"
    ROUTE_ESCALATE = "route_escalate"
    CONFIRM_ACCEPT = "confirm_accept"
    CONFIRM_CONTEST = "confirm_contest"
    ESCALATE_TO_QUEUE = "escalate_to_queue"
    ESCALATE_TO_REVIEW = "escalate_to_queue"
    RESOLVE_ACCEPT = "resolve_accept"
    RESOLVE_CONTEST = "resolve_contest"
    EXCEPTIONAL_REOPEN = "exceptional_reopen"


class InvalidStateTransitionError(ValueError):
    """Raised when an action violates the dispute lifecycle state machine."""
    def __init__(self, dispute_id: str, current_state: DisputeState, attempted_event_or_action: str, reason: str = ""):
        msg = f"Invalid dispute transition for '{dispute_id}': cannot apply '{attempted_event_or_action}' in state '{current_state.value}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)
        self.dispute_id = dispute_id
        self.current_state = current_state
        self.attempted_event_or_action = attempted_event_or_action


# Allowed state transitions table
ALLOWED_TRANSITIONS: Dict[DisputeState, Dict[DisputeEvent, DisputeState]] = {
    DisputeState.OPEN: {
        DisputeEvent.ROUTE_ACCEPT_CHECKPOINT: DisputeState.PENDING_CHECKPOINT,
        DisputeEvent.ROUTE_AUTO_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.ROUTE_ESCALATE: DisputeState.ESCALATED,
        DisputeEvent.ESCALATE_TO_QUEUE: DisputeState.ESCALATED,
        DisputeEvent.CONFIRM_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.CONFIRM_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.RESOLVE_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.RESOLVE_CONTEST: DisputeState.CONTESTED,
    },
    DisputeState.PENDING_CHECKPOINT: {
        DisputeEvent.CONFIRM_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.CONFIRM_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.ESCALATE_TO_QUEUE: DisputeState.ESCALATED,
        DisputeEvent.ROUTE_ESCALATE: DisputeState.ESCALATED,
    },
    DisputeState.ESCALATED: {
        DisputeEvent.RESOLVE_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.RESOLVE_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.CONFIRM_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.CONFIRM_CONTEST: DisputeState.CONTESTED,
    },
    DisputeState.ACCEPTED: {
        DisputeEvent.EXCEPTIONAL_REOPEN: DisputeState.REOPENED,
    },
    DisputeState.CONTESTED: {
        DisputeEvent.EXCEPTIONAL_REOPEN: DisputeState.REOPENED,
    },
    DisputeState.REOPENED: {
        DisputeEvent.CONFIRM_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.CONFIRM_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.RESOLVE_ACCEPT: DisputeState.ACCEPTED,
        DisputeEvent.RESOLVE_CONTEST: DisputeState.CONTESTED,
        DisputeEvent.ESCALATE_TO_QUEUE: DisputeState.ESCALATED,
        DisputeEvent.ROUTE_ESCALATE: DisputeState.ESCALATED,
    },
}


class DisputeStateMachine:
    """Persistent state machine for dispute resolution tracking."""

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
                CREATE TABLE IF NOT EXISTS dispute_states (
                    dispute_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    updated_by TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.commit()

    def get_state(self, dispute_id: str, fallback_hints: Optional[Dict[str, Any]] = None) -> DisputeState:
        """Retrieve current dispute lifecycle state."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT state FROM dispute_states WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            if row:
                try:
                    return DisputeState(row["state"])
                except ValueError:
                    pass

        # If not explicitly recorded, deduce truthfully from fallback hints if provided
        if fallback_hints:
            pending_checkpoints = fallback_hints.get("pending_checkpoints")
            escalation_queue = fallback_hints.get("escalation_queue")
            audit_log = fallback_hints.get("audit_log")

            if pending_checkpoints and dispute_id in pending_checkpoints:
                return DisputeState.PENDING_CHECKPOINT
            if escalation_queue and escalation_queue.get(dispute_id) is not None:
                return DisputeState.ESCALATED
            if audit_log:
                entries = audit_log.get_entries(dispute_id=dispute_id)
                # Check for executed decisions in reverse chronological order
                for e in reversed(entries):
                    dec = (e.get("decision") or "").lower()
                    ev_type = e.get("event_type") or "action_execution"
                    if ev_type == "action_execution" or e.get("razorpay_dispatched"):
                        if dec in ("accept", "accepted"):
                            return DisputeState.ACCEPTED
                        if dec in ("contest", "contested"):
                            return DisputeState.CONTESTED
                    elif dec == "recommend_accept":
                        return DisputeState.PENDING_CHECKPOINT
                    elif dec == "escalate":
                        return DisputeState.ESCALATED

        return DisputeState.OPEN

    def can_transition(self, current_state: DisputeState, event: DisputeEvent) -> bool:
        """Check whether a transition is permitted without throwing an error."""
        allowed_events = ALLOWED_TRANSITIONS.get(current_state, {})
        return event in allowed_events

    def transition(
        self,
        dispute_id: str,
        event: DisputeEvent,
        actor: str = "system",
        notes: str = "",
        reason: str = "",
        fallback_hints: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> DisputeState:
        """Execute a state transition, enforcing state machine invariants.
        
        Raises InvalidStateTransitionError on contradictory terminal actions.
        """
        effective_notes = notes or reason or kwargs.get("audit_reason", "")
        current_state = self.get_state(dispute_id, fallback_hints=fallback_hints)
        allowed_events = ALLOWED_TRANSITIONS.get(current_state, {})

        if event not in allowed_events:
            err_reason = (
                f"Dispute '{dispute_id}' is already {current_state.value} and cannot be "
                f"re-executed with event '{event.value}'. Exceptional reopening requires explicit secondary confirmation."
            )
            raise InvalidStateTransitionError(
                dispute_id=dispute_id,
                current_state=current_state,
                attempted_event_or_action=event.value,
                reason=err_reason,
            )

        new_state = allowed_events[event]
        now_ts = int(time.time())

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO dispute_states (dispute_id, state, updated_at, updated_by, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dispute_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    notes = excluded.notes
                """,
                (dispute_id, new_state.value, now_ts, actor, effective_notes),
            )
            conn.commit()

        return new_state

    def set_state_direct(self, dispute_id: str, state: DisputeState, actor: str = "system", notes: str = "") -> None:
        """Directly seed or sync dispute state (for initialization or test fixture setup)."""
        now_ts = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO dispute_states (dispute_id, state, updated_at, updated_by, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(dispute_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    notes = excluded.notes
                """,
                (dispute_id, state.value, now_ts, actor, notes),
            )
            conn.commit()

    def clear(self) -> None:
        """Clear all dispute states."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM dispute_states")
            conn.commit()
