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

# Ensure freshly modified app submodules are automatically refreshed in long-running Streamlit sessions
import importlib
for _mod_name in ["app.db", "app.clauses", "app.demo_data", "app.image_extract", "app.image_match", "app.mock_portals"]:
    if _mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[_mod_name])
        except Exception:
            pass

from app.clauses import DOCUMENT_CATEGORIES

# Only actual document credential categories are uploaded by bidders
UPLOAD_CATEGORIES = {
    cat: dtypes for cat, dtypes in DOCUMENT_CATEGORIES.items()
    if cat != "Visual identity & signatory verification"
}

import app.db
if not hasattr(app.db, "clear_extracted_images_for_bidder"):
    try:
        importlib.reload(app.db)
    except Exception:
        pass

from app.db import (
    clear_all_bidder_documents,
    clear_extracted_images_for_bidder,
    delete_document,
    get_documents_by_bidder,
    get_extracted_images,
    init_db,
    save_digilocker_document,
    save_extracted_image,
    save_uploaded_document,
    submit_bidder_documents,
)
from app.demo_data import (
    BID_PRESETS,
    generate_bidder_demo_documents,
    get_bidder_by_id,
)
from app.digilocker import (
    fetch_digilocker_document,
    generate_digilocker_consent_url,
)
from app.image_extract import extract_photo, extract_signature

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
        - Allowed file formats: **PDF, PNG, JPG, TXT**
        - Ensure documents are clearly readable.
        - You can replace or remove any uploaded document before submission.
        - Click **'Submit for Verification'** once all categories are ready.
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
# Bidder ID Input and 10-Bidder Preset Quick-Fills
# -----------------------------------------------------------------------------
preset_labels = [p["label"] for p in BID_PRESETS] + ["Custom Bidder ID..."]

col_preset, col_input, col_demo = st.columns([2.5, 1.2, 1.5])

with col_preset:
    selected_preset_label = st.selectbox(
        "Select Demo Bidder Profile:",
        options=preset_labels,
        index=0,
        help="Select any of the 10 benchmark bidder profiles to test compliance verification",
    )

is_custom = (selected_preset_label == "Custom Bidder ID...")
if not is_custom:
    matched_preset = next((p for p in BID_PRESETS if p["label"] == selected_preset_label), BID_PRESETS[0])
    default_bidder_id = matched_preset["bidder_id"]
else:
    matched_preset = None
    default_bidder_id = "CUSTOM-BIDDER"

with col_input:
    bidder_id = st.text_input(
        "Bidder ID / Ref:",
        value=default_bidder_id if not is_custom else st.session_state.get("bidder_id", "CUSTOM-BIDDER"),
        help="Unique identifier for the bidding entity or GeM bid submission",
    ).strip().upper()
    st.session_state["bidder_id"] = bidder_id

with col_demo:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    d_col1, d_col2 = st.columns(2)
    with d_col1:
        if st.button("🚀 Pre-fill Bidder Docs", use_container_width=True, help="Auto-loads benchmark credentials for the selected bidder profile"):
            target_bidder = bidder_id or (matched_preset["bidder_id"] if matched_preset else "BID-001")
            
            # Clear existing to ensure fresh state
            clear_all_bidder_documents(target_bidder)
            clear_extracted_images_for_bidder(target_bidder)

            # Generate realistic document set
            sample_docs = generate_bidder_demo_documents(target_bidder)
            if not sample_docs and matched_preset:
                sample_docs = generate_bidder_demo_documents(matched_preset["bidder_id"])

            for (cat, doc_type), (fname, fbytes) in sample_docs.items():
                save_uploaded_document(
                    bidder_id=target_bidder,
                    category=cat,
                    document_type=doc_type,
                    filename=fname,
                    file_bytes=fbytes,
                )
                if fname.lower().endswith(".pdf"):
                    photo = extract_photo(fbytes, doc_type=doc_type)
                    if photo:
                        save_extracted_image(
                            target_bidder,
                            doc_type,
                            "photo",
                            photo.to_bytes(),
                            photo.source_page,
                            photo.extraction_confidence,
                        )
                    sig = extract_signature(fbytes, doc_type=doc_type)
                    if sig:
                        save_extracted_image(
                            target_bidder,
                            doc_type,
                            "signature",
                            sig.to_bytes(),
                            sig.source_page,
                            sig.extraction_confidence,
                        )
                st.session_state[f"sig_{target_bidder}_{doc_type}"] = f"{fname}_{len(fbytes)}"
                st.session_state[f"ver_{target_bidder}_{doc_type}"] = st.session_state.get(f"ver_{target_bidder}_{doc_type}", 0) + 1

            st.success(f"Loaded {len(sample_docs)} documents for `{target_bidder}`!")
            st.rerun()

    with d_col2:
        if st.button("🗑️ Clear All Docs", use_container_width=True, help="Remove all uploaded documents for this bidder"):
            target_bidder = bidder_id or "BID-001"
            cleared = clear_all_bidder_documents(target_bidder)
            clear_extracted_images_for_bidder(target_bidder)
            for cat, dtypes in UPLOAD_CATEGORIES.items():
                for dt in dtypes:
                    st.session_state.pop(f"sig_{target_bidder}_{dt}", None)
                    st.session_state[f"ver_{target_bidder}_{dt}"] = st.session_state.get(f"ver_{target_bidder}_{dt}", 0) + 1
            st.warning(f"Cleared {cleared} document(s) for `{target_bidder}`.")
            st.rerun()

