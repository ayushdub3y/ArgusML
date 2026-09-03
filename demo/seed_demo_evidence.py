"""Seeds the evidence store and exposure store with demo records for live testing (§2, §4)."""

import hashlib
import os
import sys

# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.evidence_store import EvidenceStore
from src.exposure_store import ExposureStore


def sha256_hash(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def seed_demo_data():
    """Seed evidence and exposure for accept, contest, and escalate demo scenarios."""
    ev_store = EvidenceStore()
    exp_store = ExposureStore()

    # 1. Accept Demo Evidence: Courier GPS in vicinity, but delivery OTP unconfirmed & no POD
    # Produces calibrated p=0.08 (matching ARCHITECTURE.md §6b), demonstrating active Model A inference
    vpa_accept = sha256_hash("customer_accept@okhdfcbank")
    dev_accept = sha256_hash("dev_accept_fingerprint")
    ev_store.save_evidence({
        "order_id": "order_demo_accept_001",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735550000,
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {
            "vpa_hash": vpa_accept,
            "device_fingerprint_hash": dev_accept,
        },
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 0,
            "approx_position_vs_cd1_cd2_cap": "unknown",
        },
        "time_to_dispute_days": 4,
    })

    # 2. Contest Demo Evidence: High-confidence legitimate fulfillment with OTP, POD & Geotag
    vpa_contest = sha256_hash("customer_contest@oksbi")
    dev_contest = sha256_hash("dev_contest_fingerprint")
    ev_store.save_evidence({
        "order_id": "order_demo_contest_001",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735540000,
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_demo_verified_99",
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {
            "vpa_hash": vpa_contest,
            "device_fingerprint_hash": dev_contest,
        },
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 2,
            "approx_position_vs_cd1_cd2_cap": "over_cap_rgnb_forced",
        },
        "time_to_dispute_days": 1,
    })

    # 3. Escalate Demo Evidence: Breached velocity limit triggering §6b gate
    vpa_escalate = sha256_hash("customer_escalate@paytm")
    dev_escalate = sha256_hash("dev_escalate_fingerprint")
    ev_store.save_evidence({
        "order_id": "order_demo_escalate_001",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735560000,
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
        "delivery_geotag": None,
        "buyer_identity": {
            "vpa_hash": vpa_escalate,
            "device_fingerprint_hash": dev_escalate,
        },
        "buyer_dispute_history": {
            "disputes_raised_last_180d_this_merchant": 1,
            "approx_position_vs_cd1_cd2_cap": "unknown",
        },
        "time_to_dispute_days": 3,
    })

    # Pre-seed 4 auto-accepted transactions for escalate identity to trigger §6b velocity gate
    now_ts = 1735600000
    for i in range(4):
        exp_store.record_accept(
            vpa_hash=vpa_escalate,
            device_fingerprint_hash=dev_escalate,
            amount=20000,
            timestamp=now_ts - 500 * (i + 1),
        )

    print("Demo evidence seeded successfully for order_demo_accept_001, order_demo_contest_001, and order_demo_escalate_001.")


if __name__ == "__main__":
    seed_demo_data()
