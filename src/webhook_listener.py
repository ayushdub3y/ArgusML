import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Set

# Ensure repo root is in sys.path when run directly as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv("api.env")
    load_dotenv(".env")
    load_dotenv()
except ImportError:
    pass

from src.audit_log import AuditLog
from src.decision_engine import decide
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpoint, AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.model_b_evidence_assembler.assemble import assemble_contest_payload
from src.model_a_adjudicator.predict import predict
from src.razorpay_client import RazorpayClient
from src.ui.routes import create_ui_router


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# §2 Watchdog margin: 1 hour (3600 seconds) before respond_by deadline
WATCHDOG_MARGIN_SECONDS = 3600


class WebhookHandler:
    """Core webhook processing, deadline watchdog, and human review routing."""

    def __init__(
        self,
        evidence_store: Optional[EvidenceStore] = None,
        exposure_store: Optional[ExposureStore] = None,
        audit_log: Optional[AuditLog] = None,
        razorpay_client: Optional[RazorpayClient] = None,
        escalation_queue: Optional[EscalationQueue] = None,
        pending_checkpoints: Optional[Any] = None,
    ):
        self.evidence_store = evidence_store or EvidenceStore()
        self.exposure_store = exposure_store or ExposureStore()
        self.audit_log = audit_log or AuditLog()
        self.razorpay_client = razorpay_client or RazorpayClient()
        self.escalation_queue = escalation_queue or EscalationQueue()

        if pending_checkpoints is not None:
            self.pending_checkpoints = pending_checkpoints
            if hasattr(self.pending_checkpoints, "set_on_confirm"):
                self.pending_checkpoints.set_on_confirm(self._finalize_accept)
        else:
            self.pending_checkpoints = AcceptCheckpointStore(
                on_confirm_callback=self._finalize_accept
            )

        from src.drift_monitor import DriftMonitor
        self.drift_monitor = DriftMonitor()

        self.decided_disputes: Set[str] = set()

    def process_dispute_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming payment.dispute.created webhook event (§2)."""
        dispute_id = payload.get("id", "unknown_disp")
        payment = payload.get("payment", {})
        method = payment.get("method")
        reason_code = payload.get("reason_code")

        # 1. Reason-code + payment-method deterministic filter (§3, §4)
        if method != "upi" or reason_code != "goods_not_delivered":
            logger.info("Ignoring out-of-scope dispute %s (method=%s, reason=%s)", dispute_id, method, reason_code)
            return {"status": "ignored", "reason": "out_of_scope", "dispute_id": dispute_id}

        # 2. Webhook idempotency (§4)
        if dispute_id in self.decided_disputes:
            logger.info("Ignoring duplicate webhook for dispute %s", dispute_id)
            return {"status": "duplicate_webhook_ignored", "dispute_id": dispute_id}

        self.decided_disputes.add(dispute_id)

        # 3. Lookup merchant fulfillment evidence (§2 node C)
        order_id = payment.get("order_id", "")
        evidence = self.evidence_store.get_evidence(order_id) or {}

        # 4. Lookup cumulative exposure for identity (§2 node D2, §6b)
        dispute_ts = payload.get("created_at")
        if dispute_ts is None:
            if payload.get("respond_by"):
                dispute_ts = int(payload["respond_by"]) - 86400
            else:
                dispute_ts = int(time.time())

        buyer_id = evidence.get("buyer_identity", {})
        vpa_h = buyer_id.get("vpa_hash", "default_vpa")
        dev_h = buyer_id.get("device_fingerprint_hash", "default_dev")
        exp_count, exp_value = self.exposure_store.get_exposure(vpa_h, dev_h, now_ts=dispute_ts)

        # 5. Model A: Calibrated scoring + SHAP (§2 node E, §5)
        p, shap_values, features = predict(
            dispute_payload=payload,
            evidence_record=evidence,
            exposure_count=exp_count,
            exposure_value=exp_value,
        )
        self.drift_monitor.record_prediction(p)

        amount = int(payload.get("amount", 0))

        # 6. Deterministic EV & Velocity routing (§2 node F, §6, §6b)
        action, rule_fired, _ = decide(
            p_illegitimate=p,
            amount_paise=amount,
            exposure_count=exp_count,
            exposure_value_paise=exp_value,
        )

        respond_by = payload.get("respond_by")

        if action == "accept":
            # G0: Instantiate one-line reasoning card (§6b, Task 2)
            checkpoint = AcceptCheckpoint(
                dispute_id=dispute_id,
                amount=amount,
                p=p,
                v_cum=exp_value,
                rule_fired=rule_fired,
                respond_by=respond_by,
                features=features,
                shap_values=shap_values,
                evidence=evidence,
                buyer_dispute_history=evidence.get("buyer_dispute_history"),
                exposure_counters=(exp_count, exp_value),
                on_confirm=self._finalize_accept,
            )
            self.pending_checkpoints[dispute_id] = checkpoint

            # Initial audit entry: recommendation written by system
            self.audit_log.record(
                dispute_id=dispute_id,
                decision="accept",
                rule_fired=rule_fired,
                actor="system",
                features=features,
                shap_values=shap_values,
                evidence=evidence,
                exposure_counter=(exp_count, exp_value),
            )

            return {
                "status": "pending_human_accept",
                "dispute_id": dispute_id,
                "one_liner": checkpoint.render_one_liner(),
            }

        elif action == "contest":
            # Auto-contest with validated real evidence (§2 node H–J, §12)
            contest_payload = assemble_contest_payload(evidence)
            self.razorpay_client.contest_dispute(dispute_id, contest_payload)

            self.audit_log.record(
                dispute_id=dispute_id,
                decision="contest",
                rule_fired=rule_fired,
                actor="system",
                features=features,
                shap_values=shap_values,
                evidence=evidence,
                exposure_counter=(exp_count, exp_value),
            )

            return {"status": "contested", "dispute_id": dispute_id}

        else:
            # Escalate to human queue K (§2 node K)
            queue_item = {
                "dispute_id": dispute_id,
                "amount": amount,
                "p": p,
                "respond_by": respond_by or 0,
                "rule_fired": rule_fired,
                "features": features,
                "shap_values": shap_values,
                "evidence": evidence,
                "exposure_counters": (exp_count, exp_value),
            }
            self.escalation_queue.add(queue_item)

            self.audit_log.record(
                dispute_id=dispute_id,
                decision="escalate",
                rule_fired=rule_fired,
                actor="system",
                features=features,
                shap_values=shap_values,
                evidence=evidence,
                exposure_counter=(exp_count, exp_value),
            )

            return {"status": "escalated", "dispute_id": dispute_id}

    def _finalize_accept(self, checkpoint: AcceptCheckpoint) -> None:
        """Finalize accept after confirmation: calls Razorpay, updates exposure, and logs audit trail (Task 3)."""
        dispute_id = checkpoint.dispute_id
        try:
            self.razorpay_client.accept_dispute(dispute_id)
        except Exception as e:
            logger.warning("Razorpay accept call failed for dispute %s: %s", dispute_id, e)

        # Update cumulative exposure store
        evidence = checkpoint.evidence
        buyer_id = evidence.get("buyer_identity", {})
        vpa_h = buyer_id.get("vpa_hash", "default_vpa")
        dev_h = buyer_id.get("device_fingerprint_hash", "default_dev")
        self.exposure_store.record_accept(vpa_h, dev_h, checkpoint.amount)

        # Remove from pending checkpoints
        self.pending_checkpoints.pop(dispute_id, None)

        # Audit-log the actual accept confirmation per Task 3
        actor = checkpoint.confirmed_by or "human"
        self.audit_log.record(
            dispute_id=dispute_id,
            decision="accept",
            rule_fired=f"accept_checkpoint_confirmed:{actor}",
            actor=actor,
            features=checkpoint.features,
            shap_values=checkpoint.shap_values,
            evidence=checkpoint.evidence,
            exposure_counter=checkpoint.exposure_counters,
        )

    def deadline_watchdog_tick(self, now_ts: Optional[int] = None) -> List[str]:
        """Check pending accept checkpoints against respond_by deadline (§2 node O, Task 2).

        Force-accepts any pending checkpoint within WATCHDOG_MARGIN_SECONDS.
        Safely skips checkpoints with missing respond_by with a warning.
        """
        if now_ts is None:
            now_ts = int(time.time())

        force_accepted: List[str] = []
        pending_list = list(self.pending_checkpoints.values())

        for checkpoint in pending_list:
            if checkpoint.respond_by is None:
                logger.warning("Checkpoint %s missing respond_by; skipping watchdog check", checkpoint.dispute_id)
                continue

            time_left = checkpoint.respond_by - now_ts
            if time_left <= WATCHDOG_MARGIN_SECONDS:
                logger.warning(
                    "Watchdog force-accepting dispute %s (time_left=%ds <= margin=%ds)",
                    checkpoint.dispute_id,
                    time_left,
                    WATCHDOG_MARGIN_SECONDS,
                )
                if checkpoint.confirm(actor="watchdog"):
                    force_accepted.append(checkpoint.dispute_id)

        return force_accepted

    def resolve_escalation(
        self,
        dispute_id: str,
        action: str,
        actor: str = "human",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Resolve a pending escalation manually (§2 node K)."""
        if action not in ("accept", "contest"):
            raise ValueError(f"Invalid escalation resolution action: {action}. Must be 'accept' or 'contest'.")

        item = self.escalation_queue.pop(dispute_id)
        if item is None:
            raise ValueError(f"Dispute {dispute_id} not found in escalation queue.")

        evidence = item.get("evidence", {})
        if action == "accept":
            try:
                self.razorpay_client.accept_dispute(dispute_id)
            except Exception as e:
                logger.warning("Razorpay accept call failed during escalation resolution for %s: %s", dispute_id, e)
            buyer_id = evidence.get("buyer_identity", {})
            vpa_h = buyer_id.get("vpa_hash", "default_vpa")
            dev_h = buyer_id.get("device_fingerprint_hash", "default_dev")
            self.exposure_store.record_accept(vpa_h, dev_h, item.get("amount", 0))
        else:
            contest_payload = assemble_contest_payload(evidence, human_notes=notes or None)
            self.razorpay_client.contest_dispute(dispute_id, contest_payload)

        self.audit_log.record(
            dispute_id=dispute_id,
            decision=action,
            rule_fired=f"human_escalation_override:{action}",
            actor=actor,
            features=item.get("features"),
            shap_values=item.get("shap_values"),
            evidence=evidence,
            exposure_counter=item.get("exposure_counters"),
        )

        return {"status": f"escalation_resolved_{action}", "dispute_id": dispute_id, "actor": actor}