if matched_preset:
    st.info(f"🏢 **{matched_preset['company_name']}** ({matched_preset['category']}) — Expected: **{matched_preset['badge']}** | 📝 *{matched_preset['notes']}*")

st.markdown("---")

# -----------------------------------------------------------------------------
# Collapsible Upload Sections across 5 Categories
# -----------------------------------------------------------------------------
st.markdown("### Document Submission Checklist")
st.caption("Upload your credentials into the corresponding categories below. To change an existing document, choose a new file or click 'Remove'.")

# Fetch currently uploaded docs for this bidder to show indicators
current_docs = get_documents_by_bidder(bidder_id) if bidder_id else []
uploaded_map = {d["document_type"]: d for d in current_docs}
extracted_visuals = get_extracted_images(bidder_id) if bidder_id else []

for cat_idx, (category_name, doc_types) in enumerate(UPLOAD_CATEGORIES.items(), 1):
    # Calculate how many docs in this category are uploaded
    cat_uploaded = sum(1 for dt in doc_types if dt in uploaded_map)
    total_in_cat = len(doc_types)

    # Category Expander
    expander_title = f"{category_name} ({cat_uploaded}/{total_in_cat} uploaded)"
    with st.expander(expander_title, expanded=(cat_idx <= 2 or cat_uploaded > 0)):
        st.markdown(f"#### {category_name}")
        
        # Grid of uploaders
        for doc_type in doc_types:
            is_uploaded = doc_type in uploaded_map
            rec = uploaded_map.get(doc_type)
            ver = st.session_state.get(f"ver_{bidder_id}_{doc_type}", 0)
            uploader_key = f"uploader_{bidder_id}_{doc_type}_{ver}"

            col1, col2 = st.columns([3, 1.2])
            with col1:
                uploader_label = f"📄 {doc_type}" + (" *(Select new file to replace current)*" if is_uploaded else ":")
                uploaded_file = st.file_uploader(
                    uploader_label,
                    type=["pdf", "png", "jpg", "jpeg", "txt"],
                    key=uploader_key,
                )
                if uploaded_file is not None:
                    file_bytes = uploaded_file.getvalue()
                    current_sig = f"{uploaded_file.name}_{len(file_bytes)}"
                    last_sig = st.session_state.get(f"sig_{bidder_id}_{doc_type}")

                    if current_sig != last_sig:
                        save_uploaded_document(
                            bidder_id=bidder_id,
                            category=category_name,
                            document_type=doc_type,
                            filename=uploaded_file.name,
                            file_bytes=file_bytes,
                        )
                        if uploaded_file.name.lower().endswith(".pdf"):
                            photo = extract_photo(file_bytes, doc_type=doc_type)
                            if photo:
                                save_extracted_image(
                                    bidder_id,
                                    doc_type,
                                    "photo",
                                    photo.to_bytes(),
                                    photo.source_page,
                                    photo.extraction_confidence,
                                )
                            sig = extract_signature(file_bytes, doc_type=doc_type)
                            if sig:
                                save_extracted_image(
                                    bidder_id,
                                    doc_type,
                                    "signature",
                                    sig.to_bytes(),
                                    sig.source_page,
                                    sig.extraction_confidence,
                                )
                        st.session_state[f"sig_{bidder_id}_{doc_type}"] = current_sig
                        st.toast(f"✅ Successfully updated {doc_type} with '{uploaded_file.name}'!")
                        st.rerun()

                dl_col, link_col = st.columns([1.6, 2.4])
                with dl_col:
                    if st.button("🏛️ Fetch via DigiLocker instead", key=f"dl_btn_{bidder_id}_{doc_type}_{ver}", help=f"Fetch authentic {doc_type} directly from DigiLocker repository"):
                        consent_url = generate_digilocker_consent_url(bidder_id=bidder_id, document_type=doc_type)
                        st.session_state[f"consent_url_{bidder_id}_{doc_type}"] = consent_url
                        
                        # In mock mode / offline demo, simulate instant successful fetch using canned sample data
                        session_id = f"mock_{doc_type.lower().replace(' ', '_')}_{bidder_id}"
                        doc_payload = fetch_digilocker_document(session_id=session_id, document_type=doc_type)
                        
                        save_digilocker_document(
                            bidder_id=bidder_id,
                            category=category_name,
                            document_type=doc_type,
                            doc_data=doc_payload,
                        )
                        st.session_state[f"sig_{bidder_id}_{doc_type}"] = f"digilocker_{doc_type}"
                        st.toast(f"✅ Fetched and issuer-verified {doc_type} via DigiLocker!")
                        st.rerun()

                with link_col:
                    last_consent_url = st.session_state.get(f"consent_url_{bidder_id}_{doc_type}")
                    if last_consent_url:
                        st.markdown(
                            f"<div style='margin-top: 6px; font-size: 0.8rem;'>"
                            f"🔗 <b>Consent URL:</b> <a href='{last_consent_url}' target='_blank' style='color: #2563EB; font-weight: 600; text-decoration: underline;'>Open DigiLocker Auth</a>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

            with col2:
                if is_uploaded and rec:
                    is_digilocker = rec.get("source") == "digilocker" or rec.get("issuer_verified")
                    if is_digilocker:
                        badge_border = "#93C5FD"
                        badge_bg = "#EFF6FF"
                        header_badge = "🏛️ DigiLocker Verified"
                        header_color = "#1D4ED8"
                        source_text = "✅ Issuer-verified via DigiLocker"
                        source_color = "#2563EB"
                    else:
                        badge_border = "#BBF7D0"
                        badge_bg = "#F0FDF4"
                        header_badge = "📄 Current Upload"
                        header_color = "#166534"
                        source_text = "Manual File Upload"
                        source_color = "#059669"

                    st.markdown(
                        f"""
                        <div style='margin-top: 18px; padding: 6px 10px; background: {badge_bg}; border: 1px solid {badge_border}; border-radius: 6px;'>
                            <span style='color: {header_color}; font-weight: 700; font-size: 0.8rem;'>{header_badge}:</span><br>
                            <span style='font-size: 0.82rem; color: #1E293B; word-break: break-all;'><b>{rec['filename']}</b></span><br>
                            <span style='font-size: 0.72rem; color: {source_color}; font-weight: 600;'>{source_text}</span><br>
                            <span style='font-size: 0.7rem; color: #64748B;'>{rec['uploaded_at']}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button("🗑️ Remove", key=f"del_{bidder_id}_{doc_type}_{ver}", use_container_width=True, help=f"Remove current {doc_type}"):
                        delete_document(bidder_id, doc_type)
                        st.session_state.pop(f"sig_{bidder_id}_{doc_type}", None)
                        st.session_state.pop(f"consent_url_{bidder_id}_{doc_type}", None)
                        st.session_state[f"ver_{bidder_id}_{doc_type}"] = ver + 1
                        st.toast(f"Removed {doc_type}")
                        st.rerun()
                else:
                    st.markdown("<div style='margin-top: 36px; color: #94A3B8; font-size: 0.85rem;'><i>Pending upload</i></div>", unsafe_allow_html=True)

            # Visual identity / specimen preview card if extracted
            if is_uploaded:
                doc_visuals = [img for img in extracted_visuals if img["document_id"] == doc_type]
                if doc_visuals:
                    st.markdown(
                        "<div style='margin-top: 6px; margin-bottom: 6px; padding: 6px 12px; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px;'>"
                        "<span style='font-size: 0.78rem; font-weight: 700; color: #475569;'>👁️ CAPTURED BIOMETRIC SPECIMENS (READ-ONLY CONFIRMATION):</span>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    v_cols = st.columns(len(doc_visuals) + 1)
                    for v_idx, v_img in enumerate(doc_visuals):
                        with v_cols[v_idx]:
                            lbl = "Photo" if v_img["image_type"] == "photo" else "Signature"
                            conf = int(v_img["extraction_confidence"] * 100)
                            st.image(
                                v_img["image_blob"],
                                caption=f"{lbl} Specimen (Page {v_img['source_page']} | Conf: {conf}%)",
                                width=140 if v_img["image_type"] == "photo" else 220,
                            )
                    with v_cols[-1]:
                        st.markdown(
                            "<div style='margin-top: 14px;'>"
                            "<span style='background: #DCFCE7; color: #166534; font-weight: 700; font-size: 0.75rem; padding: 4px 8px; border-radius: 12px;'>✅ Biometrics Captured</span><br>"
                            "<span style='font-size: 0.72rem; color: #64748B;'>Ready for officer cross-verification</span>"
                            "</div>",
                            unsafe_allow_html=True,
                        )

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
        is_dl = d.get("source") == "digilocker" or d.get("issuer_verified")
        src_label = "🏛️ DigiLocker" if is_dl else "📄 Upload"
        verified_label = "✅ Verified" if is_dl else "—"
        table_data.append({
            "Category": d["category"],
            "Document Type": d["document_type"],
            "Source": src_label,
            "Issuer Verified": verified_label,
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
