"""Comprehensive test suite for the 7 hardening areas of ArgusML (§2, Section 2 hardening).

Verifies:
1. Audit log semantics: system recommendation vs human-confirmed execution & razorpay_dispatched.
2. State machine invariants: prevents contradictory transitions (409 Conflict), terminal resolution
   immutability, and exceptional reopening confirmation.
3. Deterministic velocity escalations: no fabricated ML confidence (0.98 / 98%); is_model_evaluated=False.
4. Neutral probabilistic risk language: eliminates accusatory 'FRIENDLY FRAUD' strings.
5. Truthful evidence sufficiency & decision-aware rebuttal generation: Rule 10 delivery proof gating
   and concession rationales.
6. Mobile responsiveness: layout rules for ~390px screens.
7. Truthful Model Health: empirical METRICS.md decision distribution and honest drift status.
"""

import time
import pytest
from fastapi.testclient import TestClient

from src.audit_log import AuditLog
from src.dispute_state_machine import (
    DisputeStateMachine,
    DisputeState,
    DisputeEvent,
    InvalidStateTransitionError,
)
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpoint, AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.model_b_evidence_assembler.assemble import build_contest_payload_from_evidence
from src.model_b_evidence_assembler.validate_facts import validate_facts
from src.razorpay_client import RazorpayClient, check_evidence_sufficiency
from src.ui.routes import _DASHBOARD_SHELL, _get_decision_aware_rebuttal, _read_live_model_a_metrics
from src.webhook_listener import WebhookHandler, create_app


@pytest.fixture
def hardening_env(tmp_path):
    """Isolated stores and WebhookHandler for hardening verification."""
    ev_store = EvidenceStore(db_path=str(tmp_path / "h_evidence.db"))
    exp_store = ExposureStore(db_path=str(tmp_path / "h_exposure.db"))
    audit = AuditLog(db_path=str(tmp_path / "h_audit.db"))
    razorpay = RazorpayClient()
    esc_queue = EscalationQueue(db_path=str(tmp_path / "h_escalations.db"))
    sm = DisputeStateMachine(db_path=str(tmp_path / "h_states.db"))
    cp_store = AcceptCheckpointStore(db_path=str(tmp_path / "h_checkpoints.db"))

    handler = WebhookHandler(
        evidence_store=ev_store,
        exposure_store=exp_store,
        audit_log=audit,
        razorpay_client=razorpay,
        escalation_queue=esc_queue,
        pending_checkpoints=cp_store,
        state_machine=sm,
    )

    app = create_app(handler)
    client = TestClient(app)
    return client, handler


# ==============================================================================
# 1. Audit Log Semantics: Recommendation vs Execution (§2)
# ==============================================================================

def test_audit_log_semantics_recommendation_vs_execution(hardening_env):
    """Verify distinct audit records for system recommendations vs human-confirmed executions."""
    client, handler = hardening_env
    dispute_id = "disp_audit_test_001"

    # 1. System records a recommendation (e.g. at webhook ingestion)
    handler.audit_log.record(
        dispute_id=dispute_id,
        decision="recommend_accept",
        rule_fired="low_p_auto_accept",
        actor="system",
        event_type="system_recommendation",
        recommendation="recommend_accept",
        human_decision=None,
        razorpay_dispatched=False,
        execution_status="pending_checkpoint",
    )

    entries = handler.audit_log.get_entries(dispute_id=dispute_id)
    assert len(entries) == 1
    rec_entry = entries[0]
    assert rec_entry["event_type"] == "system_recommendation"
    assert rec_entry["recommendation"] == "recommend_accept"
    assert rec_entry["human_decision"] is None
    assert rec_entry["razorpay_dispatched"] is False
    assert rec_entry["actor"] == "system"

    # 2. Operator confirms execution
    handler.audit_log.record(
        dispute_id=dispute_id,
        decision="accept",
        rule_fired="accept_checkpoint_confirmed:human",
        actor="human",
        event_type="action_execution",
        human_decision="accept",
        razorpay_dispatched=True,
        execution_status="dispatched",
    )

    entries = handler.audit_log.get_entries(dispute_id=dispute_id)
    assert len(entries) == 2
    exec_entry = entries[1]
    assert exec_entry["event_type"] == "action_execution"
    assert exec_entry["human_decision"] == "accept"
    assert exec_entry["razorpay_dispatched"] is True
    assert exec_entry["actor"] == "human"


# ==============================================================================
# 2. Dispute State Machine Invariants & 409 Conflict Handling (§2)
# ==============================================================================

