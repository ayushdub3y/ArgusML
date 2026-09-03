"""HTTP UI routes, human-review endpoints, and dashboard auth gate (§2, §6b, §10)."""

import base64
import binascii
import html
import os
import time
from typing import Any, Optional
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from src.drift_monitor import DriftMonitor


def require_dashboard_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Validate HTTP Basic Auth credentials if DASHBOARD_USERNAME/PASSWORD are configured.

    Fail-open default: If neither variable is set, requests are permitted unauthenticated
    for local sandbox/demo ergonomics.
    """
    expected_user = os.environ.get("DASHBOARD_USERNAME")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD")

    if not expected_user and not expected_pass:
        return True

    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Aegis Dashboard"'},
        )

    try:
        encoded_creds = authorization.split(" ", 1)[1]
        decoded = base64.b64decode(encoded_creds).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": 'Basic realm="Aegis Dashboard"'},
        )

    if username != (expected_user or "") or password != (expected_pass or ""):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": 'Basic realm="Aegis Dashboard"'},
        )

    return True


def create_ui_router(handler: Any) -> APIRouter:
    """Create FastAPI APIRouter bound to the given WebhookHandler instance."""
    router = APIRouter()
    drift_monitor = DriftMonitor()

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, authorization: Optional[str] = Header(None)):
        """Render Aegis operations dashboard with active queues and recent audit trail."""
        require_dashboard_auth(authorization)

        now = int(time.time())
        pending_checkpoints = handler.pending_checkpoints.values()
        escalated_items = handler.escalation_queue.all_pending()
        recent_audits = handler.audit_log.get_entries(limit=50)
        drift_status = drift_monitor.check_drift()

        sig_status = "Enabled" if os.environ.get("RAZORPAY_WEBHOOK_SECRET") else "Disabled (Sandbox Default)"
        auth_status = "Enabled" if os.environ.get("DASHBOARD_USERNAME") else "Disabled (Sandbox Default)"

        # Render Checkpoints rows
        cp_rows = []
        for cp in pending_checkpoints:
            time_left = max(0, cp.respond_by - now) if cp.respond_by else 0
            v_inr = cp.amount / 100.0
            cp_rows.append(f"""
            <tr>
                <td><code>{html.escape(cp.dispute_id)}</code></td>
                <td>₹{v_inr:.2f}</td>
                <td><span class="badge badge-warning">p={cp.p:.2f}</span></td>
                <td>{time_left}s remaining</td>
                <td>{html.escape(cp.render_one_liner())}</td>
                <td>
                    <form method="POST" action="/accept_checkpoint/{html.escape(cp.dispute_id)}/confirm" style="display:inline;">
                        <button type="submit" class="btn btn-sm btn-success">Confirm Accept</button>
                    </form>
                    <a href="/accept_checkpoint/{html.escape(cp.dispute_id)}/expand" class="btn btn-sm btn-outline" target="_blank">Expand</a>
                </td>
            </tr>
            """)
        cp_table = "\n".join(cp_rows) if cp_rows else "<tr><td colspan='6' style='text-align:center; color:#888;'>No pending accept checkpoints awaiting review</td></tr>"

        # Render Escalations rows
        esc_rows = []
        for item in escalated_items:
            time_left = handler.escalation_queue.seconds_remaining(item.get("dispute_id", ""), now_ts=now)
            v_inr = (item.get("amount") or 0) / 100.0
            p_val = item.get("p", 0.0)
            rule = item.get("rule_fired", "")
            esc_rows.append(f"""
            <tr>
                <td><code>{html.escape(item.get("dispute_id", ""))}</code></td>
                <td>₹{v_inr:.2f}</td>
                <td><span class="badge badge-danger">p={p_val:.2f}</span></td>
                <td>{time_left}s remaining</td>
                <td><code>{html.escape(rule)}</code></td>
            </tr>
            """)
        esc_table = "\n".join(esc_rows) if esc_rows else "<tr><td colspan='5' style='text-align:center; color:#888;'>No disputes in escalation queue</td></tr>"

        # Render Audit Trail rows (capped to 50, latest first)
        audit_rows = []
        for a in recent_audits:
            dec = a.get("decision", "")
            badge_class = "badge-success" if dec == "accept" else ("badge-info" if dec == "contest" else "badge-warning")
            audit_rows.append(f"""
            <tr>
                <td><code>{html.escape(str(a.get("dispute_id", "")))}</code></td>
                <td><span class="badge {badge_class}">{html.escape(dec.upper())}</span></td>
                <td><code>{html.escape(str(a.get("actor", "")))}</code></td>
                <td><small>{html.escape(str(a.get("rule_fired", "")))}</small></td>
                <td><small>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(a.get("timestamp", now)))}</small></td>
            </tr>
            """)
        audit_table = "\n".join(audit_rows) if audit_rows else "<tr><td colspan='5' style='text-align:center; color:#888;'>No audit records recorded yet</td></tr>"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aegis — UPI Dispute Defense Dashboard</title>
    <style>
        :root {{
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-heading: #f0f6fc;
            --primary: #58a6ff;
            --success: #238636;
            --warning: #d29922;
            --danger: #da3633;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 24px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        h1 {{ margin: 0; font-size: 24px; color: var(--text-heading); }}
        .status-pill {{
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            background: rgba(35, 134, 54, 0.2);
            color: #3fb950;
            border: 1px solid rgba(35, 134, 54, 0.4);
        }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 16px;
        }}
        .card h3 {{ margin-top: 0; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; color: #8b949e; }}
        .card-val {{ font-size: 20px; font-weight: 600; color: var(--text-heading); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 14px;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{ background: #21262d; color: var(--text-heading); font-weight: 600; }}
        .badge {{
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 500;
        }}
        .badge-success {{ background: rgba(35, 134, 54, 0.2); color: #3fb950; }}
        .badge-warning {{ background: rgba(210, 153, 34, 0.2); color: #e3b341; }}
        .badge-danger {{ background: rgba(218, 54, 51, 0.2); color: #f85149; }}
        .badge-info {{ background: rgba(88, 166, 255, 0.2); color: #58a6ff; }}
        .btn {{
            cursor: pointer;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            text-decoration: none;
            display: inline-block;
        }}
        .btn-success {{ background: var(--success); color: #fff; border: 1px solid rgba(240,246,252,0.1); }}
        .btn-outline {{ background: transparent; color: var(--primary); border: 1px solid var(--primary); }}
        code {{ background: rgba(110,118,129,0.4); padding: 2px 4px; border-radius: 3px; font-size: 12px; }}
        .section-title {{ font-size: 18px; color: var(--text-heading); margin: 24px 0 12px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>Aegis — UPI Dispute Defense Engine</h1>
                <small style="color:#8b949e;">Track 02: AI Risk Manager | Defense-Only Architecture (§12)</small>
            </div>
            <div>
                <span class="status-pill">Active & Ready</span>
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <h3>Model A Adjudicator</h3>
                <div class="card-val">Calibrated GBDT</div>
                <small style="color:#8b949e;">Brier 0.0338 | Recall 97.3%</small>
            </div>
            <div class="card">
                <h3>Model B Assembler</h3>
                <div class="card-val">Fact-Validated</div>
                <small style="color:#8b949e;">Zero-hallucination hard block</small>
            </div>
            <div class="card">
                <h3>Drift Monitor</h3>
                <div class="card-val">{drift_status['status'].upper()}</div>
                <small style="color:#8b949e;">Window {drift_status.get('sample_count', 0)} samples</small>
            </div>
            <div class="card">
                <h3>Security Posture</h3>
                <div class="card-val" style="font-size:14px; margin-top:4px;">Sig: {sig_status}</div>
                <div class="card-val" style="font-size:14px;">Auth: {auth_status}</div>
            </div>
        </div>

        <div class="section-title">Pending Human-Accept Checkpoints (§6b)</div>
        <div class="card" style="padding:0; overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Dispute ID</th>
                        <th>Amount</th>
                        <th>Risk Score</th>
                        <th>SLA Countdown</th>
                        <th>One-Line Reasoning</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {cp_table}
                </tbody>
            </table>
        </div>

        <div class="section-title">Escalation Review Queue (§2 Node K)</div>
        <div class="card" style="padding:0; overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Dispute ID</th>
                        <th>Amount</th>
                        <th>Risk Score</th>
                        <th>SLA Countdown</th>
                        <th>Routing Trigger</th>
                    </tr>
                </thead>
                <tbody>
                    {esc_table}
                </tbody>
            </table>
        </div>

        <div class="section-title">Immutable Audit Trail (Last 50 Entries, §2 Node L)</div>
        <div class="card" style="padding:0; overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Dispute ID</th>
                        <th>Decision</th>
                        <th>Actor</th>
                        <th>Rule Fired</th>
                        <th>Timestamp</th>
                    </tr>
                </thead>
                <tbody>
                    {audit_table}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content, status_code=200)

    @router.post("/accept_checkpoint/{dispute_id}/confirm")
    async def confirm_checkpoint(dispute_id: str):
        """Confirm a pending accept checkpoint (§6b)."""
        checkpoint = handler.pending_checkpoints.get(dispute_id)
        if not checkpoint:
            return JSONResponse(
                status_code=404,
                content={"error": f"Dispute {dispute_id} not found in pending checkpoints"},
            )

        confirmed = checkpoint.confirm(actor="human")
        return JSONResponse(
            status_code=200,
            content={
                "status": "accepted",
                "dispute_id": dispute_id,
                "confirmed_by": "human",
                "idempotent_replay": not confirmed,
            },
        )

    @router.get("/accept_checkpoint/{dispute_id}/expand")
    async def expand_checkpoint(dispute_id: str):
        """Expand card for full reasoning breakdown, SHAP, and evidence records."""
        checkpoint = handler.pending_checkpoints.get(dispute_id)
        if not checkpoint:
            return JSONResponse(
                status_code=404,
                content={"error": f"Dispute {dispute_id} not found in pending checkpoints"},
            )

        return JSONResponse(status_code=200, content=checkpoint.expand())

    return router
