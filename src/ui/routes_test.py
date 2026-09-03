"""Test suite for new operations console REST endpoints and workflows (§2, §5, §6b)."""

import pytest
from fastapi.testclient import TestClient

from src.audit_log import AuditLog
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpoint, AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.razorpay_client import RazorpayClient
from src.webhook_listener import WebhookHandler, create_app


@pytest.fixture
def ops_test_client(tmp_path):
    """Provide a TestClient with clean isolated SQLite stores and sample data."""
    ev_db = str(tmp_path / "test_ops_evidence.db")
    exp_db = str(tmp_path / "test_ops_exposure.db")
    audit_db = str(tmp_path / "test_ops_audit.db")
    esc_db = str(tmp_path / "test_ops_escalations.db")
    cp_db = str(tmp_path / "test_ops_checkpoints.db")

    ev_store = EvidenceStore(db_path=ev_db)
    exp_store = ExposureStore(db_path=exp_db)
    audit = AuditLog(db_path=audit_db)
    client = RazorpayClient()
    esc_queue = EscalationQueue(db_path=esc_db)
    cp_store = AcceptCheckpointStore(db_path=cp_db)

    handler = WebhookHandler(
        evidence_store=ev_store,
        exposure_store=exp_store,
        audit_log=audit,
        razorpay_client=client,
        escalation_queue=esc_queue,
        pending_checkpoints=cp_store,
    )

    # Seed an escalation
    esc_queue.add({
        "dispute_id": "disp_test_esc_001",
        "amount": 80000,
        "p": 0.98,
        "respond_by": 1735700000,
        "rule_fired": "velocity_cap_breached",
        "evidence": {
            "order_id": "order_test_esc_001",
            "fulfillment_type": "physical",
            "delivery_otp_confirmed": False,
        },
        "exposure_counters": (4, 80000),
    })

    # Seed an accept checkpoint
    cp = AcceptCheckpoint(
        dispute_id="disp_test_cp_001",
        amount=23000,
        p=0.08,
        v_cum=47000,
        rule_fired="low_p_auto_accept",
        respond_by=1735700000,
        evidence={"order_id": "order_test_cp_001", "delivery_otp_confirmed": False},
        on_confirm=handler._finalize_accept,
    )
    cp_store.save(cp)

    app = create_app(handler)
    return TestClient(app), handler


def test_v1_list_disputes(ops_test_client):
    """Verify GET /v1/disputes lists pending checkpoints, escalations, and metadata."""
    client, _ = ops_test_client
    resp = client.get("/v1/disputes")
    assert resp.status_code == 200
    data = resp.json()
    assert "disputes" in data
    assert data["total"] >= 2
    ids = [d["dispute_id"] for d in data["disputes"]]
    assert "disp_test_esc_001" in ids
    assert "disp_test_cp_001" in ids


def test_v1_get_dispute_detail(ops_test_client):
    """Verify GET /v1/disputes/{id} returns deep investigation record with signals and rebuttal."""
    client, _ = ops_test_client
    resp = client.get("/v1/disputes/disp_test_esc_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dispute_id"] == "disp_test_esc_001"
    assert data["amount_str"] == "₹800.00"
    assert "signals" not in data or isinstance(data.get("signals"), list)
    assert "exposure" in data
    assert data["exposure"]["cap_status"] == "CAP BREACHED"
    assert "contest_rebuttal" in data
    assert "audit_timeline" in data


def test_v1_accept_action_from_checkpoint(ops_test_client):
    """Verify POST /v1/disputes/{id}/accept confirms checkpoint and writes to audit log."""
    client, handler = ops_test_client
    resp = client.post("/v1/disputes/disp_test_cp_001/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert "disp_test_cp_001" not in handler.pending_checkpoints

    # Check audit entry
    entries = handler.audit_log.get_entries("disp_test_cp_001")
    assert len(entries) >= 1
    assert entries[-1]["decision"] == "accept"
    assert entries[-1]["actor"] == "human"


def test_v1_contest_action_from_escalation(ops_test_client):
    """Verify PATCH /v1/disputes/{id}/contest resolves escalation and writes to audit log."""
    client, handler = ops_test_client
    resp = client.patch(
        "/v1/disputes/disp_test_esc_001/contest",
        json={"notes": "Carrier delivered order to customer mailbox."},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "contested"
    assert handler.escalation_queue.get("disp_test_esc_001") is None

    # Check audit entry
    entries = handler.audit_log.get_entries("disp_test_esc_001")
    assert len(entries) >= 1
    assert entries[-1]["decision"] == "contest"
    assert entries[-1]["actor"] == "human"


def test_v1_escalate_action(ops_test_client):
    """Verify POST /v1/disputes/{id}/escalate moves dispute to escalation queue."""
    client, handler = ops_test_client
    resp = client.post("/v1/disputes/disp_test_cp_001/escalate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "escalated"
    assert handler.escalation_queue.get("disp_test_cp_001") is not None


def test_v1_audit_and_model_health(ops_test_client):
    """Verify GET /v1/audit and GET /v1/model_health endpoints return live data."""
    client, _ = ops_test_client
    resp_audit = client.get("/v1/audit")
    assert resp_audit.status_code == 200
    assert "audits" in resp_audit.json()

    resp_health = client.get("/v1/model_health")
    assert resp_health.status_code == 200
    health_data = resp_health.json()
    assert "model_a" in health_data
    assert "model_b" in health_data
    assert "drift" in health_data
    assert "security" in health_data
    assert health_data["model_a"]["precision"] == 94.4
