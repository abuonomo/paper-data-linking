#!/usr/bin/env python3
"""
PDF Annotator

This script annotates a PDF with highlights and notes based on quote locations
from an AppScientificObservationForm schema. It highlights each matched text in the PDF,
adds notes in an annotation column, and generates excerpt images.
"""

import argparse
import json
import uuid
import fitz  # PyMuPDF
import os
import re
import logging
import unicodedata
from pathlib import Path

# Import schema models from your first file
from experiments.structured.schemas.app.scientific_observation import (
    AppScientificObservationForm,
    AppQuotedList,
    PDFQuoteLocation
)


def sample_substrings(search_string, max_attempts=5, sample_length=30):
    """
    Generate a list of substrings from a search string for fallback searches.
    """
    substrings = []
    length = len(search_string)
    for i in range(min(max_attempts, length - sample_length + 1)):
        substrings.append(search_string[i:i + sample_length])
    return substrings


def preprocess_text(text):
    """
    Normalize the text by stripping extra whitespace.
    """
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def find_text_in_page(page, search_string, images_dir=None, add_highlight=True):
    """
    Find and highlight text in a PDF page. Create excerpt images if requested.

    Args:
        page: PDF page object
        search_string: Text to search for
        images_dir: Directory to save excerpt images (if None, no images are saved)
        add_highlight: Whether to add highlight annotation

    Returns:
        List of PDFQuoteLocation objects for matches
    """
    locations = []
    search_string = preprocess_text(search_string)

    # Try full string search
    text_instances = page.search_for(search_string, flags=0)

    # If not found, try with sampled substrings
    if not text_instances:
        for substring in sample_substrings(search_string):
            text_instances = page.search_for(substring, flags=0)
            if text_instances:
                logging.info(f"Found match for substring '{substring}' on page {page.number + 1}")
                break

    if not text_instances:
        return locations  # No match on this page

    for inst in text_instances:
        # Create PDF location object
        pdf_location = PDFQuoteLocation(
            page_number=page.number + 1,
            x0=inst.x0,
            y0=inst.y0,
            x1=inst.x1,
            y1=inst.y1,
            vertical_middle=(inst.y0 + inst.y1) / 2
        )

        # Create excerpt image if directory is provided
        if images_dir:
            # Define a small margin (in points) for the excerpt image
            margin = 5
            x0 = max(0, inst.x0 - margin)
            y0 = max(0, inst.y0 - margin)
            x1 = min(page.rect.width, inst.x1 + margin)
            y1 = min(page.rect.height, inst.y1 + margin)
            inst_with_margin = fitz.Rect(x0, y0, x1, y1)

            # Create excerpts directory if it doesn't exist
            os.makedirs(images_dir, exist_ok=True)

            # Capture image for the excerpt
            pix = page.get_pixmap(clip=inst_with_margin)
            image_filename = f"excerpt_{uuid.uuid4().hex}.png"
            image_path = os.path.join(images_dir, image_filename)
            pix.save(image_path)
            logging.info(f"Saved excerpt image to {image_path}")
            pdf_location.excerpt_image = image_path

        # Add highlight to PDF
        if add_highlight:
            highlight = page.add_highlight_annot(inst)
            highlight.update()

        locations.append(pdf_location)

    return locations


