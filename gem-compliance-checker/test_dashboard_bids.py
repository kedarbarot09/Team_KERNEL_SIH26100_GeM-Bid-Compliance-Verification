import io
import json
from pathlib import Path
import sys
import pandas as pd
from PIL import Image

CURRENT_DIR = Path("gem-compliance-checker").resolve()
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import (
    DOCUMENT_CATEGORIES,
    ClauseResult,
    ClauseStatus,
    GeMClauseEvaluator,
    TenderCriteria,
)
from app.db import (
    clear_all_bidder_documents,
    clear_extracted_images_for_bidder,
    get_all_bidders_summary,
    get_audit_logs,
    get_documents_by_bidder,
    get_extracted_images,
    get_image_match_results,
    get_submitted_bidders,
    init_db,
    save_extracted_image,
    save_image_match_result,
    save_uploaded_document,
    submit_bidder_documents,
    update_bidder_status,
)
from app.demo_data import (
    BID_PRESETS,
    generate_bidder_demo_documents,
    get_bidder_by_id,
)
from app.extract import ExtractedBidData, extract_bid_information
from app.image_extract import ExtractedImage, extract_photo, extract_signature
from app.image_match import MatchResult, compare_faces, compare_signatures
from app.mock_portals import EntityFullVerification, MockPortalRegistry, VerificationStatus
from app.ocr import extract_text_from_document
from app.scoring import ComplianceReport, RiskCategory, ScoringEngine

print("Running dashboard code simulation for all 10 bidders...")

criteria = TenderCriteria()

