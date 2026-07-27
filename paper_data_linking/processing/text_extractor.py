import fitz
import pytesseract
from pathlib import Path
from pdf2image import convert_from_bytes
from tqdm import tqdm

from paper_data_linking.processing.text_quality import is_junk_pdf


def ocr_image(img):
    return pytesseract.image_to_string(img)


class PDFTextExtractor:
    """Handles PDF text extraction with optional OCR fallback"""

    def __init__(self):
        self.temp_doc = None

    def _load_doc(self, content):
        if isinstance(content, Path) or isinstance(content, str):
            with open(content, "rb") as f:
                content_bytes = f.read()
            doc = fitz.open(stream=content_bytes, filetype="pdf")
        elif isinstance(content, bytes):
            doc = fitz.open(stream=content, filetype="pdf")
            content_bytes = content
        else:  # Assume content is a readable file-like object
            try:
                content_bytes = content.read()
                doc = fitz.open(stream=content_bytes, filetype="pdf")
            except Exception as e:
                raise TypeError(
                    "Content must be a Path, str, bytes, or a readable file-like object"
                ) from e
        return doc, content_bytes

    def _get_text_ocr(self, data, websocket_callback=None):
        """Extract text using OCR"""
        images = convert_from_bytes(data)
        txts = []
        total_images = len(images)

        for i, image in enumerate(tqdm(images)):
            txts.append(ocr_image(image))
            if websocket_callback:
                websocket_callback(f"OCR Progress: Page {i + 1}/{total_images}")

        return chr(12).join(txts)

    def extract_text(self, content, coerce_ocr=False, allow_ocr=True, websocket_callback=None):
        """
        Extract text from PDF with optional OCR fallback.
        Returns (text, used_ocr).

        allow_ocr=False disables the (slow, hang-prone) tesseract OCR fallback: a
        scanned / image-only PDF yields ("", False) instead of OCR'ing. Used for
        bulk/corpus runs so the OCR-needing minority doesn't dominate wall-clock.
        """
        doc = None
        try:
            doc, data = self._load_doc(content)
            if not coerce_ocr:
                txt = chr(12).join([p.get_text(sort=True) for p in doc])
                if not is_junk_pdf(txt):
                    return txt.replace('\u0000', ''), False

            if not allow_ocr:
                # No usable embedded text and OCR disabled — skip this PDF.
                return "", False

            if websocket_callback:
                websocket_callback("Using OCR for text extraction...")

            txt = self._get_text_ocr(data, websocket_callback)
            if is_junk_pdf(txt):
                raise Exception("Failed to extract usable text with both PyMuPDF and OCR.")
            return txt.replace('\u0000', ''), True

        finally:
            if doc:
                doc.close()