def process_quoted_field(quoted_field, pdf_document, images_dir, annotated_keys,
                         original_page_width, instrument_name=None):
    """
    Process an AppQuotedStr or AppQuotedList field to find and highlight quotes.

    Args:
        quoted_field: AppQuotedStr or AppQuotedList object
        pdf_document: PDF document object
        images_dir: Directory to save excerpt images
        annotated_keys: Dictionary to track annotated quotes
        original_page_width: Width of original page (for annotation column)
        instrument_name: Name of the instrument (for annotation text)

    Returns:
        Boolean indicating if any matches were found
    """
    if not quoted_field or not quoted_field.supporting_quote:
        return False

    search_string = quoted_field.supporting_quote
    found_any = False

    # Process each page for this quote
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]

        # Find and highlight text
        pdf_locations = find_text_in_page(page, search_string, images_dir)

        if pdf_locations:
            # Add to the model's pdf_locations field
            if not hasattr(quoted_field, "pdf_locations") or quoted_field.pdf_locations is None:
                quoted_field.pdf_locations = []
            quoted_field.pdf_locations.extend(pdf_locations)
            found_any = True

            # Add annotation in the margin
            for location in pdf_locations:
                vertical_middle = location.vertical_middle

                # Only annotate once per vertical position on this page
                key = f"page_{page_num}_pos_{int(vertical_middle)}"
                if key not in annotated_keys:
                    # Determine annotation text
                    field_name = getattr(quoted_field, "value", "")
                    if isinstance(quoted_field, AppQuotedList):
                        field_name = ", ".join(quoted_field.values[:2])
                        if len(quoted_field.values) > 2:
                            field_name += "..."

                    annotation_text = f"{instrument_name or 'Unknown'}: {field_name}"

                    # Create annotation in margin
                    annot_rect = fitz.Rect(
                        original_page_width + 10,
                        location.y0,
                        original_page_width + 150 - 10,
                        location.y1
                    )
                    page.insert_text(
                        annot_rect.top_left,
                        annotation_text,
                        fontsize=8,
                        fontname="helv"
                    )
                    annotated_keys[key] = True

    return found_any


