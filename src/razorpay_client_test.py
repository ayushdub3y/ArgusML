"""Test suite for Razorpay client and payload builders (§4, §13, Task 4)."""

import hashlib
import hmac
import pytest
from src.razorpay_client import (
    RazorpayClient,
    build_contest_payload_from_evidence,
    verify_webhook_signature,
)


def test_verify_webhook_signature():
    """Verify webhook signature verification accepts valid HMAC-SHA256 and rejects invalid/missing."""
    secret = "test_webhook_secret_key_123"
    body = b'{"event":"payment.dispute.created","id":"disp_123"}'
    valid_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Valid signature
    assert verify_webhook_signature(body, valid_sig, secret) is True

    # Tampered body
    tampered_body = b'{"event":"payment.dispute.created","id":"disp_999"}'
    assert verify_webhook_signature(tampered_body, valid_sig, secret) is False

    # Tampered signature
    assert verify_webhook_signature(body, "invalid_sig_abc123", secret) is False

    # Missing signature or secret
    assert verify_webhook_signature(body, None, secret) is False
    assert verify_webhook_signature(body, valid_sig, "") is False
    assert verify_webhook_signature(b"", valid_sig, secret) is False


def test_build_contest_payload_full_evidence():
    """Verify contest payload construction for full physical evidence with POD and geotag."""
    evidence = {
        "order_id": "order_full_001",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735550000,
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_789",
        "delivery_geotag": [12.9716, 77.5946],
    }

    payload = build_contest_payload_from_evidence(evidence)
    assert "summary" in payload
    assert "shipping_proof" in payload

    proof = payload["shipping_proof"]
    assert proof["order_id"] == "order_full_001"
    assert proof["dispatch_ts"] == 1735500000
    assert proof["delivery_ts"] == 1735550000
    assert proof["delivery_otp_confirmed"] is True
    assert proof["pod_document_id"] == "doc_pod_789"
    assert proof["delivery_geotag"] == [12.9716, 77.5946]


def test_build_contest_payload_missing_pod():
    """Verify contest payload construction when POD document is missing."""
    evidence = {
        "order_id": "order_no_pod_002",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735550000,
        "delivery_otp_confirmed": True,
        "pod_document_id": None,
        "delivery_geotag": None,
    }

    payload = build_contest_payload_from_evidence(evidence)
    assert "shipping_proof" in payload
    proof = payload["shipping_proof"]
    assert proof["order_id"] == "order_no_pod_002"
    assert "pod_document_id" not in proof
    assert "delivery_geotag" not in proof
    assert proof["delivery_otp_confirmed"] is True


def test_build_contest_payload_digital_voucher():
    """Verify contest payload construction for digital voucher fulfillment."""
    evidence = {
        "order_id": "order_voucher_003",
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": 1735550500,
    }

    payload = build_contest_payload_from_evidence(evidence)
    assert "digital_delivery" in payload
    assert "shipping_proof" not in payload

    digital = payload["digital_delivery"]
    assert digital["order_id"] == "order_voucher_003"
    assert digital["redemption_ts"] == 1735550500
    assert digital["fulfillment_type"] == "digital_voucher"
    assert "1735550500" in payload["summary"]


def test_razorpay_client_sandbox_mode():
    """Verify sandbox/test-mode client returns simulated responses without network calls."""
    client = RazorpayClient()
    accept_resp = client.accept_dispute("disp_test_sandbox")
    assert accept_resp["id"] == "disp_test_sandbox"
    assert accept_resp["status"] == "lost"
    assert accept_resp["mock"] is True

    contest_resp = client.contest_dispute("disp_test_sandbox", {"summary": "Test contest"})
    assert contest_resp["id"] == "disp_test_sandbox"
    assert contest_resp["status"] == "under_review"
    assert contest_resp["mock"] is True
