"""Deterministic parser for structured instrument details markdown.

Converts the markdown output from the paper_analysis LLM step into the
StructuredInstrumentDetails Pydantic schema without requiring an LLM call.
"""
from __future__ import annotations

import re
from typing import List, Optional

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    DataCollectionPeriod,
    Instrument,
    StructuredInstrumentDetails,
)


def parse_instrument_markdown(text: str) -> StructuredInstrumentDetails:
    """Parse structured instrument details markdown into Pydantic model.

    Args:
        text: The markdown text from the paper_analysis stage.

    Returns:
        StructuredInstrumentDetails validated Pydantic model.

    Raises:
        ValueError: If the markdown cannot be parsed into a valid schema.
    """
    lines = text.split("\n")

    paper_summary = ""
    instruments: List[dict] = []

    # State tracking
    current_instrument: Optional[dict] = None
    current_period: Optional[dict] = None
    current_field: Optional[str] = None  # Which field quotes/values should attach to
    in_summary = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # --- Section headers ---
        if stripped.startswith("## Summary") or stripped.startswith("## Summary of the Paper"):
            in_summary = True
            continue

        if stripped.startswith("## Instrumentation Details"):
            in_summary = False
            continue

        # --- Paper summary ---
        if in_summary:
            m = re.match(r"^-\s+\**Content Summary\**:\s*(.*)", stripped)
            if m:
                paper_summary = m.group(1).strip()
            continue

        # --- H3: New instrument ---
        if stripped.startswith("### "):
            # Save previous period and instrument
            if current_period and current_instrument is not None:
                current_instrument["data_collection_periods"].append(
                    _build_period(current_period)
                )
                current_period = None

            if current_instrument is not None:
                instruments.append(_build_instrument(current_instrument))

            name = stripped[4:].strip()
            current_instrument = {
                "name": name,
                "general_comments": "",
                "general_quotes": [],
                "data_collection_periods": [],
            }
            current_field = "instrument_general"
            continue

        # --- H4: New data collection period ---
        if stripped.startswith("#### "):
            # Save previous period
            if current_period and current_instrument is not None:
                current_instrument["data_collection_periods"].append(
                    _build_period(current_period)
                )

            period_name = _extract_period_name(stripped)
            current_period = {
                "period_name": period_name,
                "time_range": "",
                "time_quotes": [],
                "wavelengths": None,
                "wavelength_quotes": [],
                "physical_observable": "",
                "physobs_quotes": [],
                "general_quotes": [],
                "additional_comments": None,
                "_additional_comments_lines": [],
            }
            current_field = None
            continue

        # --- Skip top-level headings ---
        if stripped.startswith("# "):
            continue

        # --- Field labels (bold or plain) ---
        # Check for field labels in the current context
        if current_instrument is not None:
            field_match = _match_field_label(stripped)
            if field_match:
                field_name, field_value = field_match

                if current_period is not None:
                    # Period-level fields
                    if field_name == "time_range":
                        current_period["time_range"] = field_value
                        current_field = "time_range"
                        continue
                    elif field_name == "wavelengths":
                        current_period["wavelengths"] = field_value if field_value else None
                        current_field = "wavelengths"
                        continue
                    elif field_name == "physical_observable":
                        current_period["physical_observable"] = field_value
                        current_field = "physical_observable"
                        continue
                    elif field_name == "additional_comments":
                        if field_value:
                            current_period["_additional_comments_lines"].append(field_value)
                        current_field = "additional_comments"
                        continue

                # Instrument-level fields
                if field_name == "general_comments":
                    if current_period is None:
                        current_instrument["general_comments"] = field_value
                        current_field = "instrument_general"
                    continue

            # --- Supporting quotes ---
            quote = _extract_quote(stripped)
            if quote is not None:
                _assign_quote(
                    quote, current_field, current_instrument, current_period
                )
                continue

            # --- Italic-wrapped quotes (e.g., *"Fig. 1...from Oct 31..."*) ---
            # Some LLMs put the value as an italic quote on the line after a
            # field label instead of inline.  Treat as a quote for the current
            # field if we're inside a period.
            italic_quote = _extract_italic_quote(stripped)
            if italic_quote is not None and current_period is not None and current_field:
                _assign_quote(
                    italic_quote, current_field, current_instrument, current_period
                )
                # Also backfill the field value if it's empty
                if current_field == "time_range" and not current_period["time_range"].strip():
                    current_period["time_range"] = italic_quote
                continue

            # --- Continuation / sub-bullet values ---
            if _is_sub_bullet(line):
                sub_value = _extract_sub_bullet_value(stripped)
                if sub_value and current_field:
                    if current_period is not None:
                        if current_field == "wavelengths" and not current_period["wavelengths"]:
                            current_period["wavelengths"] = sub_value
                        elif current_field == "additional_comments":
                            current_period["_additional_comments_lines"].append(sub_value)
                        elif current_field == "instrument_general" and current_period is None:
                            # Multi-line general comment
                            if current_instrument["general_comments"]:
                                current_instrument["general_comments"] += " " + sub_value
                            else:
                                current_instrument["general_comments"] = sub_value
                    elif current_field == "instrument_general":
                        if current_instrument["general_comments"]:
                            current_instrument["general_comments"] += " " + sub_value
                        else:
                            current_instrument["general_comments"] = sub_value
                continue

    # Save final period and instrument
    if current_period and current_instrument is not None:
        current_instrument["data_collection_periods"].append(
            _build_period(current_period)
        )
    if current_instrument is not None:
        instruments.append(_build_instrument(current_instrument))

    return StructuredInstrumentDetails(
        paper_summary=paper_summary,
        instruments=[Instrument(**inst) for inst in instruments],
    )


