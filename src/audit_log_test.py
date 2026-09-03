"""Test suite for AuditLog (§2 node L)."""

import pytest
from src.audit_log import AuditLog


def test_audit_log_record_and_retrieve(tmp_path):
    """Verify recording and retrieving structured immutable audit entries."""
    db_path = str(tmp_path / "audit_test.db")
    audit = AuditLog(db_path=db_path)

    features = {"amount_paise": 129900.0, "delivery_otp_confirmed": 1.0}
    shap = {"delivery_otp_confirmed": 0.25}
    evidence = {"order_id": "ord_100"}
    exposure = (1, 47700)

    row_id = audit.record(
        dispute_id="disp_audit_001",
        decision="contest",
        rule_fired="ev_positive_high_confidence",
        actor="system",
        features=features,
        shap_values=shap,
        evidence=evidence,
        exposure_counter=exposure,
        timestamp=1735600000,
    )
    assert row_id is not None

    entries = audit.get_entries("disp_audit_001")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["dispute_id"] == "disp_audit_001"
    assert entry["decision"] == "contest"
    assert entry["rule_fired"] == "ev_positive_high_confidence"
    assert entry["actor"] == "system"
    assert entry["features"] == features
    assert entry["shap_values"] == shap
    assert entry["evidence"] == evidence
    assert entry["exposure_counter"] == list(exposure)
    assert entry["timestamp"] == 1735600000


def test_audit_log_multiple_entries_sequential_order(tmp_path):
    """Verify audit log records multiple sequential entries for the same dispute."""
    db_path = str(tmp_path / "audit_multi.db")
    audit = AuditLog(db_path=db_path)

    audit.record(
        dispute_id="disp_flow",
        decision="accept",
        rule_fired="low_p_auto_accept",
        actor="system",
        timestamp=1735600000,
    )
    audit.record(
        dispute_id="disp_flow",
        decision="accept",
        rule_fired="accept_checkpoint_confirmed:human",
        actor="human",
        timestamp=1735600050,
    )

    entries = audit.get_entries("disp_flow")
    assert len(entries) == 2
    assert entries[0]["actor"] == "system"
    assert entries[1]["actor"] == "human"
    assert entries[0]["timestamp"] < entries[1]["timestamp"]


def test_audit_log_get_all_entries_and_clear(tmp_path):
    """Verify getting all entries across disputes and clearing."""
    db_path = str(tmp_path / "audit_all.db")
    audit = AuditLog(db_path=db_path)

    audit.record("disp_A", "accept", "low_p_auto_accept")
    audit.record("disp_B", "contest", "ev_positive_high_confidence")

    all_entries = audit.get_entries()
    assert len(all_entries) == 2
    assert {e["dispute_id"] for e in all_entries} == {"disp_A", "disp_B"}

    audit.clear()
    assert len(audit.get_entries()) == 0
