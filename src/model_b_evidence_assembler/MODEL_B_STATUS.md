# Model B — Evidence Assembler Status & Architecture Notes

**Status:** BUILT & VERIFIED (Phase 2 / P1 Scope)  
**Implementation Files:**
- [`prompt_template.txt`](prompt_template.txt) — Constrained prompt template instructing the model to output ONLY a JSON object `{"summary": "..."}` based strictly on `<evidence>...</evidence>`.
- [`assemble.py`](assemble.py) — Core assembly function `assemble_contest_payload(evidence, human_notes)`. Orchestrates LLM drafting, fact-validation, and fallback degradation.
- [`validate_facts.py`](validate_facts.py) — Hard-block deterministic validator checking all document IDs, concrete timestamps, couriers, order IDs, coordinates, and affirmative OTP assertions against source evidence (§12).
- [`validate_facts_test.py`](validate_facts_test.py) — Adversarial and boundary test suite verifying zero-tolerance fact checking and graceful degradation.

---

### Non-Negotiable Invariants Upheld (§3, §5, §12, §13)

1. **Boundary Lock (§3):**
   Model B NEVER decides whether to accept, contest, or escalate a dispute. That decision is deterministic and made upstream by `decision_engine.py`. Model B is only invoked when `decision == "contest"`.

2. **No Regeneration of Known Values (§5):**
   The LLM is only tasked with drafting a human-readable narrative `summary` string. Structured values (`order_id`, `dispatch_ts`, `delivery_ts`, `delivery_otp_confirmed`, `pod_document_id`, `delivery_geotag`, `redemption_ts`) are injected directly in Python code from source evidence records (`build_contest_payload_from_evidence`), preventing identifier hallucination.

3. **Conservative Fact-Validation Hard-Block (§12):**
   Any generated narrative mentioning a document ID, concrete numeric timestamp (e.g. 10-digit Unix timestamp), courier name, or asserting OTP confirmation when absent/unconfirmed in the evidence record is HARD-BLOCKED. The failure is logged with specific reasons, and the draft is rejected.

4. **Deterministic Fallback by Design (§12, §13):**
   The fallback to `build_contest_payload_from_evidence(evidence, summary_text=human_notes)` is a permanent architectural safety feature, not interim scaffolding. If `ANTHROPIC_API_KEY` is not set, an external API error occurs, or validation fails, Aegis gracefully degrades to the verbatim evidence payload so that a valid merchant contest is never lost due to an LLM outage.
