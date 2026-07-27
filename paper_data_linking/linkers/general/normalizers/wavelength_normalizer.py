# paper_data_linking/linkers/general/wavelength_normalizer.py

import logging
import re
from typing import Optional, Dict

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedWavelength
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


@NormalizerRegistry.register("wavelength", version="1.0", data_sources=["vso"])
class WavelengthNormalizer(BaseNormalizer):
    """Wraps the LLM call that parses raw wavelength strings into structured format."""

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        from paper_data_linking.config.settings import LLMPipelineConfig
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required - no fallback to default to ensure explicit configuration")
        if not isinstance(llm_config, LLMPipelineConfig):
            raise ValueError(f"llm_config must be LLMPipelineConfig, got {type(llm_config)}")
        self.llm_config = llm_config

    def normalize(self, context: NormalizationContext) -> dict:
        # Direct typed field access - no helper method needed
        raw_wavelength = context.period_data.wavelengths

        if not raw_wavelength:
            logger.info("WavelengthNormalizer: No wavelength data found")
            return None

        # Preprocess: Replace special Unicode characters to avoid encoding issues with LLM APIs
        raw_wavelength = self._preprocess_wavelength_text(raw_wavelength)

        logger.info(f"WavelengthNormalizer: Calling LLM for wavelength: {raw_wavelength[:100]}...")
        logger.debug(f"WavelengthNormalizer: Input length: {len(raw_wavelength)} chars")

        config = self.llm_config.normalization.wavelength

        # Load prompts from XML template
        template_name = "wavelength_normalization"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            raw_wavelength=raw_wavelength
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'raw_wavelength': raw_wavelength
        }

        response = self.llm_client.completion(
            call_type="wavelength_normalization",
            model=config.model,
            messages=messages,
            **config.to_kwargs(
                response_format=None,  # Use text parsing instead of structured output
                prompt_context=prompt_context
            )
        )

        # Parse text response instead of JSON
        response_text = response.choices[0].message.content
        result = self._parse_wavelength_response(response_text, raw_wavelength)

        if result is None:
            logger.warning(f"WavelengthNormalizer: Failed to parse wavelength response: {response_text}")
            return None

        logger.debug(f"WavelengthNormalizer: Parsed result - ranges: {result.get('ranges')}")

        return result

    @staticmethod
    def _parse_wavelength_response(response: str, original_text: str) -> Optional[Dict]:
        """Parse simplified text response into structured wavelength dict using new range-based schema.

        Expected formats:
        - "211 angstrom, 193 angstrom" → discrete values: [{min:211, max:211}, {min:193, max:193}]
        - "1-8 angstrom" → single range: [{min:1, max:8}]
        - "5-10 keV, 25-50 keV" → multiple ranges: [{min:5, max:10}, {min:25, max:50}]
        - "7155 MHz" → single value: [{min:7155, max:7155}]
        - "not_applicable" → empty ranges: []
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
                "ranges": [],
                "original_text": original_text
            }

        # Map unit aliases (used throughout parsing)
        def _normalize_unit(u: str) -> str:
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
            return unit_map.get(u.lower(), u.lower())

        # Check if it's the multi-value format with unit repetition
        # e.g., "211 angstrom, 193 angstrom" or "5-10 keV, 25-50 keV"
        multi_unit_match = re.match(r'^([\d\s.,\-/]+\s+\w+(?:\s*,\s*[\d\s.,\-/]+\s+\w+)+)$', response)
        if multi_unit_match:
            # Parse multiple "value(s) unit" pairs - each range gets its own unit
            pairs = [p.strip() for p in response.split(',')]
            ranges = []
            for pair in pairs:
                # Match "number(s) unit" - could be "123 unit" or "1-8 unit"
                val_match = re.match(r'^([\d.,\-/]+)\s+(\w+)$', pair)
                if val_match:
                    val_str, u = val_match.groups()
                    normalized_unit = _normalize_unit(u)

                    # Parse the value part - could be single value or range
                    if '-' in val_str:
                        # Range: "5-10"
                        range_parts = val_str.split('-')
                        if len(range_parts) == 2:
                            min_val = _parse_number(range_parts[0])
                            max_val = _parse_number(range_parts[1])
                            ranges.append({"min": min_val, "max": max_val, "unit": normalized_unit})
                        else:
                            return None
                    else:
                        # Single value - min and max are the same
                        val = _parse_number(val_str)
                        ranges.append({"min": val, "max": val, "unit": normalized_unit})
                else:
                    return None

            if not ranges:
                return None
            values_str = None  # Already parsed
            shared_unit = None  # No shared unit in this path
        else:
            # Single unit format: "123 nm", "1-8 angstrom", "211, 193 angstrom"
            match = re.match(r'^([\d\s.,\-/]+)\s+(\w+)$', response)
            if not match:
                return None
            values_str, unit = match.groups()
            values_str = values_str.strip()
            shared_unit = _normalize_unit(unit)
            ranges = None  # Will parse below

        # Parse values_str if not already parsed (shared unit case)
        if ranges is None:
            ranges = []
            if ',' in values_str:
                # Could be multiple values ("211, 193") or multiple ranges ("5-10, 25-50")
                parts = values_str.split(',')
                try:
                    for part in parts:
                        part = part.strip()
                        if '-' in part:
                            # Range part: "5-10"
                            range_parts = part.split('-')
                            if len(range_parts) == 2:
                                min_val = _parse_number(range_parts[0])
                                max_val = _parse_number(range_parts[1])
                                ranges.append({"min": min_val, "max": max_val, "unit": shared_unit})
                            else:
                                return None
                        else:
                            # Single value part - min and max are the same
                            val = _parse_number(part)
                            ranges.append({"min": val, "max": val, "unit": shared_unit})
                except ValueError:
                    return None
            elif '-' in values_str:
                # Single range format: "1-8"
                parts = values_str.split('-')
                if len(parts) == 2:
                    try:
                        min_val = _parse_number(parts[0])
                        max_val = _parse_number(parts[1])
                        ranges.append({"min": min_val, "max": max_val, "unit": shared_unit})
                    except ValueError:
                        return None
                else:
                    return None
            else:
                # Single value
                try:
                    val = _parse_number(values_str)
                    ranges.append({"min": val, "max": val, "unit": shared_unit})
                except ValueError:
                    return None

        if not ranges:
            return None

        # Deduplicate ranges while preserving order (avoid repeated ranges)
        deduped_ranges = []
        seen = set()
        for r in ranges:
            # Round to 6 decimal places for comparison (include unit in key for proper deduplication)
            key = (round(r["min"], 6), round(r["max"], 6), r["unit"])
            if key in seen:
                continue
            seen.add(key)
            deduped_ranges.append(r)

        return {
            "ranges": deduped_ranges,
            "original_text": original_text
        }

    @staticmethod
    def _preprocess_wavelength_text(text: str) -> str:
        """Preprocess wavelength text to replace special Unicode characters.

        Replaces Unicode characters with their spelled-out equivalents to avoid
        encoding issues with LLM APIs (e.g., Bedrock).

        Args:
            text: Raw wavelength text

        Returns:
            Preprocessed text with Unicode characters replaced
        """
        # Replace common Unicode characters in wavelength/frequency contexts
        replacements = {
            'Å': 'Angstrom',  # U+00C5 - Angstrom symbol
            'å': 'angstrom',  # U+00E5 - lowercase angstrom
            '°': 'degrees',   # U+00B0 - degree symbol
            '×': 'x',         # U+00D7 - multiplication sign
            '–': '-',         # U+2013 - en dash
            '—': '-',         # U+2014 - em dash
            '∼': '~',         # U+223C - tilde operator
        }

        result = text
        for char, replacement in replacements.items():
            result = result.replace(char, replacement)

        return result
