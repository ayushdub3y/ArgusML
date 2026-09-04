"""Adversarial and boundary test suite for Model B Fact-Validation layer (§5, §12).

Tests:
1. Valid draft matching evidence passes.
2. Vague/hedgy phrasing passes without false rejections.
3. Fabricated document ID fails and names the specific claim.
4. Fabricated courier name fails.
5. Inexact/close numeric timestamp fails (exact match required; no fuzzy matching).
6. Sparse evidence record passes when null fields are omitted.
7. Fabricated OTP confirmation claim fails when evidence indicates unconfirmed.
8. Fabricated order ID fails.
9. Fabricated geotag coordinate fails.
10. assemble_contest_payload graceful fallback when credentials are absent.
11. assemble_contest_payload fallback on fact-validation rejection with logged reasons.
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from src.model_b_evidence_assembler.assemble import assemble_contest_payload
from src.model_b_evidence_assembler.validate_facts import validate_facts
from src.razorpay_client import build_contest_payload_from_evidence


@pytest.fixture
def sample_evidence():
    return {
        "order_id": "order_demo_contest_001",
        "fulfillment_type": "physical",
        "dispatch_ts": 1735500000,
        "delivery_ts": 1735540000,
        "delivery_otp_confirmed": True,
        "pod_document_id": "doc_pod_demo_verified_99",
        "delivery_geotag": [12.9716, 77.5946],
        "buyer_identity": {
            "vpa_hash": "vpa_hash_123",
            "device_fingerprint_hash": "dev_hash_456",
        },
    }


def test_valid_draft_passes(sample_evidence):
    """Verify draft containing only true evidence facts passes cleanly."""
    draft = {
        "summary": (
            "Order order_demo_contest_001 was dispatched at timestamp 1735500000 and delivered at "
            "timestamp 1735540000. Recipient OTP was confirmed. Proof of delivery document "
            "doc_pod_demo_verified_99 is attached with coordinates 12.9716, 77.5946."
        )
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is True
    assert reasons == []


def test_vague_hedgy_draft_passes(sample_evidence):
    """Verify natural hedgy prose without fabricated entities passes without false rejections."""
    draft = {
        "summary": (
            "Order order_demo_contest_001 shows delivery completed in merchant records. "
            "Dispatch and delivery logs indicate fulfillment was successful."
        )
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is True
    assert reasons == []


def test_fabricated_document_id_fails(sample_evidence):
    """Verify inventing a document ID not in evidence is rejected and identified by name."""
    draft = {
        "summary": (
            "Order order_demo_contest_001 was delivered. See proof of delivery document doc_fake_pod_999."
        )
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("doc_fake_pod_999" in r for r in reasons)
    assert any("Fabricated document ID" in r for r in reasons)


def test_fabricated_courier_fails(sample_evidence):
    """Verify inventing a courier name not present in evidence is rejected."""
    draft = {
        "summary": (
            "Order order_demo_contest_001 was dispatched via BlueDart courier and delivered successfully."
        )
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("bluedart" in r.lower() for r in reasons)
    assert any("Fabricated courier name" in r for r in reasons)


def test_inexact_timestamp_fails(sample_evidence):
    """Verify a timestamp close to but not exactly matching evidence is rejected (no fuzzy match)."""
    # Evidence delivery_ts is 1735540000; draft uses 1735540001 (1 second off)
    draft = {
        "summary": (
            "Order order_demo_contest_001 was dispatched at timestamp 1735500000 and delivered at "
            "timestamp 1735540001 with confirmed OTP."
        )
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("1735540001" in r for r in reasons)
    assert any("Unmatched or fabricated timestamp" in r for r in reasons)


def test_sparse_evidence_passes():
    """Verify sparse evidence record passes when null fields are omitted."""
    sparse_evidence = {
        "order_id": "order_sparse_001",
        "fulfillment_type": "physical",
        "dispatch_ts": None,
        "delivery_ts": None,
        "delivery_otp_confirmed": False,
        "pod_document_id": "doc_sparse_pod_only",
        "delivery_geotag": None,
    }
    draft = {
        "summary": (
            "Order order_sparse_001 has proof of delivery doc_sparse_pod_only on file. "
            "No delivery timestamp or OTP confirmation was recorded."
        )
    }
    is_valid, reasons = validate_facts(draft, sparse_evidence)
    assert is_valid is True
    assert reasons == []


def test_fabricated_otp_affirmation_fails(sample_evidence):
    """Verify claiming OTP confirmation when evidence indicates unconfirmed is rejected."""
    unconfirmed_evidence = dict(sample_evidence)
    unconfirmed_evidence["delivery_otp_confirmed"] = False

    draft = {
        "summary": (
            "Order order_demo_contest_001 was delivered and recipient delivery OTP was confirmed."
        )
    }
    is_valid, reasons = validate_facts(draft, unconfirmed_evidence)
    assert is_valid is False
    assert any("OTP" in r for r in reasons)


def test_fabricated_order_id_fails(sample_evidence):
    """Verify citing a fabricated order ID is rejected."""
    draft = {
        "summary": "Fulfillment verified for order_fake_dispute_999 per merchant records."
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("order_fake_dispute_999" in r for r in reasons)


def test_fabricated_geotag_fails(sample_evidence):
    """Verify citing fabricated coordinates is rejected."""
    draft = {
        "summary": "Order order_demo_contest_001 delivered to coordinates 19.0760, 72.8777."
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("geotag" in r.lower() for r in reasons)


def test_assemble_fallback_when_no_credentials(sample_evidence, monkeypatch):
    """Verify assemble_contest_payload degrades cleanly to deterministic fallback without credentials."""
    monkeypatch.setattr("src.model_b_evidence_assembler.assemble._resolve_credentials", lambda: (None, None, "None"))

    # 1. No credentials, no human notes: check default summary is sane
    fallback_payload = assemble_contest_payload(sample_evidence)
    expected_payload = build_contest_payload_from_evidence(sample_evidence)
    assert fallback_payload == expected_payload
    assert "order_demo_contest_001" in fallback_payload["summary"]
    assert fallback_payload["shipping_proof"]["order_id"] == "order_demo_contest_001"
    assert fallback_payload["shipping_proof"]["pod_document_id"] == "doc_pod_demo_verified_99"

    # 2. No credentials, with human notes: notes used as summary
    notes = "Customer verified package received with building security."
    fallback_with_notes = assemble_contest_payload(sample_evidence, human_notes=notes)
    expected_with_notes = build_contest_payload_from_evidence(sample_evidence, summary_text=notes)
    assert fallback_with_notes == expected_with_notes
    assert fallback_with_notes["summary"] == notes


def test_assemble_fallback_on_fact_validation_failure(sample_evidence, monkeypatch):
    """Verify assemble_contest_payload falls back to deterministic payload when LLM draft fails validation."""
    monkeypatch.setattr("src.model_b_evidence_assembler.assemble._resolve_credentials", lambda: ("gemini", "mock_gemini_key_123", "test"))

    # Mock Gemini client to return a hallucinated document ID
    mock_response = MagicMock()
    mock_response.text = '{"summary": "Order order_demo_contest_001 delivered with doc_pod_hallucinated_888."}'

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        payload = assemble_contest_payload(sample_evidence)

    # Should have fallen back to deterministic payload
    expected_fallback = build_contest_payload_from_evidence(sample_evidence)
    assert payload == expected_fallback
    assert "doc_pod_hallucinated_888" not in payload["summary"]


def test_assemble_with_gemini_api_success(sample_evidence, monkeypatch):
    """Verify assemble_contest_payload succeeds and validates draft when using GEMINI_API_KEY."""
    monkeypatch.setattr("src.model_b_evidence_assembler.assemble._resolve_credentials", lambda: ("gemini", "mock_gemini_key_123", "test"))

    valid_narrative = (
        '{"summary": "Order order_demo_contest_001 dispatched at timestamp 1735500000 and '
        'delivered at timestamp 1735540000 with recipient OTP confirmed. Proof of delivery '
        'doc_pod_demo_verified_99 on file."}'
    )

    mock_response = MagicMock()
    mock_response.text = valid_narrative

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        payload = assemble_contest_payload(sample_evidence)

    assert "order_demo_contest_001" in payload["summary"]
    assert "doc_pod_demo_verified_99" in payload["summary"]
    assert payload["shipping_proof"]["order_id"] == "order_demo_contest_001"
    assert payload["shipping_proof"]["pod_document_id"] == "doc_pod_demo_verified_99"


def test_assemble_with_gemini_api_validation_failure(sample_evidence, monkeypatch):
    """Verify assemble_contest_payload falls back if Gemini produces a draft with a fabricated courier."""
    monkeypatch.setattr("src.model_b_evidence_assembler.assemble._resolve_credentials", lambda: ("gemini", "mock_gemini_key_123", "test"))

    invalid_narrative = '{"summary": "Order order_demo_contest_001 delivered via BlueDart courier."}'

    mock_response = MagicMock()
    mock_response.text = invalid_narrative

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        payload = assemble_contest_payload(sample_evidence)

    expected_fallback = build_contest_payload_from_evidence(sample_evidence)
    assert payload == expected_fallback
    assert "BlueDart" not in payload["summary"]


def test_custom_unlisted_courier_in_evidence_accepted(sample_evidence):
    """Verify an arbitrary courier name present in evidence is accepted (not restricted to a hardcoded list)."""
    custom_evidence = dict(sample_evidence)
    custom_evidence["courier_name"] = "HyperLocalExpress"

    draft = {
        "summary": (
            "Order order_demo_contest_001 was dispatched via HyperLocalExpress courier at "
            "timestamp 1735500000 and delivered at timestamp 1735540000 with confirmed OTP."
        )
    }
    is_valid, reasons = validate_facts(draft, custom_evidence)
    assert is_valid is True
    assert reasons == []


def test_fabricated_digital_redemption_fails_when_unredeemed():
    """Verify claiming digital voucher was redeemed when evidence indicates unredeemed is rejected."""
    unredeemed_evidence = {
        "order_id": "order_vouch_unredeemed_01",
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": None,
    }
    draft = {
        "summary": "Order order_vouch_unredeemed_01 digital voucher was redeemed online by customer."
    }
    is_valid, reasons = validate_facts(draft, unredeemed_evidence)
    assert is_valid is False
    assert any("asserted digital voucher was redeemed" in r for r in reasons)


def test_valid_digital_redemption_passes():
    """Verify legitimate digital voucher redemption claims pass when backed by evidence."""
    redeemed_evidence = {
        "order_id": "order_vouch_redeemed_01",
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": 1735601500,
    }
    draft = {
        "summary": "Order order_vouch_redeemed_01 digital voucher was redeemed at timestamp 1735601500."
    }
    is_valid, reasons = validate_facts(draft, redeemed_evidence)
    assert is_valid is True
    assert reasons == []


def test_contradictory_fulfillment_type_digital_claiming_doorstep_fails():
    """Verify asserting physical courier/doorstep delivery for a digital voucher order is rejected."""
    digital_evidence = {
        "order_id": "order_vouch_physical_fail",
        "fulfillment_type": "digital_voucher",
        "digital_redemption_ts": 1735601500,
    }
    draft = {
        "summary": "Order order_vouch_physical_fail was courier delivered to doorstep at timestamp 1735601500."
    }
    is_valid, reasons = validate_facts(draft, digital_evidence)
    assert is_valid is False
    assert any("asserted physical doorstep delivery for digital voucher" in r for r in reasons)


def test_contradictory_fulfillment_type_physical_claiming_digital_fails(sample_evidence):
    """Verify asserting digital voucher redemption for a physical shipment order is rejected."""
    draft = {
        "summary": "Order order_demo_contest_001 digital voucher was redeemed online by the buyer."
    }
    is_valid, reasons = validate_facts(draft, sample_evidence)
    assert is_valid is False
    assert any("asserted digital voucher redemption for physical goods" in r for r in reasons)


def test_unverified_delivery_confirmation_fails_without_otp_or_pod():
    """Verify asserting customer confirmed delivery when neither OTP nor POD is on record fails."""
    unverified_evidence = {
        "order_id": "order_unverified_deliv_01",
        "fulfillment_type": "physical",
        "delivery_otp_confirmed": False,
        "pod_document_id": None,
    }
    draft = {
        "summary": "Order order_unverified_deliv_01 shows recipient confirmed delivery at the residence."
    }
    is_valid, reasons = validate_facts(draft, unverified_evidence)
    assert is_valid is False
    assert any("neither OTP nor POD exists in evidence" in r for r in reasons)
