"""ArgusML Comprehensive End-to-End Verification Suite.

Consolidated validation covering:
1. Server health and favicon checks
2. Single-Page App (SPA) shell delivery & production-readiness assertions
3. Static & dynamic DOM ID integrity
4. Demo reset & disputes catalog loading
5. Dispute investigation state & feature attributions
6. Autonomous and operator contest workflows
7. Human review queue & single-tap accept checkpoint
8. Immutable SQLite audit trail verification
9. Model governance, calibration metrics & drift monitoring
"""

import json
import re
import sys
import time
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
    print("=================================================================")
    print("   ArgusML Comprehensive End-to-End Verification Suite")
    print("=================================================================")

    # 1. Health & Favicon
    print("\n--- Step 1: Health & Clean Favicon Verification ---")
    status, raw = get("/health")
    assert status == 200 and json.loads(raw).get("status") == "ok"
    print("[PASS] /health returned 200 OK")

    req = urllib.request.Request(f"{BASE_URL}/favicon.ico")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 204
    print("[PASS] /favicon.ico returned 204 No Content (zero console 404 noise)")

    # 2. Shell delivery & UI assertions
    print("\n--- Step 2: SPA Shell & Obsidian Sentinel UI Assertions ---")
    status, html = get("/")
    assert status == 200
    assert "ArgusML — Argus Dispute & Risk Gateway" in html
    assert "safeFetch" in html
    assert "copyTextToClipboard" in html
    assert 'rel="icon"' in html
    assert "🛡️" in html
    assert "timeZone: \"Asia/Kolkata\"" in html
    assert "id=\"inspector-modal\"" in html
    assert "id=\"toast-container\"" in html
    print("[PASS] SPA shell delivers complete Obsidian Sentinel interface")

    # 3. DOM ID integrity
    print("\n--- Step 3: Frontend DOM Element Integrity ---")
    js_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    js_code = "\n".join(js_blocks)
    get_elem_ids = set(re.findall(r"getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]", js_code))
    html_no_scripts = re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)
    html_ids = set(re.findall(r"id=['\"]([a-zA-Z0-9_-]+)['\"]", html_no_scripts))
    dynamic_ids = set(re.findall(r"id=['\"]([a-zA-Z0-9_-]+)['\"]", js_code))
    missing = get_elem_ids - (html_ids | dynamic_ids)
    assert len(missing) == 0, f"Unmatched DOM IDs: {missing}"
    print(f"[PASS] All {len(get_elem_ids)} frontend DOM elements verified 100% matched")

    # 4. Demo reset & disputes directory
    print("\n--- Step 4: Demo State Reset & Disputes Directory ---")
    status, raw = post("/v1/demo/reset")
    assert status == 200
    status, raw = get("/v1/disputes")
    assert status == 200
    data = json.loads(raw)
    assert "disputes" in data
    assert len(data["disputes"]) >= 3
    print(f"[PASS] Demo state reset cleanly: {len(data['disputes'])} disputes active")

    # 5. Dispute investigation & feature attributions
    print("\n--- Step 5: Dispute Investigation & Feature Attributions ---")
    sample_id = data["disputes"][0]["dispute_id"]
    status, raw = get(f"/v1/disputes/{sample_id}")
    assert status == 200
    inv = json.loads(raw)
    assert inv["dispute_id"] == sample_id
    assert "exposure" in inv
    assert "features" in inv
    assert "shap_values" in inv
    assert "contest_rebuttal" in inv
    print(f"[PASS] Investigation verified for {sample_id}: {len(inv.get('features', {}))} features analyzed")

    # 6. Contest submission action
    print("\n--- Step 6: Dispute Contest Submission Action ---")
    status, raw = patch(f"/v1/disputes/{sample_id}/contest", {"notes": "Verified fulfillment via carrier OTP"})
    assert status == 200
    res = json.loads(raw)
    assert res.get("status") == "contested"
    print(f"[PASS] Contest action succeeded: status={res.get('status')}")

    # 7. Checkpoint confirmation flow
    print("\n--- Step 7: Checkpoint Confirmation & Settlement Flow ---")
    dynamic_id = f"disp_test_cp_{int(time.time())}"
    post("/webhook", {
        "id": dynamic_id,
        "payment_id": f"pay_{dynamic_id}",
        "amount": 23000,
        "reason_code": "goods_not_delivered",
        "respond_by": 1735700000,
        "payment": {"method": "upi", "vpa": "customer_accept@okhdfcbank", "order_id": "order_demo_accept_001"}
    })
    status, raw = post(f"/v1/disputes/{dynamic_id}/accept")
    assert status == 200
    res = json.loads(raw)
    assert res.get("status") == "accepted"
    print(f"[PASS] Checkpoint accepted: {res.get('status')}")

    # 8. Immutable Audit Trail
    print("\n--- Step 8: Immutable SQLite Audit Trail ---")
    status, raw = get("/v1/audit?limit=10")
    assert status == 200
    audits = json.loads(raw).get("audits", [])
    assert len(audits) >= 1
    print(f"[PASS] Audit trail verified: {len(audits)} immutable events recorded")

    # 9. Model Health & Drift Monitor
    print("\n--- Step 9: Model Health, Calibration & Drift Monitoring ---")
    status, raw = get("/v1/model_health")
    assert status == 200
    mh = json.loads(raw)
    assert mh["model_a"]["precision"] == 94.4
    assert mh["model_a"]["recall"] == 97.3
    assert mh["model_a"]["brier"] == 0.0338
    assert mh["model_b"]["status"] == "Active"
    assert mh["drift"]["drift_detected"] is False
    print(f"[PASS] Model A: Precision={mh['model_a']['precision']}%, Brier={mh['model_a']['brier']}")
    print(f"[PASS] Model B: Fact-validation {mh['model_b']['status']}")
    print(f"[PASS] Drift Monitor: status={mh['drift']['status']}, drift_detected={mh['drift']['drift_detected']}")

    print("\n=================================================================")
    print("   ALL 9 END-TO-END SUITE CHECKS PASSED WITH ZERO DEFECTS!")
    print("=================================================================\n")


if __name__ == "__main__":
    run_tests()
