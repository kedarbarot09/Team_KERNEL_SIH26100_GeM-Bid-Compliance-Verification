"""Visual Identity and Biometric Image Matching Module.

Compares extracted applicant photos and signatures across different bid credentials
to verify visual identity consistency, identify potential document tampering,
and flag cross-document identity discrepancies for procurement officers.
"""

from dataclasses import dataclass
import logging
from typing import Any, Literal, Optional, Tuple, Union

import numpy as np
from PIL import Image

# Import vision libraries with fallback safety
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore
    HAS_CV2 = False

try:
    from skimage.metrics import structural_similarity as ssim_fn
    HAS_SKIMAGE = True
except ImportError:
    ssim_fn = None  # type: ignore
    HAS_SKIMAGE = False

from app.image_extract import ExtractedImage

logger = logging.getLogger(__name__)

VerdictType = Literal["MATCH", "MISMATCH", "INCONCLUSIVE"]


@dataclass
class MatchResult:
    """Outcome of a biometric / visual identity comparison."""

    score: float  # Normalized similarity score (0.0 to 1.0)
    verdict: VerdictType  # 'MATCH', 'MISMATCH', 'INCONCLUSIVE'
    threshold_used: float  # Threshold applied for MATCH verdict
    notes: str  # Diagnostic explanation of the score and features


def _fallback_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """Pure NumPy calculation of Mean Structural Similarity Index (SSIM)."""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    x = img1.astype(np.float64)
    y = img2.astype(np.float64)

    mu_x = np.mean(x)
    mu_y = np.mean(y)

    sigma_x = np.var(x)
    sigma_y = np.var(y)
    sigma_xy = np.cov(x.flatten(), y.flatten())[0, 1] if x.size > 1 else 0.0

    numerator = (2 * mu_x * mu_y + C1) * (2 * sigma_xy + C2)
    denominator = (mu_x**2 + mu_y**2 + C1) * (sigma_x + sigma_y + C2)

    if denominator == 0:
        return 0.0
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def _compute_ssim(img1_gray: np.ndarray, img2_gray: np.ndarray) -> float:
    """Compute structural similarity between two same-sized 2D grayscale arrays."""
    if HAS_SKIMAGE and ssim_fn is not None:
        try:
            score = ssim_fn(img1_gray, img2_gray, data_range=255)
            return float(np.clip(score, 0.0, 1.0))
        except Exception as exc:
            logger.debug("skimage ssim error: %s, using fallback", exc)
    return _fallback_ssim(img1_gray, img2_gray)


def _crop_face_if_detected(pil_img: Image.Image) -> Image.Image:
    """If a frontal face is detected by Haar cascade, crop tightly around it; else return original."""
    if not HAS_CV2:
        return pil_img
    try:
        cv_img = np.array(pil_img.convert("RGB"))
        gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        if face_cascade.empty():
            return pil_img

        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))
        if len(faces) > 0:
            x, y, w, h = faces[0]
            # Add small 10% padding
            pad_x = int(w * 0.1)
            pad_y = int(h * 0.1)
            x0 = max(0, x - pad_x)
            y0 = max(0, y - pad_y)
            x1 = min(cv_img.shape[1], x + w + pad_x)
            y1 = min(cv_img.shape[0], y + h + pad_y)
            cropped = pil_img.crop((x0, y0, x1, y1))
            return cropped
    except Exception:
        pass
    return pil_img


def _trim_signature_borders(pil_img: Image.Image, threshold: int = 240) -> Image.Image:
    """Crop out redundant white borders around a signature to focus on ink strokes."""
    try:
        gray = pil_img.convert("L")
        arr = np.array(gray)
        # Identify rows and columns with ink strokes (< threshold)
        ink_mask = arr < threshold
        if not np.any(ink_mask):
            return pil_img

        rows = np.where(ink_mask.any(axis=1))[0]
        cols = np.where(ink_mask.any(axis=0))[0]

        top, bottom = rows[0], rows[-1]
        left, right = cols[0], cols[-1]

        # Add 5px padding
        pad = 5
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = min(arr.shape[0], bottom + pad)
        right = min(arr.shape[1], right + pad)

        return pil_img.crop((left, top, right, bottom))
    except Exception:
        return pil_img


