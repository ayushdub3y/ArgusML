"""Implements §7 synthetic data generator: VPA-device stochastic block model with a configurable RGNB-forced-override share, emitting the §4 schemas."""

import hashlib
import json
import os
import random
from typing import Any, Dict, List, Tuple


CATEGORIES = [
    ("food_and_beverage", 0.35, (5000, 80000)),       # ₹50 - ₹800
    ("quick_commerce_grocery", 0.30, (10000, 150000)), # ₹100 - ₹1,500
    ("fashion_apparel", 0.20, (50000, 500000)),       # ₹500 - ₹5,000
    ("electronics_accessories", 0.10, (100000, 1500000)), # ₹1,000 - ₹15,000
    ("digital_services", 0.05, (10000, 250000)),      # ₹100 - ₹2,500
]


def _hash_str(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sample_category(rng: random.Random) -> Tuple[str, int]:
    """Sample category and amount in paise using the provided seeded rng."""
    cat_names = [c[0] for c in CATEGORIES]
    weights = [c[1] for c in CATEGORIES]
    chosen_cat = rng.choices(cat_names, weights=weights, k=1)[0]
    for name, _, (low, high) in CATEGORIES:
        if name == chosen_cat:
            amount = rng.randint(low, high)
            return chosen_cat, amount
    return "quick_commerce_grocery", 45000


def generate(n: int = 6000, seed: int = 42) -> List[Dict[str, Any]]:
    """Generate n synthetic dispute and evidence records deterministically.
    
    All random operations must be strictly drawn from rng.
    """
    rng = random.Random(seed)
    records: List[Dict[str, Any]] = []

    # Base timestamps: 30-day window
    base_ts = 1735000000  # Dec 24, 2024 approx

    # Pre-generate a pool of VPAs and device fingerprints to simulate repeat/ring disputers
    n_vpas = max(10, n // 4)
    vpa_pool = [f"user_{i:04d}@{rng.choice(['okhdfcbank', 'okaxis', 'oksbi', 'paytm', 'ybl'])}" for i in range(n_vpas)]
    device_pool = [f"device_fp_{i:04d}_{rng.randint(10000, 99999)}" for i in range(n_vpas)]

    # RGNB forced override share ~ 8-12% per §7
    rgnb_pool = set(rng.sample(range(n_vpas), max(1, int(n_vpas * 0.10))))

    for i in range(n):
        dispute_id = f"disp_synth_{i:06d}"
        payment_id = f"pay_synth_{i:06d}"
        order_id = f"order_synth_{i:06d}"

        # Buyer identity
        user_idx = rng.randint(0, n_vpas - 1)
        vpa = vpa_pool[user_idx]
        device = device_pool[user_idx]
        vpa_h = _hash_str(vpa)
        device_h = _hash_str(device)

        category, amount = _sample_category(rng)
        is_digital = category == "digital_services"
        fulfillment_type = "digital_voucher" if is_digital else "physical"

        # Timestamp progression
        tx_time_offset = rng.randint(0, 30 * 86400)
        tx_ts = base_ts + tx_time_offset
        dispatch_ts = tx_ts + rng.randint(1800, 7200)
        delivery_ts = dispatch_ts + rng.randint(1800, 14400)
        time_to_dispute_days = rng.randint(1, 7)
        dispute_ts = delivery_ts + time_to_dispute_days * 86400
        respond_by = dispute_ts + 86400 * 3  # T+3 response window per §1

        # Determine true illegitimacy (ground truth label)
        is_rgnb_forced = user_idx in rgnb_pool

        prob_illegitimate = 0.50
        if is_rgnb_forced:
            prob_illegitimate += 0.35
            cd1_cd2_position = "over_cap_rgnb_forced"
        elif rng.random() < 0.15:
            cd1_cd2_position = "near_cap"
            prob_illegitimate += 0.15
        else:
            cd1_cd2_position = "unknown"

        is_illegitimate = 1 if rng.random() < prob_illegitimate else 0

        # Physical evidence generation conditional on fulfillment truth
        if is_digital:
            delivery_otp_confirmed = False
            geotag = None
            pod_doc_id = None
            digital_redemption_ts = delivery_ts + rng.randint(60, 3600) if is_illegitimate else None
        else:
            digital_redemption_ts = None
            if is_illegitimate:
                delivery_otp_confirmed = rng.random() < 0.85
                geotag = [round(12.9716 + rng.uniform(-0.05, 0.05), 4), round(77.5946 + rng.uniform(-0.05, 0.05), 4)]
                pod_doc_id = f"doc_pod_{i:06d}" if rng.random() < 0.90 else None
            else:
                delivery_otp_confirmed = rng.random() < 0.05
                geotag = [round(12.9716 + rng.uniform(-0.05, 0.05), 4), round(77.5946 + rng.uniform(-0.05, 0.05), 4)] if rng.random() < 0.3 else None
                pod_doc_id = None if rng.random() < 0.80 else f"doc_pod_unverified_{i:06d}"

        prior_disputes = rng.randint(1, 4) if is_rgnb_forced else (rng.randint(0, 2) if rng.random() < 0.25 else 0)

        dispute_payload = {
            "id": dispute_id,
            "payment_id": payment_id,
            "amount": amount,
            "reason_code": "goods_not_delivered",
            "respond_by": respond_by,
            "status": "open",
            "payment": {
                "method": "upi",
                "vpa": vpa,
                "order_id": order_id
            }
        }

        evidence_record = {
            "order_id": order_id,
            "fulfillment_type": fulfillment_type,
            "dispatch_ts": dispatch_ts,
            "delivery_ts": delivery_ts,
            "delivery_otp_confirmed": delivery_otp_confirmed,
            "delivery_geotag": geotag,
            "pod_document_id": pod_doc_id,
            "digital_redemption_ts": digital_redemption_ts,
            "buyer_identity": {
                "vpa_hash": vpa_h,
                "device_fingerprint_hash": device_h
            },
            "buyer_dispute_history": {
                "disputes_raised_last_180d_this_merchant": prior_disputes,
                "approx_position_vs_cd1_cd2_cap": cd1_cd2_position
            },
            "time_to_dispute_days": time_to_dispute_days
        }

        records.append({
            "dispute": dispute_payload,
            "evidence": evidence_record,
            "is_illegitimate": is_illegitimate,
            "created_at": dispute_ts
        })

    return records


def save_dataset(records: List[Dict[str, Any]], filepath: str) -> None:
    """Save records to jsonl format."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "synthetic_disputes.jsonl")
    data = generate(n=6000, seed=42)
    save_dataset(data, out_path)
    print(f"Generated {len(data)} synthetic disputes saved to {out_path}")
