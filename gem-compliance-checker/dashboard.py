"""Streamlit Evaluation Dashboard for GeM Bid Compliance Engine (SIH 26100).

Provides an interactive user interface for procurement officers to:
- Upload PDF / TXT bid documents
- Configure tender qualification criteria (turnover, experience, MII %)
- Run automated end-to-end verification
- Inspect the interactive 5-Clause Compliance Matrix
- Review cross-checked government portal records (PAN, GSTIN, Udyam, Debarment)
"""

import json
from pathlib import Path
import sys
from typing import Optional

import requests
import streamlit as st

# Add current directory to path so app modules can be imported directly
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from app.clauses import ClauseResult, ClauseStatus, GeMClauseEvaluator, TenderCriteria
from app.extract import ExtractedBidData, extract_bid_information
from app.mock_portals import EntityFullVerification, MockPortalRegistry
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
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    sys.exit(stcli.main())

# Page configuration
st.set_page_config(
    page_title="GeM Bid Compliance Engine | SIH 26100",
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
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stCaption {
        color: #475569 !important;
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

    /* Main Title & Subtitle */
    .main-title {
        font-size: 2.15rem;
        font-weight: 800;
        color: #0F294A !important;
        letter-spacing: -0.025em;
        margin-bottom: 0.25rem;
        line-height: 1.2;
    }
    .sub-title {
        font-size: 1rem;
        color: #475569 !important;
        margin-bottom: 1.5rem;
        line-height: 1.5;
    }

    /* Streamlit Native Metric Cards & KPI Cards */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        padding: 16px 18px !important;
        box-shadow: 0 1px 3px 0 rgba(15, 23, 42, 0.05) !important;
        transition: all 0.2s ease-in-out;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #CBD5E1 !important;
        box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.07) !important;
    }
    div[data-testid="stMetricLabel"] p {
        color: #64748B !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    div[data-testid="stMetricValue"] {
        color: #0F172A !important;
        font-size: 1.7rem !important;
        font-weight: 800 !important;
    }

    /* Unified KPI Card (for m2 and custom widgets) */
    .kpi-card {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        padding: 16px 18px !important;
        box-shadow: 0 1px 3px 0 rgba(15, 23, 42, 0.05) !important;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        transition: all 0.2s ease-in-out;
    }
    .kpi-card:hover {
        border-color: #CBD5E1 !important;
        box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.07) !important;
    }
    .kpi-label {
        font-size: 0.8rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 6px;
    }
    .kpi-caption {
        font-size: 0.75rem;
        color: #64748B;
        margin-top: 6px;
    }

    /* Light Theme Semantic Status Badges */
    .badge-compliant {
        display: inline-flex;
        align-items: center;
        background-color: #ECFDF5;
        border: 1px solid #A7F3D0;
        color: #065F46;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.88rem;
        letter-spacing: 0.02em;
    }
    .badge-conditional {
        display: inline-flex;
        align-items: center;
        background-color: #FFFBEB;
        border: 1px solid #FDE68A;
        color: #92400E;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.88rem;
        letter-spacing: 0.02em;
    }
    .badge-disqualified {
        display: inline-flex;
        align-items: center;
        background-color: #FEF2F2;
        border: 1px solid #FECACA;
        color: #991B1B;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.88rem;
        letter-spacing: 0.02em;
    }

    /* Portal Verification Card */
    .portal-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 1px 2px 0 rgba(15, 23, 42, 0.04);
    }
    .portal-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-weight: 700;
        color: #0F294A;
        font-size: 0.95rem;
        margin-bottom: 10px;
        border-bottom: 1px solid #F1F5F9;
        padding-bottom: 8px;
    }
    .portal-pill {
        font-size: 0.78rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 6px;
    }
    .portal-pill-active {
        background-color: #ECFDF5;
        color: #065F46;
        border: 1px solid #A7F3D0;
    }
    .portal-pill-warning {
        background-color: #FFFBEB;
        color: #92400E;
        border: 1px solid #FDE68A;
    }
    .portal-pill-danger {
        background-color: #FEF2F2;
        color: #991B1B;
        border: 1px solid #FECACA;
    }

    /* Recommendation Card */
    .rec-card {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #1E40AF;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
        box-shadow: 0 1px 2px 0 rgba(15, 23, 42, 0.04);
    }
    .rec-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 24px;
        height: 24px;
        background-color: #EFF6FF;
        color: #1E40AF;
        font-weight: 700;
        font-size: 0.8rem;
        border-radius: 50%;
    }
    .rec-text {
        font-size: 0.92rem;
        color: #1E293B;
        line-height: 1.5;
    }

    /* Buttons Styling */
    div[data-testid="stButton"] button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        transition: all 0.15s ease !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        color: #1E293B !important;
        box-shadow: 0 1px 2px 0 rgba(15, 23, 42, 0.04) !important;
    }
    div[data-testid="stButton"] button[kind="secondary"]:hover {
        background-color: #F8FAFC !important;
        border-color: #94A3B8 !important;
        color: #0F172A !important;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #1E40AF 0%, #2563EB 100%) !important;
        border: none !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 4px rgba(37, 99, 235, 0.25) !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background: linear-gradient(135deg, #1D4ED8 0%, #1E40AF 100%) !important;
        box-shadow: 0 4px 8px rgba(37, 99, 235, 0.35) !important;
    }

    /* Tabs Styling */
    button[data-baseweb="tab"] {
        background-color: transparent !important;
        color: #475569 !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        padding: 10px 18px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #1E40AF !important;
        border-bottom: 2px solid #1E40AF !important;
    }

    /* Expander Container */
    div[data-testid="stExpander"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 2px 0 rgba(15, 23, 42, 0.04) !important;
    }

    /* Dataframe / Table container */
    div[data-testid="stDataFrame"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_sample_bid_text() -> str:
    """Load default sample bid submission text from disk."""
    sample_path = CURRENT_DIR / "sample_data" / "sample_bid_text.txt"
    if sample_path.exists():
        return sample_path.read_text(encoding="utf-8")
    return "Sample bid text file not found."


def run_direct_pipeline(
    raw_text: str,
    criteria: TenderCriteria,
) -> ComplianceReport:
    """Run verification directly in-process without requiring a running FastAPI server."""
    bid_data: ExtractedBidData = extract_bid_information(raw_text)
    registry = MockPortalRegistry()
    verification: EntityFullVerification = registry.verify_all(
        pan=bid_data.identifiers.pan,
        gstin=bid_data.identifiers.gstin,
        udyam=bid_data.identifiers.udyam,
    )
    evaluator = GeMClauseEvaluator()
    clauses = evaluator.evaluate_all(bid_data, verification, criteria)
    return ScoringEngine.generate_report(bid_data, verification, clauses)


def run_api_pipeline(
    raw_text: str,
    criteria: TenderCriteria,
    api_url: str = "http://localhost:8000/verify-bid",
) -> Optional[ComplianceReport]:
    """Execute pipeline via FastAPI REST endpoint."""
    payload = {
        "raw_bid_text": raw_text,
        "criteria": criteria.model_dump(),
    }
    try:
        response = requests.post(api_url, json=payload, timeout=10)
        if response.status_code == 200:
            return ComplianceReport(**response.json())
        st.error(f"API Error ({response.status_code}): {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        st.warning(f"Could not connect to FastAPI server at {api_url}. Falling back to direct in-process execution.")
        return run_direct_pipeline(raw_text, criteria)


# -----------------------------------------------------------------------------
# Sidebar Configuration
# -----------------------------------------------------------------------------
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/5/55/Emblem_of_India.svg", width=60)
    st.markdown("### Tender Evaluation Criteria")
    st.caption("Configure buyer qualification thresholds:")

    tender_turnover = st.number_input(
        "Min Turnover (INR Lakhs)",
        min_value=1.0,
        max_value=1000.0,
        value=30.0,
        step=5.0,
        help="Clause 2 threshold",
    )
    tender_exp = st.slider(
        "Min Past Experience (Years)",
        min_value=0,
        max_value=15,
        value=2,
        help="Clause 3 threshold",
    )
    tender_orders = st.number_input(
        "Min Completed Orders",
        min_value=1,
        max_value=20,
        value=1,
        help="Clause 3 order requirement",
    )
    tender_mii = st.slider(
        "Min Make in India Local Content (%)",
        min_value=10,
        max_value=100,
        value=50,
        step=5,
        help="Clause 4 threshold for Class-I Local Supplier",
    )
    require_emd = st.checkbox("Require EMD (MSE exempt)", value=True)

    criteria = TenderCriteria(
        tender_id="GEM/2024/B/4568912",
        title="Supply of High-Performance Computing Workstations",
        required_turnover_lakhs=float(tender_turnover),
        min_experience_years=int(tender_exp),
        min_completed_orders=int(tender_orders),
        min_local_content_pct=float(tender_mii),
        require_emd=require_emd,
    )

    st.markdown("---")
    st.markdown("### Execution Backend")
    exec_mode = st.radio(
        "Pipeline Mode",
        options=["Direct In-Process (Fast)", "FastAPI REST Server"],
        index=0,
    )
    api_endpoint = "http://localhost:8000/verify-bid"


# -----------------------------------------------------------------------------
# Main Application Header
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="gov-badge">
        <span class="gov-badge-dot"></span>
        Government e-Marketplace (GeM) • SIH 26100 AI Compliance Engine
    </div>
    <div class="main-title">GeM Bid Compliance & Document Verification Engine</div>
    <div class="sub-title">Automated AI compliance verification, statutory registry cross-checks, and 5-clause deterministic evaluation for Smart India Hackathon (SIH 26100).</div>
    """,
    unsafe_allow_html=True,
)

# Test Scenario Presets
col_preset1, col_preset2, col_preset3 = st.columns(3)
with col_preset1:
    if st.button("🟢 Load Compliant Bid (Alpha Tech)", use_container_width=True):
        st.session_state["bid_content"] = load_sample_bid_text()
with col_preset2:
    if st.button("🟡 Load Deficient Bid (Beta Infra)", use_container_width=True):
        st.session_state["bid_content"] = (
            "================ GeM BID SUBMISSION ================\n"
            "BID NUMBER: GEM/2024/B/778899\n"
            "Legal Business Name: Beta Infra Projects Limited\n"
            "PAN: AAACB5678K\n"
            "GSTIN: 07AAACB5678K1Z2\n"
            "Udyam Registration Number: UDYAM-DL-02-0054321\n"
            "Claiming Exemption: YES\n"
            "Average Annual Turnover: 13.67 Lakhs\n"
            "Years of Relevant Experience: 3 Years\n"
            "Local Content Percentage: 45.0%\n"
            "Classification: Class-II Local Supplier\n"
            "Integrity: Affirmation provided.\n"
        )
with col_preset3:
    if st.button("🔴 Load Fraudulent Bid (Gamma Trading)", use_container_width=True):
        st.session_state["bid_content"] = (
            "================ GeM BID SUBMISSION ================\n"
            "BID NUMBER: GEM/2024/B/999111\n"
            "Legal Business Name: Gamma Fraudulent Trading Co\n"
            "PAN: XYZPG9999Z\n"
            "GSTIN: 06XYZPG9999Z1ZX\n"
            "Udyam Registration Number: UDYAM-HR-03-0099999\n"
            "Claiming Exemption: YES\n"
            "Average Annual Turnover: 0.0 Lakhs\n"
            "Years of Relevant Experience: 1 Years\n"
            "Local Content Percentage: 10.0%\n"
            "Classification: Non-Local Supplier\n"
            "Integrity: False affirmation.\n"
        )

# Upload File or Use Text
uploaded_file = st.file_uploader(
    "Or upload a bid document (PDF, TXT, or Image):",
    type=["pdf", "txt", "png", "jpg"],
)

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    ocr_result = extract_text_from_document(file_bytes, uploaded_file.name)
    st.session_state["bid_content"] = ocr_result.raw_text
    st.info(f"Ingested `{uploaded_file.name}` via {ocr_result.extraction_method} ({ocr_result.page_count} page(s)).")

# Document Text Preview
current_text = st.session_state.get("bid_content", load_sample_bid_text())
with st.expander("📄 Review Ingested Bid Document Text", expanded=False):
    edited_text = st.text_area("Bid Document Content", value=current_text, height=220)
    st.session_state["bid_content"] = edited_text

# Verification Trigger
col_btn, col_info = st.columns([1, 3])
with col_btn:
    run_btn = st.button("🚀 Verify Bid Compliance", type="primary", use_container_width=True)

report: Optional[ComplianceReport] = None
if run_btn:
    with st.spinner("Executing extraction, registry verification, and clause evaluation..."):
        if "FastAPI" in exec_mode:
            report = run_api_pipeline(st.session_state["bid_content"], criteria, api_endpoint)
        else:
            report = run_direct_pipeline(st.session_state["bid_content"], criteria)
        st.session_state["last_report"] = report

if "last_report" in st.session_state and st.session_state["last_report"] is not None:
    report = st.session_state["last_report"]

# -----------------------------------------------------------------------------
# Results Presentation
# -----------------------------------------------------------------------------
if report:
    st.markdown("---")
    st.subheader(f"Verification Report: {report.bidder_name}")

    # Top KPI Cards
    m1, m2, m3, m4 = st.columns(4)

    # Risk badge formatting
    if report.risk_category == RiskCategory.COMPLIANT:
        risk_html = '<span class="badge-compliant">🟢 COMPLIANT</span>'
    elif report.risk_category == RiskCategory.CONDITIONAL:
        risk_html = '<span class="badge-conditional">🟡 CONDITIONAL</span>'
    else:
        risk_html = '<span class="badge-disqualified">🔴 DISQUALIFIED</span>'

    with m1:
        st.metric("Compliance Score", f"{report.score_percentage:.1f}%")
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
        st.metric("Technical Eligibility", "ACCEPTED" if report.is_technically_eligible else "REJECTED", delta=eligibility)
    with m4:
        breakdown = report.scoring_breakdown
        st.metric(
            "Clause Results",
            f"{breakdown.passed_clauses_count} Pass / {breakdown.conditional_clauses_count} Cond / {breakdown.failed_clauses_count} Fail",
        )

    st.info(f"**Executive Briefing:** {report.executive_summary}")

    # Compliance Matrix Table
    st.markdown("### 📋 5-Clause GeM Compliance Matrix")

    table_data = []
    for c in report.clause_results:
        status_icon = "✅ PASS" if c.status == ClauseStatus.PASS else ("⚠️ CONDITIONAL" if c.status == ClauseStatus.CONDITIONAL else "❌ FAIL")
        table_data.append(
            {
                "Clause": c.clause_id,
                "Clause Name": c.clause_name,
                "Mandatory": "YES" if c.is_mandatory else "No",
                "Status": status_icon,
                "Tender Requirement": c.requirement_summary,
                "Declared by Bidder": c.declared_summary,
                "Government Verification": c.portal_findings,
                "Auditor Remarks": c.remarks,
            }
        )

    try:
        st.dataframe(table_data, use_container_width=True, hide_index=True)
    except Exception:
        # Resilient fallback if pandas / arrow encounters a local environment error
        headers = ["Clause", "Clause Name", "Mandatory", "Status", "Tender Requirement", "Declared by Bidder", "Government Verification", "Auditor Remarks"]
        header_row = "| " + " | ".join(headers) + " |"
        sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        data_rows = [
            "| " + " | ".join(str(row.get(h, "")).replace("\n", " ") for h in headers) + " |"
            for row in table_data
        ]
        st.markdown("\n".join([header_row, sep_row] + data_rows))

    tab1, tab2, tab3 = st.tabs(["🏛️ Portal Cross-Verification", "🔍 Extracted Identifiers", "📝 Action Recommendations"])

    with tab1:
        st.markdown("#### Government Registry Cross-Check Findings")
        if report.portal_verification:
            pv = report.portal_verification
            c1, c2 = st.columns(2)
            with c1:
                pan_badge_cls = "portal-pill-active" if pv.pan_verification.status.value.lower() == "active" else "portal-pill-danger"
                st.markdown(
                    f"""
                    <div class="portal-card">
                        <div class="portal-card-header">
                            <span>🏛️ Income Tax Department (PAN)</span>
                            <span class="portal-pill {pan_badge_cls}">{pv.pan_verification.status.value}</span>
                        </div>
                        <div style="font-size: 0.9rem; color: #334155; line-height: 1.6;">
                            <b>Query Identifier:</b> <code>{pv.pan_verification.query_identifier}</code><br>
                            <b>Registered Name:</b> {pv.pan_verification.registered_name or 'N/A'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if pv.pan_verification.risk_flags:
                    st.error(", ".join(pv.pan_verification.risk_flags))

                udyam_badge_cls = "portal-pill-active" if "valid" in pv.udyam_verification.status.value.lower() else "portal-pill-warning"
                st.markdown(
                    f"""
                    <div class="portal-card">
                        <div class="portal-card-header">
                            <span>🏭 Ministry of MSME (Udyam)</span>
                            <span class="portal-pill {udyam_badge_cls}">{pv.udyam_verification.status.value}</span>
                        </div>
                        <div style="font-size: 0.9rem; color: #334155; line-height: 1.6;">
                            <b>Query Identifier:</b> <code>{pv.udyam_verification.query_identifier}</code><br>
                            <b>Enterprise:</b> {pv.udyam_verification.registered_name or 'N/A'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if pv.udyam_verification.risk_flags:
                    st.warning(", ".join(pv.udyam_verification.risk_flags))

            with c2:
                gstin_badge_cls = "portal-pill-active" if pv.gstin_verification.status.value.lower() == "active" else "portal-pill-danger"
                st.markdown(
                    f"""
                    <div class="portal-card">
                        <div class="portal-card-header">
                            <span>📊 GSTN Taxpayer Portal</span>
                            <span class="portal-pill {gstin_badge_cls}">{pv.gstin_verification.status.value}</span>
                        </div>
                        <div style="font-size: 0.9rem; color: #334155; line-height: 1.6;">
                            <b>Query Identifier:</b> <code>{pv.gstin_verification.query_identifier}</code><br>
                            <b>Legal Name:</b> {pv.gstin_verification.registered_name or 'N/A'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if pv.gstin_verification.risk_flags:
                    st.warning(", ".join(pv.gstin_verification.risk_flags))

                deb_badge_cls = "portal-pill-active" if pv.debarment_check.is_valid else "portal-pill-danger"
                st.markdown(
                    f"""
                    <div class="portal-card">
                        <div class="portal-card-header">
                            <span>🛡️ GeM Central Debarment Watchlist</span>
                            <span class="portal-pill {deb_badge_cls}">{pv.debarment_check.status.value}</span>
                        </div>
                        <div style="font-size: 0.9rem; color: #334155; line-height: 1.6;">
                            <b>Query Identifier:</b> <code>{pv.debarment_check.query_identifier}</code><br>
                            <b>Debarment Status:</b> {'CLEARED (No debarment records found)' if pv.debarment_check.is_valid else 'BLACKLISTED ON GeM'}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if not pv.debarment_check.is_valid:
                    st.error("Entity is actively blacklisted on GeM!")
                else:
                    st.success("No debarment records found.")

    with tab2:
        st.markdown("#### Dual Extractor Output (Regex + LLM Schema)")
        if report.extracted_bid_data:
            st.json(report.extracted_bid_data.model_dump())

    with tab3:
        st.markdown("#### Procurement Officer Recommendations")
        for i, act in enumerate(report.recommended_actions, 1):
            st.markdown(
                f"""
                <div class="rec-card">
                    <span class="rec-number">{i}</span>
                    <span class="rec-text">{act}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

