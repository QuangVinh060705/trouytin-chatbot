from io import BytesIO
import unittest

from core.document_service import DocumentService
from core.exceptions import DocumentValidationError


class DocumentValidationTests(unittest.TestCase):
    def test_accepts_real_pdf_signature(self):
        stream = BytesIO(b"%PDF-1.7 sample")
        DocumentService.validate_file("rules.pdf", "application/pdf", len(stream.getvalue()))
        DocumentService.validate_signature(stream, "rules.pdf")

    def test_rejects_fake_pdf(self):
        with self.assertRaises(DocumentValidationError):
            DocumentService.validate_signature(BytesIO(b"not a pdf"), "rules.pdf")

    def test_rejects_binary_text(self):
        with self.assertRaises(DocumentValidationError):
            DocumentService.validate_signature(BytesIO(b"abc\x00def"), "rules.txt")


if __name__ == "__main__":
    unittest.main()
