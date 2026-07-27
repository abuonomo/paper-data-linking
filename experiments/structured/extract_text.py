#!/usr/bin/env python3
"""
PDF Text Extractor

This script extracts text from PDF files using the PDFTextExtractor class,
with optional OCR fallback if the normal extraction produces unusable text.

Usage:
    python extract_pdf_text.py --input input.pdf --output output.txt [--force-ocr]
"""

import argparse
import sys
from pathlib import Path

# Import the PDFTextExtractor class
from paper_data_linking.processing.text_processing import PDFTextExtractor


def main():
    """Main function to extract text from a PDF file."""
    parser = argparse.ArgumentParser(description="Extract text from a PDF file.")
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the input PDF file"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to save the extracted text"
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Force OCR processing even if normal text extraction succeeds"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Validate input file
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' does not exist", file=sys.stderr)
        sys.exit(1)

    if not input_path.is_file():
        print(f"Error: '{input_path}' is not a file", file=sys.stderr)
        sys.exit(1)

    # Extract text from PDF
    try:
        extractor = PDFTextExtractor()
        print(f"Extracting text from {input_path}...")

        def progress_callback(message):
            print(message)

        extracted_text, used_ocr = extractor.extract_text(
            input_path,
            coerce_ocr=args.force_ocr,
            websocket_callback=progress_callback
        )

        # Write the extracted text to the output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(extracted_text)

        print(f"Text extraction {'with OCR' if used_ocr else 'without OCR'} complete.")
        print(f"Extracted text saved to: {output_path}")

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()