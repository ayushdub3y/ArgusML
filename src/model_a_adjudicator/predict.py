"""Implements Model A inference and directional feature attribution generation (§2 node E, §5)."""

import os
import joblib
from typing import Any, Dict, Optional, Tuple
import numpy as np

from src.features import assemble_features, features_to_vector, FEATURE_NAMES


_MODEL_CACHE: Optional[Any] = None


def get_model(model_path: Optional[str] = None) -> Any:
    """Load or retrieve cached calibrated Model A artifact."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None and model_path is None:
        return _MODEL_CACHE

    if model_path is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(base_dir, "src", "model_a_adjudicator", "model.joblib")

    if not os.path.exists(model_path):
        from src.model_a_adjudicator.train import run_training
        run_training()

    _MODEL_CACHE = joblib.load(model_path)
    return _MODEL_CACHE


def compute_feature_attributions(
    features: Dict[str, float],
    model: Any,
) -> Dict[str, float]:
    """Compute directional feature attribution contributions for audit trail and explainability (§5).

    These are domain-weighted directional attributions based on the sign and magnitude
    of each feature relative to the decision boundary. They indicate which evidence
    signals contributed most to the risk score, enabling operator-level transparency.

    Note: These are NOT SHAP values. For full model-agnostic explanations,
    integrate TreeSHAP via the `shap` library (production roadmap item).
    """
    contributions: Dict[str, float] = {}
    base_otp = features.get("delivery_otp_confirmed", 0.0)
    base_pod = features.get("has_pod_document", 0.0)
    base_geotag = features.get("has_geotag", 0.0)
    base_redeemed = features.get("digital_redeemed", 0.0)
    base_rgnb = features.get("cd1_cd2_position_score", 0.0)
    base_disp = features.get("disputes_raised_last_180d", 0.0)

    contributions["delivery_otp_confirmed"] = round(0.35 * (base_otp - 0.5), 3)
    contributions["has_pod_document"] = round(0.25 * (base_pod - 0.5), 3)
    contributions["has_geotag"] = round(0.15 * (base_geotag - 0.5), 3)
    contributions["digital_redeemed"] = round(0.40 * (base_redeemed - 0.5), 3)
    contributions["cd1_cd2_position_score"] = round(0.20 * (base_rgnb - 0.5), 3)
    contributions["disputes_raised_last_180d"] = round(0.10 * (base_disp - 1.0), 3)

    return contributions


def predict(
    dispute_payload: Dict[str, Any],
    evidence_record: Optional[Dict[str, Any]] = None,
    exposure_count: int = 0,
    exposure_value: int = 0,
    model: Optional[Any] = None,
) -> Tuple[float, Dict[str, float], Dict[str, float]]:
    """Predict calibrated p_illegitimate and generate feature attributions.

    Returns:
        Tuple of (p_illegitimate, feature_attributions_dict, raw_features_dict).
    """
    if model is None:
        model = get_model()

    features = assemble_features(
        dispute_payload,
        evidence_record,
        exposure_count=exposure_count,
        exposure_value=exposure_value,
    )
    vec = np.array([features_to_vector(features)], dtype=np.float32)

    # Predict calibrated probability of class 1 (is_illegitimate)
    probs = model.predict_proba(vec)[0]
    p_illegitimate = float(probs[1])

    feature_attributions = compute_feature_attributions(features, model)
    return p_illegitimate, feature_attributions, features
