"""Unit tests for app/image_extract.py.

Tests photo extraction and signature extraction from PDF documents using PyMuPDF and heuristics,
verifying that images are correctly identified where present and None is returned where absent.
"""

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.demo_data import generate_bidder_demo_documents
from app.image_extract import ExtractedImage, extract_photo, extract_signature


class TestImageExtract(unittest.TestCase):
    """Test suite for photo and signature extraction from bid documents."""

    @classmethod
    def setUpClass(cls):
        # Generate demo documents for BID-001
        cls.demo_docs = generate_bidder_demo_documents("BID-001")

    def test_extract_photo_from_pan_card(self):
        """Verify that extract_photo successfully extracts the applicant photo from PAN Card PDF."""
        pan_entry = self.demo_docs.get(("Statutory / registration documents", "PAN Card"))
        self.assertIsNotNone(pan_entry, "PAN Card should be generated for BID-001")
        fname, fbytes = pan_entry

        extracted = extract_photo(fbytes, doc_type="PAN Card")
        self.assertIsNotNone(extracted, "Photo should be extracted from PAN Card")
        self.assertIsInstance(extracted, ExtractedImage)
        self.assertEqual(extracted.source_document, "PAN Card")
        self.assertEqual(extracted.image_type, "photo")
        self.assertGreater(extracted.extraction_confidence, 0.60)
        self.assertGreater(extracted.image.width, 40)
        self.assertGreater(extracted.image.height, 40)

    def test_extract_photo_from_gst_certificate(self):
        """Verify that extract_photo successfully extracts the photo from GST Registration Certificate."""
        gst_entry = self.demo_docs.get(("Statutory / registration documents", "GST Registration Certificate"))
        self.assertIsNotNone(gst_entry, "GST Certificate should be generated for BID-001")
        fname, fbytes = gst_entry

        extracted = extract_photo(fbytes, doc_type="GST Registration Certificate")
        self.assertIsNotNone(extracted, "Photo should be extracted from GST Certificate")
        self.assertIsInstance(extracted, ExtractedImage)
        self.assertGreater(extracted.extraction_confidence, 0.60)

    def test_extract_signature_from_oem_auth(self):
        """Verify that extract_signature extracts the authorized signature from OEM authorization letter."""
        oem_entry = self.demo_docs.get(("Technical / product-specific documents", "OEM authorization letter"))
        self.assertIsNotNone(oem_entry, "OEM letter should be generated for BID-001")
        fname, fbytes = oem_entry

        extracted = extract_signature(fbytes, doc_type="OEM authorization letter")
        self.assertIsNotNone(extracted, "Signature should be extracted from OEM letter")
        self.assertIsInstance(extracted, ExtractedImage)
        self.assertEqual(extracted.image_type, "signature")
        self.assertGreater(extracted.extraction_confidence, 0.65)
        self.assertGreater(extracted.image.width, 50)

    def test_extract_signature_from_gst_certificate(self):
        """Verify that extract_signature extracts the signature from GST Registration Certificate."""
        gst_entry = self.demo_docs.get(("Statutory / registration documents", "GST Registration Certificate"))
        self.assertIsNotNone(gst_entry)
        fname, fbytes = gst_entry

        extracted = extract_signature(fbytes, doc_type="GST Registration Certificate")
        self.assertIsNotNone(extracted, "Signature should be extracted from GST Certificate")
        self.assertEqual(extracted.image_type, "signature")

    def test_extract_photo_returns_none_for_text_only_doc(self):
        """Verify that extract_photo returns None and does not fabricate when no photo is present."""
        udyam_entry = self.demo_docs.get(("Statutory / registration documents", "Udyam Registration Certificate"))
        self.assertIsNotNone(udyam_entry)
        fname, fbytes = udyam_entry

        # Udyam document is text-only and has no photo embedded
        extracted = extract_photo(fbytes, doc_type="Udyam Registration Certificate")
        self.assertIsNone(extracted, "Should return None when no photo is embedded")

    def test_extract_signature_returns_none_when_absent(self):
        """Verify that extract_signature returns None when no signature or anchor is present."""
        # Arbitrary non-signature plain text
        plain_text_bytes = b"Just a plain text notice without any signature keywords or graphics."
        extracted = extract_signature(plain_text_bytes, doc_type="Notice")
        self.assertIsNone(extracted, "Should return None for plain text without signature")


if __name__ == "__main__":
    unittest.main()