def _extract_period_name(heading: str) -> str:
    """Extract period name from H4 heading like '#### Data Collection Period 1: Name'."""
    text = heading.lstrip("#").strip()
    m = re.match(r"Data Collection Period\s+\d+:\s*(.*)", text)
    if m:
        return m.group(1).strip()
    return text


def _match_field_label(line: str) -> Optional[tuple]:
    """Match a field label line, return (field_name, value) or None."""
    patterns = [
        (r"^-\s+\**General Comments\**:\s*(.*)", "general_comments"),
        (r"^-\s+\**Time Range\**:\s*(.*)", "time_range"),
        (r"^-\s+\**Wavelength\(s\)\**:\s*(.*)", "wavelengths"),
        (r"^-\s+\**Physical Observable\**:\s*(.*)", "physical_observable"),
        (r"^-\s+\**Additional Comments\**:\s*(.*)", "additional_comments"),
    ]
    for pattern, field_name in patterns:
        m = re.match(pattern, line)
        if m:
            return (field_name, m.group(1).strip())
    return None


def _extract_italic_quote(line: str) -> Optional[str]:
    """Extract a bare italic-wrapped quote like *"some text"* or *above*.

    Only matches lines that are purely an italic expression — not field labels,
    not sub-bullets, not headings.  Returns None for anything that another
    handler should process.
    """
    # Full italic-quoted string: *"..."* or *"...*
    m = re.match(r'^\s*\*["\u201c](.*?)["\u201d]\*\s*$', line)
    if m:
        return m.group(1).strip()
    # Italic without closing on same line: *"...
    m = re.match(r'^\s*\*["\u201c](.*)', line)
    if m:
        return m.group(1).rstrip('*"\u201d').strip()
    return None


def _extract_quote(line: str) -> Optional[str]:
    """Extract a supporting quote from a line, or None."""
    m = re.match(r'^-?\s*\**Supporting Quote\**:\s*["\u201c](.*?)["\u201d]\s*$', line)
    if m:
        return m.group(1).strip()
    # Also handle quotes that span or don't have closing quote on same line
    m = re.match(r'^-?\s*\**Supporting Quote\**:\s*["\u201c](.*)', line)
    if m:
        return m.group(1).rstrip('"\u201d').strip()
    return None


def _assign_quote(
    quote: str,
    current_field: Optional[str],
    instrument: dict,
    period: Optional[dict],
) -> None:
    """Assign a quote to the correct list based on current field context."""
    if period is not None:
        if current_field == "time_range":
            period["time_quotes"].append(quote)
        elif current_field == "wavelengths":
            period["wavelength_quotes"].append(quote)
        elif current_field == "physical_observable":
            period["physobs_quotes"].append(quote)
        elif current_field == "additional_comments":
            period["general_quotes"].append(quote)
        else:
            period["general_quotes"].append(quote)
    elif current_field == "instrument_general":
        instrument["general_quotes"].append(quote)


def _is_sub_bullet(line: str) -> bool:
    """Check if a line is a sub-bullet (indented with - or *)."""
    return bool(re.match(r"^\s{2,}-\s+", line))


def _extract_sub_bullet_value(line: str) -> Optional[str]:
    """Extract value from a sub-bullet line, ignoring Supporting Quote lines."""
    stripped = line.strip()
    if re.match(r"^-?\s*\**Supporting Quote\**:", stripped):
        return None
    m = re.match(r"^-\s+(.*)", stripped)
    if m:
        return m.group(1).strip()
    return None


def _build_period(period_data: dict) -> dict:
    """Build a DataCollectionPeriod dict from collected data."""
    additional = None
    if period_data["_additional_comments_lines"]:
        additional = " ".join(period_data["_additional_comments_lines"])

    # If the deterministic parser captured an empty time_range (value was on
    # the next line, not inline with the label), fall back to the first
    # time_quote which often contains the date information.
    time_range = period_data["time_range"]
    if not time_range.strip() and period_data["time_quotes"]:
        time_range = period_data["time_quotes"][0]

    return {
        "period_name": period_data["period_name"],
        "time_range": time_range,
        "time_quotes": period_data["time_quotes"],
        "wavelengths": period_data["wavelengths"],
        "wavelength_quotes": period_data["wavelength_quotes"],
        "physical_observable": period_data["physical_observable"],
        "physobs_quotes": period_data["physobs_quotes"],
        "general_quotes": period_data["general_quotes"],
        "additional_comments": additional,
    }


def _build_instrument(instrument_data: dict) -> dict:
    """Build an Instrument dict from collected data."""
    return {
        "name": instrument_data["name"],
        "general_comments": instrument_data["general_comments"],
        "general_quotes": instrument_data["general_quotes"],
        "data_collection_periods": instrument_data["data_collection_periods"],
    }