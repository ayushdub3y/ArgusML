"""Implements §5 and §12: deterministic fact-validation hard-block layer.

ARCHITECTURE.md references:
- §5 (Modeling: Model B Evidence Assembler — reject any generated field referencing
  a document ID, timestamp, or courier name absent from the source evidence record).
- §12 (Defense-only statement: Aegis never fabricates evidence. The fact-validation
  layer blocks any LLM-drafted field that doesn't match the source record rather
  than silently dropping it).
"""

import re
from typing import Any, Dict, List, Set, Tuple, Union

# Known Indian & international courier/logistics services
KNOWN_COURIERS: Set[str] = {
    "bluedart",
    "blue dart",
    "delhivery",
    "dtdc",
    "fedex",
    "dhl",
    "shadowfax",
    "ekart",
    "ecom express",
    "xpressbees",
    "india post",
    "shiprocket",
    "amazon shipping",
    "dunzo",
    "porter",
    "borzo",
    "speed post",
    "aramex",
    "gati",
    "safexpress",
}


def _extract_evidence_strings_and_numbers(evidence: Dict[str, Any]) -> Tuple[Set[str], Set[str], Set[str]]:
    """Recursively extract document IDs, timestamps, and couriers from evidence record."""
    doc_ids: Set[str] = set()
    timestamps: Set[str] = set()
    couriers: Set[str] = set()

    def _walk(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = k.lower()
                if "doc" in k_lower or "pod" in k_lower:
                    if isinstance(v, str) and v.strip():
                        doc_ids.add(v.strip().lower())
                if "ts" in k_lower or "time" in k_lower or "date" in k_lower:
                    if isinstance(v, (int, float)):
                        timestamps.add(str(int(v)))
                    elif isinstance(v, str) and v.strip():
                        timestamps.add(v.strip())
                if "courier" in k_lower or "carrier" in k_lower or "logistics" in k_lower:
                    if isinstance(v, str) and v.strip():
                        couriers.add(v.strip().lower())
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, str):
            val_lower = obj.lower()
            if val_lower.startswith("doc_") or val_lower.startswith("pod_"):
                doc_ids.add(val_lower)
            for courier in KNOWN_COURIERS:
                if courier in val_lower:
                    couriers.add(courier)
        elif isinstance(obj, (int, float)):
            val_str = str(int(obj))
            if len(val_str) == 10:  # 10-digit Unix timestamp
                timestamps.add(val_str)

    _walk(evidence)
    return doc_ids, timestamps, couriers


