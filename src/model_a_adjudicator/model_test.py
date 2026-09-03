"""Test suite for Model A adjudicator training and calibrated inference (§5, §7)."""

import numpy as np
import pytest
from src.model_a_adjudicator.predict import compute_feature_attributions, predict
from src.model_a_adjudicator.train import out_of_time_split, prepare_xy, train_model


def test_out_of_time_split():
    """Verify out-of-time split strictly orders records by created_at."""
    records = [
        {"created_at": 100, "val": 1},
        {"created_at": 300, "val": 3},
        {"created_at": 200, "val": 2},
        {"created_at": 400, "val": 4},
        {"created_at": 500, "val": 5},
    ]
    train_recs, test_recs = out_of_time_split(records, test_ratio=0.40)
    assert len(train_recs) == 3
    assert len(test_recs) == 2
    assert [r["val"] for r in train_recs] == [1, 2, 3]
    assert [r["val"] for r in test_recs] == [4, 5]


def test_model_training_and_calibration():
    """Verify training produces calibrated probabilities within [0, 1]."""
    X = np.array([
        [10000, 1, 1, 1, 0, 0, 0, 0, 2, 0, 0],
        [20000, 1, 1, 1, 0, 0, 1, 2, 1, 0, 0],
        [50000, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0],
        [40000, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0],
        [15000, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0],
        [60000, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0],
    ], dtype=np.float32)
    y = np.array([1, 1, 0, 0, 1, 0], dtype=np.int32)

    model = train_model(X, y)
    probs = model.predict_proba(X)
    assert probs.shape == (6, 2)
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)


def test_predict_and_feature_attributions():
    """Verify predict returns calibrated probability and valid feature attribution contributions."""
    dispute = {"amount": 250000}
    evidence = {
        "order_id": "ord_attr",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod",
        "delivery_geotag": [12.97, 77.59],
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 2,
            "approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced",
        },
        "time_to_dispute_days": 1,
    }

    p, attr_vals, features = predict(dispute, evidence)
    assert 0.0 <= p <= 1.0
    assert "delivery_otp_confirmed" in attr_vals
    assert "cd1_cd2_position_score" in attr_vals
    assert attr_vals["delivery_otp_confirmed"] > 0
