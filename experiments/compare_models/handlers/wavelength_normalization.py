import json
import re
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult


class NormalizedWavelength(BaseModel):
    """Pydantic model matching the production schema"""
    values: List[float] = Field(description="Wavelength values")
    unit: str = Field(description="angstrom|nm|keV|kHz|MHz|GHz|Hz")
    type: str = Field(description="discrete|range|band|not_applicable")
    band_name: Optional[str] = Field(default=None, description="Standardized band name if applicable")
    original_text: str = Field(description="Original wavelength text")


class WavelengthNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "wavelength_normalization"

    def get_response_format(self) -> Optional[type[BaseModel]]:
        return NormalizedWavelength

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response into dictionary"""
        try:
            data = json.loads(response)
            # Validate it matches the schema
            NormalizedWavelength(**data)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """Compare two wavelength normalization responses

        Note: band_name is ignored in comparison as it's optional metadata not used in code logic.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Compare key fields (band_name intentionally excluded - it's metadata only)
        type_match = resp1.get('type') == resp2.get('type')
        unit_match = resp1.get('unit') == resp2.get('unit')

        # Compare values (with tolerance for floating point)
        values1 = sorted(resp1.get('values', []))
        values2 = sorted(resp2.get('values', []))
        values_match = len(values1) == len(values2) and all(
            abs(v1 - v2) < 0.001 for v1, v2 in zip(values1, values2)
        )

        agree = type_match and unit_match and values_match

        if not agree:
            details_parts = []
            if not type_match:
                details_parts.append(f"type: {resp1.get('type')} vs {resp2.get('type')}")
            if not unit_match:
                details_parts.append(f"unit: {resp1.get('unit')} vs {resp2.get('unit')}")
            if not values_match:
                details_parts.append(f"values: {values1} vs {values2}")
            details = "; ".join(details_parts)
        else:
            details = None

        return ComparisonResult(agree=agree, resp1=resp1, resp2=resp2, details=details)

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format wavelength data for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        wl_type = response.get('type', 'unknown')
        values = response.get('values', [])
        unit = response.get('unit', '')
        band_name = response.get('band_name')
        original = response.get('original_text', '')

        # Color code by type
        type_colors = {
            'discrete': '#2563eb',  # blue
            'range': '#16a34a',     # green
            'band': '#9333ea',      # purple
            'not_applicable': '#6b7280'  # gray
        }
        color = type_colors.get(wl_type, '#000000')

        parts = []
        parts.append(f'<span style="color: {color}; font-weight: bold;">{wl_type.upper()}</span>')

        if wl_type != 'not_applicable':
            if values:
                values_str = ', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in values)
                parts.append(f'{values_str} {unit}')
            if band_name:
                parts.append(f'(band: {band_name})')

        parts.append(f'<br><span style="color: #6b7280; font-size: 0.9em;">"{original}"</span>')

        return '<br>'.join(parts)

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        wl_type = response.get('type', 'unknown')
        values = response.get('values', [])
        unit = response.get('unit', '')

        if wl_type == 'not_applicable':
            return "NOT_APPLICABLE"
        elif values:
            values_str = ', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in values)
            return f"{wl_type}: {values_str} {unit}"
        else:
            return wl_type.upper()


