"""Applicant Photo and Signature Extraction Module.

Extracts applicant identification photos and signatures from uploaded PDF credentials
(e.g., PAN card, GST certificate, OEM authorization letter, Udyam registration) using
PyMuPDF (fitz), layout heuristics, aspect ratio filtering, and facial landmark/anchor detection.
"""

from dataclasses import dataclass
import io
import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore
    HAS_CV2 = False

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """Represents an extracted visual asset (photo or signature) from a document."""

    image: Image.Image
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in document points or image pixels
    source_document: str
    source_page: int
    extraction_confidence: float
    image_type: str = "photo"  # "photo" or "signature"

    def to_bytes(self, format: str = "PNG") -> bytes:
        """Convert PIL Image to encoded byte string."""
        buf = io.BytesIO()
        # Convert RGBA to RGB if saving as JPEG
        img = self.image
        if format.upper() in ("JPG", "JPEG") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(buf, format=format)
        return buf.getvalue()


def _open_pdf_document(pdf_input: Union[str, Path, bytes]) -> Optional[fitz.Document]:
    """Open a fitz.Document from filepath, Path, or raw bytes."""
    try:
        if isinstance(pdf_input, (str, Path)):
            p = Path(pdf_input)
            if not p.is_file():
                logger.warning("PDF file path not found: %s", pdf_input)
                return None
            return fitz.open(str(p))
        elif isinstance(pdf_input, (bytes, bytearray)):
            return fitz.open(stream=pdf_input, filetype="pdf")
    except Exception as exc:
        logger.error("Failed to open PDF document: %s", exc)
        return None
    return None


def _detect_face_in_pil(img: Image.Image) -> Tuple[bool, Optional[Tuple[int, int, int, int]]]:
    """Attempt to detect a frontal face using OpenCV Haar Cascades."""
    if not HAS_CV2:
        return False, None
    try:
        cv_img = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)
        
        # Load default Haar cascade from cv2 data directory
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        if face_cascade.empty():
            return False, None

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=3,
            minSize=(30, 30),
        )
        if len(faces) > 0:
            x, y, w, h = faces[0]
            return True, (int(x), int(y), int(w), int(h))
    except Exception as exc:
        logger.debug("Haar cascade face detection error: %s", exc)
    return False, None


def _is_mostly_blank(img: Image.Image, threshold: float = 0.985) -> bool:
    """Check if an image is essentially empty/blank (e.g., all white or transparent)."""
    try:
        grayscale = img.convert("L")
        arr = np.array(grayscale)
        # Fraction of pixels that are near-white (> 245) or near-black (< 10)
        white_ratio = np.mean(arr > 245)
        black_ratio = np.mean(arr < 10)
        return bool(white_ratio >= threshold or black_ratio >= threshold)
    except Exception:
        return False


def extract_photo(
    pdf_input: Union[str, Path, bytes],
    doc_type: str = "",
) -> Optional[ExtractedImage]:
    """Extract an applicant's ID photo from a document PDF.

    Enumerates embedded images in the PDF, filtering by aspect ratio and pixel
    dimensions characteristic of identity documents (PAN, GST managing committee,
    passport-style photo slots).

    Args:
        pdf_input: File path, Path object, or raw bytes of the PDF.
        doc_type: Optional descriptive label of the document type (e.g. 'PAN Card').

    Returns:
        ExtractedImage containing the best candidate photo, or None if no photo found.
    """
    doc = _open_pdf_document(pdf_input)
    if not doc:
        return None

    candidate_images: List[Tuple[ExtractedImage, float]] = []

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    continue

                if not base_image:
                    continue

                image_bytes = base_image.get("image")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                if not image_bytes or width < 45 or height < 55:
                    continue

                # Plausible photo dimension bounds
                # Reject huge full-page backgrounds (e.g., 2000x3000 background scans)
                if width > 3000 or height > 3500:
                    continue

                aspect_ratio = height / float(width)

                # ID photos are typically portrait or square-ish: aspect ratio 0.8 to 1.7
                if not (0.75 <= aspect_ratio <= 1.85):
                    continue

                try:
                    pil_img = Image.open(io.BytesIO(image_bytes))
                except Exception:
                    continue

                if _is_mostly_blank(pil_img):
                    continue

                # Get spatial bounding box on page
                rects = page.get_image_rects(xref)
                bbox = (
                    (rects[0].x0, rects[0].y0, rects[0].x1, rects[0].y1)
                    if rects
                    else (0.0, 0.0, float(width), float(height))
                )

                # Check for face detection
                has_face, _ = _detect_face_in_pil(pil_img)

                # Calculate confidence score
                # Ideal ID photo aspect ratio is ~1.2 - 1.35
                aspect_penalty = abs(aspect_ratio - 1.25)
                score = 0.70 - min(0.35, aspect_penalty * 0.4)

                # Bonus for face detection
                if has_face:
                    score = 0.96
                else:
                    # Check for color variability (ID photos have skin/hair/background variance)
                    try:
                        arr = np.array(pil_img.convert("RGB"))
                        std_dev = float(np.std(arr))
                        if std_dev > 25:
                            score += 0.12
                    except Exception:
                        pass

                score = max(0.50, min(0.99, score))

                ext_img = ExtractedImage(
                    image=pil_img,
                    bbox=bbox,
                    source_document=doc_type or f"Page {page_idx + 1}",
                    source_page=page_idx + 1,
                    extraction_confidence=round(score, 2),
                )
                candidate_images.append((ext_img, score))

    finally:
        doc.close()

    if not candidate_images:
        return None

    # Pick candidate with highest confidence score
    candidate_images.sort(key=lambda x: x[1], reverse=True)
    best_candidate = candidate_images[0][0]
    return best_candidate


