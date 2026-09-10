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
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

# Add current directory to path so app modules can be imported directly
CURRENT_DIR = Path(__file__).resolve().parent
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
    get_all_bidders_summary,
    get_audit_logs,
    get_documents_by_bidder,
    get_submitted_bidders,
    init_db,
    save_uploaded_document,
    submit_bidder_documents,
    update_bidder_status,
)
from app.extract import ExtractedBidData, extract_bid_information
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

col_sel, col_refresh = st.columns([3, 1])

with col_refresh:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Submissions", use_container_width=True):
        st.rerun()

selected_bidder_id: Optional[str] = None

with col_sel:
    if not all_bidders:
        st.warning("⚠️ No bidder submissions found in `bidder_documents.db`. Please open the Bidder Portal (`bidder_dashboard.py`) or pre-fill a demo submission below.")
        if st.button("🚀 Load Sample Alpha Tech Bid into Database", use_container_width=True):
            # Pre-load demo documents directly into SQLite
            from app.db import save_uploaded_document, submit_bidder_documents
            demo_bidder = "BID-2024-ALPHA"
            sample_docs = {
                ("Statutory / registration documents", "Udyam Registration Certificate"): (
                    "udyam_certificate.txt",
                    b"UDYAM REGISTRATION CERTIFICATE\nUdyam Registration Number: UDYAM-MH-01-0012345\nName of Enterprise: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nType: Micro Enterprise\nStatus: ACTIVE\nMajor Activity: Manufacturing\nDate: 15-08-2020",
                ),
                ("Statutory / registration documents", "GST Registration Certificate"): (
                    "gst_registration.txt",
                    b"GOVERNMENT OF INDIA - GST REGISTRATION CERTIFICATE\nRegistration Number (GSTIN): 27AABCA1234F1Z5\nLegal Name: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nTrade Name: Alpha Tech Solutions\nConstitution: Private Limited Company\nStatus: ACTIVE\nFiling Status: UP TO DATE",
                ),
                ("Statutory / registration documents", "PAN Card"): (
                    "pan_card.txt",
                    b"INCOME TAX DEPARTMENT - GOVT OF INDIA\nPermanent Account Number: AABCA1234F\nName: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nCategory: Company\nDate of Incorporation: 12/04/2018\nStatus: ACTIVE",
                ),
                ("Statutory / registration documents", "Certificate of Incorporation (MCA)"): (
                    "mca_incorporation.txt",
                    b"MINISTRY OF CORPORATE AFFAIRS - ROC MUMBAI\nCertificate of Incorporation pursuant to Section 7(2) of the Companies Act 2013\nCorporate Identity Number (CIN): U72200MH2018PTC308912\nCompany Name: ALPHA TECH SOLUTIONS PRIVATE LIMITED\nCompany Status: ACTIVE (Not Struck Off)",
                ),
                ("Statutory / registration documents", "Income Tax Returns"): (
                    "itr_3_years.txt",
                    b"INCOME TAX DEPARTMENT - ACKNOWLEDGMENT ITR-V\nAssessment Year 2022-23: Ack No 442981023912\nAssessment Year 2023-24: Ack No 881290312904\nAssessment Year 2024-25: Ack No 992109412095\nFiling Status: Successfully Verified for last 3 Assessment Years.",
                ),
                ("Statutory / registration documents", "EPFO/ESIC registration certificate"): (
                    "epfo_esic_cert.txt",
                    b"EMPLOYEES PROVIDENT FUND ORGANISATION (EPFO)\nEstablishment Code: MH/BAN/0048192\nESIC 17-digit Registration: 31000492810001001\nStatus: Registered and active statutory employee contributions.",
                ),
                ("Financial documents", "Audited financial statement / turnover certificate"): (
                    "turnover_certificate.txt",
                    b"CHARTERED ACCOUNTANT TURNOVER CERTIFICATE\nUDIN: 24045129BCA99182\nTurnover FY 2021-22: INR 45.00 Lakhs\nTurnover FY 2022-23: INR 55.00 Lakhs\nTurnover FY 2023-24: INR 65.00 Lakhs\nAverage Annual Turnover (last 3 FYs): INR 55.00 Lakhs.\nAudited Balance Sheets and P&L attached.",
                ),
                ("Financial documents", "EMD proof"): (
                    "emd_proof.txt",
                    b"EMD EXEMPTION CLAIM UNDER PUBLIC PROCUREMENT POLICY FOR MSEs\nUdyam Registration: UDYAM-MH-01-0012345\nEnterprise Category: Micro Enterprise\n100% EMD waiver claimed in accordance with GeM GTC clause 4(m).",
                ),
                ("Eligibility exemption / preference documents", "Make in India / local content self-declaration"): (
                    "mii_declaration.txt",
                    b"MAKE IN INDIA (MII) LOCAL CONTENT SELF-DECLARATION\nTender Ref: GEM/2024/B/4568912\nWe hereby certify that the Local Value Addition / Content for the offered product is 65.0%.\nClassification: Class-I Local Supplier\nManufacturing Plant: MIDC Industrial Area, Pune, Maharashtra.",
                ),
                ("Technical / product-specific documents", "OEM authorization letter"): (
                    "oem_authorization.txt",
                    b"MANUFACTURER AUTHORIZATION FORM (MAF)\nTender Reference: GEM/2024/B/4568912\nWe hereby authorize M/s Alpha Tech Solutions Private Limited to quote and deliver high-performance workstations with full 3-year onsite OEM warranty.",
                ),
                ("Technical / product-specific documents", "BIS certification / quality certificate"): (
                    "bis_iso_cert.txt",
                    b"BUREAU OF INDIAN STANDARDS (BIS) & ISO CERTIFICATION\nBIS Registration: CM/L-7891204\nISO Standard: ISO 9001:2015 Quality Management System\nValidity: Unexpired, valid up to 2027.",
                ),
                ("Technical / product-specific documents", "Product technical specification sheet/brochure"): (
                    "tech_specs_brochure.txt",
                    b"TECHNICAL SPECIFICATION SCHEDULE & PRODUCT BROCHURE\nTender: Supply of High-Performance Computing Workstations\nOffered Model: ProWorkstation Alpha-900\nProcessor: 32-Core Enterprise CPU\nRAM: 128GB ECC DDR5\nStorage: 2TB NVMe PCIe 4.0\nCompliance: Fully compliant with tender technical schedule without deviation.",
                ),
                ("Technical / product-specific documents", "Past performance / experience certificate"): (
                    "past_performance.txt",
                    b"CLIENT PERFORMANCE & EXPERIENCE CERTIFICATES\nYears in relevant business: 6 Years\nCompleted Government Supply Orders: 14 completed contracts\nCumulative Order Value: INR 120.00 Lakhs.\nSatisfactory performance certificates attached from DRDO, IIT, and CSIR.",
                ),
                ("Compliance / background documents", "Self-declaration of non-blacklisting"): (
                    "non_blacklisting.txt",
                    b"UNDERTAKING & SELF-DECLARATION OF NON-BLACKLISTING\nWe, Alpha Tech Solutions Private Limited, solemnly affirm that our firm has never been blacklisted, debarred, or suspended by Government e-Marketplace (GeM), Central/State Ministries, or PSUs.\nSigned: Authorized Signatory\nDate: Current Date",
                ),
            }
            for (cat, doc_type), (fname, fbytes) in sample_docs.items():
                save_uploaded_document(demo_bidder, cat, doc_type, fname, fbytes)
            submit_bidder_documents(demo_bidder)
            st.success(f"Loaded demo submission for `{demo_bidder}`! Refreshing...")
            st.rerun()
    else:
        # Build options list
        options = []
        for b in all_bidders:
            status_text = b["overall_status"].upper()
            options.append(f"{b['bidder_id']}  ({b['document_count']} docs | Status: {status_text})")

        selected_option = st.selectbox(
            "Select Submitted Bidder for Evaluation:",
            options=options,
            index=0,
            help="Choose a candidate bidder from SQLite documents table",
        )
        if selected_option:
            selected_bidder_id = selected_option.split("  (")[0].strip()

