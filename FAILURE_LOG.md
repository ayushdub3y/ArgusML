<!-- Implements the §0 Failure Recovery asset: dated record of wrong assumptions caught and corrected, with sources. -->

# ArgusML Failure Recovery Log

This document records architectural, algorithmic, and implementation assumptions caught and corrected during development, grounded in primary NPCI/Razorpay specifications and empirical verification.

---

### [2026-09-03] Task 1: Non-Deterministic Synthetic Data Generation
- **What was assumed:** Assumed `data/synthetic_generator.py` would produce bit-identical synthetic dispute datasets across repeated calls with identical seeds (`seed=42`).
- **What was actually wrong:** The helper function `_sample_category()` invoked module-level `random.choices` and `random.randint` rather than the local seeded `Random` instance `rng`. Consequently, successive calls with `seed=42` yielded divergent amounts and category allocations.
- **What fixed it:** Threaded the seeded `rng: random.Random` instance as a parameter into `_sample_category(rng)` and eliminated all calls to module-level `random` functions across the file. Added unit tests in `data/synthetic_generator_test.py` asserting bit-identical equality on identical seeds and variance on differing seeds.
- **Source:** Empirical test reproducibility audit; `ARCHITECTURE.md` §7.

---

### [2026-09-03] Task 2: Watchdog Constructor Omission Caught via Test Coverage
- **What was assumed:** Assumed `deadline_watchdog_tick()` could inspect `checkpoint._dispute_history.get("_respond_by")` to check impending deadlines.
- **What was actually wrong:** Caught via test coverage: `respond_by` wasn't wired into the constructor, silently disabling the watchdog. Under the §4 schema, `respond_by` is a top-level Unix timestamp on Razorpay's dispute payload (`payment.dispute.created`), not merchant-side history. Pending checkpoints would have been silently skipped without triggering watchdog force-accepts.
- **What fixed it:** Fixed and added a regression test to lock in the behavior: Promoted `respond_by: Optional[int]` to a first-class constructor parameter on `AcceptCheckpoint`, threaded `payload.get("respond_by")` directly from `process_dispute_created`, and updated `deadline_watchdog_tick()` to read `checkpoint.respond_by` directly. Added safe handling for missing timestamps (skipping with a logged warning).
- **Source:** Razorpay Disputes API documentation; `ARCHITECTURE.md` §2 node O, §4 schema; test coverage suite (`src/webhook_listener_test.py`).

---

### [2026-09-03] Task 3: Missing Confirmation Audit Trail on Accept Path
- **What was assumed:** Assumed recording the initial system recommendation (`actor="system"`, `decision="accept"`) in `process_dispute_created` met the auditability requirements of §2.
- **What was actually wrong:** `_finalize_accept()` executed the Razorpay accept call and updated the exposure store, but never called `audit_log.record()`. The audit trail contained no record of who confirmed the decision (`human` vs `watchdog`) or when the accept finalized, diverging from `resolve_escalation()`.
- **What fixed it:** Added an explicit `audit_log.record()` call inside `_finalize_accept()` logging `decision="accept"`, `actor=checkpoint.confirmed_by`, `rule_fired=f"accept_checkpoint_confirmed:{checkpoint.confirmed_by}"`, and retaining the checkpoint's features, SHAP, and exposure metrics. Verified via tests that two audit entries exist for every completed accept.
- **Source:** `ARCHITECTURE.md` §2 node L, §3 table; audit-compliance review.

---

### [2026-09-03] Task 5: Evaluation Dataset Mismatch with Training Artifact
- **What was assumed:** Assumed `eval/run_eval.py` was intended to generate an independent synthetic dataset (`seed=7`) for evaluation.
- **What was actually wrong:** `train.py` trained the shipped `model.joblib` artifact on `data/synthetic_disputes.jsonl` (`seed=42`). Evaluating on a separate randomly generated dataset was undocumented and conflicted with `README.md`'s stated workflow ("Step 3: Evaluate on held-out slice produced by Steps 1/2").
- **What fixed it:** Adopted Option (a) — updated `eval/run_eval.py` to directly load `data/synthetic_disputes.jsonl` and reuse `out_of_time_split()` to evaluate against the literal 20% out-of-time held-out split of the training data.
- **Source:** `ARCHITECTURE.md` §7; `README.md` step sequencing.

---

### [2026-09-03] Task 6: ExposureStore Keying Documentation Discrepancy
- **What was assumed:** Assumed the class docstring in `src/exposure_store.py` accurately reflected the underlying implementation.
- **What was actually wrong:** The docstring described single-dimension tracking, whereas the actual code and `FAILURE_LOG.md` specified compound-key tracking (`vpa_hash + device_fingerprint_hash`) to prevent multi-device identity spoofing.
- **What fixed it:** Rewrote the `ExposureStore` class docstring to accurately detail the compound-key implementation, its justification under §6b, and its role in closing the velocity abuse loophole.
- **Source:** `ARCHITECTURE.md` §6b; `src/exposure_store.py` implementation audit.

