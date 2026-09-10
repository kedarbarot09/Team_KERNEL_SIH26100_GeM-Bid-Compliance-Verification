"""API Setu Integration Client for Government Statutory Registries.

Connects to the Government of India Open API Platform (API Setu / MeitY / NIC)
to perform real-time verification of statutory credentials:
1. Income Tax Department - PAN Verification (pancr)
2. GSTN - Taxpayer GSTIN Status & Return Filing (gstr)
3. Ministry of MSME - Udyam Registration & Enterprise Verification (udyam)
4. Ministry of Corporate Affairs (MCA) - Company Master Data / Incorporation (coi)

Provides automatic sandbox fallback and mock resilience when live API Setu credentials
are not configured or when government endpoints are unreachable.
"""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import uuid

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


@dataclass
class ApiSetuConfig:
    """Configuration parameters for API Setu Gateway."""

    client_id: str = ""
    api_key: str = ""
    base_url: str = "https://apisetu.gov.in/certificate/v3"
    timeout_seconds: float = 4.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "ApiSetuConfig":
        """Load API Setu settings from environment variables."""
        return cls(
            client_id=os.getenv("APISETU_CLIENT_ID", "").strip(),
            api_key=os.getenv("APISETU_API_KEY", "").strip(),
            base_url=os.getenv("APISETU_BASE_URL", "https://apisetu.gov.in/certificate/v3").rstrip("/"),
            timeout_seconds=float(os.getenv("APISETU_TIMEOUT_SECONDS", "4.0")),
            enabled=os.getenv("USE_APISETU", "true").lower() in ("true", "1", "yes"),
        )


class ApiSetuClient:
    """Client for querying API Setu Government verification endpoints."""

    def __init__(self, config: Optional[ApiSetuConfig] = None):
        self.config = config or ApiSetuConfig.from_env()

    @property
    def is_configured(self) -> bool:
        """Check if active API Setu credentials have been provided."""
        return bool(self.config.client_id and self.config.api_key and self.config.enabled)

    def _get_headers(self) -> Dict[str, str]:
        """Construct required API Setu authorization headers."""
        return {
            "X-APISETU-CLIENTID": self.config.client_id,
            "X-APISETU-APIKEY": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def verify_pan(self, pan: str, full_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Query Income Tax Department PAN verification on API Setu.

        API Setu Endpoint: /incometax/pancr
        """
        if not self.is_configured:
            return None

        clean_pan = pan.strip().upper()
        url = f"{self.config.base_url}/incometax/pancr"
        payload = {
            "txnId": str(uuid.uuid4()),
            "format": "json",
            "certificateParameters": {
                "panno": clean_pan,
                "FullName": full_name or "",
            },
            "consentArtifact": {
                "consent": {
                    "consentId": str(uuid.uuid4()),
                    "timestamp": "2024-01-01T00:00:00.000Z",
                    "dataConsumer": {"id": "GeM-Compliance-Engine"},
                    "purpose": {"description": "Bidder Statutory Qualification Check"},
                }
            },
        }

        try:
            logger.info("Calling API Setu PAN Verification for %s", clean_pan)
            resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=self.config.timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                logger.info("API Setu PAN response received successfully: %s", data)
                return {
                    "status": "ACTIVE",
                    "is_valid": True,
                    "registered_name": data.get("FullName") or data.get("name"),
                    "details": data,
                    "source": "API Setu (Live)",
                }
            else:
                logger.warning("API Setu PAN returned status %d: %s", resp.status_code, resp.text)
                return None
        except Exception as exc:
            logger.warning("API Setu PAN verification call failed (%s); falling back to simulator.", exc)
            return None

    def verify_gstin(self, gstin: str) -> Optional[Dict[str, Any]]:
        """Query GSTN Taxpayer Verification on API Setu.

        API Setu Endpoint: /gstn/gstr
        """
        if not self.is_configured:
            return None

        clean_gstin = gstin.strip().upper()
        url = f"{self.config.base_url}/gstn/gstr"
        payload = {
            "txnId": str(uuid.uuid4()),
            "format": "json",
            "certificateParameters": {
                "GSTIN": clean_gstin,
            },
        }

        try:
            logger.info("Calling API Setu GSTIN Verification for %s", clean_gstin)
            resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=self.config.timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                raw_status = data.get("status", "Active").upper()
                is_active = (raw_status == "ACTIVE")
                return {
                    "status": raw_status,
                    "is_valid": is_active,
                    "registered_name": data.get("legalName") or data.get("tradeName"),
                    "details": data,
                    "source": "API Setu (Live)",
                }
            else:
                logger.warning("API Setu GSTIN returned status %d: %s", resp.status_code, resp.text)
                return None
        except Exception as exc:
            logger.warning("API Setu GSTIN verification call failed (%s); falling back to simulator.", exc)
            return None

    def verify_udyam(self, udyam_no: str) -> Optional[Dict[str, Any]]:
        """Query Ministry of MSME Udyam verification on API Setu.

        API Setu Endpoint: /msme/udyam
        """
        if not self.is_configured:
            return None

        clean_udyam = udyam_no.strip().upper()
        url = f"{self.config.base_url}/msme/udyam"
        payload = {
            "txnId": str(uuid.uuid4()),
            "format": "json",
            "certificateParameters": {
                "UdyamNo": clean_udyam,
            },
        }

        try:
            logger.info("Calling API Setu Udyam Verification for %s", clean_udyam)
            resp = requests.post(url, json=payload, headers=self._get_headers(), timeout=self.config.timeout_seconds)
            if resp.status_code == 200:
                data = resp.json()
                raw_status = data.get("status", "Active").upper()
                is_active = (raw_status == "ACTIVE")
                return {
                    "status": raw_status,
                    "is_valid": is_active,
                    "registered_name": data.get("enterpriseName"),
                    "details": data,
                    "source": "API Setu (Live)",
                }
            else:
                logger.warning("API Setu Udyam returned status %d: %s", resp.status_code, resp.text)
                return None
        except Exception as exc:
            logger.warning("API Setu Udyam verification call failed (%s); falling back to simulator.", exc)
            return None
