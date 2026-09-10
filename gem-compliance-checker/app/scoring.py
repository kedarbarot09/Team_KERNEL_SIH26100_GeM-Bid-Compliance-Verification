"""Scoring Algorithm and Risk Categorization Engine.

Computes normalized compliance scores (0-100%), applies mandatory disqualification gates,
calculates risk deductions, and categorizes submissions into:
- COMPLIANT: Clean submission exceeding criteria (Score >= 80% and zero failed clauses).
- CONDITIONAL: Minor deficiencies or pending secondary proofs (Score 50-79%).
- DISQUALIFIED: Mandatory clause violation or severe deficiency (Score < 50% or Mandatory Fail).
"""

from enum import Enum
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from app.clauses import ClauseResult, ClauseStatus
from app.extract import ExtractedBidData
from app.mock_portals import EntityFullVerification

logger = logging.getLogger(__name__)


class RiskCategory(str, Enum):
    """Final compliance risk classification for the evaluated bid."""

    COMPLIANT = "COMPLIANT"
    CONDITIONAL = "CONDITIONAL"
    DISQUALIFIED = "DISQUALIFIED"


class ScoreBreakdown(BaseModel):
    """Detailed mathematical breakdown of points and deductions."""

    total_possible_score: float = Field(100.0, description="Maximum attainable score")
    earned_score: float = Field(..., description="Calculated score (0.0 to 100.0)")
    passed_clauses_count: int = Field(..., description="Number of fully passed clauses")
    conditional_clauses_count: int = Field(..., description="Number of conditionally approved clauses")
    failed_clauses_count: int = Field(..., description="Number of failed clauses")
    not_applicable_clauses_count: int = Field(0, description="Number of waived or not-applicable clauses")
    mandatory_failure_triggered: bool = Field(False, description="Whether an auto-disqualification clause failed")


class ComplianceReport(BaseModel):
    """Complete end-to-end evaluation report generated for a bid document."""

    report_id: str = Field(..., description="Unique verification report ID")
    bid_number: Optional[str] = Field(None, description="Tender bid number")
    bidder_name: str = Field(..., description="Name of submitting bidder entity")
    score_percentage: float = Field(..., description="Overall score percentage (0-100%)")
    risk_category: RiskCategory = Field(..., description="COMPLIANT / CONDITIONAL / DISQUALIFIED")
    is_technically_eligible: bool = Field(..., description="Eligible to proceed to financial bid opening")
    scoring_breakdown: ScoreBreakdown
    clause_results: List[ClauseResult] = Field(default_factory=list)
    portal_verification: Optional[EntityFullVerification] = None
    extracted_bid_data: Optional[ExtractedBidData] = None
    executive_summary: str = Field(..., description="Concise briefing for GeM procurement officer")
    recommended_actions: List[str] = Field(default_factory=list, description="Follow-up actions")


