"""Document Ingestion & OCR Processing Module.

Provides abstractions for extracting plain text and structured pages from bid documents
in PDF and image formats. Employs PyMuPDF (fitz) with text block sorting for direct
high-speed digital text extraction, and optical character recognition (OCR) fallback via
pytesseract/Pillow when processing scanned documents.
"""

from dataclasses import dataclass, field
import io
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path so sibling packages resolve cleanly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


def resolve_tesseract_binary(custom_path: Optional[str] = None) -> Optional[str]:
    """Auto-detect Tesseract executable path across environment and standard OS locations.

    Search priority:
    1. Explicit custom_path argument.
    2. TESSERACT_CMD_PATH environment variable.
    3. System PATH executable ('tesseract').
    4. Common Windows default installation paths.
    5. Common Linux / macOS binary paths.

    Returns:
        String path to tesseract binary if found, else None.
    """
    if custom_path and Path(custom_path).is_file():
        return custom_path

    env_path = os.environ.get("TESSERACT_CMD_PATH")
    if env_path and Path(env_path).is_file():
        return env_path

    which_path = shutil.which("tesseract")
    if which_path:
        return which_path

    standard_search_paths = [
        # Windows standard locations
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        # Linux / Unix standard locations
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        # macOS Homebrew
        "/opt/homebrew/bin/tesseract",
    ]

    for p in standard_search_paths:
        if p and Path(p).is_file():
            return p

    return None


@dataclass
class PageExtraction:
    """Represents text extracted from an individual document page."""

    page_number: int
    text: str
    confidence: float = 1.0
    is_scanned: bool = False
    ocr_applied: bool = False


@dataclass
class OCRExtractionResult:
    """Aggregated result returned by the OCR processing pipeline."""

    raw_text: str
    page_count: int
    pages: List[PageExtraction] = field(default_factory=list)
    extraction_method: str = "direct_pdf_stream"  # "direct_pdf_stream" | "hybrid_ocr_pymupdf" | "tesseract_ocr" | "plain_text"
    metadata: Dict[str, Any] = field(default_factory=dict)
    has_errors: bool = False
    error_message: Optional[str] = None


