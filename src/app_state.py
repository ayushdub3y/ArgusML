"""Global application state holder for Aegis (§2).

Provides unified access to active persistent stores, escalation queue,
pending accept checkpoints, and the central WebhookHandler.
"""

from typing import Any, Optional
from src.audit_log import AuditLog
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.razorpay_client import RazorpayClient


class AppState:
    """Manages application-wide persistent store references and active handler."""

    def __init__(self, handler: Optional[Any] = None):
        self._handler = handler

    @property
    def handler(self) -> Any:
        if self._handler is None:
            from src.webhook_listener import handler as default_handler
            self._handler = default_handler
        return self._handler

    @handler.setter
    def handler(self, value: Any) -> None:
        self._handler = value

    @property
    def pending_accepts(self) -> Any:
        """Access pending accept checkpoints (dict-like persistent store)."""
        return self.handler.pending_checkpoints

    @property
    def escalation_queue(self) -> EscalationQueue:
        """Access persistent human escalation queue."""
        return self.handler.escalation_queue

    @property
    def evidence_store(self) -> EvidenceStore:
        return self.handler.evidence_store

    @property
    def exposure_store(self) -> ExposureStore:
        return self.handler.exposure_store

    @property
    def audit_log(self) -> AuditLog:
        return self.handler.audit_log

    @property
    def razorpay_client(self) -> RazorpayClient:
        return self.handler.razorpay_client


# Module-level singleton
app_state = AppState()