# Singleton handler for server mode
handler = WebhookHandler()


def create_app(handler_instance: Optional[WebhookHandler] = None):
    """Create FastAPI ASGI app for webhook listener and dashboard."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    active_handler = handler_instance or handler
    app = FastAPI(title="Aegis Dispute-Defense Engine", version="1.0.0")

    # Check and log fail-open defaults
    if not os.environ.get("RAZORPAY_WEBHOOK_SECRET") or not os.environ.get("DASHBOARD_USERNAME"):
        logger.warning(
            "WARNING: Aegis running with fail-open defaults (RAZORPAY_WEBHOOK_SECRET unset or DASHBOARD_USERNAME unset). "
            "Webhook signatures and/or dashboard auth are not enforced. Set these environment variables in production."
        )

    # Mount UI routes (dashboard, accept confirm/expand)
    app.include_router(create_ui_router(active_handler))

    @app.post("/webhook")
    async def webhook_endpoint(request: Request):
        try:
            body_bytes = await request.body()
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

        secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
        if secret:
            signature = request.headers.get("X-Razorpay-Signature")
            if not signature or not active_handler.razorpay_client.verify_webhook_signature(
                body_bytes, signature, secret
            ):
                return JSONResponse(status_code=400, content={"error": "Invalid webhook signature"})

        result = active_handler.process_dispute_created(body)
        return JSONResponse(status_code=200, content=result)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    print("Starting Aegis Webhook Listener on 0.0.0.0:8080...")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