class OCRProcessor:
    """Document text extractor and OCR wrapper.

    Extracts text from PDF files using PyMuPDF (fitz) with sorted text layout.
    If pages have insufficient embedded vector text (indicating a scanned image PDF),
    it executes OCR fallback page-by-page via pytesseract and Pillow.
    """

    def __init__(self, tesseract_cmd: Optional[str] = None, min_char_threshold: int = 50):
        """Initialize OCR processor.

        Args:
            tesseract_cmd: Optional path to the tesseract executable binary.
            min_char_threshold: Minimum character count per page before triggering OCR fallback.
        """
        self.tesseract_cmd = resolve_tesseract_binary(tesseract_cmd)
        self.min_char_threshold = min_char_threshold

        if self.tesseract_cmd:
            logger.info("Configured Tesseract binary at: %s", self.tesseract_cmd)
        else:
            logger.debug("Tesseract binary not found on standard paths. OCR fallback will report unavailable.")

    @staticmethod
    def _clean_ocr_text(ocr_output: Any) -> str:
        """Safely extract and clean text from pytesseract output.

        Pytesseract may return a string or, depending on output configuration/type inference,
        a dict (e.g. {'text': '...'}).
        """
        if isinstance(ocr_output, str):
            return ocr_output.strip()
        if isinstance(ocr_output, dict):
            return str(ocr_output.get("text", "")).strip()
        if isinstance(ocr_output, (bytes, bytearray)):
            return ocr_output.decode("utf-8", errors="replace").strip()
        return str(ocr_output).strip() if ocr_output is not None else ""

    def extract_from_pdf(self, file_bytes: bytes) -> OCRExtractionResult:
        """Extract text from a PDF file buffer with automatic OCR fallback.

        Args:
            file_bytes: Raw bytes of the uploaded PDF file.

        Returns:
            OCRExtractionResult containing combined text and page-level metadata.
        """
        if not file_bytes:
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message="Empty file bytes provided for PDF extraction.",
            )

        try:
            import fitz  # PyMuPDF
        except ImportError:
            # Check if this is a binary PDF
            if file_bytes.startswith(b"%PDF"):
                logger.error("PyMuPDF (fitz) is not installed; cannot process binary PDF.")
                return OCRExtractionResult(
                    raw_text="",
                    page_count=0,
                    has_errors=True,
                    error_message="PyMuPDF library is missing. Install with 'pip install pymupdf'.",
                    metadata={"error_type": "MISSING_DEPENDENCY", "required_package": "pymupdf"},
                )
            # If not binary PDF (e.g. simulated plain text payload during tests), attempt UTF-8 decode
            logger.warning("PyMuPDF not installed, but file is not a binary PDF. Falling back to plain text decode.")
            decoded = file_bytes.decode("utf-8", errors="replace").strip()
            return OCRExtractionResult(
                raw_text=decoded,
                page_count=1,
                pages=[PageExtraction(page_number=1, text=decoded, is_scanned=False)],
                extraction_method="plain_text_fallback",
                metadata={"warning": "fitz not installed; plain text decode used."},
                has_errors=len(decoded) == 0,
                error_message="Empty document content." if len(decoded) == 0 else None,
            )

        doc = None
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages: List[PageExtraction] = []
            full_text_parts: List[str] = []
            used_ocr = False
            ocr_failures: List[str] = []

            for page_idx in range(len(doc)):
                page = doc[page_idx]
                # sort=True sorts text top-to-bottom, left-to-right, preserving table & column order
                page_text = page.get_text("text", sort=True).strip()

                if len(page_text) < self.min_char_threshold:
                    # Page has insufficient vector text; attempt OCR fallback
                    ocr_text, ocr_err = self._ocr_fallback_page(page)
                    if ocr_text:
                        page_text = ocr_text
                        used_ocr = True
                        extracted_pages.append(
                            PageExtraction(
                                page_number=page_idx + 1,
                                text=page_text,
                                confidence=0.85,
                                is_scanned=True,
                                ocr_applied=True,
                            )
                        )
                    else:
                        if ocr_err:
                            ocr_failures.append(f"Page {page_idx + 1}: {ocr_err}")
                        extracted_pages.append(
                            PageExtraction(
                                page_number=page_idx + 1,
                                text=page_text,
                                confidence=0.4 if not page_text else 0.8,
                                is_scanned=True,
                                ocr_applied=False,
                            )
                        )
                else:
                    extracted_pages.append(
                        PageExtraction(
                            page_number=page_idx + 1,
                            text=page_text,
                            confidence=0.98,
                            is_scanned=False,
                            ocr_applied=False,
                        )
                    )

                if page_text:
                    full_text_parts.append(page_text)

            combined_text = "\n\n".join(full_text_parts).strip()
            method = "hybrid_ocr_pymupdf" if used_ocr else "direct_pdf_stream"

            # Check if document yielded zero readable text
            has_no_text = len(combined_text) == 0
            err_msg = None
            if has_no_text:
                if ocr_failures:
                    err_msg = f"No text could be extracted. OCR errors encountered: {'; '.join(ocr_failures)}"
                else:
                    err_msg = "PDF document contains no extractable text (pages may be blank or corrupted)."

            return OCRExtractionResult(
                raw_text=combined_text,
                page_count=len(doc),
                pages=extracted_pages,
                extraction_method=method,
                metadata={
                    "format": "pdf",
                    "title": doc.metadata.get("title", "") if doc.metadata else "",
                    "ocr_applied": used_ocr,
                    "ocr_failures": ocr_failures,
                },
                has_errors=has_no_text,
                error_message=err_msg,
            )
        except Exception as exc:
            logger.error("Failed to extract text from PDF: %s", exc, exc_info=True)
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message=f"PDF extraction error: {str(exc)}",
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception as close_exc:
                    logger.debug("Error closing fitz Document: %s", close_exc)

    def extract_from_image(self, image_bytes: bytes) -> OCRExtractionResult:
        """Extract text from an image file buffer (PNG, JPG, TIFF) using pytesseract.

        Args:
            image_bytes: Raw bytes of the image document.

        Returns:
            OCRExtractionResult containing OCR recognized text.
        """
        if not image_bytes:
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message="Empty image bytes provided.",
            )

        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            logger.warning("pytesseract or Pillow is not installed.")
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message="Pillow or pytesseract is not installed. Install with 'pip install pillow pytesseract'.",
            )

        if not self.tesseract_cmd:
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message="Tesseract binary not found on system PATH or TESSERACT_CMD_PATH.",
            )

        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                fmt = image.format
                size = image.size
                raw_ocr = pytesseract.image_to_string(image, lang="eng")
                ocr_text = self._clean_ocr_text(raw_ocr)

            has_no_text = len(ocr_text) == 0
            return OCRExtractionResult(
                raw_text=ocr_text,
                page_count=1,
                pages=[
                    PageExtraction(
                        page_number=1,
                        text=ocr_text,
                        confidence=0.88 if not has_no_text else 0.0,
                        is_scanned=True,
                        ocr_applied=True,
                    )
                ],
                extraction_method="tesseract_ocr",
                metadata={"format": fmt, "size": size},
                has_errors=has_no_text,
                error_message="Image OCR produced no readable text." if has_no_text else None,
            )
        except Exception as exc:
            logger.error("Failed image OCR: %s", exc)
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message=f"Image OCR error: {str(exc)}",
            )

    def _ocr_fallback_page(self, fitz_page: Any) -> tuple[str, Optional[str]]:
        """Render a PyMuPDF page to pixmap and perform Tesseract OCR.

        Args:
            fitz_page: fitz.Page instance.

        Returns:
            Tuple of (extracted_text, error_message_if_failed).
        """
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            return "", "Pillow or pytesseract is not installed."

        if not self.tesseract_cmd:
            return "", "Tesseract executable not found (set TESSERACT_CMD_PATH in .env)."

        pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        try:
            pix = fitz_page.get_pixmap(dpi=200)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as img:
                raw_ocr = pytesseract.image_to_string(img, lang="eng")
                ocr_text = self._clean_ocr_text(raw_ocr)
            return ocr_text, None
        except Exception as exc:
            logger.warning("Tesseract OCR fallback failed on page %s: %s", getattr(fitz_page, "number", "?"), exc)
            return "", str(exc)


