"""Test suite for AcceptCheckpoint and AcceptCheckpointStore (§6b, Task 4)."""

import pytest
from src.human_review.accept_checkpoint import AcceptCheckpoint, AcceptCheckpointStore


def test_accept_checkpoint_render_one_liner():
    """Verify render_one_liner matches the documented §6b format."""
    checkpoint = AcceptCheckpoint(
        dispute_id="disp_123",
        amount=23000,  # ₹230
        p=0.08,
        v_cum=47000,   # ₹470
        rule_fired="low_p_auto_accept",
        respond_by=1735689600,
    )
    one_liner = checkpoint.render_one_liner()
    assert "p=0.08" in one_liner
    assert "V=₹230" in one_liner
    assert "V_cum(30d)=₹470" in one_liner
    assert "rule: low_p_auto_accept" in one_liner
    assert "recommend Accept" in one_liner


def test_accept_checkpoint_expand():
    """Verify expand returns full SHAP, evidence, features, and history."""
    features = {"amount_paise": 23000.0}
    shap = {"delivery_otp_confirmed": -0.15}
    evidence = {"order_id": "order_123"}
    history = {"disputes_raised_last_180d_this_merchant": 0}

    checkpoint = AcceptCheckpoint(
        dispute_id="disp_123",
        amount=23000,
        p=0.08,
        v_cum=47000,
        rule_fired="low_p_auto_accept",
        respond_by=1735689600,
        features=features,
        shap_values=shap,
        evidence=evidence,
        buyer_dispute_history=history,
    )
    expanded = checkpoint.expand()
    assert expanded["dispute_id"] == "disp_123"
    assert expanded["features"] == features
    assert expanded["shap_values"] == shap
    assert expanded["evidence"] == evidence
    assert expanded["buyer_dispute_history"] == history
    assert expanded["respond_by"] == 1735689600


def test_accept_checkpoint_confirm_idempotence():
    """Verify confirm() is idempotent and triggers on_confirm only once."""
    calls = []

    def callback(cp):
        calls.append(cp.confirmed_by)

    checkpoint = AcceptCheckpoint(
        dispute_id="disp_123",
        amount=23000,
        p=0.08,
        v_cum=0,
        rule_fired="low_p_auto_accept",
        on_confirm=callback,
    )

    # First confirm should succeed and invoke callback
    res1 = checkpoint.confirm(actor="human")
    assert res1 is True
    assert checkpoint.confirmed is True
    assert checkpoint.confirmed_by == "human"
    assert len(calls) == 1

    # Second confirm should be a no-op and NOT re-invoke callback
    res2 = checkpoint.confirm(actor="watchdog")
    assert res2 is False
    assert checkpoint.confirmed_by == "human"  # remains initial confirmed_by
    assert len(calls) == 1


def test_accept_checkpoint_store_persistence_and_rebinding(tmp_path):
    """Verify AcceptCheckpointStore persists checkpoints and rebinds active on_confirm on reload."""
    db_path = str(tmp_path / "test_checkpoints.db")
    store1 = AcceptCheckpointStore(db_path=db_path)

    checkpoint = AcceptCheckpoint(
        dispute_id="disp_store_01",
        amount=18000,
        p=0.12,
        v_cum=5000,
        rule_fired="low_p_auto_accept",
        respond_by=1735690000,
    )
    store1["disp_store_01"] = checkpoint
    assert "disp_store_01" in store1
    assert len(store1) == 1

    # Simulated restart: instantiate fresh store with a new callback
    rebound_calls = []

    def new_callback(cp):
        rebound_calls.append(cp.dispute_id)

    store2 = AcceptCheckpointStore(db_path=db_path, on_confirm_callback=new_callback)
    assert "disp_store_01" in store2
    restored = store2["disp_store_01"]
    assert restored.amount == 18000
    assert restored.p == 0.12

    # Calling confirm on restored checkpoint executes new rebound callback
    confirmed = restored.confirm(actor="human")
    assert confirmed is True
    assert rebound_calls == ["disp_store_01"]
