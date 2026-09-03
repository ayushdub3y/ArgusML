"""Integration test suite for WebhookHandler, watchdog, HTTP endpoints, and persistence (§2, Tasks 1, 2, 3, 4)."""

import base64
import hashlib
import hmac
import json
import os
import pytest
from fastapi.testclient import TestClient

from src.audit_log import AuditLog
from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore
from src.human_review.accept_checkpoint import AcceptCheckpoint, AcceptCheckpointStore
from src.human_review.escalation_queue import EscalationQueue
from src.razorpay_client import RazorpayClient
from src.webhook_listener import WATCHDOG_MARGIN_SECONDS, WebhookHandler, create_app


@pytest.fixture
def clean_handler(tmp_path):
    """Provide a WebhookHandler with clean tmp SQLite stores isolated per test."""
    ev_db = str(tmp_path / "test_evidence.db")
    exp_db = str(tmp_path / "test_exposure.db")
    audit_db = str(tmp_path / "test_audit.db")
    esc_db = str(tmp_path / "test_escalations.db")
    cp_db = str(tmp_path / "test_checkpoints.db")

    ev_store = EvidenceStore(db_path=ev_db)
    exp_store = ExposureStore(db_path=exp_db)
    audit = AuditLog(db_path=audit_db)
    client = RazorpayClient()
    esc_queue = EscalationQueue(db_path=esc_db)
    cp_store = AcceptCheckpointStore(db_path=cp_db)

    return WebhookHandler(
        evidence_store=ev_store,
        exposure_store=exp_store,
        audit_log=audit,
        razorpay_client=client,
        escalation_queue=esc_queue,
        pending_checkpoints=cp_store,
    )


# -----------------------------------------------------------------------------
# Existing Unit Tests
# -----------------------------------------------------------------------------

def test_routing_out_of_scope(clean_handler):
    """Verify out-of-scope payload (non-upi or reason != goods_not_delivered) is ignored."""
    card_payload = {
        "id": "disp_card_001",
        "reason_code": "goods_not_delivered",
        "payment": {"method": "card", "order_id": "ord_1"},
    }
    res = clean_handler.process_dispute_created(card_payload)
    assert res["status"] == "ignored"
    assert res["reason"] == "out_of_scope"

    fraud_payload = {
        "id": "disp_upi_fraud_002",
        "reason_code": "fraudulent",
        "payment": {"method": "upi", "order_id": "ord_2"},
    }
    res2 = clean_handler.process_dispute_created(fraud_payload)
    assert res2["status"] == "ignored"
    assert res2["reason"] == "out_of_scope"


def test_routing_high_p_contested(clean_handler):
    """Verify dispute with strong fulfillment evidence and high p routes to contested."""
    order_id = "order_contest_high_p"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_valid",
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {"vpa_hash": "vpa_legit", "device_fingerprint_hash": "dev_legit"},
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 2,
            "approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced",
        },
        "time_to_dispute_days": 1,
    })

    payload = {
        "id": "disp_contest_001",
        "amount": 250000,  # ₹2,500
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "vpa": "user@upi", "order_id": order_id},
    }

    res = clean_handler.process_dispute_created(payload)
    assert res["status"] == "contested"
    assert res["dispute_id"] == "disp_contest_001"

    entries = clean_handler.audit_log.get_entries("disp_contest_001")
    assert len(entries) == 1
    assert entries[0]["decision"] == "contest"
    assert entries[0]["actor"] == "system"


def test_routing_low_p_pending_human_accept(clean_handler):
    """Verify low-p dispute routes to pending_human_accept with one-liner."""
    order_id = "order_accept_low_p"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
        "delivery_geotag": None,
        "buyer_identity": {"vpa_hash": "vpa_clean", "device_fingerprint_hash": "dev_clean"},
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 0,
            "approx_position_vs_cd1_cd2_cap": "unknown",
        },
        "time_to_dispute_days": 5,
    })

    payload = {
        "id": "disp_accept_001",
        "amount": 15000,  # ₹150
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "vpa": "clean@upi", "order_id": order_id},
    }

    res = clean_handler.process_dispute_created(payload)
    assert res["status"] == "pending_human_accept"
    assert "one_liner" in res
    assert "recommend Accept" in res["one_liner"]
    assert "disp_accept_001" in clean_handler.pending_checkpoints


