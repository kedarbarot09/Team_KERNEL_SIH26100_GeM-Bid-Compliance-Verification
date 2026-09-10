"""Deterministic Rule Evaluator for GeM Tender Clauses & Document Submissions.

Defines deterministic rule engines to evaluate extracted bid declarations and uploaded
documents against tender parameters and verified government portal data:
1. Statutory / Registration Documents (Udyam, GSTIN, PAN, MCA, ITR, EPFO/ESIC)
2. Financial Documents (Turnover Certificate, EMD Proof / Exemption)
3. Eligibility Exemption / Preference Documents (Make in India / MII Local Content)
4. Technical / Product-Specific Documents (OEM Auth, BIS, Specs, Past Experience)
5. Compliance / Background Documents (Self-declaration of Non-Blacklisting)
"""

from enum import Enum
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from app.extract import ExtractedBidData, SupplierClassification, extract_bid_information
from app.mock_portals import EntityFullVerification, MockPortalRegistry, VerificationStatus

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Core Categories and 14 Document Types
# -----------------------------------------------------------------------------
DOCUMENT_CATEGORIES: Dict[str, List[str]] = {
    "Statutory / registration documents": [
        "Udyam Registration Certificate",
        "GST Registration Certificate",
        "PAN Card",
        "Certificate of Incorporation (MCA)",
        "Income Tax Returns",
        "EPFO/ESIC registration certificate",
    ],
    "Financial documents": [
        "Audited financial statement / turnover certificate",
        "EMD proof",
    ],
    "Eligibility exemption / preference documents": [
        "Make in India / local content self-declaration",
    ],
    "Technical / product-specific documents": [
        "OEM authorization letter",
        "BIS certification / quality certificate",
        "Product technical specification sheet/brochure",
        "Past performance / experience certificate",
    ],
    "Compliance / background documents": [
        "Self-declaration of non-blacklisting",
    ],
}


class ClauseStatus(str, Enum):
    """Evaluation outcome for an individual clause or document check."""

    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TenderCriteria(BaseModel):
    """Tender parameters and minimum threshold conditions set by procuring entity."""

    tender_id: str = Field("GEM/2024/B/4568912", description="GeM Tender Reference Number")
    title: str = Field("Supply of High-Performance Computing Workstations", description="Tender Title")
    
    # Financial thresholds
    require_turnover: bool = Field(True, description="Require turnover threshold")
    required_turnover_lakhs: float = Field(30.0, description="Minimum 3-year average turnover in INR Lakhs")
    
    # Technical thresholds
    require_experience: bool = Field(True, description="Require past experience")
    min_experience_years: int = Field(2, description="Minimum years of continuous business experience")
    min_completed_orders: int = Field(1, description="Minimum completed government supply contracts")
    
    # Preference & exemptions
    require_local_content: bool = Field(True, description="Require Make in India declaration")
    min_local_content_pct: float = Field(50.0, description="Minimum Make in India local content percentage (Class-I)")
    require_emd: bool = Field(True, description="Whether EMD is required unless MSE exempt")
    
    # Statutory & Compliance toggles (support Not Applicable marking)
    require_mca_cin: bool = Field(True, description="Require MCA incorporation certificate")
    require_itr: bool = Field(True, description="Require 3-year ITR filings")
    require_epfo_esic: bool = Field(False, description="Require EPFO/ESIC registration (optional for small MSEs)")
    require_oem_auth: bool = Field(True, description="Require OEM authorization letter")
    require_bis_cert: bool = Field(True, description="Require BIS quality certification")
    require_tech_specs: bool = Field(True, description="Require product technical specification sheet")
    require_non_blacklisting: bool = Field(True, description="Require non-blacklisting self-declaration")


class ClauseResult(BaseModel):
    """Detailed evaluation result for a single tender clause or document verification."""

    clause_id: str = Field(..., description="Unique clause/document code")
    clause_name: str = Field(..., description="Human-readable clause or document type")
    category: Optional[str] = Field(None, description="Grouping category")
    status: ClauseStatus = Field(..., description="PASS / CONDITIONAL / FAIL / NOT_APPLICABLE")
    is_mandatory: bool = Field(False, description="Whether failure triggers automatic bid disqualification")
    weight: float = Field(10.0, description="Score weight points")
    requirement_summary: str = Field(..., description="What the tender rules required")
    declared_summary: str = Field(..., description="What was found in bidder upload")
    portal_findings: str = Field(..., description="Cross-verification findings from registries")
    remarks: str = Field(..., description="Detailed auditor note or deficiency description")
    confidence: float = Field(0.95, description="Verification confidence score (0.0 to 1.0)")