class WavelengthNormalizationSimpleHandler(CallTypeHandler):
    """Handler for simplified text-based wavelength normalization output.

    This handler avoids structured output format issues by requesting plain text output
    in the format: "values unit" (e.g., "211 angstrom, 193 angstrom" or "1-8 nm")
    """

    def get_call_type_name(self) -> str:
        return "wavelength_normalization"

    def get_response_format(self) -> Optional[type[BaseModel]]:
        # Return None - don't use structured output, request plain text
        return None

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse simplified text response into structured dict.

        Expected formats:
        - "211 angstrom, 193 angstrom" (discrete)
        - "1-8 angstrom" (range)
        - "7155 MHz" (single)
        - "not_applicable"
        """
        def _parse_number(val_str: str) -> float:
            """Parse numeric strings, allowing simple fractions like '1/3'."""
            val_str = val_str.strip()
            if '/' in val_str and val_str.count('/') == 1:
                num, den = val_str.split('/')
                return float(num) / float(den)
            return float(val_str)

        response = response.strip()

        if response.lower() == "not_applicable":
            return {
                "values": [],
                "unit": "N/A",
                "type": "not_applicable"
            }

        # Try to extract values and unit from the response
        # Match patterns like "123 nm", "1-8 angstrom", "211 angstrom, 193 angstrom"
        # Need to handle unit appearing multiple times: "211 angstrom, 193 angstrom"

        # First check if it's the multi-unit format (e.g., "211 angstrom, 193 angstrom" or "5-10 keV, 25-50 keV")
        multi_unit_match = re.match(r'^([\d\s.,-]+\s+\w+(?:\s*,\s*[\d\s.,-]+\s+\w+)+)$', response)
        if multi_unit_match:
            # Parse multiple "value(s) unit" pairs
            pairs = [p.strip() for p in response.split(',')]
            values = []
            unit = None
            for pair in pairs:
                # Match "number(s) unit" - could be "123 unit" or "1-8 unit"
                val_match = re.match(r'^([\d.,-]+)\s+(\w+)$', pair)
                if val_match:
                    val_str, u = val_match.groups()
                    u = u.lower()
                    if unit is None:
                        unit = u

                    # Parse the value part - could be single value or range
                    if '-' in val_str:
                        # Range: "5-10"
                        range_parts = val_str.split('-')
                        if len(range_parts) == 2:
                            values.append(_parse_number(range_parts[0]))
                            values.append(_parse_number(range_parts[1]))
                        else:
                            return None
                    else:
                        # Single value
                        values.append(_parse_number(val_str))
                else:
                    return None

            if not values or unit is None:
                return None
            values_str = None  # Already parsed
        else:
            # Single unit format: "123 nm", "1-8 angstrom"
            match = re.match(r'^([\d\s,.-]+)\s+(\w+)$', response)
            if not match:
                return None
            values_str, unit = match.groups()
            values_str = values_str.strip()
            unit = unit.strip().lower()

        # Map unit aliases
        unit_map = {
            'å': 'angstrom',
            'angstrom': 'angstrom',
            'nm': 'nm',
            'kev': 'keV',
            'khz': 'kHz',
            'mhz': 'MHz',
            'ghz': 'GHz',
            'hz': 'Hz',
        }
        unit = unit_map.get(unit, unit)

        # Parse values if not already parsed
        wl_type = None

        if values_str is None:
            # Already parsed in multi-unit format
            wl_type = "discrete"
        elif ',' in values_str:
            # Could be multiple values ("211, 193") or multiple ranges ("5-10, 25-50")
            parts = values_str.split(',')
            try:
                for part in parts:
                    part = part.strip()
                    if '-' in part:
                        # Range part: "5-10"
                        range_parts = part.split('-')
                        if len(range_parts) == 2:
                            values.append(_parse_number(range_parts[0]))
                            values.append(_parse_number(range_parts[1]))
                        else:
                            return None
                    else:
                        # Single value part
                        values.append(_parse_number(part))
                # Determine type based on content
                if len(parts) == 1 and '-' in values_str:
                    wl_type = "range"
                else:
                    wl_type = "discrete"
            except ValueError:
                return None
        elif '-' in values_str:
            # Single range format: "1-8"
            parts = values_str.split('-')
            if len(parts) == 2:
                try:
                    values = [_parse_number(p) for p in parts]
                    wl_type = "range"
                except ValueError:
                    return None
            else:
                return None
        else:
            # Single value
            try:
                values = [_parse_number(values_str)]
                wl_type = "discrete"
            except ValueError:
                return None

        if not values or wl_type is None:
            return None

        # Deduplicate values while preserving order (avoid repeated lines in outputs)
        deduped_values = []
        seen = set()
        for v in values:
            key = round(v, 6) if isinstance(v, float) else v
            if key in seen:
                continue
            seen.add(key)
            deduped_values.append(v)

        return {
            "values": deduped_values,
            "unit": unit,
            "type": wl_type,
            "band_name": None,
            "original_text": response
        }

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """Compare two wavelength normalization responses"""
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        type_match = resp1.get('type') == resp2.get('type')
        unit_match = resp1.get('unit') == resp2.get('unit')

        values1 = sorted(resp1.get('values', []))
        values2 = sorted(resp2.get('values', []))
        values_match = len(values1) == len(values2) and all(
            abs(v1 - v2) < 0.001 for v1, v2 in zip(values1, values2)
        )

        agree = type_match and unit_match and values_match

        if not agree:
            details_parts = []
            if not type_match:
                details_parts.append(f"type: {resp1.get('type')} vs {resp2.get('type')}")
            if not unit_match:
                details_parts.append(f"unit: {resp1.get('unit')} vs {resp2.get('unit')}")
            if not values_match:
                details_parts.append(f"values: {values1} vs {values2}")
            details = "; ".join(details_parts)
        else:
            details = None

        return ComparisonResult(agree=agree, resp1=resp1, resp2=resp2, details=details)

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format wavelength data for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        wl_type = response.get('type', 'unknown')
        values = response.get('values', [])
        unit = response.get('unit', '')

        type_colors = {
            'discrete': '#2563eb',
            'range': '#16a34a',
            'not_applicable': '#6b7280'
        }
        color = type_colors.get(wl_type, '#000000')

        parts = []
        parts.append(f'<span style="color: {color}; font-weight: bold;">{wl_type.upper()}</span>')

        if wl_type != 'not_applicable' and values:
            values_str = ', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in values)
            parts.append(f'{values_str} {unit}')

        return '<br>'.join(parts)

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        wl_type = response.get('type', 'unknown')
        values = response.get('values', [])
        unit = response.get('unit', '')

        if wl_type == 'not_applicable':
            return "NOT_APPLICABLE"
        elif values:
            values_str = ', '.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in values)
            return f"{wl_type}: {values_str} {unit}"
        else:
            return wl_type.upper()
