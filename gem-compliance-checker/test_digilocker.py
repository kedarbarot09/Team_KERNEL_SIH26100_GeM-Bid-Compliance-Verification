"""Unit and Integration Tests for DigiLocker Document Fetching Pipeline.

Tests:
1. Consent URL Generation (mock fallback and URL formatting)
2. DigiLocker Document Fetching (canned mock responses for Udyam, PAN, GST)
3. Dual Path Document Persistence (upload path vs mocked DigiLocker path)
   - Confirms correctly structured entries in the SQLite documents table
   - Confirms correct 'source' and 'issuer_verified' fields
4. Officer Processing & OCR Bypass Verification
"""

import json
from pathlib import Path
import sys

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import GeMClauseEvaluator, TenderCriteria
from app.db import (
    clear_all_bidder_documents,
    get_documents_by_bidder,
    init_db,
    save_digilocker_document,
    save_uploaded_document,
)
from app.digilocker import (
    fetch_digilocker_document,
    generate_digilocker_consent_url,
    get_canned_mock_document,
)
from app.extract import extract_bid_information


def test_digilocker_api_client():
    print("--- 1. Testing DigiLocker API Client & Mock Responses ---")
    
    # Test consent URL generation
    bidder_id = "BID-TEST-DL-999"
    consent_url = generate_digilocker_consent_url(bidder_id, "PAN Card")
    assert isinstance(consent_url, str) and len(consent_url) > 0, "Consent URL must be a non-empty string"
    assert "digilocker" in consent_url.lower(), f"URL should contain digilocker: {consent_url}"
    print(f"   -> Generated consent URL: {consent_url}")

    # Test fetching PAN document
    pan_doc = fetch_digilocker_document(session_id="mock_session_pan", document_type="PAN Card")
    assert pan_doc["source"] == "digilocker"
    assert pan_doc["issuer_verified"] is True
    assert pan_doc["data"]["pan"] == "AABCA1234F"
    assert "ALPHA TECH SOLUTIONS" in pan_doc["data"]["name"]
    print(f"   -> Fetched PAN: {pan_doc['data']['pan']} (Issuer: {pan_doc.get('issuer')})")

    # Test fetching GST document
    gst_doc = fetch_digilocker_document(session_id="mock_session_gst", document_type="GST Registration Certificate")
    assert gst_doc["source"] == "digilocker"
    assert gst_doc["issuer_verified"] is True
    assert gst_doc["data"]["gstin"] == "27AABCA1234F1Z5"
    print(f"   -> Fetched GSTIN: {gst_doc['data']['gstin']} (Issuer: {gst_doc.get('issuer')})")

    # Test fetching Udyam document
    udyam_doc = fetch_digilocker_document(session_id="mock_session_udyam", document_type="Udyam Registration Certificate")
    assert udyam_doc["source"] == "digilocker"
    assert udyam_doc["issuer_verified"] is True
    assert udyam_doc["data"]["udyam_registration_number"] == "UDYAM-MH-01-0012345"
    print(f"   -> Fetched Udyam: {udyam_doc['data']['udyam_registration_number']} (Issuer: {udyam_doc.get('issuer')})")


