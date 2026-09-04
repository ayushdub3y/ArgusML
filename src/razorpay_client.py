"""Implements test-mode Razorpay Disputes API client and payload builders (§2, §4, §13).

Supports two operating modes:
1. **Live test-mode**: When RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are set,
   makes real HTTP calls to Razorpay's test-mode Disputes API.
2. **Sandbox mock**: When credentials are absent, logs the action and returns
   a simulated response for local development and demo.
"""

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx


logger = logging.getLogger(__name__)

# Razorpay API timeout for test-mode calls
_API_TIMEOUT = 10.0


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


def check_evidence_sufficiency(evidence: Dict[str, Any]) -> Tuple[bool, list, list]:
    """Deterministically analyze whether merchant records contain affirmative proof of fulfillment.

    Under NPCI UDIR dispute rules, contesting a Goods Not Delivered claim requires affirmative proof:
    - For physical goods: confirmed delivery OTP or a courier POD document.
    - For digital goods: confirmed voucher redemption timestamp.

    Returns:
        (is_sufficient, verified_facts, missing_facts)
    """
    if not evidence:
        return False, [], ["No merchant fulfillment records found for order"]

    fulfillment_type = evidence.get("fulfillment_type", "physical")
    verified = []
    missing = []

    if fulfillment_type == "digital_voucher":
        redemption_ts = evidence.get("digital_redemption_ts")
        if redemption_ts:
            verified.append(f"Digital voucher redeemed at Unix timestamp {redemption_ts}")
            return True, verified, missing
        else:
            missing.append("digital redemption timestamp missing / unredeemed")
            return False, verified, missing

    # Physical goods
    otp_confirmed = bool(evidence.get("delivery_otp_confirmed"))
    pod_id = evidence.get("pod_document_id")
    geotag = evidence.get("delivery_geotag")
    delivery_ts = evidence.get("delivery_ts")

    if otp_confirmed:
        verified.append("delivery OTP confirmed by recipient")
    else:
        missing.append("delivery OTP unconfirmed")

    if pod_id:
        verified.append(f"courier POD document on file ({pod_id})")
    else:
        missing.append("courier POD document missing")

    if geotag:
        verified.append(f"delivery geotag recorded ({geotag})")

    if delivery_ts:
        verified.append(f"delivery recorded at timestamp {delivery_ts}")

    # Sufficient if either delivery OTP is confirmed or courier POD document exists
    is_sufficient = otp_confirmed or bool(pod_id)
    return is_sufficient, verified, missing