def test_routing_escalated_on_velocity_breach(clean_handler):
    """Verify dispute with breached cumulative exposure is routed to escalated (§6b)."""
    order_id = "order_breach_001"
    vpa_h = "vpa_abuser"
    dev_h = "dev_abuser"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": vpa_h, "device_fingerprint_hash": dev_h},
        "buyer_dispute_history": {"disputes_raised_last_180d_this_merchant": 0},
    })

    now = 1735600000
    for _ in range(4):
        clean_handler.exposure_store.record_accept(vpa_h, dev_h, 20000, timestamp=now - 1000)

    payload = {
        "id": "disp_escalate_vel_001",
        "amount": 10000,  # ₹100
        "reason_code": "goods_not_delivered",
        "respond_by": now + 86400,
        "payment": {"method": "upi", "vpa": "abuser@upi", "order_id": order_id},
    }

    res = clean_handler.process_dispute_created(payload)
    assert res["status"] == "escalated"
    assert clean_handler.escalation_queue.get("disp_escalate_vel_001") is not None


def test_webhook_idempotency(clean_handler):
    """Verify duplicate webhooks are ignored and do not create duplicate audit records."""
    order_id = "order_idempotent_test"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": True,
        "buyer_identity": {"vpa_hash": "vpa_idemp", "device_fingerprint_hash": "dev_idemp"},
    })

    payload = {
        "id": "disp_idemp_001",
        "amount": 200000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "order_id": order_id},
    }

    first = clean_handler.process_dispute_created(payload)
    assert first["status"] in ("contested", "pending_human_accept", "escalated")

    second = clean_handler.process_dispute_created(payload)
    assert second["status"] == "duplicate_webhook_ignored"

    entries = clean_handler.audit_log.get_entries("disp_idemp_001")
    assert len(entries) == 1


def test_deadline_watchdog_force_accept(clean_handler):
    """Verify watchdog force-accepts checkpoints within margin, ignores future, and handles missing respond_by (Task 2)."""
    now = 1735600000

    order_urgent = "order_urgent"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_urgent,
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "u1", "device_fingerprint_hash": "d1"},
    })
    payload_urgent = {
        "id": "disp_urgent",
        "amount": 10000,
        "reason_code": "goods_not_delivered",
        "respond_by": now + 1800,  # 30 mins left (<= 3600 margin)
        "payment": {"method": "upi", "order_id": order_urgent},
    }
    clean_handler.process_dispute_created(payload_urgent)

    order_distant = "order_distant"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_distant,
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "u2", "device_fingerprint_hash": "d2"},
    })
    payload_distant = {
        "id": "disp_distant",
        "amount": 10000,
        "reason_code": "goods_not_delivered",
        "respond_by": now + 86400,  # 24 hours left
        "payment": {"method": "upi", "order_id": order_distant},
    }
    clean_handler.process_dispute_created(payload_distant)

    order_missing = "order_missing_rb"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_missing,
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "u3", "device_fingerprint_hash": "d3"},
    })
    payload_missing = {
        "id": "disp_missing_rb",
        "amount": 10000,
        "reason_code": "goods_not_delivered",
        "respond_by": None,
        "payment": {"method": "upi", "order_id": order_missing},
    }
    clean_handler.process_dispute_created(payload_missing)

    fired = clean_handler.deadline_watchdog_tick(now_ts=now)

    assert "disp_urgent" in fired
    assert "disp_distant" not in fired
    assert "disp_missing_rb" not in fired

    assert "disp_urgent" not in clean_handler.pending_checkpoints
    assert "disp_distant" in clean_handler.pending_checkpoints


def test_two_entry_audit_log_flow(clean_handler):
    """Verify decision -> checkpoint -> confirm produces two audit log entries: system then human (Task 3)."""
    order_id = "order_two_entry_test"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "vpa_2log", "device_fingerprint_hash": "dev_2log"},
    })
    payload = {
        "id": "disp_two_log_001",
        "amount": 12000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "order_id": order_id},
    }

    res = clean_handler.process_dispute_created(payload)
    assert res["status"] == "pending_human_accept"

    checkpoint = clean_handler.pending_checkpoints.get("disp_two_log_001")
    assert checkpoint is not None

    entries_step1 = clean_handler.audit_log.get_entries("disp_two_log_001")
    assert len(entries_step1) == 1
    assert entries_step1[0]["actor"] == "system"
    assert entries_step1[0]["decision"] == "accept"

    confirmed = checkpoint.confirm(actor="human")
    assert confirmed is True

    entries_step2 = clean_handler.audit_log.get_entries("disp_two_log_001")
    assert len(entries_step2) == 2
    assert entries_step2[0]["actor"] == "system"
    assert entries_step2[0]["decision"] == "accept"
    assert entries_step2[1]["actor"] == "human"
    assert entries_step2[1]["decision"] == "accept"
    assert entries_step2[1]["rule_fired"] == "accept_checkpoint_confirmed:human"


