"""Test suite for EvidenceStore (§2 node C, §4)."""

import pytest
from src.evidence_store import EvidenceStore


def test_evidence_store_save_get_clear(tmp_path):
    """Verify saving, retrieving, and clearing evidence records."""
    db_path = str(tmp_path / "evidence.db")
    store = EvidenceStore(db_path=db_path)

    record = {
        "order_id": "order_test_99",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735550000,
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_99",
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {"vpa_hash": "v1", "device_fingerprint_hash": "d1"},
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 1,
            "approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced",
        },
        "time_to_dispute_days": 2,
    }

    store.save_evidence(record)
    retrieved = store.get_evidence("order_test_99")
    assert retrieved == record
    assert store.get_evidence("non_existent") is None

    store.clear()
    assert store.get_evidence("order_test_99") is None


def test_evidence_store_upsert_update(tmp_path):
    """Verify saving evidence with same order_id updates record."""
    db_path = str(tmp_path / "evidence_up.db")
    store = EvidenceStore(db_path=db_path)

    rec1 = {"order_id": "ord_update", "delivery_otp_confirmed": False}
    store.save_evidence(rec1)
    assert store.get_evidence("ord_update")["delivery_otp_confirmed"] is False

    rec2 = {"order_id": "ord_update", "delivery_otp_confirmed": True, "pod_document_id": "doc_new"}
    store.save_evidence(rec2)
    updated = store.get_evidence("ord_update")
    assert updated["delivery_otp_confirmed"] is True
    assert updated["pod_document_id"] == "doc_new"


def test_evidence_store_validation_missing_order_id(tmp_path):
    """Verify save_evidence raises ValueError when order_id is missing."""
    db_path = str(tmp_path / "evidence_val.db")
    store = EvidenceStore(db_path=db_path)
    with pytest.raises(ValueError, match="order_id"):
        store.save_evidence({"fulfillment_type": "physical"})
