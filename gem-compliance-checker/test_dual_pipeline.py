"""End-to-end unit test for dual bidder/officer compliance engine."""

from pathlib import Path
import sys

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import DOCUMENT_CATEGORIES, ClauseStatus, GeMClauseEvaluator, TenderCriteria
from app.db import (
    get_audit_logs,
    get_documents_by_bidder,
    get_submitted_bidders,
    init_db,
    save_uploaded_document,
    submit_bidder_documents,
    update_bidder_status,
)
from app.extract import extract_bid_information
from app.scoring import RiskCategory, ScoringEngine


def test_pipeline():
    print("1. Initializing DB...")
    init_db()

    bidder_id = "TEST-ALPHA-101"
    print(f"2. Saving mock documents for {bidder_id}...")

    # Upload Udyam, GST, PAN, etc.
    save_uploaded_document(
        bidder_id,
        "Statutory / registration documents",
        "PAN Card",
        "pan.txt",
        b"PAN: AAACA1234A\nName: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nStatus: ACTIVE",
    )
    save_uploaded_document(
        bidder_id,
        "Statutory / registration documents",
        "GST Registration Certificate",
        "gst.txt",
        b"GSTIN: 27AAACA1234A1Z5\nStatus: ACTIVE\nFiling Status: UP TO DATE",
    )
    save_uploaded_document(
        bidder_id,
        "Statutory / registration documents",
        "Udyam Registration Certificate",
        "udyam.txt",
        b"Udyam Registration Number: UDYAM-MH-01-0012345\nType: Micro Enterprise\nStatus: ACTIVE",
    )
    save_uploaded_document(
        bidder_id,
        "Financial documents",
        "Audited financial statement / turnover certificate",
        "turnover.txt",
        b"Average Annual Turnover: 55.00 Lakhs\nUDIN: 24045129BCA99182",
    )
    save_uploaded_document(
        bidder_id,
        "Financial documents",
        "EMD proof",
        "emd.txt",
        b"Udyam Registration Number: UDYAM-MH-01-0012345\nClaiming Exemption: YES\n100% EMD waiver claimed.",
    )
    save_uploaded_document(
        bidder_id,
        "Eligibility exemption / preference documents",
        "Make in India / local content self-declaration",
        "mii.txt",
        b"Local Content: 65.0%\nClassification: Class-I Local Supplier",
    )
    save_uploaded_document(
        bidder_id,
        "Technical / product-specific documents",
        "Past performance / experience certificate",
        "exp.txt",
        b"Years of Relevant Experience: 6 Years\nCompleted Government Supply Orders: 14 completed contracts",
    )
    save_uploaded_document(
        bidder_id,
        "Compliance / background documents",
        "Self-declaration of non-blacklisting",
        "debar.txt",
        b"Solemnly affirm that our firm has never been blacklisted or debarred.\nAuthorized Signatory Signature attached.",
    )

    docs = get_documents_by_bidder(bidder_id)
    assert len(docs) == 8, f"Expected 8 documents, found {len(docs)}"
    print(f"   -> Successfully saved {len(docs)} documents.")

    print("3. Submitting documents...")
    submit_count = submit_bidder_documents(bidder_id)
    assert submit_count == 8
    submitted_bidders = get_submitted_bidders()
    matched = [b for b in submitted_bidders if b["bidder_id"] == bidder_id]
    assert len(matched) == 1
    assert matched[0]["overall_status"] == "submitted"
    print("   -> Submission successful.")

    print("4. Evaluating documents with TenderCriteria...")
    criteria = TenderCriteria(
        tender_id="GEM/2024/B/4568912",
        title="High Performance Computing",
        required_turnover_lakhs=30.0,
        min_experience_years=2,
        min_completed_orders=1,
        min_local_content_pct=50.0,
        require_emd=True,
        require_epfo_esic=False,  # Should be NOT_APPLICABLE
        require_oem_auth=False,   # Should be NOT_APPLICABLE
        require_bis_cert=False,   # Should be NOT_APPLICABLE
        require_tech_specs=False, # Should be NOT_APPLICABLE
        require_mca_cin=False,    # Should be NOT_APPLICABLE
    )

    docs_text = {d["document_type"]: Path(d["filepath"]).read_text(encoding="utf-8") for d in docs}
    bid_data = extract_bid_information("\n\n".join(docs_text.values()))
    evaluator = GeMClauseEvaluator()
    results = evaluator.evaluate_all_documents(docs_text, criteria, bid_data)

    assert len(results) == 15, f"Expected 15 results, got {len(results)}"
    
    # Check that unchecked criteria yield NOT_APPLICABLE
    na_results = [r for r in results if r.status == ClauseStatus.NOT_APPLICABLE]
    assert len(na_results) >= 5, f"Expected at least 5 NOT_APPLICABLE clauses, got {len(na_results)}"
    print(f"   -> Evaluated 15 document rules: {len(na_results)} marked Not Applicable as configured.")

    print("5. Generating compliance score report...")
    portal_verification = evaluator.portals.verify_all(
        pan=bid_data.identifiers.pan,
        gstin=bid_data.identifiers.gstin,
        udyam=bid_data.identifiers.udyam,
    )
    report = ScoringEngine.generate_report(bid_data, portal_verification, results)
    print(f"   -> Overall Score: {report.score_percentage}%")
    print(f"   -> Risk Category: {report.risk_category.value}")
    print(f"   -> Technical Eligible: {report.is_technically_eligible}")
    # Since 8 uploaded, 5 waived, and 1 missing (ITR), risk is correctly CONDITIONAL with 95% score
    assert report.score_percentage == 95.0
    assert report.risk_category == RiskCategory.CONDITIONAL
    assert report.scoring_breakdown.failed_clauses_count == 1  # Missing ITR
    assert report.scoring_breakdown.passed_clauses_count == 8
    assert report.scoring_breakdown.not_applicable_clauses_count in (5, 6)
    print("   -> Correctly flagged missing ITR as CONDITIONAL risk (95.0% score).")

    # Now toggle require_itr=False so all applicable clauses pass -> COMPLIANT
    criteria.require_itr = False
    results_compliant = evaluator.evaluate_all_documents(docs_text, criteria, bid_data)
    report_compliant = ScoringEngine.generate_report(bid_data, portal_verification, results_compliant)
    assert report_compliant.score_percentage == 100.0
    assert report_compliant.risk_category == RiskCategory.COMPLIANT
    print("   -> With ITR waived, achieved 100.0% score and COMPLIANT risk.")

    print("6. Testing Officer Decision & Audit Log...")
    ok = update_bidder_status(bidder_id, "verified", "All statutory and technical credentials verified compliant.")
    assert ok is True
    logs = get_audit_logs(bidder_id)
    assert len(logs) >= 1
    assert logs[0]["officer_action"] == "verified"
    print(f"   -> Audit log successfully saved: {logs[0]['justification']}")

    print("\nALL PIPELINE TESTS PASSED!")


if __name__ == "__main__":
    test_pipeline()
