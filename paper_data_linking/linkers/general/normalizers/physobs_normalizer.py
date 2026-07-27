# paper_data_linking/linkers/general/physobs_normalizer.py

import json
import logging
from typing import Dict, Optional

from paper_data_linking.config.paths import VSO_METADATA_JSONL
from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedObservable
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


@NormalizerRegistry.register("physobs", version="1.0", data_sources=["vso"])
class PhysObsNormalizer(BaseNormalizer):
    """
    Given an instrument_code and raw observable text, restrict choices to
    VSO-approved physobs (from vso_metadata.jsonl) and return the chosen physobs.
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required for PhysObsNormalizer")
        self.llm_config = llm_config
        self._instrument_physobs = self._load_instrument_physobs()

    def _load_instrument_physobs(self) -> Dict[str, list]:
        """Load and parse instrument-physobs mappings from VSO metadata JSONL file.

        Returns:
            Dictionary mapping instrument codes to sorted lists of available physical observables.
        """
        instrument_physobs: Dict[str, set] = {}

        if VSO_METADATA_JSONL.exists():
            with open(VSO_METADATA_JSONL, "r", encoding="utf-8") as md:
                for line in md:
                    entry = json.loads(line)
                    code = entry.get("instrument")
                    phys = entry.get("physobs")
                    if code and phys:
                        instrument_physobs.setdefault(code, set()).add(phys)

        # Convert sets to sorted lists
        return {code: sorted(phys_set) for code, phys_set in instrument_physobs.items()}

    def _build_physobs_context(self, context: NormalizationContext) -> str:
        """Build the physical observable context string from period data.

        Uses minimal context - just the physical_observable field from the period data.

        Args:
            context: NormalizationContext containing period data

        Returns:
            The physical observable string
        """
        return context.period_data.physical_observable or ""

    def normalize(self, context: NormalizationContext) -> dict:
        """Return a dict: {physical_observable, original_text}."""
        instrument_code = context.instrument_code
        raw_observable = self._build_physobs_context(context)

        if not raw_observable:
            logger.info(f"PhysObsNormalizer: No physical observable found for instrument {instrument_code}")
            return None

        logger.info(f"PhysObsNormalizer: Processing observable for instrument {instrument_code}: {raw_observable[:100]}...")

        candidates = self._instrument_physobs.get(instrument_code, [])
        logger.debug(f"PhysObsNormalizer: Found {len(candidates)} candidates for instrument {instrument_code}")

        # Route to appropriate handler based on number of candidates
        if not candidates:
            return self._handle_no_candidates(raw_observable, instrument_code)
        elif len(candidates) == 1:
            return self._handle_single_candidate(raw_observable, instrument_code)
        else:
            return self._handle_multiple_candidates(raw_observable, instrument_code, candidates)

    def _handle_no_candidates(self, raw_observable: str, instrument_code: str) -> dict:
        """Handle case when no physobs candidates exist for the instrument.

        Args:
            raw_observable: The physical observable string
            instrument_code: The instrument code

        Returns:
            NormalizedObservable result with physical_observable=None
        """
        logger.debug(f"PhysObsNormalizer: No physobs found for instrument {instrument_code}, returning None")
        result = NormalizedObservable(
            physical_observable=None,
            original_text=raw_observable
        ).model_dump()
        return result

    def _handle_single_candidate(self, raw_observable: str, instrument_code: str) -> dict:
        """Handle case when exactly one physobs candidate exists for the instrument.

        Since there's only one option, the physobs is implied and we return it directly.

        Args:
            raw_observable: The physical observable string
            instrument_code: The instrument code

        Returns:
            NormalizedObservable result with the single physobs
        """
        candidates = self._instrument_physobs[instrument_code]
        logger.debug(f"PhysObsNormalizer: Single physobs for {instrument_code}, returning directly: {candidates[0]}")
        result = NormalizedObservable(
            physical_observable=candidates[0],
            original_text=raw_observable
        ).model_dump()
        return result

    def _handle_multiple_candidates(self, raw_observable: str, instrument_code: str, candidates: list) -> dict:
        """Handle case when multiple physobs candidates exist - call LLM to choose.

        Args:
            raw_observable: The physical observable string
            instrument_code: The instrument code
            candidates: List of valid physobs candidates

        Returns:
            NormalizedObservable result with the LLM-chosen physobs
        """
        logger.info(f"PhysObsNormalizer: Calling LLM for instrument {instrument_code} with {len(candidates)} candidates")
        logger.debug(f"PhysObsNormalizer: Input length: {len(raw_observable)} chars, candidates: {candidates}")

        config = self.llm_config.normalization.physical_observable

        # Load prompts from XML template
        template_name = "physobs_normalization"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            instrument_code=instrument_code,
            candidates=candidates,
            raw_observable=raw_observable
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
            'raw_observable': raw_observable
        }

        response = self.llm_client.completion(
            call_type="physobs_normalization",
            model=config.model,
            messages=messages,
            **config.to_kwargs(prompt_context=prompt_context)
        )

        # Parse the free text response to extract physobs
        response_text = response.choices[0].message.content.strip()
        chosen_physobs = self._parse_physobs_response(response_text, candidates)

        # Validate that chosen physobs is in the viable candidates
        if chosen_physobs and chosen_physobs not in candidates:
            logger.warning(
                f"PhysObsNormalizer: LLM returned physobs '{chosen_physobs}' which is not in viable candidates {candidates}. "
                f"Response was: {response_text[:200]}"
            )
            chosen_physobs = None

        result = NormalizedObservable(
            physical_observable=chosen_physobs,
            original_text=raw_observable
        ).model_dump()
        logger.debug(f"PhysObsNormalizer: Parsed result - chosen: {result.get('physical_observable')}")

        return result

    def _parse_physobs_response(self, response_text: str, candidates: list) -> Optional[str]:
        """Parse the LLM's response to extract the chosen physical observable.

        The LLM response should be ONLY:
        - The exact physobs string from the candidates list, OR
        - The word "UNCERTAIN" if no physobs could be determined

        Args:
            response_text: The LLM's response (should be just a physobs or "UNCERTAIN")
            candidates: List of valid physobs candidates

        Returns:
            The physobs if it matches a candidate, None if "UNCERTAIN" or no match
        """
        response_clean = response_text.strip()

        # Check if the response is "UNCERTAIN"
        if response_clean.upper() == "UNCERTAIN":
            logger.debug("PhysObsNormalizer: LLM returned UNCERTAIN")
            return None

        # Check if the response exactly matches one of the candidates
        if response_clean in candidates:
            return response_clean

        # If no exact match, return None and let validation catch it
        logger.debug(f"PhysObsNormalizer: Response '{response_clean}' does not match any candidate")
        return None
