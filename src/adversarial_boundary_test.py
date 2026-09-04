"""Adversarial and boundary test suite for ArgusML.

Covers:
1. Decision thresholds & economic boundary cases (micro-amounts, borderline p, fixed fees).
2. Velocity limits & cumulative exposure boundary conditions (§6b).
3. Malformed, missing, and non-numeric webhook payloads.
4. Webhook HMAC-SHA256 signature verification and tampered payload detection.
5. In-memory and persistent cross-restart replay attack prevention.
6. Missing evidence handling and deterministic safety fallbacks.
7. Fact-validation unsupported claim rejection and correction demonstration.
"""

import hashlib
import hmac
import time
from typing import Any, Dict

import pytest

from src.audit_log import AuditLog
from src.decision_engine import (
    ACCEPT_P_THRESHOLD,
    CONTEST_P_THRESHOLD,
    DEFAULT_C_CONTEST,
    DEFAULT_C_PENALTY,
    VELOCITY_MAX_COUNT,
    VELOCITY_MAX_VALUE,
    decide,
)
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.model_b_evidence_assembler.validate_facts import validate_facts
from src.razorpay_client import RazorpayClient, verify_webhook_signature
from src.webhook_listener import WebhookHandler


# ==============================================================================
# 1. Decision Engine & Economic Boundary Tests
# ==============================================================================

