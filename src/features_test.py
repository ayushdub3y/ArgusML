"""Test suite for feature assembly (§2 node D)."""

import pytest
from src.features import assemble_features, features_to_vector, FEATURE_NAMES


def test_assemble_features_complete_record():
    """Verify feature vector assembly from dispute, evidence, and exposure."""
    dispute = {
        "amount": 250000,
    }
    evidence = {
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_123",
        "delivery_geotag": [12.9716, 77.5946],
        "digital_redemption_ts": None,
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 1,
            "approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced",
        },
        "time_to_dispute_days": 2,
    }

    feats = assemble_features(dispute, evidence, exposure_count=2, exposure_value=40000)
    assert feats["amount_paise"] == 250000.0
    assert feats["delivery_otp_confirmed"] == 1.0
    assert feats["has_pod_document"] == 1.0
    assert feats["has_geotag"] == 1.0
    assert feats["is_digital_voucher"] == 0.0
    assert feats["digital_redeemed"] == 0.0
    assert feats["cd1_cd2_position_score"] == 2.0
    assert feats["exposure_count_window"] == 2.0
    assert feats["exposure_value_window_paise"] == 40000.0

    vec = features_to_vector(feats)
    assert len(vec) == len(FEATURE_NAMES)
    assert vec[0] == 250000.0


def test_assemble_features_digital_voucher_and_cap_positions():
    """Verify digital voucher redemption and near_cap CD1/CD2 scoring."""
    dispute = {"amount": 50000}
    evidence = {
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": 1735505000,
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 0,
            "approx_position_vs_cd1_cd2_cap": "near_cap",
        },
    }
    feats = assemble_features(dispute, evidence)
    assert feats["is_digital_voucher"] == 1.0
    assert feats["digital_redeemed"] == 1.0
    assert feats["cd1_cd2_position_score"] == 1.0


def test_assemble_features_missing_evidence():
    """Verify feature assembly handles missing evidence record natively."""
    dispute = {"amount": 50000}
    feats = assemble_features(dispute, evidence_record=None)
    assert feats["amount_paise"] == 50000.0
    assert feats["delivery_otp_confirmed"] == 0.0
    assert feats["has_pod_document"] == 0.0
    assert feats["cd1_cd2_position_score"] == 0.0