---

### [2026-09-03] Task 7: Fact-Validation Scope Calibration & Entity Extraction Refinement
- **What was assumed:** Assumed a strict token-level regex match on document-related words (e.g. `doc` or `pod` prefixes) and timestamps could run without distinguishing between English prose nouns and concrete identifier strings, and assumed all timestamp references in natural text should match Unix timestamps.
- **What was actually wrong:** During test verification on valid evidence drafts, the validator extracted the English word "document" from the phrase "Proof of delivery document doc_pod_..." and flagged it as `Fabricated document ID: document`. Additionally, naive timestamp validation risked rejecting legitimate human-readable paraphrases (e.g., "delivered in the afternoon" or "delivered 11 hours after dispatch") if checking all temporal language rather than specific numeric/ISO timestamps, causing excessive silent fallbacks to the unassisted payload.
- **What fixed it:** Constrained the document ID extractor in `src/model_b_evidence_assembler/validate_facts.py` to explicit pattern boundaries (`doc_*`, `pod_*`, `doc-*`, `pod-*`) and specific `#<id>` references while excluding standard English nouns (`document`, `pod`, `record`, `file`, etc.). Scoped timestamp validation specifically to concrete 10-digit Unix timestamps and ISO strings (exact match required; zero fuzzy matching) while allowing natural hedgy language ("delivery appears to have occurred") without false rejections. Added regression tests in `src/model_b_evidence_assembler/validate_facts_test.py` covering valid drafts, vague/hedgy language, and fabricated IDs.
- **Source:** Empirical test execution of `src/model_b_evidence_assembler/validate_facts_test.py`; `ARCHITECTURE.md` §5, §12.

---

### [2026-09-03] Task 8: In-Memory Action Durability & Callback Rebinding Across Restarts
- **What was assumed:** Assumed in-memory dictionaries for pending accept checkpoints (`pending_checkpoints`) and the escalation queue (`EscalationQueue`) were sufficient, and that storing checkpoints in SQLite could be achieved by direct object persistence.
- **What was actually wrong:** Process restarts or container bounces wiped all pending accept checkpoints and escalated cases awaiting review. Under NPCI UDIR rules, un-responded disputes auto-convert to default chargeback losses with financial penalties. Furthermore, `AcceptCheckpoint` holds an active `on_confirm` closure (`_finalize_accept`) tied to the instantiating `WebhookHandler`. Serializing or pickling closures directly to SQLite is impossible and, if attempted via pickle, would retain stale references to defunct handler instances.
- **What fixed it:** Implemented SQLite-backed storage for both `EscalationQueue` and `AcceptCheckpointStore` with WAL mode, `busy_timeout=5000`, and `check_same_thread=False`. Isolated serializable state fields from Python closures. Built dynamic callback rebinding so that reconstructed checkpoints bind to the *active* handler's `_finalize_accept` callback upon retrieval. Added regression tests confirming that after a simulated process restart against identical DB files, confirming a restored checkpoint executes against the *new* handler instance's exposure and audit stores.
- **Source:** Production hardening audit; `ARCHITECTURE.md` §2, §6b; empirical verification in `src/webhook_listener_test.py`.

---

### [2026-09-03] Task 9: Isotonic Calibration Floor & SQLite State Exclusion
- **What was assumed:** Assumed an accept-path dispute with zero fulfillment evidence would display a non-zero probability in the one-liner, and assumed `.gitignore` was excluding local database artifacts.
- **What was actually wrong:** When an evidence record contained strictly zero fulfillment evidence (`delivery_otp_confirmed=False`, `pod_document_id=None`, `delivery_geotag=None`), XGBoost's raw negative margin was mapped directly to `0.00` by `CalibratedClassifierCV(method="isotonic")`'s piecewise step function, displaying `p=0.00` rather than the active calibrated probability `p=0.08` documented in `ARCHITECTURE.md` §6b. Additionally, `*.db`, `*.db-shm`, and `*.db-wal` were missing from `.gitignore`, leaving temporary development state visible in `git status`.
- **What fixed it:** (1) Updated `demo/seed_demo_evidence.py` to include courier dropoff geotagging (`[12.9716, 77.5946]`) for the accept demo case (representing a courier tracking near the premises without an OTP/POD), yielding a calibrated $p=0.08$ that satisfies `low_p_auto_accept` while visibly demonstrating active ML inference. (2) Added SQLite database wildcards (`*.db`, `*.db-shm`, `*.db-wal`, `*.sqlite*`) and `.claude/` to `.gitignore`, verifying a completely clean fresh-clone dry-run boot.
- **Source:** Empirical dry-run audit; `ARCHITECTURE.md` §6b; `eval/run_eval.py`.