def build_contest_payload_from_evidence(
    evidence: Dict[str, Any],
    summary_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct structured contest payload conforming to Razorpay PATCH /v1/disputes/{id}/contest (§4, §13).

    Builds typed evidence attachments (shipping_proof, digital redemption proof)
    purely from merchant source records without fabrication (§12).
    """
    order_id = evidence.get("order_id", "unknown") if evidence else "unknown"
    fulfillment_type = evidence.get("fulfillment_type", "physical") if evidence else "physical"
    is_sufficient, verified_facts, missing_facts = check_evidence_sufficiency(evidence)

    if summary_text:
        summary = summary_text
    elif is_sufficient:
        summary = f"Order {order_id} fulfillment verified per merchant records: {'; '.join(verified_facts)}."
    else:
        missing_desc = "; ".join(missing_facts) if missing_facts else "no proof of delivery on record"
        summary = (
            f"Merchant fulfillment records for Order {order_id} are incomplete ({missing_desc}). "
            "Evidence is insufficient to substantiate an affirmative delivery contest under NPCI UDIR guidelines."
        )

    payload: Dict[str, Any] = {
        "summary": summary,
    }

    if fulfillment_type == "digital_voucher":
        redemption_ts = evidence.get("digital_redemption_ts") if evidence else None
        if redemption_ts and str(redemption_ts) not in payload["summary"]:
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
            "dispatch_ts": evidence.get("dispatch_ts") if evidence else None,
            "delivery_ts": evidence.get("delivery_ts") if evidence else None,
            "delivery_otp_confirmed": bool(evidence.get("delivery_otp_confirmed")) if evidence else False,
        }
        if evidence and evidence.get("pod_document_id"):
            shipping_proof["pod_document_id"] = evidence.get("pod_document_id")
        if evidence and evidence.get("delivery_geotag"):
            shipping_proof["delivery_geotag"] = evidence.get("delivery_geotag")

        payload["shipping_proof"] = shipping_proof

    return payload


class RazorpayClient:
    """Razorpay Disputes API client with official test-mode HTTP support and local sandbox fallback (§13).

    Integrates with Razorpay's Disputes API in **Test Mode** (using rzp_test_... keys).
    Supports two operating modes:
    1. **Official Test-Mode API**: When RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are configured,
       executes real authenticated HTTP requests against https://api.razorpay.com/v1.
       (Note: No real financial money or production bank accounts are debited/credited).
    2. **Local Sandbox Mock**: When credentials are absent, logs the intent and returns
       simulated responses for deterministic local testing, automated evaluation, and offline demo.
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        base_url: str = "https://api.razorpay.com/v1",
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")
        self.base_url = base_url
        self._is_live = bool(self.key_id and self.key_secret)

        if self._is_live:
            logger.info("RazorpayClient initialized in OFFICIAL TEST-MODE (HTTP calls enabled to %s with test credentials)", self.base_url)
        else:
            logger.info("RazorpayClient initialized in LOCAL SANDBOX MOCK MODE (simulated responses, no outbound network calls)")

    @property
    def is_live(self) -> bool:
        """Whether real HTTP calls to the Razorpay test-mode API are enabled."""
        return self._is_live

    @property
    def is_test_mode(self) -> bool:
        """Explicit alias indicating whether test-mode API calls are active."""
        return self._is_live

    def verify_webhook_signature(
        self, body_bytes: bytes, signature: Optional[str], secret: Optional[str] = None
    ) -> bool:
        """Verify webhook signature against specified secret or client key_secret."""
        sec = secret or self.key_secret
        return verify_webhook_signature(body_bytes, signature, sec)

    def accept_dispute(self, dispute_id: str) -> Dict[str, Any]:
        """Call POST /v1/disputes/{id}/accept.

        In live test-mode, makes an authenticated HTTP POST to Razorpay.
        In sandbox mode, returns a simulated response.
        """
        if self._is_live:
            return self._api_post(f"/disputes/{dispute_id}/accept")

        logger.info("Sandbox: POST /v1/disputes/%s/accept", dispute_id)
        return {
            "id": dispute_id,
            "status": "lost",
            "phase": "chargeback",
            "mock": True,
            "sandbox": True,
        }

    def contest_dispute(self, dispute_id: str, contest_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Call PATCH /v1/disputes/{id}/contest with evidence payload.

        In live test-mode, makes an authenticated HTTP PATCH to Razorpay.
        In sandbox mode, returns a simulated response.
        """
        if self._is_live:
            return self._api_patch(f"/disputes/{dispute_id}/contest", json_body=contest_payload)

        logger.info("Sandbox: PATCH /v1/disputes/%s/contest: %s", dispute_id, contest_payload)
        return {
            "id": dispute_id,
            "status": "under_review",
            "phase": "pre_arbitration",
            "contest_payload": contest_payload,
            "mock": True,
            "sandbox": True,
        }

    def _api_post(self, path: str, json_body: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute authenticated POST request to Razorpay API."""
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.post(
                url,
                json=json_body or {},
                auth=(self.key_id, self.key_secret),
                timeout=_API_TIMEOUT,
            )
            resp.raise_for_status()
            logger.info("Razorpay API POST %s → %d", path, resp.status_code)
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("Razorpay API POST %s failed: %d %s", path, e.response.status_code, e.response.text)
            return {"error": str(e), "status_code": e.response.status_code, "dispute_path": path}
        except httpx.RequestError as e:
            logger.error("Razorpay API POST %s network error: %s", path, e)
            return {"error": str(e), "network_error": True, "dispute_path": path}

    def _api_patch(self, path: str, json_body: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute authenticated PATCH request to Razorpay API."""
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.patch(
                url,
                json=json_body or {},
                auth=(self.key_id, self.key_secret),
                timeout=_API_TIMEOUT,
            )
            resp.raise_for_status()
            logger.info("Razorpay API PATCH %s → %d", path, resp.status_code)
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.warning("Razorpay API PATCH %s failed: %d %s", path, e.response.status_code, e.response.text)
            return {"error": str(e), "status_code": e.response.status_code, "dispute_path": path}
        except httpx.RequestError as e:
            logger.error("Razorpay API PATCH %s network error: %s", path, e)
            return {"error": str(e), "network_error": True, "dispute_path": path}