def test_decision_threshold_exact_boundaries():
    """Verify exact boundaries for contest (p=0.65) and accept (p=0.25)."""
    amount = 50000  # ₹500

    # Exactly at contest threshold with positive EV
    action, rule, _ = decide(
        p_illegitimate=CONTEST_P_THRESHOLD,  # 0.65
        amount_paise=amount,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "contest"
    assert rule == "ev_positive_high_confidence"

    # Just below contest threshold (0.6499) -> must escalate, never auto-contest
    action, rule, _ = decide(
        p_illegitimate=0.6499,
        amount_paise=amount,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"

    # Exactly at accept threshold with negative EV
    action, rule, _ = decide(
        p_illegitimate=ACCEPT_P_THRESHOLD,  # 0.25
        amount_paise=amount,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "accept"
    assert rule == "low_p_auto_accept"

    # Just above accept threshold (0.2501) with negative EV -> escalate to human
    action, rule, _ = decide(
        p_illegitimate=0.2501,
        amount_paise=amount,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"


def test_economic_micro_amount_fixed_fees_defeat_high_confidence():
    """Verify micro-amounts (₹1 dispute) do NOT auto-contest even at 90% confidence.

    Economic logic: Fixed contest fee (₹30) + penalty risk on ₹1 claim yields negative net EV:
      net_advantage = 0.90 * 100 - (1 - 0.90) * 15000 - 3000 = 90 - 1500 - 3000 = -4,410 paise.
    Contesting would be economically irrational, so the engine routes to human review.
    """
    action, rule, _ = decide(
        p_illegitimate=0.90,
        amount_paise=100,  # ₹1
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"


def test_economic_zero_and_negative_amounts():
    """Verify 0 and negative amounts are handled without math exceptions."""
    # Zero amount at low p: net EV <= 0, p <= 0.25 -> accept 0-loss claim
    action, rule, _ = decide(
        p_illegitimate=0.10,
        amount_paise=0,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "accept"

    # Negative amount at high p: net EV negative -> escalate to human review
    action, rule, _ = decide(
        p_illegitimate=0.80,
        amount_paise=-500,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"


def test_economic_high_ticket_borderline_confidence():
    """Verify high-ticket dispute (₹100,000) with borderline p=0.60 routes to human review."""
    large_amount = 10000000  # ₹100,000 in paise
    action, rule, _ = decide(
        p_illegitimate=0.60,  # < 0.65 threshold
        amount_paise=large_amount,
        exposure_count=0,
        exposure_value_paise=0,
    )
    assert action == "escalate"
    assert rule == "uncertain_ev_or_mid_p"


# ==============================================================================
# 2. Velocity & Cumulative Exposure Gate Tests (§6b)
# ==============================================================================

def test_velocity_gate_count_boundary():
    """Verify velocity count boundary: 2 accepts passes, 3 accepts breaches."""
    # 2 prior accepts (under cap of 3) -> routes to accept
    action, rule, _ = decide(
        p_illegitimate=0.10,
        amount_paise=10000,
        exposure_count=VELOCITY_MAX_COUNT - 1,  # 2
        exposure_value_paise=10000,
    )
    assert action == "accept"
    assert rule == "low_p_auto_accept"

    # Exactly 3 prior accepts -> breaches velocity gate
    action, rule, _ = decide(
        p_illegitimate=0.10,
        amount_paise=10000,
        exposure_count=VELOCITY_MAX_COUNT,  # 3
        exposure_value_paise=10000,
    )
    assert action == "escalate"
    assert rule == "velocity_cap_breached"


def test_velocity_gate_value_boundary():
    """Verify velocity cumulative value boundary: ₹4,999 passes, ₹5,000 breaches."""
    # ₹4,999 in paise (499,900 paise) -> under 500,000 paise limit
    action, rule, _ = decide(
        p_illegitimate=0.10,
        amount_paise=10000,
        exposure_count=1,
        exposure_value_paise=VELOCITY_MAX_VALUE - 100,
    )
    assert action == "accept"

    # Exactly ₹5,000 (500,000 paise) -> breaches velocity gate
    action, rule, _ = decide(
        p_illegitimate=0.10,
        amount_paise=10000,
        exposure_count=1,
        exposure_value_paise=VELOCITY_MAX_VALUE,
    )
    assert action == "escalate"
    assert rule == "velocity_cap_breached"


def test_exposure_store_rolling_window_expiry(tmp_path):
    """Verify auto-accepted disputes older than window_days (30d) expire and do not count."""
    db_path = str(tmp_path / "exposure_exp.db")
    store = ExposureStore(db_path=db_path, window_days=30)
    vpa = "buyer@upi"
    dev = "device_fp"
    now = int(time.time())

    # Record accept from 31 days ago (outside window)
    store.record_accept(vpa, dev, amount=400000, timestamp=now - (31 * 86400))
    # Record accept from 10 days ago (inside window)
    store.record_accept(vpa, dev, amount=50000, timestamp=now - (10 * 86400))

    cnt, val = store.get_exposure(vpa, dev, now_ts=now)
    assert cnt == 1
    assert val == 50000


# ==============================================================================
# 3. Malformed, Missing, and Corrupted Webhook Data Tests
# ==============================================================================

@pytest.fixture
def clean_handler(tmp_path):
    audit_db = str(tmp_path / "test_audit.db")
    ev_db = str(tmp_path / "test_ev.db")
    exp_db = str(tmp_path / "test_exp.db")
    chk_db = str(tmp_path / "test_chk.db")
    esc_db = str(tmp_path / "test_esc.db")

    return WebhookHandler(
        audit_log=AuditLog(db_path=audit_db),
        evidence_store=EvidenceStore(db_path=ev_db),
        exposure_store=ExposureStore(db_path=exp_db),
        escalation_queue=EscalationQueue(db_path=esc_db),
        pending_checkpoints=AcceptCheckpointStore(db_path=chk_db),
    )


def test_webhook_non_dict_payload_handled_safely(clean_handler):
    """Verify non-dict payload string or list returns malformed_payload rather than crashing."""
    result = clean_handler.process_dispute_created("not_a_json_dict")  # type: ignore
    assert result["status"] == "ignored"
    assert result["reason"] == "malformed_payload"


def test_webhook_payment_field_explicitly_none(clean_handler):
    """Verify payment: None does not trigger AttributeError: 'NoneType' object has no attribute 'get'."""
    payload = {
        "id": "disp_malformed_none_payment",
        "payment": None,
        "reason_code": "goods_not_delivered",
    }
    result = clean_handler.process_dispute_created(payload)
    assert result["status"] == "ignored"
    assert result["reason"] == "out_of_scope"


def test_webhook_corrupt_or_string_amount(clean_handler):
    """Verify corrupt amount string ('five_hundred') defaults safely to 0 without TypeError."""
    payload = {
        "id": "disp_corrupt_amt_001",
        "payment": {"method": "upi", "order_id": "ord_missing"},
        "reason_code": "goods_not_delivered",
        "amount": "invalid_string_amount",
    }
    result = clean_handler.process_dispute_created(payload)
    assert result["status"] in ("pending_human_accept", "escalated")


def test_webhook_missing_evidence_defaults_safely(clean_handler):
    """Verify dispute with no matching evidence record routes conservatively without failing."""
    payload = {
        "id": "disp_orphan_no_evidence",
        "payment": {"method": "upi", "order_id": "order_not_in_store_999"},
        "reason_code": "goods_not_delivered",
        "amount": 15000,
    }
    result = clean_handler.process_dispute_created(payload)
    # Lacking evidence, it must NOT contest; it should recommend accept or escalate to human
    assert result["status"] in ("pending_human_accept", "escalated")
    assert result["status"] != "contested"


# ==============================================================================
# 4. Webhook Signature Verification & Tamper Detection
# ==============================================================================

def test_webhook_signature_valid_hmac():
    """Verify valid HMAC-SHA256 signature passes verification."""
    secret = "rzp_webhook_secret_secure_123"
    body = b'{"event":"payment.dispute.created","id":"disp_sig_test_01"}'
    expected_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, expected_sig, secret) is True


def test_webhook_signature_tampered_payload_rejected():
    """Verify payload modified by a single byte fails HMAC-SHA256 verification."""
    secret = "rzp_webhook_secret_secure_123"
    body = b'{"event":"payment.dispute.created","id":"disp_sig_test_01","amount":1000}'
    valid_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Tampered body with amount changed to 9000
    tampered_body = b'{"event":"payment.dispute.created","id":"disp_sig_test_01","amount":9000}'
    assert verify_webhook_signature(tampered_body, valid_sig, secret) is False


def test_webhook_signature_missing_or_empty():
    """Verify missing or empty signature or secret returns False."""
    body = b'{"data": 1}'
    assert verify_webhook_signature(body, None, "secret") is False
    assert verify_webhook_signature(body, "", "secret") is False
    assert verify_webhook_signature(body, "sig", "") is False
    assert verify_webhook_signature(b"", "sig", "secret") is False


# ==============================================================================
# 5. Persistent Replay Attack Prevention
# ==============================================================================

def test_webhook_persistent_cross_restart_idempotency(tmp_path):
    """Verify that after a server restart, an audit-logged dispute is not re-processed."""
    audit_path = str(tmp_path / "persistent_audit.db")
    audit_log = AuditLog(db_path=audit_path)

    # Simulate prior session recording dispute resolution
    audit_log.record(
        dispute_id="disp_replayed_001",
        decision="accept",
        rule_fired="low_p_auto_accept",
        actor="system",
    )

    # Fresh handler instantiated (in-memory decided_disputes is empty)
    fresh_handler = WebhookHandler(
        audit_log=audit_log,
        evidence_store=EvidenceStore(db_path=str(tmp_path / "ev.db")),
        exposure_store=ExposureStore(db_path=str(tmp_path / "exp.db")),
        escalation_queue=EscalationQueue(db_path=str(tmp_path / "esc.db")),
        pending_checkpoints=AcceptCheckpointStore(db_path=str(tmp_path / "chk.db")),
    )
    assert "disp_replayed_001" not in fresh_handler.decided_disputes

    replayed_payload = {
        "id": "disp_replayed_001",
        "payment": {"method": "upi", "order_id": "ord_replay"},
        "reason_code": "goods_not_delivered",
        "amount": 25000,
    }

    result = fresh_handler.process_dispute_created(replayed_payload)
    assert result["status"] == "duplicate_webhook_ignored"
    assert result["dispute_id"] == "disp_replayed_001"


# ==============================================================================
# 6. Fact-Validation Unsupported Claim Demonstration
# ==============================================================================

def test_fact_validator_unsupported_claim_demonstration():
    """Demonstrate the required verification flow:
    1. Trusted evidence says voucher is unredeemed (digital_redemption_ts is None).
    2. LLM draft claims voucher was redeemed.
    3. Validator rejects with specific factual reason.
    4. Legitimate summary asserting unredeemed status passes.
    """
    trusted_evidence = {
        "order_id": "order_giftcard_500",
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": None,
    }

    # Unsupported claim: asserts redemption
    hallucinated_claim = {
        "summary": "Order order_giftcard_500 digital voucher was redeemed online by the recipient."
    }
    is_valid, reasons = validate_facts(hallucinated_claim, trusted_evidence)
    assert is_valid is False
    assert any("asserted digital voucher was redeemed when evidence indicates unredeemed" in r for r in reasons)

    # Legitimate claim: aligns with trusted source record
    truthful_claim = {
        "summary": "Order order_giftcard_500 digital voucher remains unredeemed in merchant records."
    }
    is_valid, reasons = validate_facts(truthful_claim, trusted_evidence)
    assert is_valid is True
    assert reasons == []
