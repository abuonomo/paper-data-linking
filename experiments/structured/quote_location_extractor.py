#!/usr/bin/env python3
"""
Quote Location Extractor

This script finds the exact locations of supporting quotes within a text file and
converts the structured JSON output (produced by the OpenAI response) to an application
schema that includes location metadata.
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import logging

from fuzzywuzzy import fuzz

# Import the original LLM schema
from experiments.structured.schemas.llm.scientific_observation import (
    ScientificObservationForm as LLMScientificObservationForm
)

# Import the application schema
from experiments.structured.schemas.app.scientific_observation import (
    AppScientificObservationForm,
    AppSummary,
    AppQuotedStr,
    AppQuotedList,
    QuoteLocation,
    AppInstrumentationDetails,
    AppDataCollectionPeriod
)

logging.basicConfig(level=logging.WARNING)


def find_best_match_location(text: str, quote: str, threshold: int):
    location = _find_best_match_location(text, quote, threshold)
    if location is None:
        logging.warning(f"No location found for quote: {quote[:30]}... with threshold {threshold}")
    return location


def preprocess_text(text: str) -> str:
    """
    Normalize the text by removing extraneous line breaks, multiple spaces,
    and standardizing ligatures and special characters.
    """
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _find_best_match_location(text: str, quote: str, threshold: int = 80) -> dict:
    """
    Find the best match location of a quote within the text using fuzzy matching.
    Returns a dictionary with start and end indices, score, and the matched excerpt
    if above the threshold; otherwise, returns None.
    """
    if not quote or not text:
        return None

    processed_text = preprocess_text(text)
    processed_quote = preprocess_text(quote)

    best_start = None
    best_end = None
    best_score = 0
    best_excerpt = ""

    window_size = len(processed_quote)
    for i in range(len(processed_text) - window_size + 1):
        window = processed_text[i:i + window_size]
        score = fuzz.ratio(window, processed_quote)
        if score > best_score:
            best_score = score
            best_start = i
            best_end = i + window_size
            best_excerpt = window

    if best_score >= threshold:
        return {
            'start': best_start,
            'end': best_end,
            'score': best_score,
            'excerpt': best_excerpt
        }
    else:
        return None


def convert_to_app_schema(llm_model, text: str, threshold: int = 80, bibcode: str = None):
    """Convert LLM schema to application schema with quote locations"""

    # Base conversion for the main form
    app_form = AppScientificObservationForm(
        title=llm_model.title,
        summary=AppSummary(content_summary=llm_model.summary.content_summary),
        instrumentation_details=[],
        bibcode=bibcode,
        extraction_timestamp=datetime.now().isoformat()
    )

    # Process each instrument
    for instr in llm_model.instrumentation_details:
        # Convert general comments with location
        general_comments_loc = find_best_match_location(text, instr.general_comments.supporting_quote, threshold)
        app_general_comments = AppQuotedStr(
            value=instr.general_comments.value,
            supporting_quote=instr.general_comments.supporting_quote,
            location=QuoteLocation(**general_comments_loc) if general_comments_loc else None
        )

        # Convert detectors if present
        app_detectors = None
        if instr.detectors:
            detectors_loc = find_best_match_location(text, instr.detectors.supporting_quote, threshold)
            app_detectors = AppQuotedList(
                values=instr.detectors.values,
                supporting_quote=instr.detectors.supporting_quote,
                location=QuoteLocation(**detectors_loc) if detectors_loc else None
            )

        # Create instrumentation details
        app_instr = AppInstrumentationDetails(
            instrument_name=instr.instrument_name,
            spacecraft=instr.spacecraft,
            general_comments=app_general_comments,
            detectors=app_detectors,
            usage_category=instr.usage_category,
            data_collection_periods=[]
        )

        # Convert data collection periods
        for period in instr.data_collection_periods:
            # Convert all the quoted fields with locations
            start_time_loc = find_best_match_location(text, period.start_time.supporting_quote, threshold)
            app_start_time = AppQuotedStr(
                value=period.start_time.value,
                supporting_quote=period.start_time.supporting_quote,
                location=QuoteLocation(**start_time_loc) if start_time_loc else None
            )

            app_end_time = None
            if period.end_time:
                end_time_loc = find_best_match_location(text, period.end_time.supporting_quote, threshold)
                app_end_time = AppQuotedStr(
                    value=period.end_time.value,
                    supporting_quote=period.end_time.supporting_quote,
                    location=QuoteLocation(**end_time_loc) if end_time_loc else None
                )

            wavelengths_loc = find_best_match_location(text, period.wavelengths.supporting_quote, threshold)
            app_wavelengths = AppQuotedList(
                values=period.wavelengths.values,
                supporting_quote=period.wavelengths.supporting_quote,
                location=QuoteLocation(**wavelengths_loc) if wavelengths_loc else None
            )

            observable_loc = find_best_match_location(text, period.physical_observable.supporting_quote, threshold)
            app_observable = AppQuotedStr(
                value=period.physical_observable.value,
                supporting_quote=period.physical_observable.supporting_quote,
                location=QuoteLocation(**observable_loc) if observable_loc else None
            )

            # Create the period
            app_period = AppDataCollectionPeriod(
                description=period.description,
                start_time=app_start_time,
                end_time=app_end_time,
                wavelengths=app_wavelengths,
                physical_observable=app_observable,
                additional_comments=period.additional_comments
            )

            app_instr.data_collection_periods.append(app_period)

        app_form.instrumentation_details.append(app_instr)

    return app_form


def main():
    """Main function to parse arguments and run the location extraction."""
    parser = argparse.ArgumentParser(
        description="Extract quote locations from text and add location metadata to structured JSON."
    )
    parser.add_argument("--json", "-j", required=True, help="Path to the input JSON file with structured data")
    parser.add_argument("--text", "-t", required=True,
                        help="Path to the text file containing the original paper content")
    parser.add_argument("--output", "-o",
                        help="Path for the output JSON file with location data (default: adds '_with_locations' suffix)")
    parser.add_argument("--threshold", "-th", type=int, default=80,
                        help="Fuzzy matching threshold (0-100, default: 80)")
    parser.add_argument("--bibcode", "-b",
                        help="Bibcode of the paper (used for default output filename if not provided)")

    args = parser.parse_args()

    # Setup input and output paths
    json_path = Path(args.json)
    text_path = Path(args.text)

    if args.output:
        output_path = Path(args.output)
    else:
        if args.bibcode:
            output_dir = json_path.parent
            output_path = output_dir / f"{args.bibcode}_structured_output_with_locations.json"
        else:
            stem = json_path.stem
            output_path = json_path.with_name(f"{stem}_with_locations{json_path.suffix}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load the original structured JSON data into the LLM Pydantic model
    try:
        with open(json_path, 'r', encoding='utf-8') as json_file:
            json_data = json.load(json_file)
        llm_output = LLMScientificObservationForm.parse_obj(json_data)
        print(f"Loaded JSON data from: {json_path}")
    except Exception as e:
        print(f"Error loading JSON file: {e}")
        return 1

    # Load text data
    try:
        with open(text_path, 'r', encoding='utf-8') as text_file:
            raw_text = text_file.read()
        print(f"Loaded text data from: {text_path}")
    except Exception as e:
        print(f"Error loading text file: {e}")
        return 1

    # Convert to application schema with quote locations
    print(f"Finding quote locations with threshold: {args.threshold}...")
    app_output = convert_to_app_schema(llm_output, raw_text, args.threshold, args.bibcode)

    # Save the application model
    try:
        with open(output_path, 'w', encoding='utf-8') as output_file:
            output_file.write(app_output.model_dump_json(indent=2, exclude_none=True))
        print(f"Saved output with location data to: {output_path}")
    except Exception as e:
        print(f"Error saving output file: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())