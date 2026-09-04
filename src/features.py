"""Implements feature assembly: fulfillment strength, buyer/VPA reputation (incl. RGNB override flag), transaction context, and cumulative exposure (§2 node D)."""

from typing import Any, Dict, List, Optional


FEATURE_NAMES = [
    "amount_paise",
    "delivery_otp_confirmed",
    "has_pod_document",
    "has_geotag",
    "is_digital_voucher",
    "digital_redeemed",
    "disputes_raised_last_180d",
    "cd1_cd2_position_score",
    "time_to_dispute_days",
    "exposure_count_window",
    "exposure_value_window_paise",
]


def assemble_features(
    dispute_payload: Dict[str, Any],
    evidence_record: Optional[Dict[str, Any]] = None,
    exposure_count: int = 0,
    exposure_value: int = 0,
) -> Dict[str, float]:
    """Assemble standardized feature dictionary from dispute, evidence, and exposure counters.

    Args:
        dispute_payload: The Razorpay payment.dispute.created payload (§4).
        evidence_record: The merchant-side evidence record (§4) or None if missing.
        exposure_count: Rolling count of auto-accepted disputes for this identity (§6b).
        exposure_value: Rolling value (paise) of auto-accepted disputes for this identity (§6b).

    Returns:
        Dict mapping feature name to numeric value.
    """
    try:
        amount = max(0.0, float(dispute_payload.get("amount", 0) or 0.0))
    except (ValueError, TypeError):
        amount = 0.0

    if evidence_record is None:
        return {
            "amount_paise": amount,
            "delivery_otp_confirmed": 0.0,
            "has_pod_document": 0.0,
            "has_geotag": 0.0,
            "is_digital_voucher": 0.0,
            "digital_redeemed": 0.0,
            "disputes_raised_last_180d": 0.0,
            "cd1_cd2_position_score": 0.0,
            "time_to_dispute_days": 3.0,
            "exposure_count_window": float(exposure_count),
            "exposure_value_window_paise": float(exposure_value),
        }

    fulfillment_type = evidence_record.get("fulfillment_type", "physical")
    is_digital = 1.0 if fulfillment_type == "digital_voucher" else 0.0

    otp_confirmed = 1.0 if evidence_record.get("delivery_otp_confirmed") else 0.0
    has_pod = 1.0 if evidence_record.get("pod_document_id") else 0.0
    has_geotag = 1.0 if evidence_record.get("delivery_geotag") else 0.0
    digital_redeemed = 1.0 if evidence_record.get("digital_redemption_ts") is not None else 0.0

    history = evidence_record.get("buyer_dispute_history", {})
    disputes_180d = float(history.get("disputes_raised_last_180d_this_merchant", 0))

    cap_pos = history.get("approx_position_vs_cd1_cd2_cap", "unknown")
    if cap_pos == "over_cap_rgnb_forced":
        cd1_cd2_score = 2.0
    elif cap_pos == "near_cap":
        cd1_cd2_score = 1.0
    else:
        cd1_cd2_score = 0.0

    time_to_dispute = float(evidence_record.get("time_to_dispute_days", 3))

    return {
        "amount_paise": amount,
        "delivery_otp_confirmed": otp_confirmed,
        "has_pod_document": has_pod,
        "has_geotag": has_geotag,
        "is_digital_voucher": is_digital,
        "digital_redeemed": digital_redeemed,
        "disputes_raised_last_180d": disputes_180d,
        "cd1_cd2_position_score": cd1_cd2_score,
        "time_to_dispute_days": time_to_dispute,
        "exposure_count_window": float(exposure_count),
        "exposure_value_window_paise": float(exposure_value),
    }


def features_to_vector(features: Dict[str, float]) -> List[float]:
    """Convert features dict to ordered list matching FEATURE_NAMES."""
    return [features[name] for name in FEATURE_NAMES]
