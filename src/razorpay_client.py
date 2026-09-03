"""Implements test-mode Razorpay Disputes API client and payload builders (§2, §4, §13)."""

import hashlib
import hmac
import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def verify_webhook_signature(body_bytes: bytes, signature: Optional[str], secret: Optional[str]) -> bool:
    """Verify Razorpay webhook signature (pure function, no network calls).

    Args:
        body_bytes: Raw request body in bytes.
        signature: X-Razorpay-Signature header value.
        secret: Webhook secret configured for verification.

    Returns:
        True if signature matches HMAC SHA256 of body, False otherwise.
    """
    if not signature or not secret or not body_bytes:
        return False

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature)


def build_contest_payload_from_evidence(
    evidence: Dict[str, Any],
    summary_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct structured contest payload conforming to Razorpay PATCH /v1/disputes/{id}/contest (§4, §13).

    Builds typed evidence attachments (shipping_proof, digital redemption proof)
    purely from merchant source records without fabrication (§12).
    """
    order_id = evidence.get("order_id", "unknown")
    fulfillment_type = evidence.get("fulfillment_type", "physical")

    payload: Dict[str, Any] = {
        "summary": summary_text or f"Order {order_id} fulfilled legitimately per merchant records.",
    }

    if fulfillment_type == "digital_voucher":
        redemption_ts = evidence.get("digital_redemption_ts")
        if redemption_ts:
            payload["summary"] += f" Digital voucher redeemed at Unix timestamp {redemption_ts}."
        payload["digital_delivery"] = {
            "order_id": order_id,
            "redemption_ts": redemption_ts,
            "fulfillment_type": "digital_voucher",
        }
    else:
        # Physical goods
        shipping_proof: Dict[str, Any] = {
            "order_id": order_id,
            "dispatch_ts": evidence.get("dispatch_ts"),
            "delivery_ts": evidence.get("delivery_ts"),
            "delivery_otp_confirmed": bool(evidence.get("delivery_otp_confirmed")),
        }
        if evidence.get("pod_document_id"):
            shipping_proof["pod_document_id"] = evidence.get("pod_document_id")
        if evidence.get("delivery_geotag"):
            shipping_proof["delivery_geotag"] = evidence.get("delivery_geotag")

        payload["shipping_proof"] = shipping_proof

    return payload


class RazorpayClient:
    """Sandbox / test-mode client for Razorpay Disputes API (§13)."""

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: str = "https://api.razorpay.com/v1",
    ):
        self.key_id = key_id
        self.key_secret = key_secret
        self.base_url = base_url

    def verify_webhook_signature(
        self, body_bytes: bytes, signature: Optional[str], secret: Optional[str] = None
    ) -> bool:
        """Verify webhook signature against specified secret or client key_secret."""
        sec = secret or self.key_secret
        return verify_webhook_signature(body_bytes, signature, sec)

    def accept_dispute(self, dispute_id: str) -> Dict[str, Any]:
        """Call POST /v1/disputes/{id}/accept in sandbox/test mode."""
        logger.info("Sandbox Razorpay POST /v1/disputes/%s/accept", dispute_id)
        # Sandbox simulated response per Razorpay Disputes API
        return {
            "id": dispute_id,
            "status": "lost",
            "phase": "chargeback",
            "mock": True,
        }

    def contest_dispute(self, dispute_id: str, contest_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call PATCH /v1/disputes/{id}/contest in sandbox/test mode."""
        logger.info("Sandbox Razorpay PATCH /v1/disputes/%s/contest: %s", dispute_id, contest_payload)
        return {
            "id": dispute_id,
            "status": "under_review",
            "phase": "pre_arbitration",
            "contest_payload": contest_payload,
            "mock": True,
        }
