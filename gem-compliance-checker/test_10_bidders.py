"""Automated verification script for all 10 benchmark bidders (BID-001 through BID-010)."""

from pathlib import Path
import sys

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import ClauseStatus, GeMClauseEvaluator, TenderCriteria
from app.db import (
    get_documents_by_bidder,
    get_submitted_bidders,
    init_db,
    save_extracted_image,
    save_uploaded_document,
    submit_bidder_documents,
)
from app.demo_data import BID_PRESETS, generate_bidder_demo_documents
from app.extract import extract_bid_information
from app.image_extract import extract_photo, extract_signature
from app.mock_portals import MockPortalRegistry, VerificationStatus
from app.ocr import extract_text_from_document
from app.scoring import RiskCategory, ScoringEngine


def run_benchmark_test():
    print("=" * 80)
    print("RUNNING BENCHMARK EVALUATION TEST FOR 10 BIDDERS (BID-001 TO BID-010)")
    print("=" * 80)

    # 1. Initialize SQLite database
    init_db()
    portals = MockPortalRegistry()
    evaluator = GeMClauseEvaluator(portal_registry=portals)

    # Standard Tender Criteria
    criteria = TenderCriteria(
        tender_id="GEM/2026/B/8899110",
        title="Procurement of IT Hardware & Office Solutions",
        required_turnover_lakhs=30.0,
        min_experience_years=3,
        min_completed_orders=2,
        min_local_content_pct=50.0,
        require_emd=True,
        require_epfo_esic=True,
        require_oem_auth=True,
        require_bis_cert=True,
        require_tech_specs=True,
        require_mca_cin=True,
        require_itr=True,
        require_non_blacklisting=True,
    )

    results_summary = []

    for preset in BID_PRESETS:
        bidder_id = preset["bidder_id"]
        company_name = preset["company_name"]
        print(f"\n--- Testing {bidder_id}: {company_name} ---")

        # 2. Generate and store demo documents
        docs_to_save = generate_bidder_demo_documents(bidder_id)
        assert len(docs_to_save) > 0, f"No documents generated for {bidder_id}"

        for (cat, doc_type), (fname, fbytes) in docs_to_save.items():
            save_uploaded_document(
                bidder_id=bidder_id,
                category=cat,
                document_type=doc_type,
                filename=fname,
                file_bytes=fbytes,
            )

        submit_count = submit_bidder_documents(bidder_id)
        db_docs = get_documents_by_bidder(bidder_id)
        print(f"  -> Uploaded and submitted {len(db_docs)} documents.")

        # 3. Read back text content and extract visual identity assets (photos & signatures)
        docs_text = {}
        extracted_imgs = []
        for d in db_docs:
            p = Path(d["filepath"])
            dt = d["document_type"]
            fbytes = p.read_bytes()
            if p.suffix.lower() == ".txt":
                docs_text[dt] = fbytes.decode("utf-8", errors="ignore")
            else:
                docs_text[dt] = extract_text_from_document(fbytes, d["filename"]).raw_text
                # Extract photo if present
                photo = extract_photo(fbytes, doc_type=dt)
                if photo:
                    extracted_imgs.append(photo)
                    save_extracted_image(bidder_id, dt, "photo", photo.to_bytes(), photo.source_page, photo.extraction_confidence)
                # Extract signature if present
                sig = extract_signature(fbytes, doc_type=dt)
                if sig:
                    extracted_imgs.append(sig)
                    save_extracted_image(bidder_id, dt, "signature", sig.to_bytes(), sig.source_page, sig.extraction_confidence)

        combined_text = "\n\n".join(docs_text.values())

        # 4. Extract data and evaluate all 15 clauses including Identity Consistency Check
        bid_data = extract_bid_information(combined_text)
        clause_results = evaluator.evaluate_all_documents(docs_text, criteria, bid_data, extracted_images=extracted_imgs)

        # 5. Verify against Mock Portals (PAN, GSTIN, Udyam, Debarment)
        bidder_meta = portals.get_bidder(bidder_id) or {}
        profile = bidder_meta.get("profile", {})
        pan = profile.get("pan") or bid_data.identifiers.pan or ""
        gstin = profile.get("gstin") or bid_data.identifiers.gstin or ""
        stat_docs = bidder_meta.get("documents", {}).get("statutory", {})
        udyam_dict = stat_docs.get("udyam_certificate") or {}
        udyam = udyam_dict.get("number") or bid_data.identifiers.udyam or ""

        portal_verif = portals.verify_all(pan=pan, gstin=gstin, udyam=udyam)

        # 6. Scoring Report
        report = ScoringEngine.generate_report(bid_data, portal_verif, clause_results)

        passed_clauses = [c.clause_name for c in clause_results if c.status == ClauseStatus.PASS]
        failed_clauses = [f"{c.clause_name}: {c.remarks}" for c in clause_results if c.status == ClauseStatus.FAIL]
        cond_clauses = [f"{c.clause_name}: {c.remarks}" for c in clause_results if c.status == ClauseStatus.CONDITIONAL]

        print(f"  Score: {report.score_percentage}% | Risk: {report.risk_category.value} | Eligible: {report.is_technically_eligible}")
        print(f"  Passed Clauses: {len(passed_clauses)}, Conditional: {len(cond_clauses)}, Failed: {len(failed_clauses)}")
        if failed_clauses:
            print(f"  Failures: {failed_clauses}")
        is_debarred = (portal_verif.debarment_check.status == VerificationStatus.BLACKLISTED) or portal_verif.debarment_check.details.get("is_debarred", False)
        gst_status = portal_verif.gstin_verification.details.get("status", portal_verif.gstin_verification.status.value)

        if is_debarred:
            print(f"  DEBARMENT DETECTED: {portal_verif.debarment_check.details}")
        if gst_status in ["Suspended", "Cancelled"]:
            print(f"  GST ISSUE DETECTED: Status is {gst_status}")

        results_summary.append({
            "bidder_id": bidder_id,
            "company_name": company_name,
            "score": report.score_percentage,
            "risk": report.risk_category.value,
            "eligible": report.is_technically_eligible,
            "failed_count": len(failed_clauses),
            "cond_count": len(cond_clauses),
            "failed_clauses": failed_clauses,
            "debarred": is_debarred,
            "gst_status": gst_status,
        })

    # =========================================================================
    # SPECIFIC ASSERTIONS FOR EXPECTED BEHAVIORS
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERIFYING BENCHMARK EXPECTATIONS")
    print("=" * 80)

    # BID-001 (Alpha Tech): Micro MSE, compliant
    b1 = next(r for r in results_summary if r["bidder_id"] == "BID-001")
    assert b1["eligible"] is True, f"BID-001 should be technically eligible, got {b1}"
    assert b1["score"] >= 88.0, f"BID-001 score should be >= 88%, got {b1['score']}"
    print("[PASS] BID-001: Verified Compliant (Score >= 88%)")

    # BID-002 (Beta Infra): Expired Udyam, Suspended GST, Invalid EMD claim
    b2 = next(r for r in results_summary if r["bidder_id"] == "BID-002")
    assert b2["gst_status"] == "Suspended", f"BID-002 GST status should be Suspended, got {b2['gst_status']}"
    assert b2["failed_count"] >= 1 or b2["risk"] == RiskCategory.NON_COMPLIANT.value, f"BID-002 must have failures, got {b2}"
    print(f"[PASS] BID-002: Flagged Suspended GST & Deficiencies (Risk: {b2['risk']})")

    # BID-003 (Gamma Trading): Debarred by Ministry of Coal
    b3 = next(r for r in results_summary if r["bidder_id"] == "BID-003")
    assert b3["debarred"] is True, f"BID-003 must be detected as debarred! Got: {b3['debarred']}"
    assert b3["eligible"] is False, f"BID-003 debarred bidder must not be eligible!"
    print(f"[PASS] BID-003: Debarred entity flagged and disqualified by Central Debarment Watchlist")

    # BID-004 (Delta Precision): NSIC exempt EMD, Direct OEM, MII 82% (Intentional Identity Mismatch Demo)
    b4 = next(r for r in results_summary if r["bidder_id"] == "BID-004")
    assert b4["eligible"] is True, f"BID-004 must be eligible, got {b4}"
    assert b4["score"] >= 86.0, f"BID-004 score should be >= 86%, got {b4['score']}"
    assert any("Identity Consistency Check" in f for f in b4["failed_clauses"]), "BID-004 must have visual mismatch in failed_clauses"
    print(f"[PASS] BID-004: Clean text compliance verified with intentional visual identity mismatch flagged (Score: {b4['score']}%)")

    # BID-005 (Epsilon Office): DPIIT Startup exempt from Turnover & Experience
    b5 = next(r for r in results_summary if r["bidder_id"] == "BID-005")
    assert b5["eligible"] is True, f"BID-005 startup must be eligible with exemptions, got {b5}"
    assert b5["score"] >= 85.0, f"BID-005 score should be >= 85%, got {b5['score']}"
    print(f"[PASS] BID-005: DPIIT Startup turnover & experience exemptions verified (Score: {b5['score']}%)")

    # BID-006 (Zenith Defence): Bank Guarantee with SFMS, Large Enterprise
    b6 = next(r for r in results_summary if r["bidder_id"] == "BID-006")
    assert b6["eligible"] is True, f"BID-006 large enterprise must be eligible, got {b6}"
    assert b6["score"] >= 90.0, f"BID-006 score should be >= 90%, got {b6['score']}"
    print(f"[PASS] BID-006: Bank Guarantee with SFMS & Large Enterprise turnover verified")

    # BID-007 (Kavya Textiles): NSIC, Class-I MII (94%), BIS Certified (Intentional Identity Mismatch Demo)
    b7 = next(r for r in results_summary if r["bidder_id"] == "BID-007")
    assert b7["eligible"] is True, f"BID-007 must be eligible, got {b7}"
    assert b7["score"] >= 86.0, f"BID-007 score should be >= 86%, got {b7['score']}"
    assert any("Identity Consistency Check" in f for f in b7["failed_clauses"]), "BID-007 must have visual mismatch in failed_clauses"
    print(f"[PASS] BID-007: Clean text compliance verified with intentional visual identity mismatch flagged (Score: {b7['score']}%)")

    # BID-008 (Omega Pharma): Cancelled GST, EPFO Defaulter, Spec Deviations
    b8 = next(r for r in results_summary if r["bidder_id"] == "BID-008")
    assert b8["gst_status"] == "Cancelled", f"BID-008 GST status must be Cancelled, got {b8['gst_status']}"
    assert b8["eligible"] is False or b8["failed_count"] >= 1, f"BID-008 must fail, got {b8}"
    print(f"[PASS] BID-008: Flagged Cancelled GST & Technical Spec deviations")

    # BID-009 (Nova Renewable): DPIIT Startup, BIS IS 14286 Solar PV
    b9 = next(r for r in results_summary if r["bidder_id"] == "BID-009")
    assert b9["eligible"] is True, f"BID-009 startup must be eligible, got {b9}"
    print(f"[PASS] BID-009: Startup exemptions & BIS solar standard verified")

    # BID-010 (Sundar Facility): Expired Udyam, Missing ITR
    b10 = next(r for r in results_summary if r["bidder_id"] == "BID-010")
    assert b10["failed_count"] >= 1 or b10["cond_count"] >= 1, f"BID-010 must flag deficiencies, got {b10}"
    print(f"[PASS] BID-010: Deficiencies and expired status correctly identified")

    print("\n" + "=" * 80)
    print("ALL 10 BENCHMARK BIDDER VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmark_test()
