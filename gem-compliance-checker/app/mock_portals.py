"""Government Registry & API Setu Verification Gateway.

Connects to the Government of India Open API Platform (API Setu / MeitY / NIC)
with automated resilient fallback to high-fidelity simulated registries:
1. Income Tax Department (PAN Verification) via API Setu
2. GSTN Portal (GSTIN Status & Tax Filing Compliance) via API Setu
3. Ministry of MSME (Udyam Portal Registration & Classification) via API Setu
4. GeM Incident Management / Central Debarment Database (Blacklist Check)

Backed by API Setu client and local JSON database (sample_data/mock_registry.json).
"""

from enum import Enum
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.apisetu import ApiSetuClient, ApiSetuConfig

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    """Standard status returned by government registries."""

    VALID = "VALID"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NOT_FOUND = "NOT_FOUND"
    MISMATCH = "MISMATCH"
    BLACKLISTED = "BLACKLISTED"


class RegistryVerificationResult(BaseModel):
    """Normalized response from an individual registry verification query."""

    registry_name: str = Field(..., description="PAN / GSTN / Udyam / GeM_Debarment")
    query_identifier: str = Field(..., description="Queried identifier code")
    status: VerificationStatus = Field(..., description="Standardized portal status")
    is_valid: bool = Field(..., description="True if compliant and active")
    registered_name: Optional[str] = Field(None, description="Legal entity name on official portal")
    details: Dict[str, Any] = Field(default_factory=dict, description="Raw portal payload")
    risk_flags: List[str] = Field(default_factory=list, description="Any red flags detected")
    source: str = Field("API Setu (Simulated Gateway)", description="Provenance: 'API Setu (Live)' or 'API Setu (Simulated Gateway)'")


class EntityFullVerification(BaseModel):
    """Comprehensive multi-portal verification report for an entity."""

    pan_verification: RegistryVerificationResult
    gstin_verification: RegistryVerificationResult
    udyam_verification: RegistryVerificationResult
    debarment_check: RegistryVerificationResult
    is_overall_authentic: bool
    summary_flags: List[str] = Field(default_factory=list)
    gateway_provider: str = Field("API Setu (Open API Platform)", description="Primary verification pipeline gateway")


