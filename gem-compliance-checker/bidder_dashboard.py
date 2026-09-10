"""Streamlit Bidder-Side Document Upload Portal for GeM Compliance Verification (SIH 26100).

Provides an interactive user interface for bidders / vendors to:
- Enter Bidder ID / Bid Reference Number
- Upload required documents categorized across Statutory, Financial, Preference, Technical, and Compliance
- Inspect real-time upload progress and document metadata
- Submit documents to the shared SQLite database (bidder_documents.db) for Officer verification
"""

from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

# Add current directory to path so app modules can be imported directly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import DOCUMENT_CATEGORIES
from app.db import (
    get_documents_by_bidder,
    init_db,
    save_uploaded_document,
    submit_bidder_documents,
)

# Auto-detect bare python execution (e.g. VS Code 'Run/Debug' or `python bidder_dashboard.py`)
# and automatically bootstrap the Streamlit server runner.
try:
    from streamlit.runtime import exists as _st_runtime_exists
    _is_in_streamlit = _st_runtime_exists()
except Exception:
    _is_in_streamlit = False

if not _is_in_streamlit:
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve()), "--server.port=8502"]
    sys.exit(stcli.main())

# Page configuration
st.set_page_config(
    page_title="Bidder Document Submission Portal | GeM SIH 26100",
    page_icon="📤",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling - Modern Enterprise Light Theme matching officer dashboard
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

    /* Category Cards */
    .cat-header {
        background: #FFFFFF;
        padding: 12px 16px;
        border-radius: 8px;
        border: 1px solid #E2E8F0;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .cat-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1E293B;
    }
    .cat-badge {
        background-color: #F1F5F9;
        color: #475569;
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 6px;
        font-weight: 600;
    }

    /* Status Pills */
    .status-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
    }
    .status-pending {
        background-color: #FEF3C7;
        color: #92400E;
    }
    .status-submitted {
        background-color: #DBEAFE;
        color: #1E40AF;
    }
    .status-verified {
        background-color: #DCFCE7;
        color: #166534;
    }
    .status-flagged {
        background-color: #FEE2E2;
        color: #991B1B;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize DB on load
init_db()

# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/5/55/Emblem_of_India.svg", width=60)
    st.markdown("### GeM Bidder Portal")
    st.caption("Document Ingestion & Pre-Submission Desk")

    st.markdown("---")
    st.markdown("#### 🔄 Role Navigation")
    st.info("You are currently in the **Bidder-Side Portal**.")
    st.markdown(
        """
        - **Procurement Officer?** Open the Officer Evaluation Dashboard at:
          `http://localhost:8501`
        - Or run:
          ```bash
          streamlit run gem-compliance-checker/dashboard.py
          ```
        """
    )

    st.markdown("---")
    st.markdown("#### 📋 Submission Guidelines")
    st.markdown(
        """
        - Allowed file formats: **PDF, PNG, JPG**
        - Ensure documents are clearly readable.
        - Click **'Submit for Verification'** once all categories are uploaded.
        """
    )


# -----------------------------------------------------------------------------
# Main Application Header
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="gov-badge">
        <span class="gov-badge-dot"></span>
        Government e-Marketplace (GeM) • Vendor Document Upload Desk
    </div>
    <div class="main-title">Bidder Document Submission Portal</div>
    <div class="sub-title">Upload statutory credentials, financial statements, and technical schedules for tender evaluation.</div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Bidder ID Input and Preset Demo Quick-Fills
# -----------------------------------------------------------------------------
col_input, col_demo = st.columns([2, 1])

with col_input:
    bidder_id = st.text_input(
        "Enter Bidder ID / Bid Reference Number:",
        value=st.session_state.get("bidder_id", "BID-2024-ALPHA"),
        help="Unique identifier for the bidding entity or GeM bid submission (e.g., BID-2024-ALPHA or GEM/2024/B/4568912)",
    ).strip().upper()
    st.session_state["bidder_id"] = bidder_id

with col_demo:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("🚀 Pre-fill Demo Bidder Documents", use_container_width=True, help="Auto-loads sample compliant credentials for fast testing"):
        demo_bidder = bidder_id or "BID-2024-ALPHA"
        # Create standard mock attachments
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
            save_uploaded_document(
                bidder_id=demo_bidder,
                category=cat,
                document_type=doc_type,
                filename=fname,
                file_bytes=fbytes,
            )
        st.success(f"Successfully loaded all 14 sample documents for `{demo_bidder}`! You can now submit below.")
        st.rerun()

st.markdown("---")

# -----------------------------------------------------------------------------
# Collapsible Upload Sections across 5 Categories
# -----------------------------------------------------------------------------
st.markdown("### Document Submission Checklist")
st.caption("Upload your credentials into the corresponding categories below. Formats accepted: **PDF, PNG, JPG**.")

# Fetch currently uploaded docs for this bidder to show indicators
current_docs = get_documents_by_bidder(bidder_id) if bidder_id else []
uploaded_map = {d["document_type"]: d for d in current_docs}

for cat_idx, (category_name, doc_types) in enumerate(DOCUMENT_CATEGORIES.items(), 1):
    # Calculate how many docs in this category are uploaded
    cat_uploaded = sum(1 for dt in doc_types if dt in uploaded_map)
    total_in_cat = len(doc_types)

    # Category Expander
    expander_title = f"{category_name} ({cat_uploaded}/{total_in_cat} uploaded)"
    with st.expander(expander_title, expanded=(cat_idx <= 2)):
        st.markdown(f"#### {category_name}")
        
        # Grid of uploaders
        for doc_type in doc_types:
            col1, col2 = st.columns([3, 1])
            with col1:
                uploaded_file = st.file_uploader(
                    f"📄 {doc_type}:",
                    type=["pdf", "png", "jpg", "jpeg", "txt"],
                    key=f"upload_{bidder_id}_{doc_type}",
                )
                if uploaded_file is not None:
                    file_bytes = uploaded_file.read()
                    save_uploaded_document(
                        bidder_id=bidder_id,
                        category=category_name,
                        document_type=doc_type,
                        filename=uploaded_file.name,
                        file_bytes=file_bytes,
                    )
                    st.success(f"Uploaded `{uploaded_file.name}` for `{doc_type}`.")
                    st.rerun()

            with col2:
                if doc_type in uploaded_map:
                    rec = uploaded_map[doc_type]
                    st.markdown(f"<div style='margin-top: 32px;'><b>✅ Uploaded:</b><br><small>{rec['filename']}</small></div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div style='margin-top: 32px; color: #94A3B8;'><i>Pending upload</i></div>", unsafe_allow_html=True)

            st.markdown("<hr style='margin: 8px 0; border-top: 1px dashed #E2E8F0;'>", unsafe_allow_html=True)

st.markdown("---")

# -----------------------------------------------------------------------------
# Upload Summary Table & Submission Action
# -----------------------------------------------------------------------------
st.markdown("### Submission Summary & Dispatch")

refreshed_docs = get_documents_by_bidder(bidder_id) if bidder_id else []

if not refreshed_docs:
    st.info(f"No documents uploaded yet for Bidder ID `{bidder_id}`. Upload documents in the sections above or use 'Pre-fill Demo Bidder Documents'.")
else:
    # Build display table
    table_data = []
    for d in refreshed_docs:
        status_val = d["status"]
        badge_class = f"status-{status_val}"
        table_data.append({
            "Category": d["category"],
            "Document Type": d["document_type"],
            "Filename": d["filename"],
            "Uploaded At": d["uploaded_at"],
            "Status": status_val.upper(),
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    col_sub1, col_sub2 = st.columns([2, 1])
    with col_sub1:
        total_docs = len(refreshed_docs)
        submitted_docs = sum(1 for d in refreshed_docs if d["status"] in ("submitted", "verified", "flagged"))
        st.write(f"Total Uploaded Documents: **{total_docs}** | Submitted: **{submitted_docs}**")

    with col_sub2:
        if st.button("📤 Submit for Verification", type="primary", use_container_width=True):
            updated_count = submit_bidder_documents(bidder_id)
            st.success(f"Successfully submitted {updated_count} document(s) for Bidder ID `{bidder_id}`! The Procurement Officer can now review this bid on the Officer Dashboard.")
            st.balloons()
            st.rerun()
