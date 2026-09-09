"""Government Registry Simulator Module (Mock Portals).

Simulates external verification APIs for Indian government statutory registries:
1. Income Tax Department (PAN Verification)
2. GSTN Portal (GSTIN Status & Tax Filing Compliance)
3. Ministry of MSME (Udyam Portal Registration & Classification)
4. GeM Incident Management / Debarment Database (Central Blacklist Check)

Backed by a local JSON database (sample_data/mock_registry.json).
"""

from enum import Enum
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    """Standard status returned by simulated government registries."""

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


class EntityFullVerification(BaseModel):
    """Comprehensive multi-portal verification report for an entity."""

    pan_verification: RegistryVerificationResult
    gstin_verification: RegistryVerificationResult
    udyam_verification: RegistryVerificationResult
    debarment_check: RegistryVerificationResult
    is_overall_authentic: bool
    summary_flags: List[str] = Field(default_factory=list)


class MockPortalRegistry:
    """Simulated Government Registry Engine."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize registry simulator.

        Args:
            db_path: Path to the mock_registry.json file. If None, resolves default path.
        """
        if db_path is None:
            # Look relative to current file
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "sample_data" / "mock_registry.json"
        else:
            self.db_path = Path(db_path)

        self.entities: List[Dict[str, Any]] = []
        self._load_database()

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

    def verify_pan(self, pan: Optional[str]) -> RegistryVerificationResult:
        """Query simulated Income Tax PAN database.

        Args:
            pan: 10-character PAN string.

        Returns:
            RegistryVerificationResult for the PAN.
        """
        if not pan:
            return RegistryVerificationResult(
                registry_name="Income Tax Department (PAN)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing PAN identifier in submission"],
            )

        clean_pan = pan.strip().upper()
        for entity in self.entities:
            pan_data = entity.get("pan_details", {})
            if pan_data.get("pan", "").upper() == clean_pan:
                raw_status = pan_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags: List[str] = []
                if not is_valid:
                    flags.append(f"PAN status is {raw_status}: {pan_data.get('cancellation_reason', 'Unknown')}")

                return RegistryVerificationResult(
                    registry_name="Income Tax Department (PAN)",
                    query_identifier=clean_pan,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.ACTIVE,
                    is_valid=is_valid,
                    registered_name=pan_data.get("registered_name"),
                    details=pan_data,
                    risk_flags=flags,
                )

        # Unregistered / unlisted PAN
        return RegistryVerificationResult(
            registry_name="Income Tax Department (PAN)",
            query_identifier=clean_pan,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"PAN {clean_pan} not found in central registry"],
        )

    def verify_gstin(self, gstin: Optional[str]) -> RegistryVerificationResult:
        """Query simulated GSTN taxpayer portal.

        Args:
            gstin: 15-character GSTIN.

        Returns:
            RegistryVerificationResult for the GSTIN.
        """
        if not gstin:
            return RegistryVerificationResult(
                registry_name="GSTN Portal",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing GSTIN identifier in submission"],
            )

        clean_gstin = gstin.strip().upper()
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
                    registry_name="GSTN Portal",
                    query_identifier=clean_gstin,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.SUSPENDED,
                    is_valid=is_valid,
                    registered_name=gst_data.get("legal_name"),
                    details=gst_data,
                    risk_flags=flags,
                )

        return RegistryVerificationResult(
            registry_name="GSTN Portal",
            query_identifier=clean_gstin,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"GSTIN {clean_gstin} does not exist in GSTN database"],
        )

    def verify_udyam(self, udyam_reg_no: Optional[str]) -> RegistryVerificationResult:
        """Query simulated Ministry of MSME Udyam database.

        Args:
            udyam_reg_no: Official Udyam registration string.

        Returns:
            RegistryVerificationResult for MSME status.
        """
        if not udyam_reg_no:
            return RegistryVerificationResult(
                registry_name="MSME Udyam Portal",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["No Udyam registration provided"],
            )

        clean_udyam = udyam_reg_no.strip().upper()
        for entity in self.entities:
            udyam_data = entity.get("udyam_details", {})
            if udyam_data.get("udyam_registration_number", "").upper() == clean_udyam:
                raw_status = udyam_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags: List[str] = []
                if not is_valid:
                    flags.append(f"Udyam registration is {raw_status}: {udyam_data.get('expiry_reason', 'Not valid')}")

                return RegistryVerificationResult(
                    registry_name="MSME Udyam Portal",
                    query_identifier=clean_udyam,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.EXPIRED,
                    is_valid=is_valid,
                    registered_name=udyam_data.get("enterprise_name"),
                    details=udyam_data,
                    risk_flags=flags,
                )

        return RegistryVerificationResult(
            registry_name="MSME Udyam Portal",
            query_identifier=clean_udyam,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"Udyam number {clean_udyam} not found on official MSME portal"],
        )

    def check_debarment(self, pan: Optional[str]) -> RegistryVerificationResult:
        """Check GeM Central Debarment / Blacklist registry.

        Args:
            pan: PAN identifier of bidder.

        Returns:
            RegistryVerificationResult indicating blacklist status.
        """
        if not pan:
            return RegistryVerificationResult(
                registry_name="GeM Debarment Watchlist",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=True,
                risk_flags=[],
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
                    registry_name="GeM Debarment Watchlist",
                    query_identifier=clean_pan,
                    status=VerificationStatus.BLACKLISTED if is_blacklisted else VerificationStatus.ACTIVE,
                    is_valid=not is_blacklisted,
                    registered_name=entity.get("company_name"),
                    details=debar,
                    risk_flags=flags,
                )

        # Default clean record if unknown
        return RegistryVerificationResult(
            registry_name="GeM Debarment Watchlist",
            query_identifier=clean_pan,
            status=VerificationStatus.ACTIVE,
            is_valid=True,
            details={"is_blacklisted": False},
            risk_flags=[],
        )

    def verify_all(
        self,
        pan: Optional[str],
        gstin: Optional[str],
        udyam: Optional[str],
    ) -> EntityFullVerification:
        """Run complete portal verification across all statutory databases."""
        pan_res = self.verify_pan(pan)
        gst_res = self.verify_gstin(gstin)
        udyam_res = self.verify_udyam(udyam)
        debar_res = self.check_debarment(pan)

        all_flags = pan_res.risk_flags + gst_res.risk_flags + udyam_res.risk_flags + debar_res.risk_flags
        is_authentic = pan_res.is_valid and gst_res.is_valid and debar_res.is_valid

        return EntityFullVerification(
            pan_verification=pan_res,
            gstin_verification=gst_res,
            udyam_verification=udyam_res,
            debarment_check=debar_res,
            is_overall_authentic=is_authentic,
            summary_flags=all_flags,
        )


# Functional convenience helper
def verify_bidder_portals(pan: Optional[str], gstin: Optional[str], udyam: Optional[str]) -> EntityFullVerification:
    """Convenience helper to instantiate simulator and perform verification."""
    registry = MockPortalRegistry()
    return registry.verify_all(pan=pan, gstin=gstin, udyam=udyam)
