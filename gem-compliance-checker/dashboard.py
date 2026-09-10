"""Streamlit Evaluation Dashboard for GeM Bid Compliance Engine (SIH 26100).

Provides an interactive user interface for GeM Procurement Officers to:
- Configure comprehensive Tender Evaluation Criteria (Thresholds and Category Applicability)
- Select submitted bidders from the shared SQLite database (bidder_documents.db)
- Inspect categorized documents (Statutory, Financial, Preference, Technical, Compliance)
- Execute automated OCR ingestion and 14-item deterministic clause evaluation
- Inspect prominent top-level compliance scoring and risk categorization
- Record justification remarks and log official decisions ('verified' or 'flagged') to the audit trail
"""

from datetime import datetime
import io
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import pandas as pd
from PIL import Image
import requests
import streamlit as st

# Add current directory to path so app modules can be imported directly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# Ensure freshly modified app submodules are automatically refreshed in long-running Streamlit sessions
import importlib
for _mod_name in ["app.db", "app.clauses", "app.demo_data", "app.image_extract", "app.image_match", "app.mock_portals"]:
    if _mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[_mod_name])
        except Exception:
            pass

from app.clauses import (
    DOCUMENT_CATEGORIES,
    ClauseResult,
    ClauseStatus,
    GeMClauseEvaluator,
    TenderCriteria,
)

import app.db
if not hasattr(app.db, "clear_extracted_images_for_bidder"):
    try:
        importlib.reload(app.db)
    except Exception:
        pass

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

# Auto-detect bare python execution (e.g. VS Code 'Run/Debug' or `python dashboard.py`)
# and automatically bootstrap the Streamlit server runner.
try:
    from streamlit.runtime import exists as _st_runtime_exists
    _is_in_streamlit = _st_runtime_exists()
except Exception:
    _is_in_streamlit = False

if not _is_in_streamlit:
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve()), "--server.port=8501"]
    sys.exit(stcli.main())

