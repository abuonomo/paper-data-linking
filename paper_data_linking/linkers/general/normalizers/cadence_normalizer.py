from typing import Optional, List
import logging

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedCadence
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


logger = logging.getLogger(__name__)


@NormalizerRegistry.register("cadence", version="1.0", data_sources=["cdaweb"])
class CadenceNormalizer(BaseNormalizer):
    """
    Given instrument/period context, extract cadence information and normalize to ISO 8601 format.
    Open-ended extraction task (no pre-defined candidates like detector/physobs).
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required for CadenceNormalizer")
        self.llm_config = llm_config

    def _build_cadence_context(self, context: NormalizationContext) -> str:
        """Build the cadence context string from instrument and period data.

        Organizes cadence-relevant information with structural clarity:
        - Instrument-level comments (cadence info, pixel size, etc.)
        - Period-specific comments (time range, measurement details)
        - Supporting quotes from the paper

        Args:
            context: NormalizationContext containing instrument and period data

        Returns:
            A structured string of cadence context information with newline separation
        """
        sections = []

        # Section 1: Instrument-level Comments
        if context.instrument_general_comments:
            sections.append(context.instrument_general_comments)

        # Section 2: Period-specific Details
        if context.period_data.additional_comments:
            sections.append(context.period_data.additional_comments)

        # Section 3: Supporting Quotes
        if context.period_data.general_quotes:
            sections.append(" ".join(context.period_data.general_quotes))

        return "\n".join(sections).strip()

    def normalize(self, context: NormalizationContext) -> dict:
        """Return a dict: {cadences, original_text}."""
        instrument_code = context.instrument_code
        raw_cadence_context = self._build_cadence_context(context)

        if not raw_cadence_context:
            logger.info(f"CadenceNormalizer: No cadence context found for instrument {instrument_code}")
            return None

        logger.info(f"CadenceNormalizer: Processing cadence context for instrument {instrument_code}: {raw_cadence_context[:100]}...")

        # Cadence doesn't have candidates - always call LLM when context exists
        return self._handle_cadence_extraction(raw_cadence_context, instrument_code)

    def _handle_cadence_extraction(self, raw_cadence_context: str, instrument_code: str) -> dict:
        """Extract cadences using LLM with free-text v2 prompt.

        Args:
            raw_cadence_context: The cadence context string
            instrument_code: The instrument code

        Returns:
            NormalizedCadence result with extracted cadences
        """
        logger.info(f"CadenceNormalizer: Calling LLM for instrument {instrument_code}")
        logger.debug(f"CadenceNormalizer: Input length: {len(raw_cadence_context)} chars")

        config = self.llm_config.normalization.cadence

        # Load prompts from XML template
        template_name = "cadence_normalization"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            raw_cadence_context=raw_cadence_context
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'raw_cadence_context': raw_cadence_context
        }

        response = self.llm_client.completion(
            call_type="cadence_normalization",
            model=config.model,
            messages=messages,
            **config.to_kwargs(prompt_context=prompt_context)
        )

        # Parse the free text response to extract cadences
        response_text = response.choices[0].message.content.strip()
        cadences = self._parse_cadence_response(response_text)

        result = NormalizedCadence(
            cadences=cadences,
            original_text=raw_cadence_context
        ).model_dump()
        logger.debug(f"CadenceNormalizer: Parsed result - chosen: {result.get('cadences')}")

        return result

    def _parse_cadence_response(self, response_text: str) -> Optional[List[str]]:
        """Parse the LLM's response to extract cadences.

        The LLM response should be:
        - "NONE" if no cadences found, OR
        - ISO 8601 duration strings, comma-separated for multiple cadences

        Examples:
        - "NONE" -> None
        - "PT3S" -> ["PT3S"]
        - "PT3S, PT1M" -> ["PT3S", "PT1M"]
        - "PT12S/PT16S" -> ["PT12S/PT16S"]

        Args:
            response_text: The LLM's response (should be cadence strings or "NONE")

        Returns:
            List of cadence strings if found, None if "NONE" or empty response
        """
        response_clean = response_text.strip()

        # Check if the response is "NONE"
        if response_clean.upper() == "NONE":
            logger.debug("CadenceNormalizer: LLM returned NONE")
            return None

        # Split by comma for multiple cadences and strip whitespace
        if response_clean:
            cadences = [c.strip() for c in response_clean.split(",")]
            return cadences if cadences else None

        logger.debug("CadenceNormalizer: Empty response")
        return None