for preset in BID_PRESETS:
    bid_id = preset["bidder_id"]
    print(f"\n================ Testing Bidder: {bid_id} ================")
    
    # 1. Load documents if not already loaded
    docs = get_documents_by_bidder(bid_id)
    if not docs:
        print(f"Loading docs for {bid_id}...")
        sample_docs = generate_bidder_demo_documents(bid_id)
        for (cat, doc_type), (fname, fbytes) in sample_docs.items():
            save_uploaded_document(bid_id, cat, doc_type, fname, fbytes)
        submit_bidder_documents(bid_id)
        docs = get_documents_by_bidder(bid_id)
    
    # 2. Run the exact dashboard pipeline
    docs_text_map = {}
    docs_record_map = {}
    combined_texts = []
    digilocker_docs = []
    digilocker_structured_data = {}
    extracted_imgs = []

    for doc in docs:
        doc_type = doc["document_type"]
        filepath = Path(doc["filepath"])
        raw_text = ""
        is_dl = (doc.get("source") == "digilocker") or bool(doc.get("issuer_verified"))

        if is_dl:
            digilocker_docs.append(doc_type)
            if filepath.is_file():
                try:
                    payload = json.loads(filepath.read_text(encoding="utf-8"))
                    digilocker_structured_data[doc_type] = payload
                    raw_text = payload.get("raw_text") or json.dumps(payload.get("data", {}), indent=2)
                except Exception as e:
                    raw_text = f"DigiLocker record: {e}"
        else:
            if filepath.is_file():
                try:
                    fbytes = filepath.read_bytes()
                    ocr_res = extract_text_from_document(fbytes, doc["filename"])
                    raw_text = ocr_res.raw_text

                    if filepath.suffix.lower() == ".pdf":
                        photo = extract_photo(fbytes, doc_type=doc_type)
                        if photo:
                            extracted_imgs.append(photo)
                            save_extracted_image(bid_id, doc_type, "photo", photo.to_bytes(), photo.source_page, photo.extraction_confidence)
                        sig = extract_signature(fbytes, doc_type=doc_type)
                        if sig:
                            extracted_imgs.append(sig)
                            save_extracted_image(bid_id, doc_type, "signature", sig.to_bytes(), sig.source_page, sig.extraction_confidence)
                except Exception as e:
                    raw_text = f"Error reading document: {e}"

        docs_text_map[doc_type] = raw_text
        docs_record_map[doc_type] = doc
        if raw_text:
            combined_texts.append(raw_text)

    if not extracted_imgs:
        db_imgs = get_extracted_images(bid_id)
        for dimg in db_imgs:
            try:
                pil_im = Image.open(io.BytesIO(dimg["image_blob"]))
                extracted_imgs.append(
                    ExtractedImage(
                        image=pil_im,
                        bbox=(0.0, 0.0, float(pil_im.width), float(pil_im.height)),
                        source_document=dimg["document_id"],
                        source_page=dimg["source_page"],
                        extraction_confidence=dimg["extraction_confidence"],
                        image_type=dimg["image_type"],
                    )
                )
            except Exception:
                pass

    photos = [img for img in extracted_imgs if img.image_type == "photo"]
    signatures = [img for img in extracted_imgs if img.image_type == "signature"]

    # Pairwise cross-verification
    match_results = []
    for i in range(len(photos)):
        for j in range(i + 1, len(photos)):
            p1, p2 = photos[i], photos[j]
            if p1.source_document != p2.source_document:
                res = compare_faces(p1, p2)
                save_image_match_result(bid_id, "photo", p1.source_document, p2.source_document, res.score, res.verdict)
                match_results.append({
                    "Document Pair": f"{p1.source_document} <-> {p2.source_document}",
                    "Biometric Type": "Photo / Facial Identity",
                    "Similarity Score": f"{res.score:.1%}",
                    "Verdict": res.verdict,
                    "Notes": res.notes,
                })

    for i in range(len(signatures)):
        for j in range(i + 1, len(signatures)):
            s1, s2 = signatures[i], signatures[j]
            if s1.source_document != s2.source_document:
                res = compare_signatures(s1, s2)
                save_image_match_result(bid_id, "signature", s1.source_document, s2.source_document, res.score, res.verdict)
                match_results.append({
                    "Document Pair": f"{s1.source_document} <-> {s2.source_document}",
                    "Biometric Type": "Authorised Signature",
                    "Similarity Score": f"{res.score:.1%}",
                    "Verdict": res.verdict,
                    "Notes": res.notes,
                })

    print(f"Extracted {len(photos)} photos, {len(signatures)} signatures, {len(match_results)} matches.")

    # 3. Clauses evaluation
    full_text = "\n\n".join(combined_texts)
    bid_data = extract_bid_information(full_text)

    evaluator = GeMClauseEvaluator()
    clause_results = evaluator.evaluate_all_documents(
        docs_by_type=docs_text_map,
        criteria=criteria,
        bid_data=bid_data,
        extracted_images=extracted_imgs,
    )

    # 4. Portal verification
    portal_verification = evaluator.portals.verify_all(
        pan=bid_data.identifiers.pan,
        gstin=bid_data.identifiers.gstin,
        udyam=bid_data.identifiers.udyam,
    )

    # 5. Report
    report = ScoringEngine.generate_report(
        bid_data=bid_data,
        verification=portal_verification,
        clauses=clause_results,
    )

    # 6. Check category tables formatting
    clause_map = {c.clause_name: c for c in clause_results}
    for cat_name, doc_types in DOCUMENT_CATEGORIES.items():
        rows = []
        for dt in doc_types:
            c = clause_map.get(dt)
            if not c:
                continue
            rows.append({"Document Type": dt, "Status": c.status.value, "Remarks": c.remarks})
        df = pd.DataFrame(rows)

    # 7. Check Styler styling on match_results
    if match_results:
        df_match = pd.DataFrame(match_results)
        display_cols = ["Document Pair", "Biometric Type", "Similarity Score", "Verdict", "Notes"]
        df_display = df_match[display_cols]
        def _color_verdict(val):
            v = str(val).upper()
            if v == "MATCH":
                return "background-color: #D1FAE5; color: #065F46; font-weight: 700;"
            elif v == "MISMATCH":
                return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
            elif v == "INCONCLUSIVE":
                return "background-color: #FEF3C7; color: #92400E; font-weight: 700;"
            return ""
        if hasattr(df_display.style, "map"):
            styled_df = df_display.style.map(_color_verdict, subset=["Verdict"])
        else:
            styled_df = df_display.style.applymap(_color_verdict, subset=["Verdict"])
        html = styled_df.to_html()

    print(f"Bidder {bid_id} evaluated cleanly! Score: {report.score_percentage}% Risk: {report.risk_category.value}")

print("\nALL BIDDERS TESTED IN DASHBOARD PIPELINE!")
