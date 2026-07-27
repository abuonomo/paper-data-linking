# paper_data_linking/linkers/general/detector_normalizer.py

import json
import logging
from typing import Dict, Optional

from paper_data_linking.config.paths import VSO_METADATA_JSONL
from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedDetector
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


@NormalizerRegistry.register("detector", version="1.0", data_sources=["vso"])
class DetectorNormalizer(BaseNormalizer):
    """
    Given an instrument_code and raw detector context text, restrict choices to
    VSO-approved detectors (from vso_metadata.jsonl) and return the chosen detector.
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required for DetectorNormalizer")
        self.llm_config = llm_config
        self._instrument_detectors = self._load_instrument_detectors()

    def _load_instrument_detectors(self) -> Dict[str, list]:
        """Load and parse instrument-detector mappings from VSO metadata JSONL file.

        Returns:
            Dictionary mapping instrument codes to sorted lists of available detectors.
        """
        instrument_detectors: Dict[str, set] = {}

        if VSO_METADATA_JSONL.exists():
            with open(VSO_METADATA_JSONL, "r", encoding="utf-8") as md:
                for line in md:
                    entry = json.loads(line)
                    code = entry.get("instrument")
                    detector = entry.get("detector")
                    if code and detector:
                        # detector can be a list or single value
                        if isinstance(detector, list):
                            for det in detector:
                                instrument_detectors.setdefault(code, set()).add(det)
                        else:
                            instrument_detectors.setdefault(code, set()).add(detector)

        # Convert sets to sorted lists
        return {code: sorted(detectors) for code, detectors in instrument_detectors.items()}

    def _build_detector_context(self, context: NormalizationContext) -> str:
        """Build the detector context string from instrument and period data.

        Organizes detector-relevant information with structural clarity:
        - Instrument identification and mission context
        - Observation period details (time range, wavelengths)
        - Instrument-level and period-specific comments
        - Supporting quotes from the paper

        Args:
            context: NormalizationContext containing instrument and period data

        Returns:
            A structured string of detector context information with newline separation
        """
        sections = []

        # Section 1: Instrument and Mission Context
        instrument_section = []
        instrument_section.append(f"Instrument: {context.instrument_name}")
        if context.grounding_result.matched_instrument_name:
            mission_info = context.grounding_result.matched_instrument_name
            if context.grounding_result.matched_mission_name:
                mission_info += f" ({context.grounding_result.matched_mission_name})"
            instrument_section.append(f"Matched: {mission_info}")
        if context.grounding_result.reasoning:
            instrument_section.append(f"Purpose: {context.grounding_result.reasoning}")
        if instrument_section:
            sections.append(" ".join(instrument_section))

        # Section 2: Period Information
        period_section = []
        period_section.append(f"Period: {context.period_name}")
        if context.period_data.time_range:
            period_section.append(f"Time Range: {context.period_data.time_range}")
        if context.period_data.wavelengths:
            period_section.append(f"Wavelengths: {context.period_data.wavelengths}")
        if period_section:
            sections.append(" ".join(period_section))

        # Section 3: Instrument-level Comments
        if context.instrument_general_comments:
            sections.append(context.instrument_general_comments)

        # Section 4: Period-specific Details
        period_details = []
        if context.period_data.additional_comments:
            period_details.append(context.period_data.additional_comments)
        if context.period_data.physical_observable:
            period_details.append(context.period_data.physical_observable)
        if period_details:
            sections.append(" ".join(period_details))

        # Section 5: Supporting Quotes
        if context.period_data.general_quotes:
            sections.append(" ".join(context.period_data.general_quotes))

        return "\n".join(sections).strip()

    def normalize(self, context: NormalizationContext) -> dict:
        """Return a dict: {detector, original_text}."""
        instrument_code = context.instrument_code
        raw_detector_context = self._build_detector_context(context)

        if not raw_detector_context:
            logger.info(f"DetectorNormalizer: No detector context found for instrument {instrument_code}")
            return None

        logger.info(f"DetectorNormalizer: Processing detector context for instrument {instrument_code}: {raw_detector_context[:100]}...")

        candidates = self._instrument_detectors.get(instrument_code, [])
        logger.debug(f"DetectorNormalizer: Found {len(candidates)} candidates for instrument {instrument_code}")

        # Route to appropriate handler based on number of candidates
        if not candidates:
            return self._handle_no_candidates(raw_detector_context, instrument_code)
        elif len(candidates) == 1:
            return self._handle_single_candidate(raw_detector_context, instrument_code)
        else:
            return self._handle_multiple_candidates(raw_detector_context, instrument_code, candidates)

    def _handle_no_candidates(self, raw_detector_context: str, instrument_code: str) -> dict:
        """Handle case when no detector candidates exist for the instrument.

        Args:
            raw_detector_context: The detector context string
            instrument_code: The instrument code

        Returns:
            NormalizedDetector result with detector=None
        """
        logger.debug(f"DetectorNormalizer: No detectors found for instrument {instrument_code}, returning None")
        result = NormalizedDetector(
            detector=None,
            original_text=raw_detector_context
        ).model_dump()
        return result

    def _handle_single_candidate(self, raw_detector_context: str, instrument_code: str) -> dict:
        """Handle case when exactly one detector candidate exists for the instrument.

        Since there's only one option, the detector is implied and we return None.

        Args:
            raw_detector_context: The detector context string
            instrument_code: The instrument code

        Returns:
            NormalizedDetector result with detector=None
        """
        logger.debug(f"DetectorNormalizer: Single detector for {instrument_code}, returning None (detector implied)")
        result = NormalizedDetector(
            detector=None,
            original_text=raw_detector_context
        ).model_dump()
        return result

    def _handle_multiple_candidates(self, raw_detector_context: str, instrument_code: str, candidates: list) -> dict:
        """Handle case when multiple detector candidates exist - call LLM to choose.

        Args:
            raw_detector_context: The detector context string
            instrument_code: The instrument code
            candidates: List of valid detector candidates

        Returns:
            NormalizedDetector result with the LLM-chosen detector
        """
        logger.info(f"DetectorNormalizer: Calling LLM for instrument {instrument_code} with {len(candidates)} candidates")
        logger.debug(f"DetectorNormalizer: Input length: {len(raw_detector_context)} chars, candidates: {candidates}")

        config = self.llm_config.normalization.detector

        # Load prompts from XML template
        template_name = "detector_normalization"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            instrument_code=instrument_code,
            candidates=candidates,
            raw_detector_context=raw_detector_context
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'instrument_code': instrument_code,
            'candidates': candidates,
            'raw_detector_context': raw_detector_context
        }

        response = self.llm_client.completion(
            call_type="detector_normalization",
            model=config.model,
            messages=messages,
            **config.to_kwargs(prompt_context=prompt_context)
        )

        # Parse the free text response to extract detector name
        response_text = response.choices[0].message.content.strip()
        chosen_detector = self._parse_detector_response(response_text, candidates)

        # Validate that chosen detector is in the viable candidates
        if chosen_detector and chosen_detector not in candidates:
            logger.warning(
                f"DetectorNormalizer: LLM returned detector '{chosen_detector}' which is not in viable candidates {candidates}. "
                f"Response was: {response_text[:200]}"
            )
            chosen_detector = None

        result = NormalizedDetector(
            detector=chosen_detector,
            original_text=raw_detector_context
        ).model_dump()
        logger.debug(f"DetectorNormalizer: Parsed result - chosen: {result.get('detector')}")

        return result

    def _parse_detector_response(self, response_text: str, candidates: list) -> Optional[str]:
        """Parse the LLM's response to extract the chosen detector.

        The LLM response should be ONLY:
        - The exact detector string from the candidates list, OR
        - The word "UNCERTAIN" if no detector could be determined

        Args:
            response_text: The LLM's response (should be just a detector name or "UNCERTAIN")
            candidates: List of valid detector candidates

        Returns:
            The detector name if it matches a candidate, None if "UNCERTAIN" or no match
        """
        response_clean = response_text.strip()

        # Check if the response is "UNCERTAIN"
        if response_clean.upper() == "UNCERTAIN":
            logger.debug("DetectorNormalizer: LLM returned UNCERTAIN")
            return None

        # Check if the response exactly matches one of the candidates
        if response_clean in candidates:
            return response_clean

        # If no exact match, return None and let validation catch it
        logger.debug(f"DetectorNormalizer: Response '{response_clean}' does not match any candidate")
        return None