def test_state_machine_prevents_contradictory_transitions(hardening_env):
    """Direct test of DisputeStateMachine: CONTESTED -> ACCEPTED and ACCEPTED -> CONTESTED throw."""
    _, handler = hardening_env
    sm = handler.state_machine
    disp_id = "disp_sm_test_001"

    # Transition to CONTESTED
    sm.transition(disp_id, DisputeEvent.ROUTE_AUTO_CONTEST, actor="system")
    assert sm.get_state(disp_id) == DisputeState.CONTESTED

    # Contradictory attempt: cannot confirm accept on an already contested dispute
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        sm.transition(disp_id, DisputeEvent.CONFIRM_ACCEPT, actor="human")
    assert "cannot apply 'confirm_accept' in state 'CONTESTED'" in str(exc_info.value)

    # State remains CONTESTED
    assert sm.get_state(disp_id) == DisputeState.CONTESTED


def test_api_returns_409_on_conflicting_action(hardening_env):
    """REST API returns HTTP 409 Conflict when an action contradicts dispute state."""
    client, handler = hardening_env
    disp_id = "disp_conflict_001"

    # Seed dispute as CONTESTED in state machine
    handler.state_machine.set_state_direct(disp_id, DisputeState.CONTESTED, actor="system")

    # Attempting to accept a CONTESTED dispute must return 409 Conflict
    resp = client.post(f"/v1/disputes/{disp_id}/accept")
    assert resp.status_code == 409
    data = resp.json()
    assert "Invalid state transition" in data["error"]
    assert data["current_state"] == "CONTESTED"
    assert data["is_terminal"] is True