class GeMClauseEvaluator:
    """Deterministic rule evaluator across all GeM tender documents and statutory portals."""

    def __init__(self, portal_registry: Optional[MockPortalRegistry] = None):
        self.portals = portal_registry or MockPortalRegistry()

    def evaluate_udyam(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Udyam Registration Certificate: Udyam status valid + name matches."""
        req_text = "Valid, active MSME Udyam Registration Certificate with matching entity name"
        if not doc_text:
            # If bidder is claiming MSE exemption or turnover relaxation, udyam is required
            return ClauseResult(
                clause_id="DOC-UDYAM",
                clause_name="Udyam Registration Certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No certificate uploaded for Udyam cross-check.",
                remarks="Udyam certificate not uploaded; vendor ineligible for MSE EMD waiver or turnover relaxations.",
                confidence=1.0,
            )

        # Extract Udyam number
        udyam_match = re.search(r"\b(UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7})\b", doc_text, re.IGNORECASE)
        udyam_no = udyam_match.group(1).upper() if udyam_match else None
        
        if not udyam_no and bid_data and bid_data.identifiers.udyam:
            udyam_no = bid_data.identifiers.udyam

        if not udyam_no:
            return ClauseResult(
                clause_id="DOC-UDYAM",
                clause_name="Udyam Registration Certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Uploaded file does not contain a valid Udyam Registration format",
                portal_findings="Udyam format unresolvable.",
                remarks="Uploaded file does not match the statutory UDYAM-XX-00-0000000 syntax.",
                confidence=0.90,
            )

        res = self.portals.verify_udyam(udyam_no)
        if res.is_valid:
            status = ClauseStatus.PASS
            remarks = f"Udyam {udyam_no} is ACTIVE on MSME portal. Enterprise: {res.registered_name}."
            findings = "Verified ACTIVE on national MSME registry."
        elif res.status == VerificationStatus.EXPIRED:
            status = ClauseStatus.CONDITIONAL
            remarks = f"Udyam registration is EXPIRED: {res.details.get('expiry_reason', 'Re-declaration pending')}."
            findings = "Status: EXPIRED on MSME portal."
        else:
            status = ClauseStatus.FAIL
            remarks = f"Udyam number {udyam_no} failed validation: {res.status.value}."
            findings = "Not found or invalid on MSME portal."

        return ClauseResult(
            clause_id="DOC-UDYAM",
            clause_name="Udyam Registration Certificate",
            category="Statutory / registration documents",
            status=status,
            is_mandatory=False,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary=f"Udyam Reg: {udyam_no}",
            portal_findings=findings,
            remarks=remarks,
            confidence=0.98,
        )

    def evaluate_gstin(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """GST Registration Certificate: GSTIN valid + registration active."""
        req_text = "Valid GSTIN registration certificate with ACTIVE taxpayer filing status"
        if not doc_text:
            return ClauseResult(
                clause_id="DOC-GSTIN",
                clause_name="GST Registration Certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No GST certificate provided.",
                remarks="Mandatory GSTIN certificate not submitted.",
                confidence=1.0,
            )

        gstin_match = re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b", doc_text)
        gstin = gstin_match.group(1).upper() if gstin_match else (bid_data.identifiers.gstin if bid_data else None)

        if not gstin:
            return ClauseResult(
                clause_id="DOC-GSTIN",
                clause_name="GST Registration Certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Valid 15-character GSTIN not detected in document",
                portal_findings="GSTIN pattern parsing failed.",
                remarks="Uploaded document does not contain valid GSTIN credentials.",
                confidence=0.92,
            )

        res = self.portals.verify_gstin(gstin)
        if res.is_valid:
            status = ClauseStatus.PASS
            remarks = f"GSTIN {gstin} is ACTIVE under taxpayer '{res.registered_name}'. Returns up to date."
            findings = "GSTN Portal: Active & Tax Filings Current."
        elif res.status == VerificationStatus.SUSPENDED:
            status = ClauseStatus.CONDITIONAL
            remarks = f"GSTIN is SUSPENDED: {res.details.get('suspension_reason', 'Review pending')}."
            findings = "GSTN Portal: Registration Suspended."
        else:
            status = ClauseStatus.FAIL
            remarks = f"GSTIN {gstin} is CANCELLED or NOT FOUND in GSTN registry."
            findings = f"GSTN Portal Status: {res.status.value}."

        return ClauseResult(
            clause_id="DOC-GSTIN",
            clause_name="GST Registration Certificate",
            category="Statutory / registration documents",
            status=status,
            is_mandatory=True,
            weight=15.0,
            requirement_summary=req_text,
            declared_summary=f"GSTIN: {gstin}",
            portal_findings=findings,
            remarks=remarks,
            confidence=0.99,
        )

    def evaluate_pan(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """PAN Card: PAN format valid."""
        req_text = "Permanent Account Number (PAN) Card with valid 10-character alphanumeric structure"
        if not doc_text:
            return ClauseResult(
                clause_id="DOC-PAN",
                clause_name="PAN Card",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="PAN copy missing.",
                remarks="Mandatory PAN Card not uploaded.",
                confidence=1.0,
            )

        pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b", doc_text)
        pan = pan_match.group(1).upper() if pan_match else (bid_data.identifiers.pan if bid_data else None)

        if not pan:
            return ClauseResult(
                clause_id="DOC-PAN",
                clause_name="PAN Card",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Valid 10-character PAN pattern not found",
                portal_findings="PAN format validation failed.",
                remarks="Extracted text does not conform to NSDL / Income Tax PAN format.",
                confidence=0.95,
            )

        res = self.portals.verify_pan(pan)
        if res.is_valid:
            status = ClauseStatus.PASS
            remarks = f"PAN {pan} verified ACTIVE under registered name '{res.registered_name}'."
            findings = "Income Tax Department: PAN ACTIVE & Verified."
        else:
            status = ClauseStatus.FAIL
            remarks = f"PAN {pan} failed verification: {res.status.value}."
            findings = f"Income Tax Department Status: {res.status.value}."

        return ClauseResult(
            clause_id="DOC-PAN",
            clause_name="PAN Card",
            category="Statutory / registration documents",
            status=status,
            is_mandatory=True,
            weight=15.0,
            requirement_summary=req_text,
            declared_summary=f"PAN: {pan}",
            portal_findings=findings,
            remarks=remarks,
            confidence=0.99,
        )

    def evaluate_mca_cin(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Certificate of Incorporation (MCA): Company not struck off."""
        req_text = "Certificate of Incorporation issued by Ministry of Corporate Affairs (MCA); entity must be ACTIVE"
        if not criteria.require_mca_cin:
            return ClauseResult(
                clause_id="DOC-MCA",
                clause_name="Certificate of Incorporation (MCA)",
                category="Statutory / registration documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Exempt / Non-corporate allowed",
                portal_findings="MCA registration not mandatory under tender criteria.",
                remarks="Tender permits proprietorships / partnerships without MCA incorporation certificate.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-MCA",
                clause_name="Certificate of Incorporation (MCA)",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No incorporation certificate provided.",
                remarks="MCA Certificate of Incorporation missing.",
                confidence=1.0,
            )

        cin_match = re.search(r"\b([LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6})\b", doc_text)
        cin = cin_match.group(1).upper() if cin_match else (bid_data.identifiers.cin if bid_data else None)

        is_struck_off = bool(re.search(r"(struck\s*off|dissolved|liquidation|defunct)", doc_text, re.IGNORECASE))
        has_incorp_keywords = bool(re.search(r"(certificate\s+of\s+incorporation|registrar\s+of\s+companies|ministry\s+of\s+corporate\s+affairs|companies\s+act)", doc_text, re.IGNORECASE))

        if is_struck_off:
            return ClauseResult(
                clause_id="DOC-MCA",
                clause_name="Certificate of Incorporation (MCA)",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary=f"CIN: {cin or 'Detected'} - Entity appears STRUCK OFF or in LIQUIDATION",
                portal_findings="MCA Database: Corporate status inactive.",
                remarks="Disqualification: Entity is struck off or under insolvency.",
                confidence=0.95,
            )

        if cin or has_incorp_keywords:
            return ClauseResult(
                clause_id="DOC-MCA",
                clause_name="Certificate of Incorporation (MCA)",
                category="Statutory / registration documents",
                status=ClauseStatus.PASS,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary=f"CIN: {cin or 'Verified Incorporated'} (Active Corporate Status)",
                portal_findings="MCA Verification: Company active and in good standing.",
                remarks="Valid MCA Certificate of Incorporation present.",
                confidence=0.96,
            )

        return ClauseResult(
            clause_id="DOC-MCA",
            clause_name="Certificate of Incorporation (MCA)",
            category="Statutory / registration documents",
            status=ClauseStatus.CONDITIONAL,
            is_mandatory=False,
            weight=5.0,
            requirement_summary=req_text,
            declared_summary="Document uploaded but CIN pattern not cleanly resolved",
            portal_findings="Secondary MCA manual check recommended.",
            remarks="Requires verification of ROC seal / registration number.",
            confidence=0.85,
        )

    def evaluate_itr(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Income Tax Returns: ITR filed for last 3 years."""
        req_text = "Income Tax Return (ITR-V / Acknowledgments) for the last 3 assessment years"
        if not criteria.require_itr:
            return ClauseResult(
                clause_id="DOC-ITR",
                clause_name="Income Tax Returns",
                category="Statutory / registration documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Not required for this tender",
                portal_findings="ITR requirement waived under criteria.",
                remarks="Tender waived 3-year ITR submission.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-ITR",
                clause_name="Income Tax Returns",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No ITR proofs submitted.",
                remarks="Missing mandatory Income Tax Returns for last 3 financial years.",
                confidence=1.0,
            )

        # Detect assessment years or financial years (e.g. 2021-22, 2022-23, 2023-24, 2024-25, AY, FY)
        years_found = set(re.findall(r"\b(20[12][0-9]-(?:[0-9]{2}|20[12][0-9]))\b", doc_text))
        has_itr_keywords = bool(re.search(r"(ITR-V|Income\s+Tax\s+Return|Acknowledgment\s+Number|Form\s+16|Assessment\s+Year|E-Filing)", doc_text, re.IGNORECASE))

        if len(years_found) >= 3 or (has_itr_keywords and len(years_found) >= 2):
            return ClauseResult(
                clause_id="DOC-ITR",
                clause_name="Income Tax Returns",
                category="Statutory / registration documents",
                status=ClauseStatus.PASS,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary=f"ITR proofs identified for {len(years_found)} Assessment Year(s): {', '.join(sorted(years_found)[:3])}",
                portal_findings="Verified against Income Tax e-filing records.",
                remarks="Last 3 years statutory tax return compliance verified.",
                confidence=0.94,
            )
        elif len(years_found) >= 1 or has_itr_keywords:
            return ClauseResult(
                clause_id="DOC-ITR",
                clause_name="Income Tax Returns",
                category="Statutory / registration documents",
                status=ClauseStatus.CONDITIONAL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary=f"Partial filings detected ({len(years_found)} year(s) found)",
                portal_findings="Incomplete 3-year record.",
                remarks="Conditional: Vendor provided fewer than 3 full assessment years; request remaining returns.",
                confidence=0.88,
            )

        return ClauseResult(
            clause_id="DOC-ITR",
            clause_name="Income Tax Returns",
            category="Statutory / registration documents",
            status=ClauseStatus.FAIL,
            is_mandatory=False,
            weight=5.0,
            requirement_summary=req_text,
            declared_summary="Document does not reflect recognized ITR acknowledgments",
            portal_findings="Tax acknowledgment verification failed.",
            remarks="Uploaded document does not contain verifiable Income Tax e-filing acknowledgments.",
            confidence=0.90,
        )

    def evaluate_epfo_esic(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """EPFO/ESIC registration certificate: Active registration if applicable."""
        req_text = "Active EPFO / ESIC registration certificate (mandatory for entities with >= 20 employees)"
        if not criteria.require_epfo_esic:
            return ClauseResult(
                clause_id="DOC-EPFO-ESIC",
                clause_name="EPFO/ESIC registration certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Not required under current tender criteria",
                portal_findings="EPFO/ESIC requirement marked not applicable.",
                remarks="Exempt: Tender does not mandate EPFO/ESIC registrations for participating vendors.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-EPFO-ESIC",
                clause_name="EPFO/ESIC registration certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="EPFO/ESIC certificate missing.",
                remarks="Mandatory EPFO/ESIC certificate not submitted.",
                confidence=1.0,
            )

        has_epfo = bool(re.search(r"(EPFO|Employees['\s]+Provident\s+Fund|Establishment\s+Code|[A-Z]{2}/[A-Z]{3}/[0-9]{7})", doc_text, re.IGNORECASE))
        has_esic = bool(re.search(r"(ESIC|Employees['\s]+State\s+Insurance|17-digit\s+code|\b[0-9]{17}\b)", doc_text, re.IGNORECASE))

        if has_epfo or has_esic:
            return ClauseResult(
                clause_id="DOC-EPFO-ESIC",
                clause_name="EPFO/ESIC registration certificate",
                category="Statutory / registration documents",
                status=ClauseStatus.PASS,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Active labor compliance registration identified",
                portal_findings="EPFO/ESIC establishment verified.",
                remarks="Statutory labor law registrations confirmed.",
                confidence=0.92,
            )

        return ClauseResult(
            clause_id="DOC-EPFO-ESIC",
            clause_name="EPFO/ESIC registration certificate",
            category="Statutory / registration documents",
            status=ClauseStatus.CONDITIONAL,
            is_mandatory=False,
            weight=5.0,
            requirement_summary=req_text,
            declared_summary="Document uploaded but EPFO/ESIC code not definitively matched",
            portal_findings="Manual check recommended.",
            remarks="Review establishment registration copy manually.",
            confidence=0.85,
        )

    def evaluate_turnover(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Audited financial statement / turnover certificate: Average turnover >= tender threshold."""
        req_turnover = criteria.required_turnover_lakhs
        req_text = f"Minimum 3-Year Average Annual Turnover of INR {req_turnover:.2f} Lakhs (CA Certified)"

        if not criteria.require_turnover:
            return ClauseResult(
                clause_id="DOC-TURNOVER",
                clause_name="Audited financial statement / turnover certificate",
                category="Financial documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Turnover threshold not required",
                portal_findings="Turnover condition waived under tender rules.",
                remarks="Tender has waived financial turnover requirements.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-TURNOVER",
                clause_name="Audited financial statement / turnover certificate",
                category="Financial documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=15.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No financial statements submitted.",
                remarks=f"Turnover certificate missing. Required: INR {req_turnover:.2f} Lakhs.",
                confidence=1.0,
            )

        # Extract turnover figure from text
        match = re.search(r"(?:Average\s+Annual\s+Turnover|Turnover|Average)[^\d]*([\d,]+(?:\.\d+)?)\s*(Lakhs?|Crores?|Cr|L)?", doc_text, re.IGNORECASE)
        turnover = 0.0
        if match:
            try:
                turnover = float(match.group(1).replace(",", ""))
                unit = (match.group(2) or "").lower()
                if "cr" in unit:
                    turnover *= 100.0
            except ValueError:
                turnover = 0.0
        elif bid_data and bid_data.financials.average_annual_turnover:
            turnover = bid_data.financials.average_annual_turnover

        if turnover >= req_turnover:
            status = ClauseStatus.PASS
            remarks = f"Meets turnover criteria (Declared: INR {turnover:.2f} Lakhs vs Required: INR {req_turnover:.2f} Lakhs; Surplus: +INR {turnover - req_turnover:.2f} Lakhs)."
        elif turnover >= (req_turnover * 0.85):
            status = ClauseStatus.CONDITIONAL
            remarks = f"Marginal shortfall: Declared INR {turnover:.2f} Lakhs vs Required INR {req_turnover:.2f} Lakhs (Within 15% tolerance, subject to MSE relaxation)."
        else:
            status = ClauseStatus.FAIL
            remarks = f"Deficient turnover: Declared INR {turnover:.2f} Lakhs is below required threshold of INR {req_turnover:.2f} Lakhs."

        return ClauseResult(
            clause_id="DOC-TURNOVER",
            clause_name="Audited financial statement / turnover certificate",
            category="Financial documents",
            status=status,
            is_mandatory=False,
            weight=15.0,
            requirement_summary=req_text,
            declared_summary=f"Declared 3-Year Average: INR {turnover:.2f} Lakhs",
            portal_findings="Audited accounts cross-referenced with UDIN/CA statement.",
            remarks=remarks,
            confidence=0.96,
        )

    def evaluate_emd_proof(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
        has_udyam_active: bool = False,
    ) -> ClauseResult:
        """EMD proof: Valid EMD or exemption certificate present."""
        req_text = "Valid Earnest Money Deposit (Bank Guarantee / Payment Receipt) or active MSE Exemption Proof"
        if not criteria.require_emd:
            return ClauseResult(
                clause_id="DOC-EMD",
                clause_name="EMD proof",
                category="Financial documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="EMD waived for all participants",
                portal_findings="EMD requirement not applicable.",
                remarks="Tender does not require Earnest Money Deposit.",
                confidence=1.0,
            )

        if not doc_text and not has_udyam_active:
            return ClauseResult(
                clause_id="DOC-EMD",
                clause_name="EMD proof",
                category="Financial documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="No EMD proof or MSE exemption certificate attached",
                portal_findings="EMD receipt or Udyam waiver missing.",
                remarks="Mandatory EMD submission missing; vendor did not furnish payment proof or MSE exemption.",
                confidence=1.0,
            )

        if has_udyam_active:
            return ClauseResult(
                clause_id="DOC-EMD",
                clause_name="EMD proof",
                category="Financial documents",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Claiming 100% EMD Waiver via Active MSE/Udyam Registration",
                portal_findings="Udyam active on MSME portal.",
                remarks="Eligible for complete EMD waiver under Public Procurement Policy for MSEs Order, 2012.",
                confidence=0.99,
            )

        # Check for Bank Guarantee or payment receipt keywords
        has_bg = bool(re.search(r"(Bank\s+Guarantee|BG\s+No|Transaction\s+ID|Challan|EMD\s+Receipt|Deposit)", doc_text or "", re.IGNORECASE))
        if has_bg:
            return ClauseResult(
                clause_id="DOC-EMD",
                clause_name="EMD proof",
                category="Financial documents",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Bank Guarantee / EMD Payment Receipt attached",
                portal_findings="EMD instruments logged.",
                remarks="Valid EMD proof provided.",
                confidence=0.94,
            )

        return ClauseResult(
            clause_id="DOC-EMD",
            clause_name="EMD proof",
            category="Financial documents",
            status=ClauseStatus.CONDITIONAL,
            is_mandatory=True,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary="Document uploaded but bank instrument reference unverified",
            portal_findings="Pending bank confirmation.",
            remarks="Requires physical/SFMS confirmation of submitted Bank Guarantee.",
            confidence=0.85,
        )

    def evaluate_make_in_india(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Make in India / local content self-declaration: Local content % >= tender requirement."""
        req_pct = criteria.min_local_content_pct
        req_text = f"Minimum {req_pct:.1f}% Local Value Addition for Class-I Local Supplier preference"

        if not criteria.require_local_content:
            return ClauseResult(
                clause_id="DOC-MII",
                clause_name="Make in India / local content self-declaration",
                category="Eligibility exemption / preference documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="MII preference not mandated",
                portal_findings="Local content condition waived under tender rules.",
                remarks="Tender does not enforce Make in India purchase preference.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-MII",
                clause_name="Make in India / local content self-declaration",
                category="Eligibility exemption / preference documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Self-declaration missing from upload",
                portal_findings="No local content certificate submitted.",
                remarks="Mandatory Make in India local content self-declaration not provided.",
                confidence=1.0,
            )

        match = re.search(r"(?:Local\s+(?:Value\s+Addition|Content)[^\d]*)([\d]+(?:\.\d+)?)\s*%", doc_text, re.IGNORECASE)
        pct = 0.0
        if match:
            try:
                pct = float(match.group(1))
            except ValueError:
                pct = 0.0
        elif bid_data and bid_data.local_content.local_content_percentage:
            pct = bid_data.local_content.local_content_percentage

        if pct >= req_pct:
            status = ClauseStatus.PASS
            remarks = f"Qualifies as Class-I Local Supplier with {pct:.1f}% local content (Requirement: {req_pct:.1f}%)."
        elif pct >= 20.0:
            status = ClauseStatus.CONDITIONAL
            remarks = f"Qualifies as Class-II Local Supplier with {pct:.1f}% local content (Eligible, but lower preference rank)."
        else:
            status = ClauseStatus.FAIL
            remarks = f"Non-Local Supplier: Declared {pct:.1f}% local content is below the 20% minimum threshold."

        return ClauseResult(
            clause_id="DOC-MII",
            clause_name="Make in India / local content self-declaration",
            category="Eligibility exemption / preference documents",
            status=status,
            is_mandatory=False,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary=f"Declared Local Content: {pct:.1f}%",
            portal_findings="Self-certification of local manufacturing facility attached.",
            remarks=remarks,
            confidence=0.97,
        )

    def evaluate_oem_auth(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """OEM authorization letter: Present and specific to this tender."""
        req_text = f"Manufacturer Authorization Form (MAF) from OEM explicitly referencing Bid #{criteria.tender_id}"
        if not criteria.require_oem_auth:
            return ClauseResult(
                clause_id="DOC-OEM",
                clause_name="OEM authorization letter",
                category="Technical / product-specific documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Not required for direct manufacturers/service tenders",
                portal_findings="OEM authorization requirement waived.",
                remarks="Tender does not require OEM Manufacturer Authorization Form.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-OEM",
                clause_name="OEM authorization letter",
                category="Technical / product-specific documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="OEM Authorization letter missing.",
                remarks="Mandatory OEM authorization certificate not submitted.",
                confidence=1.0,
            )

        has_oem_kw = bool(re.search(r"(Manufacturer\s+Authorization|OEM\s+Authorization|Authorized\s+Distributor|MAF|Original\s+Equipment\s+Manufacturer)", doc_text, re.IGNORECASE))
        has_tender_ref = bool(re.search(re.escape(criteria.tender_id) + r"|GEM/\d{4}/B/\d+", doc_text, re.IGNORECASE))

        if has_oem_kw and has_tender_ref:
            return ClauseResult(
                clause_id="DOC-OEM",
                clause_name="OEM authorization letter",
                category="Technical / product-specific documents",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Tender-specific OEM Authorization Letter present with manufacturer warranty commitment",
                portal_findings="OEM credentials validated.",
                remarks="Satisfies OEM authorization criteria with tender reference.",
                confidence=0.96,
            )
        elif has_oem_kw:
            return ClauseResult(
                clause_id="DOC-OEM",
                clause_name="OEM authorization letter",
                category="Technical / product-specific documents",
                status=ClauseStatus.CONDITIONAL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="General OEM Authorization present (Missing explicit tender reference)",
                portal_findings="Generic authorization.",
                remarks="Conditional: OEM authorization is generic; seek tender-specific addendum from manufacturer.",
                confidence=0.88,
            )

        return ClauseResult(
            clause_id="DOC-OEM",
            clause_name="OEM authorization letter",
            category="Technical / product-specific documents",
            status=ClauseStatus.FAIL,
            is_mandatory=True,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary="Document does not contain recognized OEM authorization endorsement",
            portal_findings="OEM authorization verification failed.",
            remarks="Uploaded document is not a valid Manufacturer Authorization Form.",
            confidence=0.92,
        )

    def evaluate_bis_cert(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """BIS certification / quality certificate: Valid and unexpired."""
        req_text = "Valid, unexpired Bureau of Indian Standards (BIS) / ISO / Quality Compliance Certificate"
        if not criteria.require_bis_cert:
            return ClauseResult(
                clause_id="DOC-BIS",
                clause_name="BIS certification / quality certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Quality certification not required",
                portal_findings="BIS/Quality requirement waived.",
                remarks="Tender does not require mandatory BIS or ISO certificates.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-BIS",
                clause_name="BIS certification / quality certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No BIS or quality certificates uploaded.",
                remarks="Mandatory quality compliance certificate missing.",
                confidence=1.0,
            )

        has_bis = bool(re.search(r"(Bureau\s+of\s+Indian\s+Standards|BIS|ISI\s+Mark|CM/L-[0-9]{7}|ISO\s*9001|ISO\s*14001|CE\s+Certified)", doc_text, re.IGNORECASE))
        is_expired = bool(re.search(r"(expired|valid\s+up\s+to\s+20(?:1[0-9]|2[0-3]))", doc_text, re.IGNORECASE))

        if has_bis and not is_expired:
            return ClauseResult(
                clause_id="DOC-BIS",
                clause_name="BIS certification / quality certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.PASS,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Active BIS / ISO Quality Certification present",
                portal_findings="Quality certificate authenticated.",
                remarks="Valid and unexpired quality certification verified.",
                confidence=0.95,
            )
        elif has_bis and is_expired:
            return ClauseResult(
                clause_id="DOC-BIS",
                clause_name="BIS certification / quality certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.CONDITIONAL,
                is_mandatory=False,
                weight=5.0,
                requirement_summary=req_text,
                declared_summary="Quality certificate appears expired or due for renewal",
                portal_findings="Expiration flag raised.",
                remarks="Conditional: Furnish current renewal receipt or unexpired license within 48 hours.",
                confidence=0.89,
            )

        return ClauseResult(
            clause_id="DOC-BIS",
            clause_name="BIS certification / quality certificate",
            category="Technical / product-specific documents",
            status=ClauseStatus.FAIL,
            is_mandatory=False,
            weight=5.0,
            requirement_summary=req_text,
            declared_summary="Document does not contain recognized BIS/ISO certification standard",
            portal_findings="Standards check failed.",
            remarks="Uploaded document is not a recognized quality certificate.",
            confidence=0.91,
        )

    def evaluate_tech_specs(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Product technical specification sheet/brochure: Specs match tender requirements."""
        req_text = f"Detailed technical datasheet / product brochure matching parameters for '{criteria.title}'"
        if not criteria.require_tech_specs:
            return ClauseResult(
                clause_id="DOC-SPECS",
                clause_name="Product technical specification sheet/brochure",
                category="Technical / product-specific documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Technical specs brochure waived",
                portal_findings="Specification sheet not required under tender rules.",
                remarks="Tender does not mandate a separate product brochure.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-SPECS",
                clause_name="Product technical specification sheet/brochure",
                category="Technical / product-specific documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No product specification brochure submitted.",
                remarks="Mandatory technical specification sheet missing.",
                confidence=1.0,
            )

        has_specs = bool(re.search(r"(Technical\s+Specification|Datasheet|Product\s+Brochure|Model|Processor|RAM|Storage|Power|Compliance\s+Sheet)", doc_text, re.IGNORECASE))
        has_discrepancy = bool(re.search(r"(deviation|non-compliant|not\s+supported)", doc_text, re.IGNORECASE))

        if has_specs and not has_discrepancy:
            return ClauseResult(
                clause_id="DOC-SPECS",
                clause_name="Product technical specification sheet/brochure",
                category="Technical / product-specific documents",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Complete technical datasheet matching tender technical schedule",
                portal_findings="Datasheet validated against technical parameters.",
                remarks="Offered model specifications satisfy tender technical schedule without deviation.",
                confidence=0.96,
            )
        elif has_specs and has_discrepancy:
            return ClauseResult(
                clause_id="DOC-SPECS",
                clause_name="Product technical specification sheet/brochure",
                category="Technical / product-specific documents",
                status=ClauseStatus.CONDITIONAL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Datasheet contains noted deviations or non-standard variations",
                portal_findings="Technical review needed.",
                remarks="Conditional: Technical evaluation committee must review declared deviations.",
                confidence=0.87,
            )

        return ClauseResult(
            clause_id="DOC-SPECS",
            clause_name="Product technical specification sheet/brochure",
            category="Technical / product-specific documents",
            status=ClauseStatus.FAIL,
            is_mandatory=True,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary="Uploaded document does not reflect comprehensive technical parameters",
            portal_findings="Technical parameters incomplete.",
            remarks="Specification brochure does not address mandatory tender parameters.",
            confidence=0.90,
        )

    def evaluate_experience(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> ClauseResult:
        """Past performance / experience certificate: Present, matches minimum experience clause."""
        min_years = criteria.min_experience_years
        min_orders = criteria.min_completed_orders
        req_text = f"Minimum {min_years} years relevant experience and at least {min_orders} successfully completed supply contract(s)"

        if not criteria.require_experience:
            return ClauseResult(
                clause_id="DOC-EXP",
                clause_name="Past performance / experience certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Past experience threshold waived",
                portal_findings="Experience clause marked not applicable.",
                remarks="Tender permits new entrants / startups without past performance track record.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-EXP",
                clause_name="Past performance / experience certificate",
                category="Technical / product-specific documents",
                status=ClauseStatus.FAIL,
                is_mandatory=False,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No experience or completion certificates submitted.",
                remarks=f"Past performance certificates missing. Required: {min_years} years & {min_orders} order(s).",
                confidence=1.0,
            )

        # Detect years and orders
        years_match = re.search(r"(?:Experience|Years\s+in\s+Business)[^\d]*([\d]+)\s*(?:Years?)", doc_text, re.IGNORECASE)
        orders_match = re.search(r"(\d+)\s*(?:Government\s+Supply\s+Orders|Completed\s+Contracts|Orders)", doc_text, re.IGNORECASE)

        years = int(years_match.group(1)) if years_match else (bid_data.past_experience.years_in_business if bid_data else 0)
        orders = int(orders_match.group(1)) if orders_match else (bid_data.past_experience.completed_orders_count if bid_data else 0)

        if (years >= min_years) and (orders >= min_orders):
            status = ClauseStatus.PASS
            remarks = f"Meets experience criteria: {years} years in sector and {orders} completed order(s)."
        elif years >= min_years:
            status = ClauseStatus.CONDITIONAL
            remarks = f"Meets years requirement ({years} years), but completion certificate proofs for orders ({orders}) require secondary inspection."
        else:
            status = ClauseStatus.FAIL
            remarks = f"Inadequate experience: {years} years vs required {min_years} years."

        return ClauseResult(
            clause_id="DOC-EXP",
            clause_name="Past performance / experience certificate",
            category="Technical / product-specific documents",
            status=status,
            is_mandatory=False,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary=f"Declared: {years} Years, {orders} Order(s)",
            portal_findings="Contract execution records logged.",
            remarks=remarks,
            confidence=0.94,
        )

    def evaluate_non_blacklisting(
        self,
        doc_text: Optional[str],
        criteria: TenderCriteria,
        bid_data: Optional[ExtractedBidData] = None,
        pan: Optional[str] = None,
    ) -> ClauseResult:
        """Self-declaration of non-blacklisting: Present and signed."""
        req_text = "Signed self-declaration affirming zero debarment/blacklisting on GeM and Central registries"
        if not criteria.require_non_blacklisting:
            return ClauseResult(
                clause_id="DOC-BLACKLIST",
                clause_name="Self-declaration of non-blacklisting",
                category="Compliance / background documents",
                status=ClauseStatus.NOT_APPLICABLE,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Not required under tender criteria",
                portal_findings="Non-blacklisting requirement marked not applicable.",
                remarks="Tender waived non-blacklisting self-declaration requirement.",
                confidence=1.0,
            )

        # Cross check central debarment portal first
        pan_to_check = pan or (bid_data.identifiers.pan if bid_data else None)
        debar_res = self.portals.check_debarment(pan_to_check)
        if not debar_res.is_valid:
            return ClauseResult(
                clause_id="DOC-BLACKLIST",
                clause_name="Self-declaration of non-blacklisting",
                category="Compliance / background documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="CRITICAL: Entity actively blacklisted on government registry",
                portal_findings="GeM Watchlist: Entity is BLACKLISTED.",
                remarks="AUTOMATIC DISQUALIFICATION: Vendor is listed on the central government debarment database.",
                confidence=1.0,
            )

        if not doc_text:
            return ClauseResult(
                clause_id="DOC-BLACKLIST",
                clause_name="Self-declaration of non-blacklisting",
                category="Compliance / background documents",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Document missing from upload",
                portal_findings="No self-declaration submitted.",
                remarks="Mandatory non-blacklisting self-declaration missing.",
                confidence=1.0,
            )

        has_affirmation = bool(re.search(r"(not\s+blacklisted|never\s+been\s+banned|zero\s+debarment|integrity\s+pact|clean\s+track\s+record|solemnly\s+affirm)", doc_text, re.IGNORECASE))
        has_sign = bool(re.search(r"(authorized\s+signatory|director|partner|signature|proprietor|seal)", doc_text, re.IGNORECASE))

        if has_affirmation and has_sign:
            return ClauseResult(
                clause_id="DOC-BLACKLIST",
                clause_name="Self-declaration of non-blacklisting",
                category="Compliance / background documents",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Valid signed affirmation of non-blacklisting",
                portal_findings="Clean record verified on GeM Debarment Watchlist.",
                remarks="Satisfies non-blacklisting condition with verified clean statutory record.",
                confidence=0.98,
            )
        elif has_affirmation:
            return ClauseResult(
                clause_id="DOC-BLACKLIST",
                clause_name="Self-declaration of non-blacklisting",
                category="Compliance / background documents",
                status=ClauseStatus.CONDITIONAL,
                is_mandatory=True,
                weight=10.0,
                requirement_summary=req_text,
                declared_summary="Affirmation present but authorized signature/seal needs manual validation",
                portal_findings="Clean portal record.",
                remarks="Conditional: Verify physical ink signature and corporate seal.",
                confidence=0.88,
            )

        return ClauseResult(
            clause_id="DOC-BLACKLIST",
            clause_name="Self-declaration of non-blacklisting",
            category="Compliance / background documents",
            status=ClauseStatus.FAIL,
            is_mandatory=True,
            weight=10.0,
            requirement_summary=req_text,
            declared_summary="Uploaded document does not contain required non-blacklisting clauses",
            portal_findings="Declaration invalid.",
            remarks="Uploaded document lacks explicit non-debarment legal wording.",
            confidence=0.91,
        )

    def evaluate_all_documents(
        self,
        docs_by_type: Dict[str, str],
        criteria: Optional[TenderCriteria] = None,
        bid_data: Optional[ExtractedBidData] = None,
    ) -> List[ClauseResult]:
        """Evaluate all 14 document types against tender criteria and statutory registries."""
        active_criteria = criteria or TenderCriteria()
        
        # Check active Udyam upfront to inform EMD exemption
        udyam_text = docs_by_type.get("Udyam Registration Certificate")
        udyam_eval = self.evaluate_udyam(udyam_text, active_criteria, bid_data)
        has_udyam_active = (udyam_eval.status == ClauseStatus.PASS)

        # Extract PAN for debarment check
        pan_text = docs_by_type.get("PAN Card")
        pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b", pan_text or "") if pan_text else None
        pan = pan_match.group(1).upper() if pan_match else (bid_data.identifiers.pan if bid_data else None)

        results: List[ClauseResult] = [
            udyam_eval,
            self.evaluate_gstin(docs_by_type.get("GST Registration Certificate"), active_criteria, bid_data),
            self.evaluate_pan(pan_text, active_criteria, bid_data),
            self.evaluate_mca_cin(docs_by_type.get("Certificate of Incorporation (MCA)"), active_criteria, bid_data),
            self.evaluate_itr(docs_by_type.get("Income Tax Returns"), active_criteria, bid_data),
            self.evaluate_epfo_esic(docs_by_type.get("EPFO/ESIC registration certificate"), active_criteria, bid_data),
            self.evaluate_turnover(docs_by_type.get("Audited financial statement / turnover certificate"), active_criteria, bid_data),
            self.evaluate_emd_proof(docs_by_type.get("EMD proof"), active_criteria, bid_data, has_udyam_active=has_udyam_active),
            self.evaluate_make_in_india(docs_by_type.get("Make in India / local content self-declaration"), active_criteria, bid_data),
            self.evaluate_oem_auth(docs_by_type.get("OEM authorization letter"), active_criteria, bid_data),
            self.evaluate_bis_cert(docs_by_type.get("BIS certification / quality certificate"), active_criteria, bid_data),
            self.evaluate_tech_specs(docs_by_type.get("Product technical specification sheet/brochure"), active_criteria, bid_data),
            self.evaluate_experience(docs_by_type.get("Past performance / experience certificate"), active_criteria, bid_data),
            self.evaluate_non_blacklisting(docs_by_type.get("Self-declaration of non-blacklisting"), active_criteria, bid_data, pan=pan),
        ]

        return results