def test_dual_path_persistence():
    print("\n--- 2. Testing Dual Document Path: Upload vs Mocked DigiLocker ---")
    init_db()
    bidder_id = "TEST-DUAL-BIDDER-2024"

    # Reset any previous test records
    clear_all_bidder_documents(bidder_id)

    # Path A: Normal File Upload
    print("   [Path A] Executing Normal Document Upload...")
    upload_res = save_uploaded_document(
        bidder_id=bidder_id,
        category="Statutory / registration documents",
        document_type="PAN Card",
        filename="scanned_pan_card.txt",
        file_bytes=b"INCOME TAX DEPARTMENT - GOVT OF INDIA\nPAN: AABCA1234F\nName: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nStatus: ACTIVE",
        source="upload",
        issuer_verified=False,
    )
    assert upload_res["source"] == "upload"
    assert upload_res["issuer_verified"] is False
    print(f"      -> Uploaded: ID={upload_res['id']}, source='{upload_res['source']}', issuer_verified={upload_res['issuer_verified']}")

    # Path B: Mocked DigiLocker Fetch
    print("   [Path B] Executing Mocked DigiLocker Fetch...")
    consent_url = generate_digilocker_consent_url(bidder_id, "GST Registration Certificate")
    assert consent_url is not None
    mock_payload = fetch_digilocker_document(
        session_id=f"mock_gst_{bidder_id}",
        document_type="GST Registration Certificate",
    )
    dl_res = save_digilocker_document(
        bidder_id=bidder_id,
        category="Statutory / registration documents",
        document_type="GST Registration Certificate",
        doc_data=mock_payload,
    )
    assert dl_res["source"] == "digilocker"
    assert dl_res["issuer_verified"] is True
    print(f"      -> DigiLocker: ID={dl_res['id']}, source='{dl_res['source']}', issuer_verified={dl_res['issuer_verified']}")

    # Query database and verify table structure and fields
    print("   [Verification] Inspecting entries in documents SQLite table...")
    docs = get_documents_by_bidder(bidder_id)
    assert len(docs) == 2, f"Expected 2 documents in DB, found {len(docs)}"

    doc_by_type = {d["document_type"]: d for d in docs}
    
    # 1. Verify Upload document record
    pan_doc = doc_by_type["PAN Card"]
    assert pan_doc["source"] == "upload", f"Expected source 'upload', got '{pan_doc['source']}'"
    assert pan_doc["issuer_verified"] is False, f"Expected issuer_verified False, got {pan_doc['issuer_verified']}"
    assert pan_doc["filename"] == "scanned_pan_card.txt"
    assert Path(pan_doc["filepath"]).is_file(), f"File should exist on disk: {pan_doc['filepath']}"
    print("      -> Upload document verified: source='upload', issuer_verified=False")

    # 2. Verify DigiLocker document record
    gst_doc = doc_by_type["GST Registration Certificate"]
    assert gst_doc["source"] == "digilocker", f"Expected source 'digilocker', got '{gst_doc['source']}'"
    assert gst_doc["issuer_verified"] is True, f"Expected issuer_verified True, got {gst_doc['issuer_verified']}"
    assert "digilocker" in gst_doc["filename"].lower()
    assert Path(gst_doc["filepath"]).is_file(), f"File should exist on disk: {gst_doc['filepath']}"
    
    # Verify underlying file is structured JSON
    with open(gst_doc["filepath"], "r", encoding="utf-8") as f:
        stored_json = json.load(f)
    assert stored_json["source"] == "digilocker"
    assert stored_json["data"]["gstin"] == "27AABCA1234F1Z5"
    print("      -> DigiLocker document verified: source='digilocker', issuer_verified=True, JSON valid")


def test_officer_digilocker_pipeline_bypass():
    print("\n--- 3. Testing Officer Pipeline: OCR Bypass & Direct Schema Ingestion ---")
    bidder_id = "TEST-DUAL-BIDDER-2024"
    docs = get_documents_by_bidder(bidder_id)
    
    # Simulate officer ingestion loop as implemented in dashboard.py
    docs_text_map = {}
    digilocker_structured_data = {}
    digilocker_docs = []

    for doc in docs:
        doc_type = doc["document_type"]
        filepath = Path(doc["filepath"])
        is_dl = (doc.get("source") == "digilocker") or bool(doc.get("issuer_verified"))

        if is_dl:
            digilocker_docs.append(doc_type)
            payload = json.loads(filepath.read_text(encoding="utf-8"))
            digilocker_structured_data[doc_type] = payload
            raw_text = payload.get("raw_text") or json.dumps(payload.get("data", {}))
        else:
            raw_text = filepath.read_text(encoding="utf-8")
        
        docs_text_map[doc_type] = raw_text

    assert "GST Registration Certificate" in digilocker_docs
    assert "PAN Card" not in digilocker_docs
    print("   -> Correctly routed DigiLocker document to bypass OCR extraction.")

    # Ingest structured data into bid_data
    bid_data = extract_bid_information("\n\n".join(docs_text_map.values()))
    for dt, payload in digilocker_structured_data.items():
        data_fields = payload.get("data", {})
        if "gstin" in data_fields:
            bid_data.identifiers.gstin = str(data_fields["gstin"]).strip().upper()

    assert bid_data.identifiers.gstin == "27AABCA1234F1Z5"
    assert bid_data.identifiers.pan == "AABCA1234F"
    print("   -> Directly injected DigiLocker GSTIN into bid_data identifiers: 27AABCA1234F1Z5")

    # Evaluate compliance
    criteria = TenderCriteria(tender_id="GEM/2024/B/TEST", title="Test Tender")
    evaluator = GeMClauseEvaluator()
    results = evaluator.evaluate_all_documents(docs_text_map, criteria, bid_data)
    assert len(results) in (14, 15)
    print(f"   -> Successfully evaluated all {len(results)} clauses with DigiLocker document incorporated.")

    # Cleanup test bidder records
    clear_all_bidder_documents(bidder_id)
    print("   -> Cleaned up test records.")


if __name__ == "__main__":
    test_digilocker_api_client()
    test_dual_path_persistence()
    test_officer_digilocker_pipeline_bypass()
    print("\n" + "=" * 60)
    print("ALL DIGILOCKER TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
