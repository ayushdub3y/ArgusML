"""Programmatic End-to-End verification of Aegis console HTTP server."""

import json
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8080"

def get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")

def post(path, body=None):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")

def patch(path, body=None):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="PATCH"
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8")

def run_tests():
    print("=== Step 0: Resetting Demo Data ===")
    status, raw = post("/v1/demo/reset")
    assert status == 200
    print("[PASS] Demo state cleanly reset.")

    print("\n=== Step 1: Testing Shell / HTML Delivery ===")
    status, html = get("/")
    assert status == 200
    assert "Aegis — UPI Dispute Defense Engine" in html
    assert "Aegis" in html
    assert "--surface-ground" in html
    assert "Dispute Investigation" in html
    assert "Review Queue" in html
    assert "Audit Log" in html
    assert "Model Health" in html
    print("[PASS] Shell delivered complete Obsidian Sentinel SPA.")

    print("\n=== Step 2: Testing Disputes Listing ===")
    status, raw = get("/v1/disputes")
    assert status == 200
    data = json.loads(raw)
    assert "disputes" in data
    assert data["total"] >= 1
    disp_ids = [d["dispute_id"] for d in data["disputes"]]
    print(f"[PASS] Disputes retrieved: {disp_ids}")

    print("\n=== Step 3: Testing Investigation for disp_demo_escalate_001 ===")
    status, raw = get("/v1/disputes/disp_demo_escalate_001")
    assert status == 200
    inv = json.loads(raw)
    assert inv["dispute_id"] == "disp_demo_escalate_001"
    assert inv["state"] == "ESCALATED TO HUMAN REVIEW"
    assert inv["exposure"]["cap_status"] == "CAP BREACHED"
    assert "shap_values" in inv
    assert "features" in inv
    assert "contest_rebuttal" in inv
    print(f"[PASS] Investigation verified. SHAP features: {len(inv['shap_values'])}")

    print("\n=== Step 4: Testing Contest Action on disp_demo_escalate_001 ===")
    status, raw = patch("/v1/disputes/disp_demo_escalate_001/contest", {"notes": "Verified fulfillment via carrier OTP"})
    assert status == 200
    res = json.loads(raw)
    assert res["status"] == "contested"
    print(f"[PASS] Dispute contested successfully: {res}")

    print("\n=== Step 5: Testing Review Queue and Acceptance ===")
    import time
    dynamic_id = f"disp_test_cp_{int(time.time())}"
    post("/webhook", {
        "id": dynamic_id,
        "payment_id": f"pay_{dynamic_id}",
        "amount": 23000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "vpa": "customer_accept@okhdfcbank", "order_id": "order_demo_accept_001"}
    })
    status, raw = get(f"/v1/disputes/{dynamic_id}")
    assert status == 200
    inv2 = json.loads(raw)
    assert inv2["state"] == "PENDING HUMAN CHECKPOINT"
    print(f"[PASS] Pending checkpoint found: {inv2['dispute_id']}, State: {inv2['state']}")

    status, raw = post(f"/v1/disputes/{dynamic_id}/accept")
    assert status == 200
    res = json.loads(raw)
    assert res["status"] == "accepted"
    print(f"[PASS] Checkpoint accepted: {res}")

    print("\n=== Step 6: Testing Immutable Audit Log ===")
    status, raw = get("/v1/audit")
    assert status == 200
    audit_data = json.loads(raw)
    assert len(audit_data["audits"]) >= 1
    latest = audit_data["audits"][0]
    print(f"[PASS] Latest audit entry: ID={latest['dispute_id']}, Decision={latest['decision']}, Actor={latest['actor']}, Rule={latest['rule_fired']}")

    print("\n=== Step 7: Testing Model Health & Governance ===")
    status, raw = get("/v1/model_health")
    assert status == 200
    health = json.loads(raw)
    assert health["model_a"]["precision"] == 94.4
    assert health["model_a"]["recall"] == 97.3
    assert health["model_a"]["brier"] == 0.0338
    assert health["drift"]["status"] in ("NOMINAL", "insufficient_data")
    assert health["drift"]["drift_detected"] is False
    print(f"[PASS] Model health verified: Precision={health['model_a']['precision']}%, Brier={health['model_a']['brier']}, Drift={health['drift']['status']}")

    print("\nALL VERIFICATIONS PASSED CLEANLY!")

if __name__ == "__main__":
    run_tests()
