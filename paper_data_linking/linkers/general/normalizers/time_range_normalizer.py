# paper_data_linking/linkers/general/time_range_normalizer.py

import logging
from typing import Optional
from datetime import datetime, timedelta

from pydantic import ValidationError

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedTimeRange
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)

# Precision hierarchy for coarsest precision logic
PRECISION_HIERARCHY = ["year", "month", "day", "hour", "minute", "second"]
STRUCTURED_OUTPUT_VALIDATION_ATTEMPTS = 2


@NormalizerRegistry.register("time_range", version="1.0", data_sources=["vso", "cdaweb"])
class TimeRangeNormalizer(BaseNormalizer):
    """Wraps the LLM call that parses raw time‐range strings into ISO format.

    Post-processes LLM output to:
    1. Use coarsest precision across start and end times (conservative)
    2. Handle single-date inputs as full-day spans (ISO 8601 convention)
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required for TimeRangeNormalizer")
        self.llm_config = llm_config

    def normalize(self, context: NormalizationContext) -> dict:
        """Normalize time range with post-processing for precision and single-date handling."""
        raw_time = context.period_data.time_range

        if not raw_time:
            logger.info("TimeRangeNormalizer: No time range data found")
            return None

        logger.info(f"TimeRangeNormalizer: Calling LLM for time range: {raw_time[:100]}...")
        logger.debug(f"TimeRangeNormalizer: Input length: {len(raw_time)} chars")

        config = self.llm_config.normalization.time_range

        # Load prompts from XML template
        template_name = "time_normalization"
        system_msg, user_msg = load_and_render_prompt(
            template_name,
            raw_time=raw_time
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]

        # Capture template variables for render_context
        prompt_context = {
            'template_name': template_name,
            'raw_time': raw_time
        }

        completion_kwargs = {
            "call_type": "time_normalization",
            "model": config.model,
            "messages": messages,
            **config.to_kwargs(response_format=NormalizedTimeRange, prompt_context=prompt_context),
        }
        parsed_obj = None

        for attempt in range(1, STRUCTURED_OUTPUT_VALIDATION_ATTEMPTS + 1):
            response = self.llm_client.completion(**completion_kwargs)

            try:
                parsed_obj = NormalizedTimeRange.model_validate_json(response.choices[0].message.content)
                break
            except ValidationError:
                if attempt == STRUCTURED_OUTPUT_VALIDATION_ATTEMPTS:
                    raise

                logger.warning(
                    "TimeRangeNormalizer: Structured output validation failed on attempt %s/%s; retrying once",
                    attempt,
                    STRUCTURED_OUTPUT_VALIDATION_ATTEMPTS,
                    exc_info=True,
                )

        result = parsed_obj.model_dump()

        # Post-process: adjust precision and single-date handling
        result = self._post_process_time_range(result, raw_time)

        logger.debug(f"TimeRangeNormalizer: Parsed result - start: {result.get('start_datetime')}, end: {result.get('end_datetime')}, precision: {result.get('precision')}")

        return result

    def _post_process_time_range(self, result: dict, raw_time: str) -> dict:
        """Post-process LLM output to ensure consistent precision and handle single dates.

        Rules:
        1. Use coarsest precision across start and end times (conservative approach)
        2. If start and end are the same date, span full day with ISO 8601 convention:
           - start: YYYY-MM-DDT00:00:00Z
           - end: YYYY-MM-DD+1T00:00:00Z (next day at midnight)

        Args:
            result: The LLM-parsed result dict
            raw_time: Original time string for logging

        Returns:
            Adjusted result dict with coarsest precision and proper date spanning
        """
        start_str = result.get("start_datetime")
        end_str = result.get("end_datetime")
        precision = result.get("precision")

        if not start_str or not end_str:
            return result

        try:
            # Parse ISO strings to datetime objects
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

            # Rule 1: Determine coarsest precision
            start_precision = self._determine_precision(start_str)
            end_precision = self._determine_precision(end_str)
            coarsest_precision = self._get_coarsest_precision(start_precision, end_precision)

            # Rule 2: Handle single-date inputs (same date, midnight to midnight)
            if self._is_single_date(start_dt, end_dt, precision):
                logger.debug(f"TimeRangeNormalizer: Single-date detected, expanding to full day")
                # ISO 8601: full day is [start_date 00:00, next_date 00:00)
                start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = start_dt + timedelta(days=1)
                coarsest_precision = "day"  # Single date always has day precision

            # Update result
            result["start_datetime"] = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            result["end_datetime"] = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            result["precision"] = coarsest_precision

            logger.debug(
                f"TimeRangeNormalizer: Post-processed - precision: {precision} → {coarsest_precision}, "
                f"single_date_expanded: {self._is_single_date(start_dt, end_dt, precision)}"
            )

        except (ValueError, AttributeError) as e:
            logger.warning(f"TimeRangeNormalizer: Failed to post-process time range: {e}")
            # Return original result if post-processing fails

        return result

    def _determine_precision(self, iso_datetime_str: str) -> str:
        """Determine the precision level of an ISO datetime string.

        Analyzes what precision level is actually present by checking significant components.
        E.g., "2003-11-03T02:01:00Z" is minute precision (no non-zero seconds),
        while "2003-11-03T01:02:20Z" is second precision (non-zero seconds).

        Args:
            iso_datetime_str: ISO 8601 datetime string (e.g., "2003-11-03T01:02:20Z")

        Returns:
            Precision level: "year", "month", "day", "hour", "minute", or "second"
        """
        # Remove timezone info for analysis
        clean_str = iso_datetime_str.replace("Z", "").replace("+00:00", "")

        # Count components: YYYY-MM-DDTHH:MM:SS
        if "T" not in clean_str:
            # Just a date
            parts = clean_str.split("-")
            if len(parts) == 1:
                return "year"
            elif len(parts) == 2:
                return "month"
            else:
                return "day"
        else:
            # Date and time - analyze what's significant
            date_part, time_part = clean_str.split("T")
            time_components = time_part.split(":")

            if len(time_components) == 1:
                return "hour"
            elif len(time_components) == 2:
                return "minute"
            elif len(time_components) >= 3:
                # Have HH:MM:SS format
                seconds_part = time_components[2]
                # Check if seconds are significant (non-zero)
                try:
                    seconds_float = float(seconds_part)
                    if seconds_float == 0.0:
                        # Seconds are :00, so real precision is minute
                        return "minute"
                    else:
                        return "second"
                except ValueError:
                    # If we can't parse, default to second
                    return "second"

    def _get_coarsest_precision(self, precision1: str, precision2: str) -> str:
        """Return the coarsest (lowest) precision from two precisions.

        Args:
            precision1: First precision level
            precision2: Second precision level

        Returns:
            The coarsest of the two precisions
        """
        idx1 = PRECISION_HIERARCHY.index(precision1) if precision1 in PRECISION_HIERARCHY else 0
        idx2 = PRECISION_HIERARCHY.index(precision2) if precision2 in PRECISION_HIERARCHY else 0
        return PRECISION_HIERARCHY[min(idx1, idx2)]

    def _is_single_date(self, start_dt: datetime, end_dt: datetime, precision: str) -> bool:
        """Check if this represents a single date (not a time range).

        Single date indicators:
        - Start and end are on the same calendar day
        - Precision is "day" (indicating date-only input)
        - End is at exactly 23:59:59 or 00:00:00 of the same day

        Args:
            start_dt: Start datetime
            end_dt: End datetime
            precision: Reported precision level

        Returns:
            True if this appears to be a single date, False otherwise
        """
        # Same calendar day
        same_day = start_dt.date() == end_dt.date()

        # Both at midnight or end at last second of day
        start_at_midnight = start_dt.time() == start_dt.replace(hour=0, minute=0, second=0, microsecond=0).time()
        end_at_midnight = end_dt.time() == end_dt.replace(hour=0, minute=0, second=0, microsecond=0).time()
        end_at_eod = end_dt.time() == end_dt.replace(hour=23, minute=59, second=59, microsecond=0).time()

        return same_day and start_at_midnight and (end_at_midnight or end_at_eod)

if __name__ == "__main__":
    from paper_data_linking.linkers.general.normalizers.normalization_context import GroundingResult
    
    normalizer = TimeRangeNormalizer()
    
    # Create mock context for testing
    mock_context = NormalizationContext(
        period_data={"time_range": "from 1996 to 2007"},
        instrument_code="test_instrument",
        instrument_name="Test Instrument",
        data_system="vso",
        period_name="test_period",
        grounding_result=GroundingResult(
            matched_instrument_code="test_instrument",
            matched_mission_code="test_mission", 
            matched_instrument_name="Test Instrument",
            matched_mission_name="Test Mission",
            data_system="vso",
            reasoning="Test grounding"
        )
    )
    
    result = normalizer.normalize(mock_context)
    print("Result:", result)