def process_data_collection_period(period, pdf_document, images_dir, annotated_keys,
                                   original_page_width, instrument_name):
    """
    Process an AppDataCollectionPeriod to find and highlight all quoted fields.

    Args:
        period: AppDataCollectionPeriod object
        pdf_document: PDF document object
        images_dir: Directory to save excerpt images
        annotated_keys: Dictionary to track annotated quotes
        original_page_width: Width of original page
        instrument_name: Name of the instrument

    Returns:
        Boolean indicating if any matches were found
    """
    found_any = False

    # Process each quoted field in the period
    if period.start_time:
        if process_quoted_field(period.start_time, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    if period.end_time:
        if process_quoted_field(period.end_time, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    if period.wavelengths:
        if process_quoted_field(period.wavelengths, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    if period.physical_observable:
        if process_quoted_field(period.physical_observable, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    return found_any


def process_instrumentation_details(instrumentation, pdf_document, images_dir, annotated_keys,
                                    original_page_width):
    """
    Process AppInstrumentationDetails to find and highlight all quotes.

    Args:
        instrumentation: AppInstrumentationDetails object
        pdf_document: PDF document object
        images_dir: Directory to save excerpt images
        annotated_keys: Dictionary to track annotated quotes
        original_page_width: Width of original page

    Returns:
        Boolean indicating if any matches were found
    """
    found_any = False
    instrument_name = instrumentation.instrument_name

    # Process general comments
    if instrumentation.general_comments:
        if process_quoted_field(instrumentation.general_comments, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    # Process detectors if present
    if instrumentation.detectors:
        if process_quoted_field(instrumentation.detectors, pdf_document, images_dir,
                                annotated_keys, original_page_width, instrument_name):
            found_any = True

    # Process each data collection period
    for period in instrumentation.data_collection_periods:
        if process_data_collection_period(period, pdf_document, images_dir,
                                          annotated_keys, original_page_width, instrument_name):
            found_any = True

    return found_any


def annotate_pdf(pdf_infile, json_infile, pdf_outfile, images_dir):
    """
    Annotate a PDF with quotes from AppScientificObservationForm data.

    Args:
        pdf_infile: Path to input PDF
        json_infile: Path to JSON file with AppScientificObservationForm data
        pdf_outfile: Path to save annotated PDF
        images_dir: Directory to save excerpt images

    Returns:
        Tuple of (pdf_outfile, updated_json_outfile) paths
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Load JSON data
    with open(json_infile, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    # Parse data using the schema
    observation_form = AppScientificObservationForm.parse_obj(json_data)

    # Define annotation column width (in PDF points)
    annotation_column_width = 150

    # Open the PDF document
    pdf_document = fitz.open(pdf_infile)
    logging.info(f"Opened PDF with {len(pdf_document)} pages.")

    # First pass: expand each page to add annotation column
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        original_page_width = page.rect.width
        page_height = page.rect.height

        # Expand page's media box to add annotation column
        new_rect = fitz.Rect(0, 0, original_page_width + annotation_column_width, page_height)
        page.set_mediabox(new_rect)

        # Draw vertical border to separate annotation column
        border_rect = fitz.Rect(original_page_width, 0, original_page_width + 2, page_height)
        page.add_rect_annot(border_rect)

    # Second pass: process instrumentation details
    annotated_keys = {}
    instrumentation_found = {}

    for instrument in observation_form.instrumentation_details:
        instrument_id = str(instrument.instrument_name)
        instrumentation_found[instrument_id] = process_instrumentation_details(
            instrument,
            pdf_document,
            images_dir,
            annotated_keys,
            original_page_width
        )

    # Log info about found/not found quotes
    for instrument_id, found in instrumentation_found.items():
        if not found:
            logging.warning(f"No quotes found for instrument '{instrument_id}'")

    # Save the annotated PDF
    pdf_document.save(pdf_outfile, garbage=4, deflate=True)
    pdf_document.close()
    logging.info(f"Annotated PDF saved to {pdf_outfile}")

    # Save updated observation form with PDF locations to JSON
    updated_json_outfile = os.path.splitext(pdf_outfile)[0] + "_with_locations.json"
    with open(updated_json_outfile, 'w', encoding='utf-8') as f:
        json.dump(observation_form.dict(), f, ensure_ascii=False, indent=2)
    logging.info(f"Updated JSON with PDF locations saved to {updated_json_outfile}")

    return pdf_outfile, updated_json_outfile


def main():
    """Main function to parse arguments and run PDF annotation."""
    parser = argparse.ArgumentParser(
        description="Annotate a PDF with highlights and notes based on AppScientificObservationForm data."
    )
    parser.add_argument(
        "--pdf", "-p",
        required=True,
        help="Path to the input PDF file"
    )
    parser.add_argument(
        "--json", "-j",
        required=True,
        help="Path to the JSON file with AppScientificObservationForm data"
    )
    parser.add_argument(
        "--output", "-o",
        help="Path for the annotated PDF output (default: adds '_annotated' suffix)"
    )
    parser.add_argument(
        "--images-dir", "-i",
        default="excerpts_images",
        help="Directory to save excerpt images (default: excerpts_images)"
    )
    parser.add_argument(
        "--bibcode", "-b",
        help="Bibcode of the paper (used for default output filename if not provided)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging based on verbosity
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Setup input and output paths
    pdf_inpath = Path(args.pdf)
    json_inpath = Path(args.json)

    # Determine output path
    if args.output:
        pdf_outpath = Path(args.output)
    else:
        # If bibcode is provided, use it for the output filename
        if args.bibcode:
            pdf_outdir = pdf_inpath.parent
            pdf_outpath = pdf_outdir / f"{args.bibcode}_annotated.pdf"
        else:
            # Add '_annotated' before the extension
            stem = pdf_inpath.stem
            pdf_outpath = pdf_inpath.with_name(f"{stem}_annotated{pdf_inpath.suffix}")

    # Ensure output directory exists
    pdf_outpath.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Run annotation
        annotate_pdf(
            pdf_infile=str(pdf_inpath),
            json_infile=str(json_inpath),
            pdf_outfile=str(pdf_outpath),
            images_dir=args.images_dir
        )
        logging.info("Annotation completed successfully")
        return 0
    except Exception as e:
        logging.error(f"Error during annotation: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())