"""FastAPI Application & Pipeline Orchestration Server.

Exposes REST APIs for the GeM Bid Compliance & Document Verification Engine:
- GET  /health: Service liveness and dependency status
- POST /verify-bid: Core JSON endpoint for raw bid text and custom criteria
- POST /verify-bid-file: Multipart endpoint supporting direct PDF/Image/TXT uploads
"""

import logging
from pathlib import Path
import sys
from typing import Any, Dict, Optional

# Ensure project root is in sys.path so 'app' is resolvable regardless of invocation directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import __version__
from app.clauses import GeMClauseEvaluator, TenderCriteria
from app.extract import ExtractedBidData, extract_bid_information
from app.mock_portals import MockPortalRegistry
from app.ocr import extract_text_from_document
from app.scoring import ComplianceReport, ScoringEngine

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gem_compliance_api")

app = FastAPI(
    title="GeM Bid Compliance & Document Verification API",
    description="Automated compliance engine for GeM tenders combining OCR, Regex/LLM extractors, "
                "government portal simulators, deterministic clause evaluation, and risk scoring.",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for local Streamlit frontend and external integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global simulator instance
portal_registry = MockPortalRegistry()
clause_evaluator = GeMClauseEvaluator()


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------
class BidVerificationRequest(BaseModel):
    """Payload for text-based bid verification."""

    raw_bid_text: str = Field(..., description="Plain text extracted from the bid document or OCR")
    criteria: Optional[TenderCriteria] = Field(
        default_factory=TenderCriteria,
        description="Buyer's tender criteria parameters",
    )


class HealthResponse(BaseModel):
    """System health & readiness information."""

    status: str
    version: str
    registered_mock_entities: int
    modules: Dict[str, str]


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@app.get("/", tags=["General"])
def root_endpoint() -> Dict[str, Any]:
    """Root metadata endpoint."""
    return {
        "service": "GeM Bid Compliance & Document Verification Engine",
        "version": __version__,
        "documentation": "/docs",
        "health_check": "/health",
        "endpoints": {
            "verify_bid_json": "POST /verify-bid",
            "verify_bid_file": "POST /verify-bid-file",
        },
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
def health_check() -> HealthResponse:
    """Liveness probe verifying that core pipeline modules are loaded."""
    return HealthResponse(
        status="healthy",
        version=__version__,
        registered_mock_entities=len(portal_registry.entities),
        modules={
            "ocr": "PyMuPDF/Pytesseract interface ready",
            "extraction": "Regex + LLM schema parser ready",
            "mock_portals": f"Loaded {len(portal_registry.entities)} entities",
            "clauses": "5 deterministic GeM rules active",
            "scoring": "Risk matrix (0-100%) active",
        },
    )


@app.post(
    "/verify-bid",
    response_model=ComplianceReport,
    status_code=status.HTTP_200_OK,
    tags=["Pipeline"],
)
def verify_bid_text(payload: BidVerificationRequest) -> ComplianceReport:
    """Run full verification pipeline on raw bid document text.

    Pipeline Steps:
    1. Extract identifiers and bid declarations (Regex + LLM heuristic).
    2. Query mock government portals (PAN, GSTIN, Udyam, Debarment).
    3. Evaluate 5 deterministic GeM tender clauses.
    4. Calculate weighted score (0-100%) and assign risk category.
    """
    raw_text = payload.raw_bid_text.strip()
    if not raw_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="raw_bid_text cannot be empty.",
        )

    logger.info("Executing verification pipeline for text payload (%d characters)...", len(raw_text))

    try:
        # Step 1: Extract structured bid info
        bid_data: ExtractedBidData = extract_bid_information(raw_text)

        # Step 2: Cross-verify on government registries
        verification = portal_registry.verify_all(
            pan=bid_data.identifiers.pan,
            gstin=bid_data.identifiers.gstin,
            udyam=bid_data.identifiers.udyam,
        )

        # Step 3: Evaluate 5 GeM clauses
        criteria = payload.criteria or TenderCriteria()
        clauses = clause_evaluator.evaluate_all(
            bid_data=bid_data,
            verification=verification,
            criteria=criteria,
        )

        # Step 4: Compute score and risk report
        report = ScoringEngine.generate_report(
            bid_data=bid_data,
            verification=verification,
            clauses=clauses,
        )

        logger.info(
            "Verification complete for '%s': Score=%.1f%%, Risk=%s",
            report.bidder_name,
            report.score_percentage,
            report.risk_category.value,
        )
        return report

    except Exception as exc:
        logger.error("Error during verification pipeline: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Verification pipeline failed: {str(exc)}",
        )


@app.post(
    "/verify-bid-file",
    response_model=ComplianceReport,
    status_code=status.HTTP_200_OK,
    tags=["Pipeline"],
)
async def verify_bid_file(
    file: UploadFile = File(..., description="PDF or plain text bid document"),
    required_turnover_lakhs: float = Form(30.0),
    min_experience_years: int = Form(2),
    min_local_content_pct: float = Form(50.0),
) -> ComplianceReport:
    """Run verification pipeline directly from uploaded PDF or text document."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Ingest document via OCR / Text wrapper
    ocr_result = extract_text_from_document(file_bytes, file.filename or "uploaded_bid.pdf")
    if ocr_result.has_errors or not ocr_result.raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not extract readable text from document: {ocr_result.error_message}",
        )

    criteria = TenderCriteria(
        required_turnover_lakhs=required_turnover_lakhs,
        min_experience_years=min_experience_years,
        min_local_content_pct=min_local_content_pct,
    )

    return verify_bid_text(
        BidVerificationRequest(
            raw_bid_text=ocr_result.raw_text,
            criteria=criteria,
        )
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

