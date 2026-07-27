#!/usr/bin/env python3
"""
Scientific Paper Analysis Script

This script reads a scientific paper from a text file, processes it through the OpenAI API,
and outputs structured analysis in both JSON and Markdown formats.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from experiments.structured.schemas.llm.scientific_observation import ScientificObservationForm


def get_cache_key(model: str, content: str) -> str:
    """Generate a unique cache key based on model and content."""
    key_string = f"{model}:{content}"
    return hashlib.md5(key_string.encode('utf-8')).hexdigest()


def get_cached_completion(
        client: OpenAI,
        model: str,
        content: str,
        system_prompt: str,
        cache_dir: str = "cache"
) -> ScientificObservationForm:
    """Return cached completion or make a new API call if not cached."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_key = get_cache_key(model, content)
    cache_path = os.path.join(cache_dir, f"{cache_key}.json")

    if os.path.exists(cache_path):
        print(f"Loading result from cache: {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ScientificObservationForm.parse_obj(data)
    else:
        print(f"Making API call with model: {model}")
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            response_format=ScientificObservationForm,
        )
        structured_output = completion.choices[0].message.parsed
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(structured_output.dict(), f, indent=2)
        return structured_output


def generate_markdown(output: ScientificObservationForm) -> str:
    """Generate markdown representation of the structured output."""
    md_lines = []

    # Title
    md_lines.append("# Scientific Observation Instrumentation Form\n")

    # Summary section
    md_lines.append("## Summary of the Paper\n")
    md_lines.append(f"**Content Summary:** {output.summary.content_summary}\n")
    md_lines.append("---\n")

    # Complete Instrument List section
    instrument_list = [
        f"{instr.instrument_name} ({instr.usage_category.value.capitalize()})"
        for instr in output.instrumentation_details
    ]
    md_lines.append("## Complete Instrument List\n")
    for idx, instrument in enumerate(instrument_list, start=1):
        md_lines.append(f"- {idx}. {instrument}")
    md_lines.append("---\n")

    # Instrumentation Details section
    md_lines.append("## Instrumentation Details\n")
    for idx, instrument in enumerate(output.instrumentation_details, start=1):
        usage = instrument.usage_category.value.upper()
        md_lines.append(f"### {idx}. {instrument.instrument_name} on board {instrument.spacecraft} ({usage})\n")
        md_lines.append("**General Comments:**")
        md_lines.append(f"> {instrument.general_comments.value}\n")
        md_lines.append("**Supporting Quote:**")
        md_lines.append(f"> {instrument.general_comments.supporting_quote}\n")

        if instrument.detectors:
            detectors_str = ", ".join(instrument.detectors.values)
            md_lines.append(f"- **Detectors:** {detectors_str}")
            md_lines.append(f"  - *Supporting Quote:* {instrument.detectors.supporting_quote}\n")

        for period_idx, period in enumerate(instrument.data_collection_periods, start=1):
            md_lines.append(f"#### Data Collection Period {period_idx}: {period.description}\n")

            # Time Range
            end_time = period.end_time.value if period.end_time is not None else "N/A"
            md_lines.append(f"- **Time Range:** {period.start_time.value} – {end_time}")
            md_lines.append(f"  - *Supporting Quote:* {period.start_time.supporting_quote}\n")

            # Wavelengths
            wavelengths_str = ", ".join(period.wavelengths.values) if period.wavelengths.values else "N/A"
            md_lines.append(f"- **Wavelength(s):** {wavelengths_str}")
            md_lines.append(f"  - *Supporting Quote:* {period.wavelengths.supporting_quote}\n")

            # Physical Observable
            md_lines.append(f"- **Physical Observable:** {period.physical_observable.value}")
            md_lines.append(f"  - *Supporting Quote:* {period.physical_observable.supporting_quote}\n")

            # Additional Comments
            md_lines.append(f"- **Additional Comments:** {period.additional_comments}\n")

        md_lines.append("---\n")

    return "\n".join(md_lines)


def save_output(
        output: ScientificObservationForm,
        output_dir: str = "output",
        bibcode: Optional[str] = None
) -> tuple[Path, Path]:
    """Save the structured output to JSON and Markdown files."""
    os.makedirs(output_dir, exist_ok=True)

    # Create base filenames
    prefix = f"{bibcode}_" if bibcode else ""
    json_path = Path(output_dir) / f"{prefix}structured_output.json"
    md_path = Path(output_dir) / f"{prefix}structured_output.md"

    # Save JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output.dict(), f, indent=2)
    print(f"JSON output saved to: {json_path}")

    # Save Markdown
    markdown_str = generate_markdown(output)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_str)
    print(f"Markdown output saved to: {md_path}")

    return json_path, md_path


def main():
    """Main function to parse arguments and run the analysis."""
    parser = argparse.ArgumentParser(description="Analyze scientific papers for instrumentation details.")
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the input text file containing the paper content"
    )
    parser.add_argument(
        "--model", "-m",
        default="o3-mini",
        help="OpenAI model to use (default: o3-mini)"
    )
    parser.add_argument(
        "--template", "-t",
        default="templates/system_instructions.xml",
        help="Path to the system prompt template file"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Directory to save output files"
    )
    parser.add_argument(
        "--bibcode", "-b",
        help="Bibcode of the paper (used for output filename)"
    )
    args = parser.parse_args()

    # Extract bibcode from filename if not provided
    if not args.bibcode:
        input_path = Path(args.input)
        if input_path.stem.endswith(".txt"):
            args.bibcode = input_path.stem[:-4]  # Remove .txt extension
        else:
            args.bibcode = input_path.stem

    # Read the paper content
    try:
        with open(args.input, "r", encoding="utf-8") as file:
            paper_content = file.read().strip()
        print(f"Read {len(paper_content)} characters from {args.input}")
    except FileNotFoundError:
        print(f"Error: File not found: {args.input}")
        return 1
    except Exception as e:
        print(f"Error reading file: {e}")
        return 1

    # Load the system prompt template
    try:
        template_path = Path(args.template)
        template_dir = str(template_path.parent)
        template_file = template_path.name
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template(template_file)
        system_prompt = template.render()
        print(f"Loaded system prompt template from {args.template}")
    except Exception as e:
        print(f"Error loading template: {e}")
        return 1

    # Initialize OpenAI client and get completion
    client = OpenAI()
    try:
        structured_output = get_cached_completion(
            client=client,
            model=args.model,
            content=paper_content,
            system_prompt=system_prompt
        )
        # Save output
        save_output(structured_output, args.output_dir, args.bibcode)
        print("Analysis completed successfully")
        return 0
    except Exception as e:
        print(f"Error during analysis: {e}")
        return 1


if __name__ == "__main__":
    exit(main())