# -----------------------------------------------------------------------------
# Functional Helpers
# -----------------------------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes, processor: Optional[OCRProcessor] = None) -> str:
    """Extract raw text string from PDF bytes."""
    p = processor or OCRProcessor()
    result = p.extract_from_pdf(file_bytes)
    return result.raw_text


def extract_text_from_image(file_bytes: bytes, processor: Optional[OCRProcessor] = None) -> str:
    """Extract raw text string from image bytes."""
    p = processor or OCRProcessor()
    result = p.extract_from_image(file_bytes)
    return result.raw_text


def extract_text_from_document(
    file_bytes: bytes,
    filename: Optional[str] = None,
    processor: Optional[OCRProcessor] = None,
) -> OCRExtractionResult:
    """Universal dispatcher routing file bytes to the appropriate extractor based on format."""
    p = processor or OCRProcessor()
    safe_filename = (filename or "").strip()
    lower_name = safe_filename.lower()

    if not file_bytes:
        return OCRExtractionResult(
            raw_text="",
            page_count=0,
            has_errors=True,
            error_message="Uploaded document is empty.",
            metadata={"filename": safe_filename},
        )

    # Route by extension or file signature
    if lower_name.endswith(".pdf") or file_bytes.startswith(b"%PDF"):
        return p.extract_from_pdf(file_bytes)
    elif lower_name.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp")):
        return p.extract_from_image(file_bytes)
    else:
        # Check if binary data was passed without known text extension
        is_binary = b"\x00" in file_bytes[:1024]
        if is_binary and not lower_name.endswith((".txt", ".md", ".json", ".csv", ".log")):
            return OCRExtractionResult(
                raw_text="",
                page_count=0,
                has_errors=True,
                error_message=f"Unsupported binary file format for '{safe_filename or 'document'}'.",
                metadata={"filename": safe_filename},
            )

        # Plain text document
        text = file_bytes.decode("utf-8", errors="replace").strip()
        has_no_text = len(text) == 0
        return OCRExtractionResult(
            raw_text=text,
            page_count=1,
            pages=[PageExtraction(page_number=1, text=text, is_scanned=False)],
            extraction_method="plain_text",
            metadata={"filename": safe_filename},
            has_errors=has_no_text,
            error_message="Document text is empty." if has_no_text else None,
        )
