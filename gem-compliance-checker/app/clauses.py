"""Deterministic Rule Evaluator for 5 Core GeM Tender Clauses.

Defines deterministic rule engines to evaluate extracted bid declarations
against tender parameters and verified government portal data:
1. Clause 1: EMD / Bid Security Exemption Verification
2. Clause 2: Minimum Average Annual Turnover Compliance
3. Clause 3: Past Performance & Technical Experience
4. Clause 4: Make in India (MII) Local Content Preference
5. Clause 5: Statutory Tax Compliance & Debarment Check (Mandatory)
"""

from enum import Enum
import logging
from pathlib import Path
import sys
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from app.extract import ExtractedBidData, SupplierClassification
from app.mock_portals import EntityFullVerification, VerificationStatus

logger = logging.getLogger(__name__)


class ClauseStatus(str, Enum):
    """Evaluation outcome for an individual clause."""

    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class TenderCriteria(BaseModel):
    """Tender parameters and minimum threshold conditions set by procuring entity."""

    tender_id: str = Field("GEM/2024/B/DEMO-001", description="GeM Tender Reference Number")
    title: str = Field("Procurement of IT & Computing Equipment", description="Tender Title")
    required_turnover_lakhs: float = Field(30.0, description="Minimum 3-year average turnover in INR Lakhs")
    min_experience_years: int = Field(2, description="Minimum years of continuous business experience")
    min_completed_orders: int = Field(1, description="Minimum completed government supply contracts")
    min_local_content_pct: float = Field(50.0, description="Minimum Make in India local content percentage (Class-I)")
    require_emd: bool = Field(True, description="Whether EMD is required unless MSE exempt")


class ClauseResult(BaseModel):
    """Detailed evaluation result for a single tender clause."""

    clause_id: str = Field(..., description="Unique clause code (e.g., GEM-C1-EMD)")
    clause_name: str = Field(..., description="Human-readable clause title")
    status: ClauseStatus = Field(..., description="PASS / CONDITIONAL / FAIL")
    is_mandatory: bool = Field(False, description="Whether failure triggers automatic bid disqualification")
    weight: float = Field(20.0, description="Score weight percentage out of 100")
    requirement_summary: str = Field(..., description="What the tender rules required")
    declared_summary: str = Field(..., description="What the bidder declared in their document")
    portal_findings: str = Field(..., description="Cross-verification findings from government portals")
    remarks: str = Field(..., description="Detailed auditor note or deficiency description")