def extract_signature(
    pdf_input: Union[str, Path, bytes],
    doc_type: str = "",
) -> Optional[ExtractedImage]:
    """Extract an applicant's / signatory's signature from a document PDF.

    Locates signature-block regions using layout anchor keywords (e.g. 'Authorised Signatory',
    'Signature', 'Digitally signed by') and checks for embedded signature images or crops
    the signature bounding region.

    Args:
        pdf_input: File path, Path object, or raw bytes of the PDF.
        doc_type: Optional descriptive label of the document type.

    Returns:
        ExtractedImage containing the signature region crop/image, or None if not found.
    """
    doc = _open_pdf_document(pdf_input)
    if not doc:
        return None

    signature_keywords = [
        "authorised signatory",
        "authorized signatory",
        "digitally signed by",
        "signature of bidder",
        "signature of applicant",
        "seal & signature",
        "signature",
        "signatory",
        "approved by",
        "verified by",
    ]

    candidate_signatures: List[Tuple[ExtractedImage, float]] = []

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]

            # 1. First search for embedded images with signature aspect ratio (landscape: width > height)
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    continue

                if not base_image:
                    continue

                image_bytes = base_image.get("image")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                if not image_bytes or width < 60 or height < 20:
                    continue

                aspect_ratio = width / float(height)
                # Signature aspect ratio is typically wide/landscape: 1.4 to 6.0
                if 1.3 <= aspect_ratio <= 7.0:
                    try:
                        pil_img = Image.open(io.BytesIO(image_bytes))
                        if pil_img.mode in ("RGBA", "LA") or (pil_img.mode == "P" and "transparency" in pil_img.info):
                            bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                            rgba_img = pil_img.convert("RGBA")
                            bg.paste(rgba_img, mask=rgba_img.split()[3])
                            pil_img = bg
                    except Exception:
                        continue

                    if _is_mostly_blank(pil_img):
                        continue

                    rects = page.get_image_rects(xref)
                    bbox = (
                        (rects[0].x0, rects[0].y0, rects[0].x1, rects[0].y1)
                        if rects
                        else (0.0, 0.0, float(width), float(height))
                    )

                    # Check proximity to any signature keyword
                    is_near_kw = False
                    for kw in signature_keywords:
                        kw_rects = page.search_for(kw)
                        if kw_rects and rects:
                            for kr in kw_rects:
                                # Within 160 points vertically
                                if abs(rects[0].y0 - kr.y0) < 160:
                                    is_near_kw = True
                                    break
                        if is_near_kw:
                            break

                    conf = 0.92 if is_near_kw else 0.78
                    candidate_signatures.append((
                        ExtractedImage(
                            image=pil_img,
                            bbox=bbox,
                            source_document=doc_type or f"Page {page_idx + 1}",
                            source_page=page_idx + 1,
                            extraction_confidence=conf,
                            image_type="signature",
                        ),
                        conf,
                    ))

            # 2. If no embedded signature image was detected, search for anchor keywords and crop
            if not candidate_signatures:
                for kw in signature_keywords:
                    found_rects = page.search_for(kw)
                    for rect in found_rects:
                        # Define crop region: typically signature is situated directly above or below keyword
                        # Usually 60-80 pt above the keyword label
                        crop_rect = fitz.Rect(
                            max(0, rect.x0 - 20),
                            max(0, rect.y0 - 75),
                            min(page.rect.width, rect.x1 + 80),
                            max(0, rect.y0 + 5),
                        )

                        # Render crop at 150 DPI
                        try:
                            pix = page.get_pixmap(clip=crop_rect, dpi=150)
                            crop_bytes = pix.tobytes("png")
                            pil_crop = Image.open(io.BytesIO(crop_bytes))
                            if not _is_mostly_blank(pil_crop, threshold=0.99):
                                conf = 0.75
                                candidate_signatures.append((
                                    ExtractedImage(
                                        image=pil_crop,
                                        bbox=(crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1),
                                        source_document=doc_type or f"Page {page_idx + 1}",
                                        source_page=page_idx + 1,
                                        extraction_confidence=conf,
                                        image_type="signature",
                                    ),
                                    conf,
                                ))
                                break
                        except Exception as e:
                            logger.debug("Crop extraction failed: %s", e)
                    if candidate_signatures:
                        break

    finally:
        doc.close()

    if not candidate_signatures:
        return None

    candidate_signatures.sort(key=lambda x: x[1], reverse=True)
    return candidate_signatures[0][0]
