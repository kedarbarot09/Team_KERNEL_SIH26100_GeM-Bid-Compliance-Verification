"""Unit tests for app/image_match.py.

Tests face comparison and signature matching algorithms with known-identical images
(expecting MATCH with high score), deliberately mismatched images (expecting MISMATCH with low score),
and degraded/low-confidence inputs (expecting INCONCLUSIVE graceful degradation).
"""

import io
from pathlib import Path
import sys
import unittest

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.demo_data import generate_synthetic_headshot, generate_synthetic_signature
from app.image_extract import ExtractedImage
from app.image_match import MatchResult, compare_faces, compare_signatures


class TestImageMatch(unittest.TestCase):
    """Test suite for biometric and signature comparison algorithms."""

    def setUp(self):
        # Generate synthetic test fixtures
        headshot_a_bytes = generate_synthetic_headshot("BID-TEST", variant="A")
        headshot_b_bytes = generate_synthetic_headshot("BID-TEST", variant="B")
        sig_a_bytes = generate_synthetic_signature("BID-TEST", variant="A")
        sig_b_bytes = generate_synthetic_signature("BID-TEST", variant="B")

        img_headshot_a = Image.open(io.BytesIO(headshot_a_bytes))
        img_headshot_b = Image.open(io.BytesIO(headshot_b_bytes))
        img_sig_a = Image.open(io.BytesIO(sig_a_bytes))
        img_sig_b = Image.open(io.BytesIO(sig_b_bytes))

        self.face_a1 = ExtractedImage(
            image=img_headshot_a,
            bbox=(0, 0, 200, 240),
            source_document="PAN Card",
            source_page=1,
            extraction_confidence=0.92,
            image_type="photo",
        )
        self.face_a2 = ExtractedImage(
            image=img_headshot_a.copy(),
            bbox=(10, 10, 210, 250),
            source_document="GST Registration Certificate",
            source_page=1,
            extraction_confidence=0.90,
            image_type="photo",
        )
        self.face_b = ExtractedImage(
            image=img_headshot_b,
            bbox=(0, 0, 200, 240),
            source_document="GST Registration Certificate",
            source_page=1,
            extraction_confidence=0.88,
            image_type="photo",
        )

        self.sig_a1 = ExtractedImage(
            image=img_sig_a,
            bbox=(0, 0, 260, 85),
            source_document="PAN Card",
            source_page=1,
            extraction_confidence=0.85,
            image_type="signature",
        )
        self.sig_a2 = ExtractedImage(
            image=img_sig_a.copy(),
            bbox=(5, 5, 265, 90),
            source_document="OEM authorization letter",
            source_page=1,
            extraction_confidence=0.84,
            image_type="signature",
        )
        self.sig_b = ExtractedImage(
            image=img_sig_b,
            bbox=(0, 0, 260, 85),
            source_document="GST Registration Certificate",
            source_page=1,
            extraction_confidence=0.82,
            image_type="signature",
        )

    def test_compare_faces_identical_images_match(self):
        """Identical face images must produce a high similarity score and MATCH verdict."""
        result = compare_faces(self.face_a1, self.face_a2)
        self.assertIsInstance(result, MatchResult)
        self.assertEqual(result.verdict, "MATCH")
        self.assertGreaterEqual(result.score, 0.70)
        self.assertIn("SSIM=", result.notes)

    def test_compare_faces_different_images_mismatch(self):
        """Deliberately different face images must yield a low similarity score and MISMATCH verdict."""
        result = compare_faces(self.face_a1, self.face_b)
        self.assertIsInstance(result, MatchResult)
        self.assertEqual(result.verdict, "MISMATCH", f"Score was {result.score}, notes: {result.notes}")
        self.assertLess(result.score, 0.55)

    def test_compare_signatures_identical_images_match(self):
        """Identical signature images must produce a high similarity score and MATCH verdict."""
        result = compare_signatures(self.sig_a1, self.sig_a2)
        self.assertIsInstance(result, MatchResult)
        self.assertEqual(result.verdict, "MATCH")
        self.assertGreaterEqual(result.score, 0.60)

    def test_compare_signatures_different_images_mismatch(self):
        """Deliberately different signature images must produce a low score and MISMATCH verdict."""
        result = compare_signatures(self.sig_a1, self.sig_b)
        self.assertIsInstance(result, MatchResult)
        self.assertEqual(result.verdict, "MISMATCH")
        self.assertLess(result.score, 0.40)

    def test_graceful_degradation_on_low_confidence(self):
        """When extraction confidence is too low, comparison must degrade to INCONCLUSIVE."""
        degraded_face = ExtractedImage(
            image=self.face_a1.image,
            bbox=(0, 0, 200, 240),
            source_document="Corrupted Card",
            source_page=1,
            extraction_confidence=0.25,  # Too low
            image_type="photo",
        )
        result = compare_faces(self.face_a1, degraded_face)
        self.assertEqual(result.verdict, "INCONCLUSIVE")
        self.assertIn("Extraction confidence too low", result.notes)

    def test_blank_image_handling(self):
        """When an image is uniform/blank, comparison should return INCONCLUSIVE rather than false match."""
        blank_img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        blank_ext = ExtractedImage(
            image=blank_img,
            bbox=(0, 0, 100, 100),
            source_document="Blank Doc",
            source_page=1,
            extraction_confidence=0.80,
            image_type="photo",
        )
        result = compare_faces(self.face_a1, blank_ext)
        self.assertEqual(result.verdict, "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