class ScoringEngine:
    """Computes weighted compliance scores and enforces risk gates."""

    @staticmethod
    def calculate_score(clause_results: List[ClauseResult]) -> ScoreBreakdown:
        """Compute earned points based on clause status and weights.

        Scoring Rules:
        - PASS: 100% of clause weight
        - CONDITIONAL: 50% of clause weight
        - FAIL: 0% of clause weight
        - NOT_APPLICABLE: Excluded from active denominator so non-applicable rules don't penalize.

        Args:
            clause_results: List of evaluated ClauseResult objects.

        Returns:
            ScoreBreakdown containing points and counts.
        """
        earned = 0.0
        total_possible = 0.0
        passed_cnt = 0
        conditional_cnt = 0
        failed_cnt = 0
        na_cnt = 0
        mandatory_fail = False

        for clause in clause_results:
            if clause.status == ClauseStatus.NOT_APPLICABLE:
                na_cnt += 1
                continue

            total_possible += clause.weight
            if clause.status == ClauseStatus.PASS:
                earned += clause.weight
                passed_cnt += 1
            elif clause.status == ClauseStatus.CONDITIONAL:
                earned += (clause.weight * 0.5)
                conditional_cnt += 1
            elif clause.status == ClauseStatus.FAIL:
                failed_cnt += 1
                if clause.is_mandatory:
                    mandatory_fail = True

        # Normalized percentage
        if total_possible > 0:
            clamped_score = max(0.0, min(100.0, round((earned / total_possible) * 100.0, 2)))
        else:
            clamped_score = 100.0

        return ScoreBreakdown(
            total_possible_score=100.0,
            earned_score=clamped_score,
            passed_clauses_count=passed_cnt,
            conditional_clauses_count=conditional_cnt,
            failed_clauses_count=failed_cnt,
            not_applicable_clauses_count=na_cnt,
            mandatory_failure_triggered=mandatory_fail,
        )

    @classmethod
    def determine_risk(cls, breakdown: ScoreBreakdown) -> RiskCategory:
        """Categorize risk level using thresholds and mandatory gates.

        Args:
            breakdown: ScoreBreakdown object.

        Returns:
            RiskCategory.
        """
        # Hard gate: any mandatory failure results in disqualification
        if breakdown.mandatory_failure_triggered:
            return RiskCategory.DISQUALIFIED

        if breakdown.earned_score >= 80.0 and breakdown.failed_clauses_count == 0:
            return RiskCategory.COMPLIANT
        elif breakdown.earned_score >= 50.0:
            return RiskCategory.CONDITIONAL
        else:
            return RiskCategory.DISQUALIFIED

    @classmethod
    def generate_report(
        cls,
        bid_data: ExtractedBidData,
        verification: EntityFullVerification,
        clauses: List[ClauseResult],
        report_id: Optional[str] = None,
    ) -> ComplianceReport:
        """Synthesize the complete compliance report with actionable recommendations.

        Args:
            bid_data: Extracted document data.
            verification: Portal verification findings.
            clauses: Evaluated clauses.
            report_id: Optional unique report ID.

        Returns:
            ComplianceReport.
        """
        import uuid

        rep_id = report_id or f"REP-GeM-{uuid.uuid4().hex[:8].upper()}"
        breakdown = cls.calculate_score(clauses)
        risk = cls.determine_risk(breakdown)
        eligible = (risk == RiskCategory.COMPLIANT) or (risk == RiskCategory.CONDITIONAL)

        bidder_name = bid_data.vendor_profile.legal_name or "Unknown Entity"
        if verification.pan_verification.registered_name:
            bidder_name = verification.pan_verification.registered_name

        # Synthesize recommendations and summary
        actions: List[str] = []
        if risk == RiskCategory.COMPLIANT:
            summary = (
                f"Bidder '{bidder_name}' achieved a compliance score of {breakdown.earned_score:.1f}% "
                f"({breakdown.passed_clauses_count} passed, {breakdown.not_applicable_clauses_count} waived). "
                f"Recommended for Technical Acceptance."
            )
            actions.append("Proceed to Financial Bid Opening.")
        elif risk == RiskCategory.CONDITIONAL:
            summary = (
                f"Bidder '{bidder_name}' meets minimum criteria with a score of {breakdown.earned_score:.1f}%, "
                f"but has {breakdown.conditional_clauses_count} item(s) requiring clarification."
            )
            for c in clauses:
                if c.status == ClauseStatus.CONDITIONAL:
                    actions.append(f"Seek clarification on {c.clause_name}: {c.remarks}")
        else:
            summary = (
                f"Bidder '{bidder_name}' is DISQUALIFIED with a score of {breakdown.earned_score:.1f}%. "
                "One or more mandatory statutory or technical qualification conditions were violated."
            )
            actions.append("Issue formal technical rejection letter citing non-compliance reasons.")
            for c in clauses:
                if c.status == ClauseStatus.FAIL:
                    actions.append(f"Deficiency ({c.clause_name}): {c.remarks}")

        return ComplianceReport(
            report_id=rep_id,
            bid_number=bid_data.bid_number,
            bidder_name=bidder_name,
            score_percentage=breakdown.earned_score,
            risk_category=risk,
            is_technically_eligible=eligible,
            scoring_breakdown=breakdown,
            clause_results=clauses,
            portal_verification=verification,
            extracted_bid_data=bid_data,
            executive_summary=summary,
            recommended_actions=actions,
        )


# Functional convenience helper
def score_and_summarize(
    bid_data: ExtractedBidData,
    verification: EntityFullVerification,
    clauses: List[ClauseResult],
) -> ComplianceReport:
    """Convenience helper to generate complete compliance report."""
    return ScoringEngine.generate_report(bid_data, verification, clauses)