def test_exceptional_reopening_lifecycle(hardening_env):
    """Verify exceptional reopening requires explicit secondary confirmation and moves to review."""
    client, handler = hardening_env
    disp_id = "disp_reopen_001"

    # Mark as ACCEPTED
    handler.state_machine.set_state_direct(disp_id, DisputeState.ACCEPTED, actor="system")

    # 1. Calling reopen without confirm_reopen returns 400 Bad Request
    resp = client.post(f"/v1/disputes/{disp_id}/reopen", json={"reason": "New tracking evidence"})
    assert resp.status_code == 400
    assert "confirm_reopen" in resp.json()["error"]

    # 2. Calling reopen with confirmation succeeds
    resp = client.post(
        f"/v1/disputes/{disp_id}/reopen",
        json={"confirm_reopen": True, "reason": "Courier pod discovered post-settlement"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "reopened"
    assert handler.state_machine.get_state(disp_id) == DisputeState.REOPENED
    assert handler.escalation_queue.get(disp_id) is not None

    # 3. Audit trail records exceptional reopening
    entries = handler.audit_log.get_entries(dispute_id=disp_id)
    assert any(e.get("event_type") == "exceptional_reopen" for e in entries)


# ==============================================================================
# 3. Deterministic Velocity Safeguard: No Fabricated ML Confidence (§2)
# ==============================================================================

def test_velocity_safeguard_confidence_gating(hardening_env):
    """Velocity cap escalations must not display fabricated ML confidence (0.98 or 98%)."""
    client, handler = hardening_env
    disp_id = "disp_velocity_001"

    # Add velocity breach escalation item to queue
    handler.escalation_queue.add({
        "dispute_id": disp_id,
        "amount": 80000,
        "p": None,  # Velocity gate fires before model evaluation
        "respond_by": int(time.time()) + 1800,
        "rule_fired": "velocity_cap_breached",
        "evidence": {"order_id": "ord_vel_001"},
        "exposure_counters": (4, 80000),
    })

    resp = client.get(f"/v1/disputes/{disp_id}")
    assert resp.status_code == 200
    detail = resp.json()

    assert detail["is_model_evaluated"] is False
    assert detail["p"] is None
    assert detail["risk_percent"] is None
    assert "No ML score" in detail["score_note"]
    assert "deterministic velocity safeguard" in detail["score_note"]
    assert "98%" not in detail.get("risk_label", "")


# ==============================================================================
# 4. Neutral Probabilistic Risk Language (§2)
# ==============================================================================

def test_neutral_probabilistic_risk_language(hardening_env):
    """Dispute investigation responses must use neutral, probabilistic risk descriptions."""
    client, handler = hardening_env

    # Check high-confidence dispute detail
    resp = client.get("/v1/disputes/disp_demo_contest_001")
    assert resp.status_code == 200
    detail = resp.json()

    risk_label = detail.get("risk_label", "")
    # Must NOT use accusatory language
    assert "FRIENDLY FRAUD" not in risk_label
    assert "FALSE CLAIM" not in risk_label
    # Must use probabilistic phrasing
    assert "estimated probability of an illegitimate claim" in risk_label or "estimated claim dispute risk" in risk_label


# ==============================================================================
# 5. Truthful Evidence Sufficiency & Decision-Aware Rebuttal (§2)
# ==============================================================================

def test_evidence_sufficiency_missing_physical_proof():
    """check_evidence_sufficiency correctly identifies missing physical proof."""
    weak_evidence = {
        "order_id": "ord_no_proof",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
    }
    is_suff, verified, missing = check_evidence_sufficiency(weak_evidence)
    assert is_suff is False
    assert any("delivery_otp_confirmed" in m or "OTP" in m for m in missing)
    assert any("pod_document_id" in m or "POD" in m for m in missing)


def test_rebuttal_payload_truthful_limitation_statement():
    """Contest payload assembly generates a limitation statement when OTP/POD are absent."""
    weak_evidence = {
        "order_id": "ord_limited",
        "fulfillment_type": "physical",
        "carrier_name": "Delhivery",
        "tracking_number": "DEL12345",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
    }
    payload = build_contest_payload_from_evidence(weak_evidence)
    summary = payload.get("summary", "")

    # Must NOT claim legitimate fulfillment when proof is missing
    assert "Order fulfilled legitimately per merchant records" not in summary
    assert "Evidence is insufficient to substantiate an affirmative delivery contest" in summary


def test_validate_facts_rule_10_blocks_false_delivery_claims():
    """Rule 10 in validate_facts hard-blocks false legitimate delivery claims without physical proof."""
    weak_evidence = {
        "order_id": "ord_rule10",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
    }

    # Summary falsely asserts legitimate delivery
    false_summary = "Order fulfilled legitimately per merchant records."
    is_valid, reasons = validate_facts(false_summary, weak_evidence)
    assert is_valid is False
    assert any("asserted legitimate/verified fulfillment" in r for r in reasons)


def test_decision_aware_rebuttal_previews():
    """Verify decision-aware rebuttal previews: concession rationale on accept, pending notice on escalate."""
    evidence = {"order_id": "ord_test_001"}

    # Accept preview
    accept_rebuttal = _get_decision_aware_rebuttal(evidence, decision="accept", dispute_id="disp_acc_001")
    assert "CLAIM CONCESSION RATIONALE" in accept_rebuttal["summary"]
    assert "₹30 processing fee" in accept_rebuttal["summary"]

    # Escalate preview
    esc_rebuttal = _get_decision_aware_rebuttal(
        evidence, decision="escalate", dispute_id="disp_esc_001", rule_fired="velocity_cap_breached"
    )
    assert "PENDING OPERATOR REVIEW" in esc_rebuttal["summary"]
    assert "velocity_cap_breached" in esc_rebuttal["summary"]


# ==============================================================================
# 6. Mobile Responsiveness Layout Rules (§2)
# ==============================================================================

def test_mobile_responsive_css_present():
    """Verify mobile media queries are embedded in the dashboard shell for ~390px screens."""
    assert "@media (max-width: 768px)" in _DASHBOARD_SHELL
    # Primary actions full width & touch friendly
    assert ".inv-actions" in _DASHBOARD_SHELL
    assert "flex-direction: column" in _DASHBOARD_SHELL
    assert "min-height: 44px" in _DASHBOARD_SHELL
    # Responsive table container
    assert "overflow-x: auto" in _DASHBOARD_SHELL


# ==============================================================================
# 7. Truthful Model Health & Drift Monitoring (§2)
# ==============================================================================

def test_model_health_empirical_decision_distribution():
    """Verify Model Health returns real decision distribution from METRICS.md."""
    metrics = _read_live_model_a_metrics()
    decisions = metrics.get("decisions", {})

    assert decisions["contest"]["pct"] == 58.3
    assert decisions["contest"]["count"] == 700
    assert decisions["accept"]["pct"] == 37.8
    assert decisions["accept"]["count"] == 453
    assert decisions["escalate"]["pct"] == 3.9
    assert decisions["escalate"]["count"] == 47
    assert decisions["total"] == 1200


def test_drift_monitoring_truthful_state_on_insufficient_samples(hardening_env):
    """Drift monitor truthfully reports 'insufficient_data' when samples < 100."""
    client, _ = hardening_env
    resp = client.get("/dashboard/data")
    assert resp.status_code == 200
    data = resp.json()
    drift = data.get("drift", {})

    # With 0 samples, drift status must be insufficient_data, not stable
    assert drift.get("status") == "insufficient_data"
    assert drift.get("drift_detected") is False