# -----------------------------------------------------------------------------
# Per-Document Ingestion & Execution Pipeline
# -----------------------------------------------------------------------------
if selected_bidder_id:
    bidder_docs = get_documents_by_bidder(selected_bidder_id)
    
    # Read files from disk and run OCR / Text extraction
    docs_text_map: Dict[str, str] = {}
    docs_record_map: Dict[str, Dict[str, Any]] = {}
    combined_texts: List[str] = []

    for doc in bidder_docs:
        doc_type = doc["document_type"]
        filepath = Path(doc["filepath"])
        raw_text = ""
        if filepath.is_file():
            try:
                fbytes = filepath.read_bytes()
                ocr_res = extract_text_from_document(fbytes, doc["filename"])
                raw_text = ocr_res.raw_text
            except Exception as e:
                raw_text = f"Error reading document: {e}"
        docs_text_map[doc_type] = raw_text
        docs_record_map[doc_type] = doc
        if raw_text:
            combined_texts.append(raw_text)

    # Extract global structured entity schema
    full_text = "\n\n".join(combined_texts)
    bid_data = extract_bid_information(full_text)

    # Evaluate all 14 document types against criteria & portal registry
    evaluator = GeMClauseEvaluator()
    clause_results = evaluator.evaluate_all_documents(
        docs_by_type=docs_text_map,
        criteria=criteria,
        bid_data=bid_data,
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

            # Check if file was uploaded
            uploaded_rec = docs_record_map.get(dt)
            evidence_prefix = f"[{uploaded_rec['filename']}] " if uploaded_rec else ""
            evidence = f"{evidence_prefix}{c.remarks}"

            rows.append({
                "Document Type": dt,
                "Status": status_display,
                "Evidence / Reason": evidence,
                "Confidence": f"{int(c.confidence * 100)}%",
            })

        df_cat = pd.DataFrame(rows)
        st.dataframe(df_cat, use_container_width=True, hide_index=True)

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
            doc_meta.append({
                "Category": d["category"],
                "Document Type": d["document_type"],
                "File Name": d["filename"],
                "File Path": d["filepath"],
                "Uploaded At": d["uploaded_at"],
                "Status": d["status"].upper(),
            })
        st.dataframe(pd.DataFrame(doc_meta), use_container_width=True, hide_index=True)

    with tab2:
        st.markdown("#### Live Verification from Statutory Registries (API Setu)")
        pv = report.portal_verification
        if pv:
            st.info(f"**Verification Gateway:** `{pv.gateway_provider}` • Connected to Government of India Open API Platform (`apisetu.gov.in`) with automated fallback.")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f"""
                    <div class="kpi-card" style="margin-bottom: 12px;">
                        <div class="kpi-label">Income Tax Department (PAN)</div>
                        <div class="kpi-value" style="font-size: 1.1rem;">{pv.pan_verification.query_identifier}</div>
                        <div>Status: <b>{pv.pan_verification.status.value}</b></div>
                        <div>Name: {pv.pan_verification.registered_name or 'N/A'}</div>
                        <div style="margin-top: 6px; font-size: 0.75rem; color: #2563EB;"><b>Source:</b> {pv.pan_verification.source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"""
                    <div class="kpi-card">
                        <div class="kpi-label">MSME Udyam Portal</div>
                        <div class="kpi-value" style="font-size: 1.1rem;">{pv.udyam_verification.query_identifier}</div>
                        <div>Status: <b>{pv.udyam_verification.status.value}</b></div>
                        <div>Enterprise: {pv.udyam_verification.registered_name or 'N/A'}</div>
                        <div style="margin-top: 6px; font-size: 0.75rem; color: #2563EB;"><b>Source:</b> {pv.udyam_verification.source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f"""
                    <div class="kpi-card" style="margin-bottom: 12px;">
                        <div class="kpi-label">GSTN Taxpayer Registry</div>
                        <div class="kpi-value" style="font-size: 1.1rem;">{pv.gstin_verification.query_identifier}</div>
                        <div>Status: <b>{pv.gstin_verification.status.value}</b></div>
                        <div>Legal Name: {pv.gstin_verification.registered_name or 'N/A'}</div>
                        <div style="margin-top: 6px; font-size: 0.75rem; color: #2563EB;"><b>Source:</b> {pv.gstin_verification.source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"""
                    <div class="kpi-card">
                        <div class="kpi-label">GeM Debarment Watchlist</div>
                        <div class="kpi-value" style="font-size: 1.1rem;">{pv.debarment_check.query_identifier}</div>
                        <div>Blacklist Status: <b>{'BLACKLISTED' if not pv.debarment_check.is_valid else 'CLEAN (ACTIVE)'}</b></div>
                        <div style="margin-top: 6px; font-size: 0.75rem; color: #2563EB;"><b>Source:</b> {pv.debarment_check.source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with tab3:
        st.markdown("#### Dual Extractor Structured Output (Regex + LLM Schema)")
        if report.extracted_bid_data:
            st.json(report.extracted_bid_data.model_dump())