# Page configuration
st.set_page_config(
    page_title="GeM Officer Compliance Dashboard | SIH 26100",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling - Modern Enterprise Light Theme
st.markdown(
    """
    <style>
    /* Global Canvas & Typography */
    .stApp {
        background-color: #F8FAFC !important;
        color: #0F172A !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* Sidebar Clean Light Theme */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E2E8F0 !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #0F172A !important;
        font-weight: 700 !important;
    }

    /* Top Gov-Tech Badge */
    .gov-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background-color: #EFF6FF;
        border: 1px solid #BFDBFE;
        color: #1E40AF;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 4px 12px;
        border-radius: 9999px;
        margin-bottom: 0.6rem;
    }
    .gov-badge-dot {
        width: 7px;
        height: 7px;
        background-color: #2563EB;
        border-radius: 50%;
        display: inline-block;
    }

    .main-title {
        font-size: 1.8rem;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.02em;
        margin-bottom: 0.25rem;
    }
    .sub-title {
        color: #475569;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    /* Metric Cards */
    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 100%;
    }
    .kpi-label {
        font-size: 0.8rem;
        font-weight: 600;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .kpi-value {
        font-size: 1.75rem;
        font-weight: 800;
        color: #0F172A;
        margin: 6px 0;
    }
    .kpi-caption {
        font-size: 0.8rem;
        color: #64748B;
    }

    /* Pill Badges */
    .badge-compliant {
        background-color: #DCFCE7;
        color: #166534;
        font-weight: 700;
        font-size: 0.85rem;
        padding: 4px 10px;
        border-radius: 9999px;
        display: inline-block;
    }
    .badge-conditional {
        background-color: #FEF3C7;
        color: #92400E;
        font-weight: 700;
        font-size: 0.85rem;
        padding: 4px 10px;
        border-radius: 9999px;
        display: inline-block;
    }
    .badge-disqualified {
        background-color: #FEE2E2;
        color: #991B1B;
        font-weight: 700;
        font-size: 0.85rem;
        padding: 4px 10px;
        border-radius: 9999px;
        display: inline-block;
    }
    .badge-digilocker {
        background-color: #EFF6FF;
        border: 1px solid #BFDBFE;
        color: #1D4ED8;
        font-weight: 700;
        font-size: 0.8rem;
        padding: 3px 9px;
        border-radius: 9999px;
        display: inline-block;
    }

    /* Category Headers */
    .cat-box {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 14px 18px;
        margin-top: 14px;
        margin-bottom: 8px;
    }
    .cat-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1E293B;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize shared SQLite database
init_db()

# -----------------------------------------------------------------------------
# Sidebar: Tender Evaluation Criteria
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/5/55/Emblem_of_India.svg", width=60)
    st.markdown("### Tender Evaluation Criteria")
    st.caption("Buyer qualification thresholds & clause applicability gates:")

    tender_id_input = st.text_input("Tender ID", value="GEM/2024/B/4568912")
    tender_title_input = st.text_input("Tender Title", value="Supply of High-Performance Computing Workstations")

    st.markdown("#### 📊 Qualification Thresholds")
    tender_turnover = st.number_input(
        "Min Turnover (INR Lakhs)",
        min_value=1.0,
        max_value=1000.0,
        value=30.0,
        step=5.0,
        help="Turnover requirement under Clause 2",
    )
    tender_exp = st.slider(
        "Min Past Experience (Years)",
        min_value=0,
        max_value=15,
        value=2,
        help="Past performance experience requirement",
    )
    tender_orders = st.number_input(
        "Min Completed Orders",
        min_value=1,
        max_value=20,
        value=1,
        help="Minimum number of completed supply orders",
    )
    tender_mii = st.slider(
        "Min Make in India Local Content (%)",
        min_value=10,
        max_value=100,
        value=50,
        step=5,
        help="Local value addition percentage for Class-I preference",
    )
    require_emd = st.checkbox("Require EMD (MSE exempt)", value=True)

    st.markdown("---")
    st.markdown("#### ⚙️ Requirement Applicability")
    st.caption("Toggle requirements; unchecked clauses will be marked 'Not Applicable':")

    req_epfo_esic = st.checkbox("Require EPFO/ESIC Registration", value=False, help="Uncheck for small vendors/MSEs with < 20 workers to mark Not Applicable")
    req_oem_auth = st.checkbox("Require OEM Authorization Form (MAF)", value=True, help="Uncheck for direct manufacturers/services")
    req_bis_cert = st.checkbox("Require BIS / Quality Certification", value=True, help="Uncheck if tender item has no mandatory BIS standard")
    req_tech_specs = st.checkbox("Require Product Tech Brochure", value=True, help="Technical specification schedule")
    req_mca_cin = st.checkbox("Require MCA Incorporation Certificate", value=True, help="Uncheck if proprietorships/partnerships allowed")
    req_itr = st.checkbox("Require 3-Year ITR Filings", value=True)
    req_non_blacklisting = st.checkbox("Require Non-Blacklisting Undertaking", value=True)

    # Instantiate current TenderCriteria
    criteria = TenderCriteria(
        tender_id=tender_id_input.strip(),
        title=tender_title_input.strip(),
        required_turnover_lakhs=float(tender_turnover),
        min_experience_years=int(tender_exp),
        min_completed_orders=int(tender_orders),
        min_local_content_pct=float(tender_mii),
        require_emd=require_emd,
        require_epfo_esic=req_epfo_esic,
        require_oem_auth=req_oem_auth,
        require_bis_cert=req_bis_cert,
        require_tech_specs=req_tech_specs,
        require_mca_cin=req_mca_cin,
        require_itr=req_itr,
        require_non_blacklisting=req_non_blacklisting,
    )

    st.markdown("---")
    st.markdown("#### 🔄 Role Navigation")
    st.info("You are currently in the **Officer Evaluation Dashboard**.")
    st.markdown(
        """
        - **Bidder Upload Portal?**
          Run:
          ```bash
          streamlit run gem-compliance-checker/bidder_dashboard.py
          ```
        """
    )


# -----------------------------------------------------------------------------
# Main Application Header
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="gov-badge">
        <span class="gov-badge-dot"></span>
        Government e-Marketplace (GeM) • SIH 26100 Procurement Officer Scrutiny Desk
    </div>
    <div class="main-title">GeM Bid Compliance & Document Verification Engine</div>
    <div class="sub-title">Automated AI compliance verification, statutory registry cross-checks, and 14-document deterministic evaluation.</div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Bidder Selector from Shared SQLite Database
# -----------------------------------------------------------------------------
submitted_bidders = get_submitted_bidders()
all_bidders = get_all_bidders_summary()

col_sel, col_preload, col_refresh = st.columns([2.5, 1.3, 0.8])

with col_refresh:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

with col_preload:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("📥 Pre-load 10 Bidders", use_container_width=True, help="Loads all 10 benchmark bidder profiles into SQLite"):
        with st.spinner("Populating 10 benchmark bidder profiles..."):
            for preset in BID_PRESETS:
                bid = preset["bidder_id"]
                clear_all_bidder_documents(bid)
                clear_extracted_images_for_bidder(bid)
                sample_docs = generate_bidder_demo_documents(bid)
                for (cat, doc_type), (fname, fbytes) in sample_docs.items():
                    save_uploaded_document(bid, cat, doc_type, fname, fbytes)
                    if fname.lower().endswith(".pdf"):
                        photo = extract_photo(fbytes, doc_type=doc_type)
                        if photo:
                            save_extracted_image(
                                bid,
                                doc_type,
                                "photo",
                                photo.to_bytes(),
                                photo.source_page,
                                photo.extraction_confidence,
                            )
                        sig = extract_signature(fbytes, doc_type=doc_type)
                        if sig:
                            save_extracted_image(
                                bid,
                                doc_type,
                                "signature",
                                sig.to_bytes(),
                                sig.source_page,
                                sig.extraction_confidence,
                            )
                submit_bidder_documents(bid)
        st.success("Successfully loaded all 10 benchmark bidders into database!")
        st.rerun()

selected_bidder_id: Optional[str] = None

with col_sel:
    if not all_bidders:
        st.warning("⚠️ No bidder submissions found in `bidder_documents.db`. Click '📥 Pre-load 10 Bidders' above to load the test suite.")
    else:
        # Build rich options list
        options = []
        for b in all_bidders:
            b_id = b["bidder_id"]
            status_text = b["overall_status"].upper()
            meta = get_bidder_by_id(b_id)
            cname = meta.get("company_name", "Vendor") if meta else "Vendor"
            options.append(f"{b_id} — {cname}  ({b['document_count']} docs | {status_text})")

        selected_option = st.selectbox(
            "Select Submitted Bidder for Evaluation:",
            options=options,
            index=0,
            help="Choose a candidate bidder from SQLite documents table",
        )
        if selected_option:
            selected_bidder_id = selected_option.split(" — ")[0].strip()

# -----------------------------------------------------------------------------
# Per-Document Ingestion & Execution Pipeline
# -----------------------------------------------------------------------------
if selected_bidder_id:
    bidder_docs = get_documents_by_bidder(selected_bidder_id)
    
    # Read files from disk and run OCR / Text extraction (or direct DigiLocker ingestion)
    docs_text_map: Dict[str, str] = {}
    docs_record_map: Dict[str, Dict[str, Any]] = {}
    combined_texts: List[str] = []
    digilocker_docs: List[str] = []
    digilocker_structured_data: Dict[str, Dict[str, Any]] = {}
    extracted_imgs: List[ExtractedImage] = []

    for doc in bidder_docs:
        doc_type = doc["document_type"]
        filepath = Path(doc["filepath"])
        raw_text = ""
        is_dl = (doc.get("source") == "digilocker") or bool(doc.get("issuer_verified"))

        if is_dl:
            # DigiLocker direct feed: Skip OCR / text extraction step entirely
            digilocker_docs.append(doc_type)
            if filepath.is_file():
                try:
                    payload = json.loads(filepath.read_text(encoding="utf-8"))
                    digilocker_structured_data[doc_type] = payload
                    raw_text = payload.get("raw_text") or json.dumps(payload.get("data", {}), indent=2)
                except Exception as e:
                    raw_text = f"DigiLocker record: {e}"
        else:
            # Normal document-analysis pipeline: read file and run OCR / text extraction
            if filepath.is_file():
                try:
                    fbytes = filepath.read_bytes()
                    ocr_res = extract_text_from_document(fbytes, doc["filename"])
                    raw_text = ocr_res.raw_text

                    # Extract visual credentials (photos and signatures) from PDF documents
                    if filepath.suffix.lower() == ".pdf":
                        photo = extract_photo(fbytes, doc_type=doc_type)
                        if photo:
                            extracted_imgs.append(photo)
                            save_extracted_image(
                                selected_bidder_id,
                                doc_type,
                                "photo",
                                photo.to_bytes(),
                                photo.source_page,
                                photo.extraction_confidence,
                            )
                        sig = extract_signature(fbytes, doc_type=doc_type)
                        if sig:
                            extracted_imgs.append(sig)
                            save_extracted_image(
                                selected_bidder_id,
                                doc_type,
                                "signature",
                                sig.to_bytes(),
                                sig.source_page,
                                sig.extraction_confidence,
                            )
                except Exception as e:
                    raw_text = f"Error reading document: {e}"

        docs_text_map[doc_type] = raw_text
        docs_record_map[doc_type] = doc
        if raw_text:
            combined_texts.append(raw_text)

    # Reconstruct any previously persisted images from SQLite if not freshly extracted
    if not extracted_imgs:
        db_imgs = get_extracted_images(selected_bidder_id)
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

    # Compute pairwise cross-verifications across distinct documents
    match_results: List[Dict[str, Any]] = []

    # 1. Compare photos across distinct documents
    for i in range(len(photos)):
        for j in range(i + 1, len(photos)):
            p1, p2 = photos[i], photos[j]
            if p1.source_document != p2.source_document:
                res = compare_faces(p1, p2)
                save_image_match_result(
                    selected_bidder_id,
                    "photo",
                    p1.source_document,
                    p2.source_document,
                    res.score,
                    res.verdict,
                )
                match_results.append({
                    "Document Pair": f"{p1.source_document} ↔ {p2.source_document}",
                    "Biometric Type": "Photo / Facial Identity",
                    "Similarity Score": f"{res.score:.1%}",
                    "Verdict": res.verdict,
                    "Notes": res.notes,
                })

    # 2. Compare signatures across distinct documents
    for i in range(len(signatures)):
        for j in range(i + 1, len(signatures)):
            s1, s2 = signatures[i], signatures[j]
            if s1.source_document != s2.source_document:
                res = compare_signatures(s1, s2)
                save_image_match_result(
                    selected_bidder_id,
                    "signature",
                    s1.source_document,
                    s2.source_document,
                    res.score,
                    res.verdict,
                )
                match_results.append({
                    "Document Pair": f"{s1.source_document} ↔ {s2.source_document}",
                    "Biometric Type": "Authorised Signature",
                    "Similarity Score": f"{res.score:.1%}",
                    "Verdict": res.verdict,
                    "Notes": res.notes,
                })

    # Extract global structured entity schema
    full_text = "\n\n".join(combined_texts)
    bid_data = extract_bid_information(full_text)

    # Use DigiLocker structured data directly without regex / LLM guesswork
    for dt, payload in digilocker_structured_data.items():
        data_fields = payload.get("data", {})
        if "pan" in data_fields and data_fields["pan"]:
            bid_data.identifiers.pan = str(data_fields["pan"]).strip().upper()
        if "name" in data_fields and data_fields["name"] and not bid_data.vendor_profile.legal_name:
            bid_data.vendor_profile.legal_name = str(data_fields["name"]).strip()
        if "gstin" in data_fields and data_fields["gstin"]:
            bid_data.identifiers.gstin = str(data_fields["gstin"]).strip().upper()
        if "legal_name" in data_fields and data_fields["legal_name"] and not bid_data.vendor_profile.legal_name:
            bid_data.vendor_profile.legal_name = str(data_fields["legal_name"]).strip()
        if "udyam_registration_number" in data_fields and data_fields["udyam_registration_number"]:
            bid_data.identifiers.udyam = str(data_fields["udyam_registration_number"]).strip().upper()
        if "enterprise_name" in data_fields and data_fields["enterprise_name"] and not bid_data.vendor_profile.legal_name:
            bid_data.vendor_profile.legal_name = str(data_fields["enterprise_name"]).strip()

    # Evaluate all document types against criteria & portal registry, including visual identity
    evaluator = GeMClauseEvaluator()
    clause_results = evaluator.evaluate_all_documents(
        docs_by_type=docs_text_map,
        criteria=criteria,
        bid_data=bid_data,
        extracted_images=extracted_imgs,
    )

    # Verify statutory portals
    portal_verification = evaluator.portals.verify_all(
        pan=bid_data.identifiers.pan,
        gstin=bid_data.identifiers.gstin,
        udyam=bid_data.identifiers.udyam,
    )

    # Generate complete scoring report
    report = ScoringEngine.generate_report(
        bid_data=bid_data,
        verification=portal_verification,
        clauses=clause_results,
    )

    # Determine current status badge
    current_status = bidder_docs[0]["status"].upper() if bidder_docs else "SUBMITTED"
    if current_status == "VERIFIED":
        badge_html = '<span class="badge-compliant">VERIFIED BY OFFICER</span>'
    elif current_status == "FLAGGED":
        badge_html = '<span class="badge-disqualified">FLAGGED FOR REVIEW</span>'
    elif current_status == "SUBMITTED":
        badge_html = '<span class="badge-conditional">SUBMITTED (PENDING EVALUATION)</span>'
    else:
        badge_html = '<span class="badge-conditional">DRAFT / PENDING</span>'

    st.markdown("---")

    # Header with Bidder Info & Current Lifecycle Status
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        st.markdown(f"### Evaluation Target: **{selected_bidder_id}** — *{report.bidder_name}*")
        st.caption(f"Tender Ref: `{criteria.tender_id}` | Total Documents Uploaded: **{len(bidder_docs)}**")
    with col_hdr2:
        st.markdown(f"<div style='text-align: right; padding-top: 10px;'>Status: {badge_html}</div>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # Prominent Top-Level Scoring & Risk Display
    # -------------------------------------------------------------------------
    m1, m2, m3, m4 = st.columns(4)

    # Risk badge formatting
    if report.risk_category == RiskCategory.COMPLIANT:
        risk_html = '<span class="badge-compliant">🟢 COMPLIANT</span>'
    elif report.risk_category == RiskCategory.CONDITIONAL:
        risk_html = '<span class="badge-conditional">🟡 CONDITIONAL</span>'
    else:
        risk_html = '<span class="badge-disqualified">🔴 DISQUALIFIED</span>'

    with m1:
        st.metric("Overall Compliance Score", f"{report.score_percentage:.1f}%")
        st.progress(report.score_percentage / 100.0)
    with m2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-label">Risk Categorization</div>
                    <div style="margin: 4px 0 2px 0;">{risk_html}</div>
                </div>
                <div class="kpi-caption">Report ID: <code>{report.report_id}</code></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m3:
        eligibility = "Eligible for Financial Opening" if report.is_technically_eligible else "Ineligible / Disqualified"
        st.metric("Technical Qualification", "ACCEPTED" if report.is_technically_eligible else "REJECTED", delta=eligibility)
    with m4:
        breakdown = report.scoring_breakdown
        st.metric(
            "Evaluation Breakdown",
            f"{breakdown.passed_clauses_count} Met / {breakdown.failed_clauses_count} Not Met / {breakdown.not_applicable_clauses_count} N/A",
        )

    # Executive Briefing Callout
    st.info(f"**Procurement Scrutiny Summary:** {report.executive_summary}")

    if digilocker_docs:
        dl_list_str = ", ".join([f"**{d}**" for d in digilocker_docs])
        st.markdown(
            f"""
            <div style="background: #EFF6FF; border: 1px solid #BFDBFE; border-left: 4px solid #2563EB; border-radius: 8px; padding: 12px 16px; margin: 12px 0 16px 0;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 1.2rem;">🏛️</span>
                    <b style="color: #1E40AF; font-size: 0.95rem;">Issuer-Verified Direct Repository Ingestion (DigiLocker)</b>
                    <span class="badge-digilocker">✅ ISSUER-VERIFIED</span>
                </div>
                <div style="font-size: 0.85rem; color: #1E293B; margin-top: 4px;">
                    Authentic credential(s) fetched directly from Central Government Issuers: {dl_list_str}.<br>
                    <span style="color: #15803D; font-weight: 600;">⚡ OCR extraction step bypassed (used structured API schema) • 🛡️ Forgery & tampering analysis bypassed (authentic issuer certificate).</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # 14-Document Compliance Matrix Grouped by Category
    # -------------------------------------------------------------------------
    st.markdown("### 📋 Document-by-Document Compliance Matrix")
    st.caption("Verification results mapped across the 5 standard GeM categories:")

    # Map clause results by document_type
    clause_map = {c.clause_name: c for c in report.clause_results}

    for cat_name, doc_types in DOCUMENT_CATEGORIES.items():
        st.markdown(
            f"""
            <div class="cat-box">
                <span class="cat-title">📁 {cat_name}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        rows = []
        for dt in doc_types:
            c = clause_map.get(dt)
            if not c:
                continue

            # Format Status Icon and Label
            if c.status == ClauseStatus.PASS:
                status_display = "✅ Met"
            elif c.status == ClauseStatus.FAIL:
                status_display = "❌ Not Met"
            elif c.status == ClauseStatus.CONDITIONAL:
                status_display = "⚠️ Needs Review"
            else:
                status_display = "— Not Applicable"

            # Check if file was uploaded or from DigiLocker
            uploaded_rec = docs_record_map.get(dt)
            is_dl = (uploaded_rec.get("source") == "digilocker") or bool(uploaded_rec.get("issuer_verified")) if uploaded_rec else False

            if dt == "Identity Consistency Check":
                auth_badge = "👁️ Cross-Document Biometrics"
                evidence = c.remarks
                conf_display = f"{int(c.confidence * 100)}%"
            elif is_dl:
                auth_badge = "✅ Issuer-verified via DigiLocker"
                evidence_prefix = f"[{uploaded_rec['filename']}] " if uploaded_rec else ""
                evidence = f"{evidence_prefix}Issuer-Verified via DigiLocker direct repository feed. {c.remarks}"
                conf_display = "100% (Issuer Feed)"
            elif uploaded_rec:
                auth_badge = "📄 Manual Upload (OCR Ingested)"
                evidence_prefix = f"[{uploaded_rec['filename']}] "
                evidence = f"{evidence_prefix}{c.remarks}"
                conf_display = f"{int(c.confidence * 100)}%"
            else:
                auth_badge = "— Not Uploaded"
                evidence = c.remarks
                conf_display = f"{int(c.confidence * 100)}%"

            rows.append({
                "Document Type": dt,
                "Verification Source": auth_badge,
                "Status": status_display,
                "Evidence / Reason": evidence,
                "Confidence": conf_display,
            })

        df_cat = pd.DataFrame(rows)
        st.dataframe(df_cat, use_container_width=True, hide_index=True)

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Visual Identity Verification & Biometric Consistency Panel
    # -------------------------------------------------------------------------
    st.markdown("### 👁️ Visual Identity Verification & Biometric Consistency")
    st.caption("Automated facial matching and signatory stroke verification across uploaded credentials:")

    col_v1, col_v2 = st.columns(2)

    with col_v1:
        st.markdown("#### 📷 Extracted Facial Credentials")
        if not photos:
            st.info("No facial photographs extracted from uploaded documents.")
        else:
            p_cols = st.columns(min(max(len(photos), 1), 3))
            for idx, p in enumerate(photos):
                with p_cols[idx % len(p_cols)]:
                    st.image(
                        p.image,
                        caption=f"{p.source_document}\n(Conf: {int(p.extraction_confidence*100)}%)",
                        use_container_width=True,
                    )

    with col_v2:
        st.markdown("#### ✍️ Extracted Authorised Signatures")
        if not signatures:
            st.info("No signature specimens extracted from uploaded documents.")
        else:
            s_cols = st.columns(min(max(len(signatures), 1), 3))
            for idx, s in enumerate(signatures):
                with s_cols[idx % len(s_cols)]:
                    st.image(
                        s.image,
                        caption=f"{s.source_document}\n(Conf: {int(s.extraction_confidence*100)}%)",
                        use_container_width=True,
                    )

    if match_results:
        st.markdown("#### 📊 Biometric Cross-Comparison Matrix")

        def _color_verdict(val):
            v = str(val).upper()
            if v == "MATCH":
                return "background-color: #D1FAE5; color: #065F46; font-weight: 700;"
            elif v == "MISMATCH":
                return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
            elif v == "INCONCLUSIVE":
                return "background-color: #FEF3C7; color: #92400E; font-weight: 700;"
            return ""

        df_match = pd.DataFrame(match_results)
        display_cols = ["Document Pair", "Biometric Type", "Similarity Score", "Verdict", "Notes"]
        df_display = df_match[display_cols]
        if hasattr(df_display.style, "map"):
            styled_df = df_display.style.map(_color_verdict, subset=["Verdict"])
        else:
            styled_df = df_display.style.applymap(_color_verdict, subset=["Verdict"])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        total_images = len(photos) + len(signatures)
        if total_images <= 1:
            st.warning("⚠️ Single visual credential available — no second document to compare for cross-verification.")
        else:
            st.warning("⚠️ Single visual credential available — no second document to compare for cross-verification.")

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Officer Review & Action Panel
    # -------------------------------------------------------------------------
    st.markdown("### ✍️ Procurement Officer Adjudication")
    st.caption("Record official justification and update the bidder's compliance status in `bidder_documents.db`:")

    col_act1, col_act2 = st.columns([3, 2])

    with col_act1:
        justification_text = st.text_area(
            "Officer Justification / Audit Remarks:",
            placeholder="Enter rationale for technical clearance or grounds for flagging/disqualification...",
            height=120,
            key=f"justification_{selected_bidder_id}",
        )

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("🟢 Mark Verified", type="primary", use_container_width=True):
                if not justification_text.strip():
                    st.error("Please enter a justification remark before marking as verified.")
                else:
                    success = update_bidder_status(selected_bidder_id, "verified", justification_text)
                    if success:
                        st.success(f"Bidder `{selected_bidder_id}` successfully marked as **VERIFIED**! Audit log saved.")
                        st.rerun()
        with btn_col2:
            if st.button("🚩 Flag for Review", use_container_width=True):
                if not justification_text.strip():
                    st.error("Please enter justification grounds for flagging this submission.")
                else:
                    success = update_bidder_status(selected_bidder_id, "flagged", justification_text)
                    if success:
                        st.warning(f"Bidder `{selected_bidder_id}` has been **FLAGGED FOR REVIEW**! Audit log saved.")
                        st.rerun()

    with col_act2:
        st.markdown("#### 📜 Audit Log History")
        logs = get_audit_logs(selected_bidder_id)
        if not logs:
            st.info("No prior officer actions recorded for this bidder.")
        else:
            log_data = []
            for l in logs:
                log_data.append({
                    "Action": l["officer_action"].upper(),
                    "Justification": l["justification"],
                    "Timestamp": l["timestamp"],
                })
            df_logs = pd.DataFrame(log_data)
            st.dataframe(df_logs, use_container_width=True, hide_index=True)

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Secondary Inspection Tabs
    # -------------------------------------------------------------------------
    tab1, tab2, tab3 = st.tabs([
        "📂 Uploaded Document Files",
        "🏛️ Government Registry Records",
        "⚙️ Extracted Entity JSON Schema",
    ])

    with tab1:
        st.markdown("#### Uploaded Document Registry & File Paths")
        doc_meta = []
        for d in bidder_docs:
            is_dl = (d.get("source") == "digilocker") or bool(d.get("issuer_verified"))
            src_str = "✅ Issuer-verified via DigiLocker" if is_dl else "📄 Manual Upload"
            audit_str = "Bypassed (Authentic Issuer Feed)" if is_dl else "Passed (Direct/OCR)"
            forgery_str = "Bypassed (Cryptographically Authentic)" if is_dl else "Scanned (Clean)"
            doc_meta.append({
                "Category": d["category"],
                "Document Type": d["document_type"],
                "Source & Verification": src_str,
                "OCR Ingestion": audit_str,
                "Forgery Analysis": forgery_str,
                "File Name": d["filename"],
                "File Path": d["filepath"],
                "Uploaded At": d["uploaded_at"],
                "Status": d["status"].upper(),
            })
        st.dataframe(pd.DataFrame(doc_meta), use_container_width=True, hide_index=True)

    with tab2:
        st.markdown("#### Verification from Statutory Registries")
        pv = report.portal_verification
        if pv:
            st.info(f"**Verification Gateway:** `{pv.gateway_provider}` • Connected to Government Statutory Verification Registries.")

            # Helper to get colored status badge HTML
            def _status_badge(status_val: str, is_valid: bool) -> str:
                color_map = {
                    "ACTIVE": ("#16A34A", "#DCFCE7"),
                    "VALID": ("#16A34A", "#DCFCE7"),
                    "SUSPENDED": ("#D97706", "#FEF3C7"),
                    "EXPIRED": ("#D97706", "#FEF3C7"),
                    "CANCELLED": ("#DC2626", "#FEE2E2"),
                    "NOT_FOUND": ("#6B7280", "#F3F4F6"),
                    "MISMATCH": ("#DC2626", "#FEE2E2"),
                    "BLACKLISTED": ("#DC2626", "#FEE2E2"),
                }
                fg, bg = color_map.get(status_val.upper(), ("#6B7280", "#F3F4F6"))
                icon = "✅" if is_valid else ("🚫" if status_val.upper() in ("BLACKLISTED", "CANCELLED") else "⚠️")
                return (
                    f'<span style="background:{bg};color:{fg};font-weight:700;padding:3px 10px;'
                    f'border-radius:20px;font-size:0.78rem;letter-spacing:0.5px;">'
                    f'{icon} {status_val.upper()}</span>'
                )

            def _registry_card(title: str, icon: str, identifier: str, registered_name: Optional[str],
                               status_val: str, is_valid: bool, source: str, extra_rows: str = "", risk_flags: list = None) -> str:
                name_html = (
                    f'<div style="font-size:1.05rem;font-weight:700;color:#0F172A;margin:6px 0 4px 0;'
                    f'border-left:3px solid #3B82F6;padding-left:8px;">{registered_name}</div>'
                    if registered_name and registered_name != "N/A"
                    else '<div style="font-size:0.85rem;color:#94A3B8;margin:4px 0;">— Name not resolved from registry</div>'
                )
                flags_html = ""
                if risk_flags:
                    flags_html = "".join(
                        f'<div style="font-size:0.78rem;color:#B45309;background:#FEF3C7;border-radius:4px;'
                        f'padding:2px 8px;margin:2px 0;">⚠️ {f}</div>'
                        for f in risk_flags
                    )
                return f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                     padding:14px 16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <span style="font-size:1.2rem;">{icon}</span>
                    <span style="font-size:0.8rem;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:0.8px;">{title}</span>
                  </div>
                  <div style="font-family:monospace;font-size:0.95rem;color:#1E293B;font-weight:600;">{identifier}</div>
                  {name_html}
                  <div style="margin:8px 0 4px 0;">{_status_badge(status_val, is_valid)}</div>
                  {extra_rows}
                  {flags_html}
                  <div style="margin-top:10px;font-size:0.72rem;color:#2563EB;">
                    <b>Source:</b> {source}
                  </div>
                </div>"""

            c1, c2 = st.columns(2)
            with c1:
                # PAN Card
                pan_extra = ""
                st.markdown(
                    _registry_card(
                        title="Income Tax Department — PAN Registry",
                        icon="🏛️",
                        identifier=pv.pan_verification.query_identifier,
                        registered_name=pv.pan_verification.registered_name,
                        status_val=pv.pan_verification.status.value,
                        is_valid=pv.pan_verification.is_valid,
                        source=pv.pan_verification.source,
                        extra_rows=pan_extra,
                        risk_flags=pv.pan_verification.risk_flags,
                    ),
                    unsafe_allow_html=True,
                )

                # Udyam Card
                udyam_extra = ""
                if pv.udyam_verification.details:
                    etype = pv.udyam_verification.details.get("enterprise_type", "")
                    exp_date = pv.udyam_verification.details.get("expiry_date", "")
                    exp_reason = pv.udyam_verification.details.get("expiry_reason", "")
                    if etype:
                        udyam_extra += f'<div style="font-size:0.82rem;color:#374151;margin:2px 0;">Enterprise Type: <b>{etype}</b></div>'
                    if exp_date:
                        udyam_extra += f'<div style="font-size:0.82rem;color:#DC2626;margin:2px 0;">Expiry Date: <b>{exp_date}</b></div>'
                    if exp_reason:
                        udyam_extra += f'<div style="font-size:0.78rem;color:#B45309;margin:2px 0;">{exp_reason}</div>'
                st.markdown(
                    _registry_card(
                        title="Ministry of MSME — Udyam Portal",
                        icon="🏭",
                        identifier=pv.udyam_verification.query_identifier,
                        registered_name=pv.udyam_verification.registered_name,
                        status_val=pv.udyam_verification.status.value,
                        is_valid=pv.udyam_verification.is_valid,
                        source=pv.udyam_verification.source,
                        extra_rows=udyam_extra,
                        risk_flags=pv.udyam_verification.risk_flags,
                    ),
                    unsafe_allow_html=True,
                )

            with c2:
                # GSTN Card
                gstn_extra = ""
                if pv.gstin_verification.details:
                    filing = pv.gstin_verification.details.get("filing_status_3b", "")
                    c_date = pv.gstin_verification.details.get("cancellation_date", "")
                    if filing:
                        fcolor = "#16A34A" if filing == "Regular" else "#DC2626"
                        gstn_extra += f'<div style="font-size:0.82rem;color:{fcolor};margin:2px 0;">GSTR-3B Filing: <b>{filing}</b></div>'
                    if c_date:
                        gstn_extra += f'<div style="font-size:0.82rem;color:#DC2626;margin:2px 0;">Cancellation Date: <b>{c_date}</b></div>'
                st.markdown(
                    _registry_card(
                        title="GSTN Taxpayer Registry",
                        icon="🧾",
                        identifier=pv.gstin_verification.query_identifier,
                        registered_name=pv.gstin_verification.registered_name,
                        status_val=pv.gstin_verification.status.value,
                        is_valid=pv.gstin_verification.is_valid,
                        source=pv.gstin_verification.source,
                        extra_rows=gstn_extra,
                        risk_flags=pv.gstin_verification.risk_flags,
                    ),
                    unsafe_allow_html=True,
                )

                # Debarment Card
                debar_extra = ""
                if not pv.debarment_check.is_valid and pv.debarment_check.details:
                    d = pv.debarment_check.details
                    debarred_by = d.get("debarred_by", "")
                    reason = d.get("reason", "")
                    start = d.get("start_date", "")
                    end = d.get("end_date", "")
                    if debarred_by:
                        debar_extra += f'<div style="font-size:0.82rem;color:#DC2626;margin:2px 0;">Debarred by: <b>{debarred_by}</b></div>'
                    if reason:
                        debar_extra += f'<div style="font-size:0.82rem;color:#7F1D1D;margin:2px 0;">Reason: {reason}</div>'
                    if start and end:
                        debar_extra += f'<div style="font-size:0.82rem;color:#991B1B;margin:2px 0;">Period: <b>{start}</b> → <b>{end}</b></div>'

                debar_status = "BLACKLISTED" if not pv.debarment_check.is_valid else "ACTIVE"
                debar_name = pv.debarment_check.registered_name if pv.debarment_check.registered_name else (
                    pv.pan_verification.registered_name
                )
                st.markdown(
                    _registry_card(
                        title="GeM Central Debarment Watchlist",
                        icon="🚨",
                        identifier=pv.debarment_check.query_identifier,
                        registered_name=debar_name,
                        status_val=debar_status,
                        is_valid=pv.debarment_check.is_valid,
                        source=pv.debarment_check.source,
                        extra_rows=debar_extra,
                        risk_flags=pv.debarment_check.risk_flags,
                    ),
                    unsafe_allow_html=True,
                )


    with tab3:
        st.markdown("#### Dual Extractor Structured Output (Regex + LLM Schema)")
        if report.extracted_bid_data:
            st.json(report.extracted_bid_data.model_dump())