def test_resolve_escalation_validation_and_success(clean_handler):
    """Verify resolve_escalation raises ValueError for bad input and records valid resolutions."""
    with pytest.raises(ValueError, match="Invalid escalation resolution action"):
        clean_handler.resolve_escalation("disp_fake", action="invalid_action")

    with pytest.raises(ValueError, match="not found in escalation queue"):
        clean_handler.resolve_escalation("disp_nonexistent", action="accept")

    item = {
        "dispute_id": "disp_esc_valid",
        "amount": 40000,
        "respond_by": 1735800000,
        "features": {},
        "evidence": {
            "order_id": "ord_esc",
            "buyer_identity": {"vpa_hash": "vpa_e", "device_fingerprint_hash": "dev_e"},
        },
    }
    clean_handler.escalation_queue.add(item)

    res = clean_handler.resolve_escalation("disp_esc_valid", action="accept", actor="human_reviewer_42")
    assert res["status"] == "escalation_resolved_accept"

    entries = clean_handler.audit_log.get_entries("disp_esc_valid")
    assert len(entries) == 1
    assert entries[0]["actor"] == "human_reviewer_42"
    assert entries[0]["decision"] == "accept"
    assert entries[0]["rule_fired"] == "human_escalation_override:accept"


# -----------------------------------------------------------------------------
# End-to-End HTTP Route Integration Tests (Task 2)
# -----------------------------------------------------------------------------

