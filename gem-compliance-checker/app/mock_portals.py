"""Government Statutory Registry Verification Gateway.

Provides verification of statutory credentials against government registries:
1. Income Tax Department (PAN Verification)
2. GSTN Portal (GSTIN Status & Tax Filing Compliance)
3. Ministry of MSME (Udyam Portal Registration & Classification)
4. GeM Incident Management / Central Debarment Database (Blacklist Check)

Backed by local JSON statutory database (sample_data/mock_registry.json).
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
    source: str = Field("Statutory Registry (Simulated)", description="Provenance: 'Statutory Registry (Simulated)'")


class EntityFullVerification(BaseModel):
    """Comprehensive multi-portal verification report for an entity."""

    pan_verification: RegistryVerificationResult
    gstin_verification: RegistryVerificationResult
    udyam_verification: RegistryVerificationResult
    debarment_check: RegistryVerificationResult
    is_overall_authentic: bool
    summary_flags: List[str] = Field(default_factory=list)
    gateway_provider: str = Field("Government Statutory Registry Gateway", description="Primary verification pipeline gateway")


class MockPortalRegistry:
    """Government Portal Gateway with local statutory registry simulation."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize registry gateway.

        Args:
            db_path: Path to the mock_registry.json file.
        """
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.db_path = base_dir / "sample_data" / "mock_registry.json"
        else:
            self.db_path = Path(db_path)

        self.entities: List[Dict[str, Any]] = []
        self.bidders: List[Dict[str, Any]] = []
        self.bidders_by_id: Dict[str, Dict[str, Any]] = {}
        self.bidders_by_pan: Dict[str, Dict[str, Any]] = {}
        self.bidders_by_gstin: Dict[str, Dict[str, Any]] = {}
        self.bidders_by_udyam: Dict[str, Dict[str, Any]] = {}
        self._load_database()

    def _load_database(self) -> None:
        """Load mock records from JSON file."""
        if not self.db_path.exists():
            logger.warning("Mock database not found at %s. Initializing with empty store.", self.db_path)
            self.entities = []
            self.bidders = []
            return

        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.entities = data.get("entities", [])
                self.bidders = data.get("bidders", [])

                # Index bidders by identifiers for instant lookup
                for b in self.bidders:
                    bid = b.get("bidder_id", "")
                    if bid:
                        self.bidders_by_id[bid] = b

                    prof = b.get("profile") or {}
                    stat = (b.get("documents") or {}).get("statutory") or {}

                    pan_card = stat.get("pan_card") or {}
                    pan = (prof.get("pan") or pan_card.get("pan") or "").strip().upper()
                    if pan:
                        self.bidders_by_pan[pan] = b

                    gst_reg = stat.get("gst_registration") or {}
                    gstin = (prof.get("gstin") or gst_reg.get("gstin") or "").strip().upper()
                    if gstin:
                        self.bidders_by_gstin[gstin] = b

                    udyam_obj = stat.get("udyam_certificate")
                    if udyam_obj and isinstance(udyam_obj, dict):
                        unum = udyam_obj.get("number", "").strip().upper()
                        if unum:
                            self.bidders_by_udyam[unum] = b

                logger.info(
                    "Loaded %d mock entities and %d mock bidders from %s",
                    len(self.entities),
                    len(self.bidders),
                    self.db_path,
                )
        except Exception as exc:
            logger.error("Failed to parse mock registry database: %s", exc)
            self.entities = []
            self.bidders = []

    def get_bidder(self, bidder_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full profile of bidder by bidder_id."""
        return self.bidders_by_id.get(bidder_id.strip().upper())

    def find_bidder(
        self,
        pan: Optional[str] = None,
        gstin: Optional[str] = None,
        udyam: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find bidder record by any statutory identifier."""
        if pan and pan.strip().upper() in self.bidders_by_pan:
            return self.bidders_by_pan[pan.strip().upper()]
        if gstin and gstin.strip().upper() in self.bidders_by_gstin:
            return self.bidders_by_gstin[gstin.strip().upper()]
        if udyam and udyam.strip().upper() in self.bidders_by_udyam:
            return self.bidders_by_udyam[udyam.strip().upper()]
        return None

    def get_all_bidders(self) -> List[Dict[str, Any]]:
        """Return all bidders in database."""
        return self.bidders

    def verify_pan(self, pan: Optional[str], full_name: Optional[str] = None) -> RegistryVerificationResult:
        """Query PAN database with fallback to local registry."""
        if not pan:
            return RegistryVerificationResult(
                registry_name="Income Tax Department (PAN)",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing PAN identifier in submission"],
                source="Statutory Registry (Simulated)",
            )

        clean_pan = pan.strip().upper()

        # 1. Query 10-bidder database
        if clean_pan in self.bidders_by_pan:
            bidder = self.bidders_by_pan[clean_pan]
            pan_doc = (bidder.get("documents") or {}).get("statutory", {}).get("pan_card") or {}
            raw_status = pan_doc.get("status", "VALID").upper()
            verified = pan_doc.get("verified", True)
            is_valid = (raw_status == "VALID" and verified)
            flags: List[str] = []
            if not is_valid:
                flags.append(f"PAN status is {raw_status} (Verified: {verified})")

            return RegistryVerificationResult(
                registry_name="Income Tax Department (PAN)",
                query_identifier=clean_pan,
                status=VerificationStatus.ACTIVE if is_valid else VerificationStatus.CANCELLED,
                is_valid=is_valid,
                registered_name=bidder.get("company_name"),
                details=pan_doc,
                risk_flags=flags,
                source="Statutory Registry (Simulated)",
            )

        # 2. Query legacy simulated local registry entities
        for entity in self.entities:
            pan_data = entity.get("pan_details", {})
            if pan_data.get("pan", "").upper() == clean_pan:
                raw_status = pan_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags = []
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
                    source="Statutory Registry (Simulated)",
                )

        # Unregistered / unlisted PAN
        return RegistryVerificationResult(
            registry_name="Income Tax Department (PAN)",
            query_identifier=clean_pan,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"PAN {clean_pan} not found in central registry"],
            source="Statutory Registry (Simulated)",
        )

    def verify_gstin(self, gstin: Optional[str]) -> RegistryVerificationResult:
        """Query GSTN taxpayer portal with fallback to local registry."""
        if not gstin:
            return RegistryVerificationResult(
                registry_name="GSTN Taxpayer Portal",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["Missing GSTIN identifier in submission"],
                source="Statutory Registry (Simulated)",
            )

        clean_gstin = gstin.strip().upper()

        # 1. Query 10-bidder database
        if clean_gstin in self.bidders_by_gstin:
            bidder = self.bidders_by_gstin[clean_gstin]
            gst_doc = (bidder.get("documents") or {}).get("statutory", {}).get("gst_registration") or {}
            raw_status = gst_doc.get("status", "Active")
            filing_status = gst_doc.get("filing_status_3b", "Regular")
            verified = gst_doc.get("verified", True)
            is_active = (raw_status.lower() == "active" and verified)
            is_valid = is_active and (filing_status.lower() != "defaulter")

            flags: List[str] = []
            if raw_status.lower() != "active":
                flags.append(f"GSTIN is {raw_status.upper()} on GSTN Portal")
                if gst_doc.get("cancellation_date"):
                    flags.append(f"GSTIN registration cancelled effective {gst_doc.get('cancellation_date')}")
            if filing_status.lower() == "defaulter":
                flags.append("Statutory GST returns (GSTR-3B) are in default")
            elif filing_status.lower() == "late_filer":
                flags.append("Statutory GST returns (GSTR-3B) show late filing pattern")

            status_enum = VerificationStatus.ACTIVE
            if raw_status.upper() in ["SUSPENDED", "CANCELLED"]:
                status_enum = VerificationStatus(raw_status.upper())
            elif not is_valid:
                status_enum = VerificationStatus.SUSPENDED

            return RegistryVerificationResult(
                registry_name="GSTN Taxpayer Portal",
                query_identifier=clean_gstin,
                status=status_enum,
                is_valid=is_valid,
                registered_name=bidder.get("company_name"),
                details=gst_doc,
                risk_flags=flags,
                source="Statutory Registry (Simulated)",
            )

        # 2. Query legacy simulated local registry
        for entity in self.entities:
            gst_data = entity.get("gstin_details", {})
            if gst_data.get("gstin", "").upper() == clean_gstin:
                raw_status = gst_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags = []
                if not is_valid:
                    flags.append(f"GSTIN is {raw_status}: {gst_data.get('suspension_reason', 'Non-compliant')}")
                if gst_data.get("filing_status") == "OVERDUE_RETURNS":
                    flags.append("Statutory GST returns (GSTR-3B) are overdue")

                return RegistryVerificationResult(
                    registry_name="GSTN Taxpayer Portal",
                    query_identifier=clean_gstin,
                    status=VerificationStatus(raw_status) if raw_status in VerificationStatus.__members__ else VerificationStatus.SUSPENDED,
                    is_valid=is_valid,
                    registered_name=gst_data.get("legal_name"),
                    details=gst_data,
                    risk_flags=flags,
                    source="Statutory Registry (Simulated)",
                )

        return RegistryVerificationResult(
            registry_name="GSTN Taxpayer Portal",
            query_identifier=clean_gstin,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"GSTIN {clean_gstin} does not exist in GSTN database"],
            source="Statutory Registry (Simulated)",
        )

    def verify_udyam(self, udyam_reg_no: Optional[str]) -> RegistryVerificationResult:
        """Query Ministry of MSME Udyam database with fallback."""
        if not udyam_reg_no:
            return RegistryVerificationResult(
                registry_name="MSME Udyam Portal",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=False,
                risk_flags=["No Udyam registration provided"],
                source="Statutory Registry (Simulated)",
            )

        clean_udyam = udyam_reg_no.strip().upper()

        # 1. Query 10-bidder database
        if clean_udyam in self.bidders_by_udyam:
            bidder = self.bidders_by_udyam[clean_udyam]
            udyam_doc = (bidder.get("documents") or {}).get("statutory", {}).get("udyam_certificate") or {}
            validity = udyam_doc.get("validity", "PERMANENT").upper()
            verified = udyam_doc.get("verified", True)
            is_valid = (validity == "PERMANENT" and verified)

            flags: List[str] = []
            if not is_valid:
                flags.append(f"Udyam registration is {validity} (Annual re-declaration unverified or expired)")

            return RegistryVerificationResult(
                registry_name="MSME Udyam Portal",
                query_identifier=clean_udyam,
                status=VerificationStatus.ACTIVE if is_valid else VerificationStatus.EXPIRED,
                is_valid=is_valid,
                registered_name=bidder.get("company_name"),
                details=udyam_doc,
                risk_flags=flags,
                source="Statutory Registry (Simulated)",
            )

        # 2. Query legacy simulated local registry
        for entity in self.entities:
            udyam_data = entity.get("udyam_details", {})
            if udyam_data.get("udyam_registration_number", "").upper() == clean_udyam:
                raw_status = udyam_data.get("status", "ACTIVE").upper()
                is_valid = raw_status == "ACTIVE"
                flags = []
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
                    source="Statutory Registry (Simulated)",
                )

        return RegistryVerificationResult(
            registry_name="MSME Udyam Portal",
            query_identifier=clean_udyam,
            status=VerificationStatus.NOT_FOUND,
            is_valid=False,
            risk_flags=[f"Udyam number {clean_udyam} not found on official MSME portal"],
            source="Statutory Registry (Simulated)",
        )

    def check_debarment(self, pan: Optional[str]) -> RegistryVerificationResult:
        """Check GeM Central Debarment / Blacklist registry."""
        if not pan:
            return RegistryVerificationResult(
                registry_name="GeM Central Debarment Watchlist",
                query_identifier="N/A",
                status=VerificationStatus.NOT_FOUND,
                is_valid=True,
                risk_flags=[],
                source="Statutory Registry (Simulated)",
            )

        clean_pan = pan.strip().upper()

        # 1. Query 10-bidder database
        if clean_pan in self.bidders_by_pan:
            bidder = self.bidders_by_pan[clean_pan]
            comp = (bidder.get("documents") or {}).get("compliance_background") or {}
            is_blacklisted = comp.get("central_blacklist_match", False)
            meta = comp.get("blacklist_metadata") or {}
            flags: List[str] = []
            if is_blacklisted:
                flags.append(
                    f"CRITICAL: Entity is BLACKLISTED until {meta.get('end_date')} "
                    f"by {meta.get('debarred_by')}. Reason: {meta.get('reason')}"
                )

            return RegistryVerificationResult(
                registry_name="GeM Central Debarment Watchlist",
                query_identifier=clean_pan,
                status=VerificationStatus.BLACKLISTED if is_blacklisted else VerificationStatus.ACTIVE,
                is_valid=not is_blacklisted,
                registered_name=bidder.get("company_name"),
                details=meta if is_blacklisted else comp,
                risk_flags=flags,
                source="Statutory Registry (Simulated)",
            )

        # 2. Query legacy entities
        for entity in self.entities:
            if entity.get("pan_details", {}).get("pan", "").upper() == clean_pan:
                debar = entity.get("debarment_status", {})
                is_blacklisted = debar.get("is_blacklisted", False)
                flags = []
                if is_blacklisted:
                    flags.append(
                        f"CRITICAL: Entity is BLACKLISTED until {debar.get('debarment_period')} "
                        f"by {debar.get('banned_by')}. Reason: {debar.get('reason')}"
                    )

                return RegistryVerificationResult(
                    registry_name="GeM Central Debarment Watchlist",
                    query_identifier=clean_pan,
                    status=VerificationStatus.BLACKLISTED if is_blacklisted else VerificationStatus.ACTIVE,
                    is_valid=not is_blacklisted,
                    registered_name=entity.get("company_name"),
                    details=debar,
                    risk_flags=flags,
                    source="Statutory Registry (Simulated)",
                )

        # Default clean record if unknown
        return RegistryVerificationResult(
            registry_name="GeM Central Debarment Watchlist",
            query_identifier=clean_pan,
            status=VerificationStatus.ACTIVE,
            is_valid=True,
            details={"is_blacklisted": False},
            risk_flags=[],
            source="Statutory Registry (Simulated)",
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

        return EntityFullVerification(
            pan_verification=pan_res,
            gstin_verification=gst_res,
            udyam_verification=udyam_res,
            debarment_check=debar_res,
            is_overall_authentic=is_authentic,
            summary_flags=all_flags,
            gateway_provider="Government Statutory Registry Gateway",
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
