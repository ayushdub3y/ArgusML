"""Implements Model A training pipeline with an out-of-time split (§5, §7)."""

import json
import os
import pickle
from typing import Any, Dict, List, Tuple
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from xgboost import XGBClassifier

from src.features import assemble_features, features_to_vector, FEATURE_NAMES


def load_dataset(filepath: str) -> List[Dict[str, Any]]:
    """Load JSONL dataset."""
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def out_of_time_split(
    records: List[Dict[str, Any]], test_ratio: float = 0.20
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split records strictly out-of-time based on creation timestamp (§7)."""
    sorted_records = sorted(records, key=lambda r: r.get("created_at", 0))
    split_idx = int(len(sorted_records) * (1.0 - test_ratio))
    train_records = sorted_records[:split_idx]
    test_records = sorted_records[split_idx:]
    return train_records, test_records


def prepare_xy(records: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
    """Extract feature matrix X and ground truth label vector y."""
    X_list: List[List[float]] = []
    y_list: List[int] = []

    for rec in records:
        disp = rec["dispute"]
        ev = rec.get("evidence")
        feats = assemble_features(disp, ev)
        vec = features_to_vector(feats)
        X_list.append(vec)
        y_list.append(int(rec["is_illegitimate"]))

    return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.int32)


def train_model(X_train: np.ndarray, y_train: np.ndarray) -> Any:
    """Train gradient-boosted trees with isotonic calibration (§3, §5)."""
    base_model = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.08,
        random_state=42,
        eval_metric="logloss",
    )
    # CalibratedClassifierCV ensures calibrated probability outputs
    calibrated_model = CalibratedClassifierCV(
        estimator=base_model,
        method="isotonic",
        cv=3,
    )
    calibrated_model.fit(X_train, y_train)
    return calibrated_model


def save_model(model: Any, filepath: str) -> None:
    """Serialize model artifact to disk."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "wb") as f:
        pickle.dump(model, f)


def run_training() -> str:
    """Main training routine."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_path = os.path.join(base_dir, "data", "synthetic_disputes.jsonl")
    model_path = os.path.join(base_dir, "src", "model_a_adjudicator", "model.joblib")

    if not os.path.exists(data_path):
        from data.synthetic_generator import generate, save_dataset
        data = generate(n=6000, seed=42)
        save_dataset(data, data_path)

    records = load_dataset(data_path)
    train_records, test_records = out_of_time_split(records, test_ratio=0.20)
    X_train, y_train = prepare_xy(train_records)

    model = train_model(X_train, y_train)
    save_model(model, model_path)
    print(f"Model trained on {len(X_train)} samples and saved to {model_path}")
    return model_path


if __name__ == "__main__":
    run_training()
