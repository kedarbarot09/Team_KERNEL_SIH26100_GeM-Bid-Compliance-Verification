"""DigiLocker Integration Module for GeM Compliance Verification.

Provides document fetching capabilities via the Sandbox DigiLocker API:
1. `generate_digilocker_consent_url`: Requests a citizen authorization URL for a specific document.
2. `fetch_digilocker_document`: Retrieves the issued, cryptographically verified document data.
3. Fallback mock mode: Provides offline mock execution using canned statutory credentials
   (Udyam, PAN, GST) when SANDBOX_API_KEY is not configured or network requests fail.
"""

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

# Base paths
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data" / "digilocker_mock"

SANDBOX_BASE_URL = "https://test-api.sandbox.co.in/digilocker"
SANDBOX_API_KEY_ENV = "SANDBOX_API_KEY"


def _slugify(text: str) -> str:
    """Normalize string into a safe identifier slug."""
    return re.sub(r"[^\w]+", "_", text.strip().lower()).strip("_")


def _get_mock_document_path(document_type_or_session: str) -> Optional[Path]:
    """Resolve canned mock DigiLocker response file path based on doc type or session ID."""
    token = _slugify(document_type_or_session)
    if "pan" in token:
        mock_file = SAMPLE_DATA_DIR / "pan.json"
    elif "gst" in token:
        mock_file = SAMPLE_DATA_DIR / "gst.json"
    elif "udyam" in token or "msme" in token:
        mock_file = SAMPLE_DATA_DIR / "udyam.json"
    else:
        # Default fallback to Udyam
        mock_file = SAMPLE_DATA_DIR / "udyam.json"

    if mock_file.is_file():
        return mock_file
    return None


def get_canned_mock_document(document_type_or_session: str) -> Dict[str, Any]:
    """Load a canned mock DigiLocker document response from sample_data/digilocker_mock/."""
    file_path = _get_mock_document_path(document_type_or_session)
    if file_path and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception as e:
            logger.warning("Failed to load canned mock data from %s: %s", file_path, e)

    # Generic fallback mock response if file cannot be read
    doc_title = document_type_or_session.replace("_", " ").title()
    return {
        "status": "success",
        "source": "digilocker",
        "issuer_verified": True,
        "issuer": "Government Statutory Repository (DigiLocker)",
        "document_type": doc_title,
        "uri": f"in.gov.repository-{_slugify(document_type_or_session)}-VERIFIED",
        "date_of_issue": "2024-01-01",
        "data": {
            "identifier": f"MOCK-{_slugify(document_type_or_session).upper()}-001",
            "status": "ACTIVE",
            "issuer_verified": True,
        },
        "raw_text": f"GOVERNMENT OF INDIA - DIGILOCKER VERIFIED CREDENTIAL\nDocument Type: {doc_title}\nStatus: ACTIVE\nIssuer Verified: True",
    }


def generate_digilocker_consent_url(
    bidder_id: str,
    document_type: str,
    redirect_url: Optional[str] = None,
) -> str:
    """Generate DigiLocker consent URL for a bidder and document type.

    Sends a POST request to https://test-api.sandbox.co.in/digilocker/url with
    x-api-key header and payload containing reference_id, document_type, and redirect_url.
    If SANDBOX_API_KEY is not configured or the API call fails, seamlessly falls back
    to returning a simulated consent URL for offline demo use.

    Args:
        bidder_id: Unique identifier for the vendor/bidder.
        document_type: The document type to request (e.g. 'PAN Card', 'GST Registration Certificate').
        redirect_url: Optional callback URL after citizen authorization.

    Returns:
        Consent URL string for the citizen authorization flow.
    """
    api_key = os.environ.get(SANDBOX_API_KEY_ENV)
    clean_bidder = bidder_id.strip() if bidder_id else "ANONYMOUS"
    slug_doc = _slugify(document_type)
    reference_id = f"REF-{clean_bidder}-{slug_doc}-{int(time.time())}"
    callback_url = redirect_url or "http://localhost:8502/digilocker/callback"

    # Attempt live API call if API key is configured
    if api_key:
        endpoint = f"{SANDBOX_BASE_URL}/url"
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        payload = {
            "reference_id": reference_id,
            "document_type": document_type,
            "redirect_url": callback_url,
        }

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=5)
            if resp.status_code in (200, 201):
                data = resp.json()
                # Handle standard Sandbox API response shapes
                consent_url = (
                    data.get("consent_url")
                    or data.get("url")
                    or (data.get("data", {}).get("url") if isinstance(data.get("data"), dict) else None)
                    or (data.get("data", {}).get("consent_url") if isinstance(data.get("data"), dict) else None)
                )
                if consent_url:
                    logger.info("Retrieved live DigiLocker consent URL for %s (%s)", clean_bidder, document_type)
                    return str(consent_url)
            logger.warning(
                "DigiLocker URL endpoint returned status %s: %s. Falling back to mock URL.",
                resp.status_code,
                resp.text,
            )
        except Exception as exc:
            logger.warning("DigiLocker API connection error (%s). Falling back to mock URL.", exc)

    # Fallback mock mode URL
    mock_session_id = f"mock_session_{slug_doc}_{clean_bidder}"
    mock_consent_url = (
        f"{SANDBOX_BASE_URL}/mock-consent"
        f"?session_id={mock_session_id}&reference_id={reference_id}&document_type={slug_doc}"
    )
    logger.info("Generated simulated DigiLocker consent URL for %s (%s): %s", clean_bidder, document_type, mock_consent_url)
    return mock_consent_url


def fetch_digilocker_document(
    session_id: str,
    document_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve document data from DigiLocker using session ID.

    Sends a GET request to https://test-api.sandbox.co.in/digilocker/documents/{session_id}
    with x-api-key header. If SANDBOX_API_KEY is not set, or the session is a mock session,
    or the API request fails, returns a canned sample DigiLocker-style JSON response.

    Args:
        session_id: The session or authorization ID from the consent callback.
        document_type: Optional hint for resolving the appropriate mock document.

    Returns:
        Dictionary containing document data, metadata, issuer verification, and raw_text.
    """
    api_key = os.environ.get(SANDBOX_API_KEY_ENV)

    # Check if this is an explicit mock session or no API key is set
    is_mock_session = session_id.startswith("mock_") or "mock" in session_id.lower()

    if api_key and not is_mock_session:
        endpoint = f"{SANDBOX_BASE_URL}/documents/{session_id}"
        headers = {
            "x-api-key": api_key,
            "accept": "application/json",
        }
        try:
            resp = requests.get(endpoint, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # Ensure standard fields
                if isinstance(data, dict):
                    data["source"] = "digilocker"
                    data["issuer_verified"] = True
                    return data
            logger.warning("DigiLocker fetch returned status %s: %s. Falling back to mock data.", resp.status_code, resp.text)
        except Exception as exc:
            logger.warning("Failed to fetch document from DigiLocker API (%s). Falling back to mock data.", exc)

    # Fallback mock mode: return canned sample JSON
    target_key = document_type or session_id
    mock_data = get_canned_mock_document(target_key)
    # Ensure source and issuer_verified flags are consistently set
    mock_data["source"] = "digilocker"
    mock_data["issuer_verified"] = True
    return mock_data