def _normalize_image_input(img: Any) -> Tuple[Image.Image, float]:
    """Helper to accept either ExtractedImage dataclass, PIL Image, or array."""
    if hasattr(img, "image") and isinstance(img.image, Image.Image):
        conf = getattr(img, "extraction_confidence", 1.0)
        return img.image, float(conf)
    elif isinstance(img, Image.Image):
        conf = getattr(img, "extraction_confidence", 1.0)
        return img, float(conf)
    else:
        try:
            return Image.fromarray(np.array(img)), 1.0
        except Exception:
            raise TypeError(f"Expected ExtractedImage or PIL Image, got {type(img)}")


def compare_faces(
    img_a: Union[ExtractedImage, Image.Image],
    img_b: Union[ExtractedImage, Image.Image],
    match_threshold: float = 0.65,
    mismatch_threshold: float = 0.48,
) -> MatchResult:
    """Compare two extracted applicant photos using face alignment, SSIM, and HSV color histograms.

    Args:
        img_a: First extracted photo (ExtractedImage or PIL Image).
        img_b: Second extracted photo (ExtractedImage or PIL Image).
        match_threshold: Score threshold for MATCH (default 0.65).
        mismatch_threshold: Score threshold below which is MISMATCH (default 0.48).

    Returns:
        MatchResult with score, verdict, threshold, and diagnostic notes.
    """
    try:
        pil_a, conf_a = _normalize_image_input(img_a)
        pil_b, conf_b = _normalize_image_input(img_b)
    except Exception as e:
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes=f"Invalid image format: {e}",
        )

    # Guard against low-confidence extractions or degenerate images
    if conf_a < 0.45 or conf_b < 0.45:
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes="Extraction confidence too low for reliable facial comparison.",
        )

    # Standardize image size for facial analysis
    TARGET_SIZE = (160, 160)

    try:
        face_a = _crop_face_if_detected(pil_a).convert("RGB").resize(TARGET_SIZE, Image.Resampling.LANCZOS)
        face_b = _crop_face_if_detected(pil_b).convert("RGB").resize(TARGET_SIZE, Image.Resampling.LANCZOS)

        arr_a = np.array(face_a)
        arr_b = np.array(face_b)

        # Check for essentially blank images
        std_a = np.std(arr_a)
        std_b = np.std(arr_b)
        if std_a < 8 or std_b < 8:
            return MatchResult(
                score=0.0,
                verdict="INCONCLUSIVE",
                threshold_used=match_threshold,
                notes="One or both face images have insufficient contrast / detail.",
            )

        # 1. Structural Similarity on Grayscale
        gray_a = np.array(face_a.convert("L"))
        gray_b = np.array(face_b.convert("L"))
        ssim_score = _compute_ssim(gray_a, gray_b)

        # 2. HSV Color Histogram Comparison (skin tones, hair, background palette)
        hist_score = 0.50
        if HAS_CV2:
            try:
                hsv_a = cv2.cvtColor(arr_a, cv2.COLOR_RGB2HSV)
                hsv_b = cv2.cvtColor(arr_b, cv2.COLOR_RGB2HSV)

                hist_a = cv2.calcHist([hsv_a], [0, 1], None, [24, 24], [0, 180, 0, 256])
                hist_b = cv2.calcHist([hsv_b], [0, 1], None, [24, 24], [0, 180, 0, 256])

                cv2.normalize(hist_a, hist_a, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
                cv2.normalize(hist_b, hist_b, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

                # Correlation produces [-1, 1]
                corr = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
                hist_score = float(np.clip(corr, 0.0, 1.0))
            except Exception as e:
                logger.debug("Histogram comparison error: %s", e)
                hist_score = ssim_score
        else:
            hist_score = ssim_score

        # Weighted combination: 55% SSIM + 45% Color Distribution
        combined_score = round(0.55 * ssim_score + 0.45 * hist_score, 3)

        # Determine Verdict
        if combined_score >= match_threshold:
            verdict: VerdictType = "MATCH"
        elif combined_score <= mismatch_threshold:
            verdict = "MISMATCH"
        else:
            verdict = "INCONCLUSIVE"

        notes = (
            f"Face comparison: SSIM={ssim_score:.3f}, HSV Color Corr={hist_score:.3f}, "
            f"Combined={combined_score:.3f} vs Threshold={match_threshold:.2f}."
        )

        return MatchResult(
            score=combined_score,
            verdict=verdict,
            threshold_used=match_threshold,
            notes=notes,
        )

    except Exception as exc:
        logger.error("Face comparison failed with exception: %s", exc)
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes=f"Comparison error: {str(exc)}",
        )


def compare_signatures(
    img_a: Union[ExtractedImage, Image.Image],
    img_b: Union[ExtractedImage, Image.Image],
    match_threshold: float = 0.52,
    mismatch_threshold: float = 0.32,
) -> MatchResult:
    """Compare two extracted applicant signatures using stroke trimming, SSIM, and ORB keypoints.

    Args:
        img_a: First extracted signature (ExtractedImage or PIL Image).
        img_b: Second extracted signature (ExtractedImage or PIL Image).
        match_threshold: Score threshold for MATCH (default 0.52 - calibrated looser for signatures).
        mismatch_threshold: Score threshold below which is MISMATCH (default 0.32).

    Returns:
        MatchResult with score, verdict, threshold, and diagnostic notes.
    """
    try:
        pil_a, conf_a = _normalize_image_input(img_a)
        pil_b, conf_b = _normalize_image_input(img_b)
    except Exception as e:
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes=f"Invalid signature image format: {e}",
        )

    if conf_a < 0.40 or conf_b < 0.40:
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes="Signature extraction confidence too low for reliable stroke comparison.",
        )

    TARGET_SIZE = (240, 80)

    try:
        # Trim white margins and resize
        sig_a = _trim_signature_borders(pil_a).convert("L").resize(TARGET_SIZE, Image.Resampling.LANCZOS)
        sig_b = _trim_signature_borders(pil_b).convert("L").resize(TARGET_SIZE, Image.Resampling.LANCZOS)

        arr_a = np.array(sig_a)
        arr_b = np.array(sig_b)

        # Check for nearly blank signature boxes
        std_a = np.std(arr_a)
        std_b = np.std(arr_b)
        if std_a < 5 or std_b < 5:
            return MatchResult(
                score=0.0,
                verdict="INCONCLUSIVE",
                threshold_used=match_threshold,
                notes="One or both signature crops appear blank or lack sufficient stroke strokes.",
            )

        # 1. Structural Similarity on Ink Strokes
        ssim_score = _compute_ssim(arr_a, arr_b)

        # 2. Ink stroke overlap (IoU)
        ink_a = arr_a < 220
        ink_b = arr_b < 220
        intersection = float(np.sum(ink_a & ink_b))
        union = float(np.sum(ink_a | ink_b))
        iou_score = (intersection / union) if union > 0 else 0.0

        # 3. Feature Keypoint Matching via ORB
        orb_score = ssim_score
        if HAS_CV2:
            try:
                orb = cv2.ORB_create(nfeatures=200)
                kp1, des1 = orb.detectAndCompute(arr_a, None)
                kp2, des2 = orb.detectAndCompute(arr_b, None)

                if des1 is not None and des2 is not None and len(des1) > 5 and len(des2) > 5:
                    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                    matches = bf.match(des1, des2)
                    good_matches = [m for m in matches if m.distance < 55]
                    max_kp = max(len(kp1), len(kp2))
                    orb_ratio = len(good_matches) / float(max_kp) if max_kp > 0 else 0.0
                    orb_score = float(np.clip(orb_ratio * 2.5, 0.0, 1.0))
                else:
                    orb_score = iou_score
            except Exception as e:
                logger.debug("ORB signature match error: %s", e)
                orb_score = iou_score

        # Combine: 40% SSIM + 35% Ink IoU Overlap + 25% Keypoint distribution
        combined_score = round(0.40 * ssim_score + 0.35 * iou_score + 0.25 * orb_score, 3)

        if combined_score >= match_threshold:
            verdict: VerdictType = "MATCH"
        elif combined_score < mismatch_threshold:
            verdict = "MISMATCH"
        else:
            verdict = "INCONCLUSIVE"

        notes = (
            f"Signature comparison: SSIM={ssim_score:.3f}, Ink IoU={iou_score:.3f}, ORB={orb_score:.3f}, "
            f"Combined={combined_score:.3f} vs Threshold={match_threshold:.2f}."
        )

        return MatchResult(
            score=combined_score,
            verdict=verdict,
            threshold_used=match_threshold,
            notes=notes,
        )

    except Exception as exc:
        logger.error("Signature comparison failed with exception: %s", exc)
        return MatchResult(
            score=0.0,
            verdict="INCONCLUSIVE",
            threshold_used=match_threshold,
            notes=f"Comparison error: {str(exc)}",
        )