def test_http_webhook_three_payload_shapes(clean_handler):
    """Verify POST /webhook for each of the three demo payload shapes returns correct action and 200."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = create_app(clean_handler)
    client = TestClient(app)

    # Seed evidence for the 3 demo cases
    clean_handler.evidence_store.save_evidence({
        "order_id": "order_demo_accept_001",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {"vpa_hash": "vpa_acc", "device_fingerprint_hash": "dev_acc"},
    })
    clean_handler.evidence_store.save_evidence({
        "order_id": "order_demo_contest_001",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_99",
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {"vpa_hash": "vpa_con", "device_fingerprint_hash": "dev_con"},
        "buyer_dispute_history": {"approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced"},
    })
    clean_handler.evidence_store.save_evidence({
        "order_id": "order_demo_escalate_001",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "vpa_esc", "device_fingerprint_hash": "dev_esc"},
    })
    for i in range(4):
        clean_handler.exposure_store.record_accept("vpa_esc", "dev_esc", 20000, timestamp=1735600000 - i * 100)

    # 1. Accept sample
    with open(os.path.join(repo_root, "demo", "sample_accept.json"), "r") as f:
        accept_payload = json.load(f)
    resp_accept = client.post("/webhook", json=accept_payload)
    assert resp_accept.status_code == 200
    data_accept = resp_accept.json()
    assert data_accept["status"] == "pending_human_accept"
    assert "one_liner" in data_accept
    assert "recommend Accept" in data_accept["one_liner"]

    # 2. Contest sample
    with open(os.path.join(repo_root, "demo", "sample_contest.json"), "r") as f:
        contest_payload = json.load(f)
    resp_contest = client.post("/webhook", json=contest_payload)
    assert resp_contest.status_code == 200
    assert resp_contest.json()["status"] == "contested"

    # 3. Escalate sample
    with open(os.path.join(repo_root, "demo", "sample_escalate.json"), "r") as f:
        escalate_payload = json.load(f)
    resp_escalate = client.post("/webhook", json=escalate_payload)
    assert resp_escalate.status_code == 200
    assert resp_escalate.json()["status"] == "escalated"


def test_http_webhook_signature_verification(clean_handler, monkeypatch):
    """Verify POST /webhook rejects invalid X-Razorpay-Signature when RAZORPAY_WEBHOOK_SECRET is set."""
    secret = "test_webhook_secret_key_123"
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", secret)

    app = create_app(clean_handler)
    client = TestClient(app)

    payload = {
        "id": "disp_sig_test",
        "amount": 20000,
        "reason_code": "goods_not_delivered",
        "payment": {"method": "upi", "order_id": "ord_sig"},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    # 1. Missing signature header -> 400
    resp_missing = client.post("/webhook", content=payload_bytes)
    assert resp_missing.status_code == 400
    assert "Invalid webhook signature" in resp_missing.json().get("error", "")

    # 2. Wrong signature header -> 400
    resp_wrong = client.post("/webhook", content=payload_bytes, headers={"X-Razorpay-Signature": "bad_signature"})
    assert resp_wrong.status_code == 400
    assert "Invalid webhook signature" in resp_wrong.json().get("error", "")

    # 3. Valid HMAC-SHA256 signature -> 200
    valid_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    resp_valid = client.post("/webhook", content=payload_bytes, headers={"X-Razorpay-Signature": valid_sig})
    assert resp_valid.status_code == 200


def test_http_accept_checkpoint_confirm_and_expand(clean_handler):
    """Verify POST /accept_checkpoint/<id>/confirm and GET .../expand return 404 for nonexistent and 200 for existing."""
    app = create_app(clean_handler)
    client = TestClient(app)

    # 1. Nonexistent dispute -> 404 with error body
    resp_confirm_404 = client.post("/accept_checkpoint/nonexistent_disp_999/confirm")
    assert resp_confirm_404.status_code == 404
    assert "not found" in resp_confirm_404.json().get("error", "").lower()

    resp_expand_404 = client.get("/accept_checkpoint/nonexistent_disp_999/expand")
    assert resp_expand_404.status_code == 404
    assert "not found" in resp_expand_404.json().get("error", "").lower()

    # 2. Create actual checkpoint in handler
    order_id = "order_http_cp"
    clean_handler.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "vpa_h", "device_fingerprint_hash": "dev_h"},
    })
    clean_handler.process_dispute_created({
        "id": "disp_http_cp_01",
        "amount": 15000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "order_id": order_id},
    })
    assert "disp_http_cp_01" in clean_handler.pending_checkpoints

    # 3. Expand existing checkpoint -> 200 with data
    resp_expand_200 = client.get("/accept_checkpoint/disp_http_cp_01/expand")
    assert resp_expand_200.status_code == 200
    data = resp_expand_200.json()
    assert data["dispute_id"] == "disp_http_cp_01"
    assert data["amount"] == 15000

    # 4. Confirm existing checkpoint -> 200 with status=accepted
    resp_confirm_200 = client.post("/accept_checkpoint/disp_http_cp_01/confirm")
    assert resp_confirm_200.status_code == 200
    assert resp_confirm_200.json()["status"] == "accepted"
    assert resp_confirm_200.json()["confirmed_by"] == "human"

    # Checkpoint is now confirmed and removed from pending store
    assert "disp_http_cp_01" not in clean_handler.pending_checkpoints


def test_http_dashboard_auth_gate(clean_handler, monkeypatch):
    """Verify dashboard auth rejects unauthenticated when credentials set and permits when unset."""
    # State A: Credentials unset -> permits without auth
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    app_open = create_app(clean_handler)
    client_open = TestClient(app_open)
    resp_open = client_open.get("/")
    assert resp_open.status_code == 200
    assert "Aegis — UPI Dispute Defense Engine" in resp_open.text

    # State B: Credentials set -> rejects without auth, allows with valid Basic auth
    username = "admin_aegis"
    password = "SuperSecretPassword123"
    monkeypatch.setenv("DASHBOARD_USERNAME", username)
    monkeypatch.setenv("DASHBOARD_PASSWORD", password)

    app_auth = create_app(clean_handler)
    client_auth = TestClient(app_auth)

    # 1. Unauthenticated request -> 401
    resp_unauth = client_auth.get("/")
    assert resp_unauth.status_code == 401
    assert "WWW-Authenticate" in resp_unauth.headers

    # 2. Invalid credentials -> 401
    bad_auth = base64.b64encode(b"admin_aegis:wrongpassword").decode("utf-8")
    resp_bad = client_auth.get("/", headers={"Authorization": f"Basic {bad_auth}"})
    assert resp_bad.status_code == 401

    # 3. Valid credentials -> 200 with dashboard HTML
    valid_auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    resp_ok = client_auth.get("/", headers={"Authorization": f"Basic {valid_auth}"})
    assert resp_ok.status_code == 200
    assert "Aegis — UPI Dispute Defense Engine" in resp_ok.text


def test_persistence_and_rebound_closure_across_restart(tmp_path):
    """Verify pending checkpoints & escalations survive restart and rebound closure executes on new handler instance."""
    ev_db = str(tmp_path / "persist_evidence.db")
    exp_db = str(tmp_path / "persist_exposure.db")
    audit_db = str(tmp_path / "persist_audit.db")
    esc_db = str(tmp_path / "persist_escalations.db")
    cp_db = str(tmp_path / "persist_checkpoints.db")

    # Instance 1: Initial server running
    ev1 = EvidenceStore(db_path=ev_db)
    exp1 = ExposureStore(db_path=exp_db)
    audit1 = AuditLog(db_path=audit_db)
    client1 = RazorpayClient()
    esc1 = EscalationQueue(db_path=esc_db)
    cp1 = AcceptCheckpointStore(db_path=cp_db)

    handler1 = WebhookHandler(
        evidence_store=ev1,
        exposure_store=exp1,
        audit_log=audit1,
        razorpay_client=client1,
        escalation_queue=esc1,
        pending_checkpoints=cp1,
    )

    # Add an escalation item
    esc_item = {
        "dispute_id": "disp_esc_durability",
        "amount": 55000,
        "respond_by": 1735700000,
        "rule_fired": "velocity_breach",
    }
    handler1.escalation_queue.add(esc_item)

    # Process an accept dispute
    order_id = "order_persist_test"
    handler1.evidence_store.save_evidence({
        "order_id": order_id,
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "buyer_identity": {"vpa_hash": "vpa_persist", "device_fingerprint_hash": "dev_persist"},
    })
    res = handler1.process_dispute_created({
        "id": "disp_accept_durability",
        "amount": 22000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "order_id": order_id},
    })
    assert res["status"] == "pending_human_accept"
    assert "disp_accept_durability" in handler1.pending_checkpoints

    # Verify initial audit trail has exactly 1 entry on handler1
    assert len(handler1.audit_log.get_entries("disp_accept_durability")) == 1

    # SIMULATE SERVER RESTART:
    # Completely fresh handler instance pointing to the identical SQLite DB files
    ev2 = EvidenceStore(db_path=ev_db)
    exp2 = ExposureStore(db_path=exp_db)
    audit2 = AuditLog(db_path=audit_db)
    client2 = RazorpayClient()
    esc2 = EscalationQueue(db_path=esc_db)
    cp2 = AcceptCheckpointStore(db_path=cp_db)

    handler2 = WebhookHandler(
        evidence_store=ev2,
        exposure_store=exp2,
        audit_log=audit2,
        razorpay_client=client2,
        escalation_queue=esc2,
        pending_checkpoints=cp2,
    )

    # 1. Verify escalation survived restart
    retrieved_esc = handler2.escalation_queue.get("disp_esc_durability")
    assert retrieved_esc is not None
    assert retrieved_esc["amount"] == 55000

    # 2. Verify checkpoint survived restart
    assert "disp_accept_durability" in handler2.pending_checkpoints
    restored_checkpoint = handler2.pending_checkpoints.get("disp_accept_durability")
    assert restored_checkpoint is not None
    assert restored_checkpoint.amount == 22000
    assert restored_checkpoint.rule_fired == "low_p_auto_accept"

    # 3. Confirm checkpoint through handler2 — this proves rebound on_confirm closure executes against handler2!
    confirmed = restored_checkpoint.confirm(actor="human")
    assert confirmed is True

    # 4. Assert accept finalized on handler2's stores:
    # Checkpoint popped from handler2
    assert "disp_accept_durability" not in handler2.pending_checkpoints

    # Exposure recorded on handler2's exposure_store
    exp_count, exp_val = handler2.exposure_store.get_exposure("vpa_persist", "dev_persist")
    assert exp_count == 1
    assert exp_val == 22000

    # Audit log entry for confirmed accept written to handler2's audit_log
    entries = handler2.audit_log.get_entries("disp_accept_durability")
    assert len(entries) == 2
    assert entries[1]["actor"] == "human"
    assert entries[1]["decision"] == "accept"
    assert entries[1]["rule_fired"] == "accept_checkpoint_confirmed:human"
