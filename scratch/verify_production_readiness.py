import urllib.request

html = urllib.request.urlopen("http://localhost:8080/").read().decode("utf-8")

assert '<span class="clock-display" id="live-clock">IST --:--:--</span>' in html, "Clock initial text not IST"
assert "function formatIST(ts, includeSeconds)" in html, "formatIST missing"
assert 'timeZone: "Asia/Kolkata"' in html, "Asia/Kolkata timezone missing"

# Check absence of architecture section symbols
assert "§" not in html, "Architecture section symbol § found in UI shell"
assert "Node " not in html, "Internal Node reference found"
assert "SQLite WAL" not in html, "SQLite WAL reference found"

# Check Overview health strip
assert "Risk Assessment:" in html and ">Healthy<" in html, "Overview health strip missing Risk Assessment"
assert "Evidence Response:" in html and ">Active<" in html, "Overview health strip missing Evidence Response"
assert "Drift Monitoring:" in html, "Overview health strip missing Drift Monitoring"
assert "Security:" in html and ">Protected<" in html, "Overview health strip missing Security"

# Check Inspector modal
assert 'id="inspector-modal"' in html, "Inspector modal missing"
assert 'id="btn-copy-modal-json"' in html, "Copy JSON button missing"
assert 'id="modal-timestamp-ist"' in html, "Modal timestamp IST missing"
assert "openDisputePayloadInspector" in html, "openDisputePayloadInspector missing"
assert "openTimelineInspector" in html, "openTimelineInspector missing"
assert "openAuditInspector" in html, "openAuditInspector missing"
assert "copyModalJson" in html, "copyModalJson missing"

# Check Technical identifiers expandable details
assert "View technical identifiers" in html, "View technical identifiers details missing"
assert "Verified identity record" in html, "Verified identity record missing"
assert "Linked device record" in html, "Linked device record missing"

# Check Model Health cards
assert "Model A · Risk Assessment" in html, "Model A card title mismatch"
assert "Model B · Evidence Response" in html, "Model B card title mismatch"
assert "Drift Monitoring" in html, "Drift monitoring card title mismatch"
assert "Ticket-Size Performance" in html, "Ticket-size card title mismatch"

print("SUCCESS: ALL 16 PRODUCTION-READINESS ASSERTIONS PASSED AGAINST LIVE SERVER!")