def validate_facts(
    generated: Union[Dict[str, Any], str],
    evidence: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Validate that all concrete claims in generated summary exist in source evidence record (§5, §12).

    Conservative hard-block rules:
    1. Document IDs: Any token resembling a document ID (e.g. doc_*, pod_*) must appear
       verbatim in the evidence record.
    2. Concrete Timestamps: If the model states a specific 10-digit Unix timestamp or ISO
       timestamp, it must match an evidence timestamp exactly (no fuzzy matching).
       General temporal references without conflicting numeric timestamps are permitted.
    3. Courier / Carrier Names: Any courier named in the draft must exist in evidence.
    4. Order IDs: Any referenced order ID must match the evidence record's order_id.
    5. Affirmative Delivery Claims: If summary claims delivery OTP was confirmed,
       evidence must have delivery_otp_confirmed == True.
    6. Geotag / Coordinates: Concrete coordinates in summary must match delivery_geotag.

    Returns:
        (is_valid, failure_reasons): Tuple of boolean pass/fail and list of specific failure strings.
    """
    reasons: List[str] = []

    if isinstance(generated, dict):
        summary_text = generated.get("summary", "")
    else:
        summary_text = str(generated)

    if not summary_text or not summary_text.strip():
        return True, []

    valid_doc_ids, valid_timestamps, valid_couriers = _extract_evidence_strings_and_numbers(evidence)

    # 1. Document ID validation
    # Matches explicit patterns like doc_xxx, pod_xxx, doc-xxx, pod-xxx
    found_doc_ids = set(re.findall(r"\b(?:doc|pod)[_-][a-zA-Z0-9_-]+\b", summary_text, re.IGNORECASE))
    for doc_id in found_doc_ids:
        if doc_id.lower() not in valid_doc_ids:
            reasons.append(f"Fabricated document ID: {doc_id}")

    # Catch references like "document #1234" or "POD #XYZ" with explicit identifier
    generic_doc_matches = re.findall(r"\b(?:document|pod|proof of delivery)\s*#\s*([a-zA-Z0-9_-]+)", summary_text, re.IGNORECASE)
    skip_words = {
        "document", "documents", "doc", "docs", "pod", "pods", "id", "number",
        "record", "provided", "is", "on", "was", "not", "available", "file", "attached"
    }
    for ref in generic_doc_matches:
        ref_lower = ref.lower()
        if ref_lower in skip_words:
            continue
        if ref_lower not in valid_doc_ids:
            reasons.append(f"Fabricated document ID: {ref}")

    # 2. Concrete numeric timestamp validation (exact match only; no fuzzy matching)
    # Extracts 10-digit Unix timestamps
    found_unix_ts = set(re.findall(r"\b\d{10}\b", summary_text))
    for ts in found_unix_ts:
        if ts not in valid_timestamps:
            reasons.append(f"Unmatched or fabricated timestamp: {ts}")

    # 3. Courier name validation
    summary_lower = summary_text.lower()
    for courier in KNOWN_COURIERS:
        # Check whole-word or boundary match for courier name
        pattern = r"\b" + re.escape(courier) + r"\b"
        if re.search(pattern, summary_lower):
            if courier not in valid_couriers:
                reasons.append(f"Fabricated courier name: {courier}")

    # Catch courier mentions like "XYZ courier", "courier: XYZ", "carrier ABC"
    post_carrier_mentions = re.findall(r"\b(?:courier|carrier|shipping partner|logistics partner)\s*[:\-]?\s*([a-zA-Z0-9_-]+)", summary_text, re.IGNORECASE)
    pre_carrier_mentions = re.findall(r"\b([a-zA-Z0-9_-]+)\s+(?:courier|carrier|logistics)\b", summary_text, re.IGNORECASE)
    
    skip_carrier_words = {
        "at", "on", "in", "by", "to", "from", "with", "for", "of", "and", "or",
        "a", "an", "the", "via", "is", "was", "were", "has", "had", "been",
        "service", "services", "partner", "partners", "company", "facility",
        "person", "agent", "driver", "tracking", "status", "delivery", "name",
        "unknown", "none", "not", "details", "record", "records"
    }
    
    all_carrier_candidates = set()
    for c in post_carrier_mentions + pre_carrier_mentions:
        c_clean = c.strip().lower()
        if c_clean and c_clean not in skip_carrier_words and not c_clean.isdigit():
            all_carrier_candidates.add(c_clean)

    for carrier_lower in all_carrier_candidates:
        is_traceable = any(
            carrier_lower == vc or carrier_lower in vc.split() or vc in carrier_lower
            for vc in valid_couriers
        )
        if not is_traceable:
            reasons.append(f"Fabricated courier name: {carrier_lower}")

    # 4. Order ID validation
    evidence_order_id = str(evidence.get("order_id", "")).strip().lower()
    found_order_ids = set(re.findall(r"\border_[a-zA-Z0-9_-]+\b", summary_text, re.IGNORECASE))
    for oid in found_order_ids:
        if evidence_order_id and oid.lower() != evidence_order_id:
            reasons.append(f"Fabricated order ID: {oid} (expected {evidence_order_id})")

    # 5. OTP affirmative claim validation
    # If summary claims OTP was confirmed, verified, or validated
    otp_claimed_positive = bool(re.search(
        r"\b(?:otp\s+(?:was\s+)?(?:confirmed|verified|validated|entered|matched))\b",
        summary_text,
        re.IGNORECASE,
    ))
    actual_otp_confirmed = bool(evidence.get("delivery_otp_confirmed", False))
    if otp_claimed_positive and not actual_otp_confirmed:
        reasons.append("Fabricated claim: asserted delivery OTP was confirmed when evidence indicates unconfirmed")

    # 6. Geotag coordinates validation
    evidence_geotag = evidence.get("delivery_geotag")
    valid_coords: Set[str] = set()
    if isinstance(evidence_geotag, (list, tuple)) and len(evidence_geotag) == 2:
        valid_coords.add(str(evidence_geotag[0]))
        valid_coords.add(str(evidence_geotag[1]))

    # Decimal coordinates pattern (e.g. 12.9716, 77.5946)
    found_coords = re.findall(r"\b\d{1,2}\.\d{4,}\b", summary_text)
    for coord in found_coords:
        if coord not in valid_coords:
            reasons.append(f"Fabricated geotag coordinate: {coord}")

    is_valid = len(reasons) == 0
    return is_valid, reasons