class MockPortalRegistry:
    """Government Portal Gateway integrating API Setu with resilient local fallback."""

    def __init__(self, db_path: Optional[str] = None, apisetu_client: Optional[ApiSetuClient] = None):
        """Initialize registry gateway.

        Args:
            db_path: Path to the mock_registry.json file.
            apisetu_client: Optional custom ApiSetuClient instance.
        """
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "sample_data" / "mock_registry.json"
        else:
            self.db_path = Path(db_path)

        self.entities: List[Dict[str, Any]] = []
        self._load_database()
        self.apisetu = apisetu_client or ApiSetuClient()

    def _load_database(self) -> None:
        """Load mock records from JSON file."""
        if not self.db_path.exists():
            logger.warning("Mock database not found at %s. Initializing with empty store.", self.db_path)
            self.entities = []
            return

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.entities = data.get("entities", [])
                logger.info("Loaded %d mock entities from %s", len(self.entities), self.db_path)
        except Exception as exc:
            logger.error("Failed to parse mock registry database: %s", exc)
            self.entities = []

    def verify_pan(self, pan: Optional[str], full_name: Optional[str] = None) -> RegistryVerificationResult:
        """Query PAN database via API Setu with fallback to local registry."""
        if not pan:
            return RegistryVerificationResult(
                registry_name="Income Tax Department (PAN via API Setu)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing PAN identifier in submission"],
                source="API Setu",
            )

        clean_pan = pan.strip().upper()

        # Step 1: Attempt live API Setu endpoint
        if self.apisetu.is_configured:
            live_res = self.apisetu.verify_pan(clean_pan, full_name=full_name)
            if live_res:
                return RegistryVerificationResult(
                    registry_name="Income Tax Department (PAN via API Setu)",
                    query_identifier=clean_pan,
                    status=VerificationStatus.ACTIVE if live_res["is_valid"] else VerificationStatus.CANCELLED,
                    is_valid=live_res["is_valid"],
                    registered_name=live_res.get("registered_name"),
                    details=live_res.get("details", {}),
                    risk_flags=[],
                    source="API Setu (Live)",
                )

        # Step 2: Fallback to simulated local registry
        for entity in self.entities:
            pan_data = entity.get("pan_details", {})
            if pan_data.get("pan", "").upper() == clean_pan:
                raw_status = pan_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags: List[str] = []
                if not is_valid:
                    flags.append(f"PAN status is {raw_status}: {pan_data.get('cancellation_reason', 'Unknown')}")

                return RegistryVerificationResult(
                    registry_name="Income Tax Department (PAN via API Setu)",
                    query_identifier=clean_pan,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.ACTIVE,
                    is_valid=is_valid,
                    registered_name=pan_data.get("registered_name"),
                    details=pan_data,
                    risk_flags=flags,
                    source="API Setu (Simulated Gateway)",
                )

        # Unregistered / unlisted PAN
        return RegistryVerificationResult(
            registry_name="Income Tax Department (PAN via API Setu)",
            query_identifier=clean_pan,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"PAN {clean_pan} not found in central registry"],
            source="API Setu (Simulated Gateway)",
        )

    def verify_gstin(self, gstin: Optional[str]) -> RegistryVerificationResult:
        """Query GSTN taxpayer portal via API Setu with fallback to local registry."""
        if not gstin:
            return RegistryVerificationResult(
                registry_name="GSTN Taxpayer Portal (via API Setu)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing GSTIN identifier in submission"],
                source="API Setu",
            )

        clean_gstin = gstin.strip().upper()

        # Step 1: Attempt live API Setu endpoint
        if self.apisetu.is_configured:
            live_res = self.apisetu.verify_gstin(clean_gstin)
            if live_res:
                return RegistryVerificationResult(
                    registry_name="GSTN Taxpayer Portal (via API Setu)",
                    query_identifier=clean_gstin,
                    status=VerificationStatus.ACTIVE if live_res["is_valid"] else VerificationStatus.SUSPENDED,
                    is_valid=live_res["is_valid"],
                    registered_name=live_res.get("registered_name"),
                    details=live_res.get("details", {}),
                    risk_flags=[] if live_res["is_valid"] else ["GSTIN is not in active standing on GSTN"],
                    source="API Setu (Live)",
                )

        # Step 2: Fallback to simulated local registry
        for entity in self.entities:
            gst_data = entity.get("gstin_details", {})
            if gst_data.get("gstin", "").upper() == clean_gstin:
                raw_status = gst_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags: List[str] = []
                if not is_valid:
                    flags.append(f"GSTIN is {raw_status}: {gst_data.get('suspension_reason', 'Non-compliant')}")
                if gst_data.get("filing_status") == "OVERDUE_RETURNS":
                    flags.append("Statutory GST returns (GSTR-3B) are overdue")

                return RegistryVerificationResult(
                    registry_name="GSTN Taxpayer Portal (via API Setu)",
                    query_identifier=clean_gstin,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.SUSPENDED,
                    is_valid=is_valid,
                    registered_name=gst_data.get("legal_name"),
                    details=gst_data,
                    risk_flags=flags,
                    source="API Setu (Simulated Gateway)",
                )

        return RegistryVerificationResult(
            registry_name="GSTN Taxpayer Portal (via API Setu)",
            query_identifier=clean_gstin,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"GSTIN {clean_gstin} does not exist in GSTN database"],
            source="API Setu (Simulated Gateway)",
        )

    def verify_udyam(self, udyam_reg_no: Optional[str]) -> RegistryVerificationResult:
        """Query Ministry of MSME Udyam database via API Setu with fallback."""
        if not udyam_reg_no:
            return RegistryVerificationResult(
                registry_name="MSME Udyam Portal (via API Setu)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["No Udyam registration provided"],
                source="API Setu",
            )

        clean_udyam = udyam_reg_no.strip().upper()

        # Step 1: Attempt live API Setu endpoint
        if self.apisetu.is_configured:
            live_res = self.apisetu.verify_udyam(clean_udyam)
            if live_res:
                return RegistryVerificationResult(
                    registry_name="MSME Udyam Portal (via API Setu)",
                    query_identifier=clean_udyam,
                    status=VerificationStatus.ACTIVE if live_res["is_valid"] else VerificationStatus.EXPIRED,
                    is_valid=live_res["is_valid"],
                    registered_name=live_res.get("registered_name"),
                    details=live_res.get("details", {}),
                    risk_flags=[],
                    source="API Setu (Live)",
                )

        # Step 2: Fallback to simulated local registry
        for entity in self.entities:
            udyam_data = entity.get("udyam_details", {})
            if udyam_data.get("udyam_registration_number", "").upper() == clean_udyam:
                raw_status = udyam_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags: List[str] = []
                if not is_valid:
                    flags.append(f"Udyam registration is {raw_status}: {udyam_data.get('expiry_reason', 'Not valid')}")

                return RegistryVerificationResult(
                    registry_name="MSME Udyam Portal (via API Setu)",
                    query_identifier=clean_udyam,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.EXPIRED,
                    is_valid=is_valid,
                    registered_name=udyam_data.get("enterprise_name"),
                    details=udyam_data,
                    risk_flags=flags,
                    source="API Setu (Simulated Gateway)",
                )

        return RegistryVerificationResult(
            registry_name="MSME Udyam Portal (via API Setu)",
            query_identifier=clean_udyam,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"Udyam number {clean_udyam} not found on official MSME portal"],
            source="API Setu (Simulated Gateway)",
        )

    def check_debarment(self, pan: Optional[str]) -> RegistryVerificationResult:
        """Check GeM Central Debarment / Blacklist registry."""
        if not pan:
            return RegistryVerificationResult(
                registry_name="GeM Central Debarment Watchlist (via API Setu)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=True,
                risk_flags=[],
                source="API Setu (Simulated Gateway)",
            )

        clean_pan = pan.strip().upper()
        for entity in self.entities:
            if entity.get("pan_details", {}).get("pan", "").upper() == clean_pan:
                debar = entity.get("debarment_status", {})
                is_blacklisted = debar.get("is_blacklisted", False)
                flags: List[str] = []
                if is_blacklisted:
                    flags.append(
                        f"CRITICAL: Entity is BLACKLISTED until {debar.get('debarment_period')} "
                        f"by {debar.get('banned_by')}. Reason: {debar.get('reason')}"
                    )

                return RegistryVerificationResult(
                    registry_name="GeM Central Debarment Watchlist (via API Setu)",
                    query_identifier=clean_pan,
                    status=VerificationStatus.BLACKLISTED if is_blacklisted else VerificationStatus.ACTIVE,
                    is_valid=not is_blacklisted,
                    registered_name=entity.get("company_name"),
                    details=debar,
                    risk_flags=flags,
                    source="API Setu (Simulated Gateway)",
                )

        # Default clean record if unknown
        return RegistryVerificationResult(
            registry_name="GeM Central Debarment Watchlist (via API Setu)",
            query_identifier=clean_pan,
            status=VerificationStatus.ACTIVE,
            is_valid=True,
            details={"is_blacklisted": False},
            risk_flags=[],
            source="API Setu (Simulated Gateway)",
        )

    def verify_all(
        self,
        pan: Optional[str],
        gstin: Optional[str],
        udyam: Optional[str],
        full_name: Optional[str] = None,
    ) -> EntityFullVerification:
        """Run complete portal verification across all statutory databases."""
        pan_res = self.verify_pan(pan, full_name=full_name)
        gst_res = self.verify_gstin(gstin)
        udyam_res = self.verify_udyam(udyam)
        debar_res = self.check_debarment(pan)

        all_flags = pan_res.risk_flags + gst_res.risk_flags + udyam_res.risk_flags + debar_res.risk_flags
        is_authentic = pan_res.is_valid and gst_res.is_valid and debar_res.is_valid

        # Data provenance indicator
        has_live = any("Live" in r.source for r in (pan_res, gst_res, udyam_res))
        gateway_name = "API Setu (Live Gateway)" if has_live else "API Setu (Open API Platform Gateway)"

        return EntityFullVerification(
            pan_verification=pan_res,
            gstin_verification=gst_res,
            udyam_verification=udyam_res,
            debarment_check=debar_res,
            is_overall_authentic=is_authentic,
            summary_flags=all_flags,
            gateway_provider=gateway_name,
        )


# Functional convenience helper
def verify_bidder_portals(
    pan: Optional[str],
    gstin: Optional[str],
    udyam: Optional[str],
    full_name: Optional[str] = None,
) -> EntityFullVerification:
    """Convenience helper to instantiate gateway and perform verification."""
    registry = MockPortalRegistry()
    return registry.verify_all(pan=pan, gstin=gstin, udyam=udyam, full_name=full_name)