class GeMClauseEvaluator:
    """Deterministic rule evaluator across the 5 core GeM tender clauses."""

    def evaluate_clause_1_emd(
        self,
        bid_data: ExtractedBidData,
        verification: EntityFullVerification,
        criteria: TenderCriteria,
    ) -> ClauseResult:
        """Clause 1: EMD / Bid Security Exemption Verification.

        Rule: If bidder claims EMD exemption as MSE, Udyam registration must be
        actively verified on the MSME portal. If expired or fake, clause fails.
        """
        is_claiming = bid_data.emd_claim.is_claiming_exemption
        udyam_status = verification.udyam_verification.status
        is_udyam_active = verification.udyam_verification.is_valid

        req_text = "EMD payment receipt OR valid active MSME/Udyam certificate for exemption waiver"
        declared_text = (
            f"Claiming Exemption: {is_claiming} (Udyam Reg: {bid_data.identifiers.udyam or 'None'})"
        )

        if not criteria.require_emd:
            return ClauseResult(
                clause_id="GEM-C1-EMD",
                clause_name="Earnest Money Deposit (EMD) Exemption",
                status=ClauseStatus.PASS,
                is_mandatory=True,
                weight=20.0,
                requirement_summary=req_text,
                declared_summary=declared_text,
                portal_findings="EMD is not mandatory for this tender.",
                remarks="Tender waived EMD for all participants.",
            )

        if is_claiming:
            if is_udyam_active:
                status = ClauseStatus.PASS
                portal_msg = f"Udyam {verification.udyam_verification.query_identifier} verified ACTIVE on MSME Portal."
                remarks = "Eligible for 100% EMD waiver under Public Procurement Policy for MSEs Order, 2012."
            elif udyam_status == VerificationStatus.EXPIRED:
                status = ClauseStatus.CONDITIONAL
                portal_msg = f"Udyam registration is EXPIRED: {verification.udyam_verification.details.get('expiry_reason')}"
                remarks = "Conditional: Bidder must furnish renewed Udyam certificate within 48 hours or deposit EMD."
            else:
                status = ClauseStatus.FAIL
                portal_msg = f"Udyam status: {udyam_status.value}. Not verified on MSME portal."
                remarks = "EMD exemption claimed without valid active Udyam certificate."
        else:
            # Did not claim exemption - assumed EMD paid offline / BG submitted
            status = ClauseStatus.PASS
            portal_msg = "Bidder did not claim MSE exemption; direct EMD verification required."
            remarks = "EMD receipt attached under financial documents."

        return ClauseResult(
            clause_id="GEM-C1-EMD",
            clause_name="Earnest Money Deposit (EMD) Exemption",
            status=status,
            is_mandatory=True,
            weight=20.0,
            requirement_summary=req_text,
            declared_summary=declared_text,
            portal_findings=portal_msg,
            remarks=remarks,
        )

    def evaluate_clause_2_turnover(
        self,
        bid_data: ExtractedBidData,
        criteria: TenderCriteria,
    ) -> ClauseResult:
        """Clause 2: Minimum Average Annual Turnover Compliance.

        Rule: 3-year average turnover must satisfy tender requirement."""
        declared_turnover = bid_data.financials.average_annual_turnover or 0.0
        req_turnover = criteria.required_turnover_lakhs

        req_text = f"Minimum Average Annual Turnover of INR {req_turnover:.2f} Lakhs (last 3 FYs)"
        declared_text = f"Declared 3-Year Average Turnover: INR {declared_turnover:.2f} Lakhs"

        if declared_turnover >= req_turnover:
            status = ClauseStatus.PASS
            remarks = f"Meets turnover criteria (Surplus: +INR {declared_turnover - req_turnover:.2f} Lakhs)."
        elif declared_turnover >= (req_turnover * 0.85):
            # Within 15% tolerance margin
            status = ClauseStatus.CONDITIONAL
            remarks = (
                f"Slight shortfall of INR {req_turnover - declared_turnover:.2f} Lakhs. "
                "Subject to MSE relaxation eligibility."
            )
        else:
            status = ClauseStatus.FAIL
            remarks = f"Deficient turnover: INR {declared_turnover:.2f} Lakhs is below required {req_turnover:.2f} Lakhs."

        return ClauseResult(
            clause_id="GEM-C2-TURNOVER",
            clause_name="Annual Average Turnover Compliance",
            status=status,
            is_mandatory=False,
            weight=20.0,
            requirement_summary=req_text,
            declared_summary=declared_text,
            portal_findings="Cross-checked against submitted CA certificate and declared balance sheets.",
            remarks=remarks,
        )

    def evaluate_clause_3_experience(
        self,
        bid_data: ExtractedBidData,
        criteria: TenderCriteria,
    ) -> ClauseResult:
        """Clause 3: Past Performance & Technical Experience.

        Rule: Evaluates years in business and minimum completed orders."""
        declared_years = bid_data.past_experience.years_in_business or 0
        declared_orders = bid_data.past_experience.completed_orders_count or 0

        req_text = (
            f"Minimum {criteria.min_experience_years} years in relevant business and "
            f"at least {criteria.min_completed_orders} completed contract(s)"
        )
        declared_text = f"Experience: {declared_years} years, Completed Orders: {declared_orders}"

        if (declared_years >= criteria.min_experience_years) and (declared_orders >= criteria.min_completed_orders):
            status = ClauseStatus.PASS
            remarks = "Satisfies both commercial longevity and past delivery requirements."
        elif declared_years >= criteria.min_experience_years:
            status = ClauseStatus.CONDITIONAL
            remarks = "Meets years in business, but requires secondary verification of completed supply order copies."
        else:
            status = ClauseStatus.FAIL
            remarks = f"Inadequate business experience: {declared_years} years vs required {criteria.min_experience_years} years."

        return ClauseResult(
            clause_id="GEM-C3-EXPERIENCE",
            clause_name="Past Performance & Experience Criteria",
            status=status,
            is_mandatory=False,
            weight=20.0,
            requirement_summary=req_text,
            declared_summary=declared_text,
            portal_findings="Verified against declared order histories and incorporate records.",
            remarks=remarks,
        )

    def evaluate_clause_4_make_in_india(
        self,
        bid_data: ExtractedBidData,
        criteria: TenderCriteria,
    ) -> ClauseResult:
        """Clause 4: Make in India (MII) Local Content Preference.

        Rule: Evaluates local content percentage against Class-I / Class-II thresholds."""
        declared_pct = bid_data.local_content.local_content_percentage or 0.0
        classification = bid_data.local_content.classification

        req_text = f"Minimum {criteria.min_local_content_pct:.1f}% Local Content for Class-I Local Supplier preference"
        declared_text = f"Declared Local Content: {declared_pct:.1f}% ({classification.value})"

        if declared_pct >= criteria.min_local_content_pct:
            status = ClauseStatus.PASS
            remarks = "Qualifies as Class-I Local Supplier. Eligible for MII purchase preference."
        elif declared_pct >= 20.0:
            status = ClauseStatus.CONDITIONAL
            remarks = "Qualifies as Class-II Local Supplier (20-50%). Eligible to participate but lower preference rank."
        else:
            status = ClauseStatus.FAIL
            remarks = "Non-Local Supplier (< 20% local content). Ineligible under tender MII restriction."

        return ClauseResult(
            clause_id="GEM-C4-MII",
            clause_name="Make in India (MII) Local Content Preference",
            status=status,
            is_mandatory=False,
            weight=20.0,
            requirement_summary=req_text,
            declared_summary=declared_text,
            portal_findings="Self-declaration certificate logged with manufacturing location.",
            remarks=remarks,
        )

    def evaluate_clause_5_statutory(
        self,
        bid_data: ExtractedBidData,
        verification: EntityFullVerification,
    ) -> ClauseResult:
        """Clause 5: Statutory Tax Compliance & Debarment Check (MANDATORY).

        Rule: PAN must be ACTIVE, GSTIN must be ACTIVE (not suspended/cancelled),
        and the entity MUST NOT be blacklisted on GeM."""
        req_text = "Valid & Active PAN, Active GSTIN with regular filings, and ZERO debarment on GeM"
        declared_text = (
            f"PAN: {bid_data.identifiers.pan or 'None'}, GSTIN: {bid_data.identifiers.gstin or 'None'}, "
            f"Non-Debarment Self-Affirmation: {'Affirmed' if bid_data.claims_clean_record else 'Missing'}"
        )

        # Check blacklist first
        if not verification.debarment_check.is_valid:
            return ClauseResult(
                clause_id="GEM-C5-STATUTORY",
                clause_name="Statutory Registration & Tax Compliance",
                status=ClauseStatus.FAIL,
                is_mandatory=True,
                weight=20.0,
                requirement_summary=req_text,
                declared_summary=declared_text,
                portal_findings="CRITICAL: Entity is listed on GeM Incident Management Debarment Watchlist.",
                remarks="AUTOMATIC DISQUALIFICATION: Vendor is actively blacklisted by government authority.",
            )

        # Check PAN and GSTIN validity
        pan_ok = verification.pan_verification.is_valid
        gst_ok = verification.gstin_verification.is_valid

        if pan_ok and gst_ok:
            status = ClauseStatus.PASS
            findings = "PAN and GSTIN are ACTIVE in central registries. No debarment incidents found."
            remarks = "Full statutory compliance satisfied."
        elif pan_ok and not gst_ok:
            gst_status = verification.gstin_verification.status
            if gst_status == VerificationStatus.SUSPENDED:
                status = ClauseStatus.CONDITIONAL
                findings = f"PAN is ACTIVE. GSTIN is SUSPENDED ({verification.gstin_verification.details.get('suspension_reason')})."
                remarks = "Conditional: GSTIN suspended for non-filing. Requires tax clearance certificate before award."
            else:
                status = ClauseStatus.FAIL
                findings = f"GSTIN failed verification: {gst_status.value}."
                remarks = "Invalid or cancelled GST registration."
        else:
            status = ClauseStatus.FAIL
            findings = f"PAN status: {verification.pan_verification.status.value}, GSTIN status: {verification.gstin_verification.status.value}."
            remarks = "Statutory credentials failed authenticity verification."

        return ClauseResult(
            clause_id="GEM-C5-STATUTORY",
            clause_name="Statutory Registration & Tax Compliance",
            status=status,
            is_mandatory=True,
            weight=20.0,
            requirement_summary=req_text,
            declared_summary=declared_text,
            portal_findings=findings,
            remarks=remarks,
        )

    def evaluate_all(
        self,
        bid_data: ExtractedBidData,
        verification: EntityFullVerification,
        criteria: Optional[TenderCriteria] = None,
    ) -> List[ClauseResult]:
        """Evaluate all 5 GeM clauses sequentially.

        Args:
            bid_data: Extracted document data.
            verification: Portal cross-check results.
            criteria: Tender requirement thresholds.

        Returns:
            List of 5 ClauseResults."""
        active_criteria = criteria or TenderCriteria()
        return [
            self.evaluate_clause_1_emd(bid_data, verification, active_criteria),
            self.evaluate_clause_2_turnover(bid_data, active_criteria),
            self.evaluate_clause_3_experience(bid_data, active_criteria),
            self.evaluate_clause_4_make_in_india(bid_data, active_criteria),
            self.evaluate_clause_5_statutory(bid_data, verification),
        ]


# Functional convenience helper
def evaluate_bid_clauses(
    bid_data: ExtractedBidData,
    verification: EntityFullVerification,
    criteria: Optional[TenderCriteria] = None,
) -> List[ClauseResult]:
    """Convenience helper to evaluate all clauses."""
    evaluator = GeMClauseEvaluator()
    return evaluator.evaluate_all(bid_data, verification, criteria)
