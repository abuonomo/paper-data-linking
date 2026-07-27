import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import ValidationError

from paper_data_linking.linkers.general.normalizers.time_range_normalizer import TimeRangeNormalizer
from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.normalization_context import (
    GroundingResult,
    NormalizationContext,
)
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod


class TestTimeRangeNormalizer:
    """Unit tests for TimeRangeNormalizer post-processing logic."""

    @pytest.fixture
    def llm_config(self):
        """Fixture providing a mock LLM config for time range normalizer."""
        from paper_data_linking.config.settings import get_llm_configuration
        return get_llm_configuration("standard")

    @pytest.fixture
    def time_normalizer(self, llm_config):
        """Fixture providing a TimeRangeNormalizer instance."""
        llm_client = LiteLLMClient()
        return TimeRangeNormalizer(llm_client=llm_client, llm_config=llm_config)

    @pytest.fixture
    def normalization_context(self):
        """Fixture providing a minimal normalization context for time ranges."""
        period = InternalDataCollectionPeriod(
            period_name="Test period",
            time_range="2014-08-30 14:40:22 UT",
        )

        grounding_result = GroundingResult(
            matched_instrument_code="IRIS",
            matched_instrument_name="IRIS",
            matched_mission_name="IRIS",
            data_system="vso",
            reasoning="Test time range",
        )

        return NormalizationContext(
            instrument_code="IRIS",
            instrument_name="IRIS",
            data_system="vso",
            period_name="Test period",
            period_data=period,
            grounding_result=grounding_result,
        )

    def _mock_completion_response(self, content):
        """Build a minimal LiteLLM-like response object."""
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    # Tests for _determine_precision
    def test_determine_precision_year_only(self, time_normalizer):
        """Test precision detection for year-only date."""
        result = time_normalizer._determine_precision("2003Z")
        assert result == "year"

    def test_determine_precision_year_month(self, time_normalizer):
        """Test precision detection for year-month date."""
        result = time_normalizer._determine_precision("2003-11Z")
        assert result == "month"

    def test_determine_precision_full_date(self, time_normalizer):
        """Test precision detection for full date (no time)."""
        result = time_normalizer._determine_precision("2003-11-03Z")
        assert result == "day"

    def test_determine_precision_datetime_hour(self, time_normalizer):
        """Test precision detection for datetime with hour only."""
        result = time_normalizer._determine_precision("2003-11-03T01Z")
        assert result == "hour"

    def test_determine_precision_datetime_minute(self, time_normalizer):
        """Test precision detection for datetime with hour:minute."""
        result = time_normalizer._determine_precision("2003-11-03T01:02Z")
        assert result == "minute"

    def test_determine_precision_datetime_second(self, time_normalizer):
        """Test precision detection for datetime with hour:minute:second."""
        result = time_normalizer._determine_precision("2003-11-03T01:02:20Z")
        assert result == "second"

    # Tests for _get_coarsest_precision
    def test_get_coarsest_precision_second_vs_minute(self, time_normalizer):
        """Test coarsest precision is minute when comparing minute vs second."""
        result = time_normalizer._get_coarsest_precision("second", "minute")
        assert result == "minute"

    def test_get_coarsest_precision_minute_vs_hour(self, time_normalizer):
        """Test coarsest precision is hour when comparing hour vs minute."""
        result = time_normalizer._get_coarsest_precision("minute", "hour")
        assert result == "hour"

    def test_get_coarsest_precision_day_vs_second(self, time_normalizer):
        """Test coarsest precision is day when comparing day vs second."""
        result = time_normalizer._get_coarsest_precision("second", "day")
        assert result == "day"

    def test_get_coarsest_precision_same(self, time_normalizer):
        """Test coarsest precision returns same when both are equal."""
        result = time_normalizer._get_coarsest_precision("minute", "minute")
        assert result == "minute"

    # Tests for _is_single_date
    def test_is_single_date_same_day_midnight(self, time_normalizer):
        """Test single date detection: same day, both at midnight."""
        start = datetime.fromisoformat("2000-05-05T00:00:00+00:00")
        end = datetime.fromisoformat("2000-05-05T00:00:00+00:00")
        result = time_normalizer._is_single_date(start, end, "day")
        assert result is True

    def test_is_single_date_same_day_eod(self, time_normalizer):
        """Test single date detection: same day, end at 23:59:59."""
        start = datetime.fromisoformat("2000-05-05T00:00:00+00:00")
        end = datetime.fromisoformat("2000-05-05T23:59:59+00:00")
        result = time_normalizer._is_single_date(start, end, "day")
        assert result is True

    def test_is_single_date_different_days(self, time_normalizer):
        """Test single date detection returns False for different days."""
        start = datetime.fromisoformat("2000-05-05T00:00:00+00:00")
        end = datetime.fromisoformat("2000-05-06T00:00:00+00:00")
        result = time_normalizer._is_single_date(start, end, "day")
        assert result is False

    def test_is_single_date_with_time_in_range(self, time_normalizer):
        """Test single date detection returns False when time range isn't midnight-based."""
        start = datetime.fromisoformat("2000-05-05T10:00:00+00:00")
        end = datetime.fromisoformat("2000-05-05T15:00:00+00:00")
        result = time_normalizer._is_single_date(start, end, "day")
        assert result is False

    # Tests for _post_process_time_range
    def test_post_process_coarsest_precision_minute(self, time_normalizer):
        """Test post-processing applies coarsest precision (minute over second)."""
        result = {
            "start_datetime": "2003-11-03T01:02:20Z",
            "end_datetime": "2003-11-03T02:01:00Z",
            "precision": "second"
        }
        processed = time_normalizer._post_process_time_range(result, "2003-11-03 01:02:20–02:01 UT")

        # Should detect start is "second" and end is "minute", choose coarsest "minute"
        assert processed["precision"] == "minute"
        # Post-processing reports coarsest precision but doesn't truncate time values
        assert processed["start_datetime"] == "2003-11-03T01:02:20Z"
        assert processed["end_datetime"] == "2003-11-03T02:01:00Z"

    def test_post_process_single_date_expands_to_next_day(self, time_normalizer):
        """Test post-processing expands single date to full day (ISO 8601)."""
        result = {
            "start_datetime": "2000-05-05T00:00:00Z",
            "end_datetime": "2000-05-05T23:59:59Z",
            "precision": "day"
        }
        processed = time_normalizer._post_process_time_range(result, "2000-05-05")

        # Should expand to next day midnight
        assert processed["start_datetime"] == "2000-05-05T00:00:00Z"
        assert processed["end_datetime"] == "2000-05-06T00:00:00Z"
        assert processed["precision"] == "day"

    def test_post_process_preserves_time_range(self, time_normalizer):
        """Test post-processing preserves actual time ranges (not single dates)."""
        result = {
            "start_datetime": "1995-08-29T08:55:00Z",
            "end_datetime": "1995-08-29T09:15:00Z",
            "precision": "minute"
        }
        processed = time_normalizer._post_process_time_range(result, "1995-08-29 08:55:00 to 09:15:00 UT")

        # Should preserve as-is (not a single date due to time in range)
        assert processed["start_datetime"] == "1995-08-29T08:55:00Z"
        assert processed["end_datetime"] == "1995-08-29T09:15:00Z"
        assert processed["precision"] == "minute"

    def test_post_process_handles_missing_fields(self, time_normalizer):
        """Test post-processing gracefully handles missing datetime fields."""
        result = {
            "start_datetime": None,
            "end_datetime": "2000-05-05T00:00:00Z",
            "precision": "day"
        }
        processed = time_normalizer._post_process_time_range(result, "2000-05-05")

        # Should return unchanged due to missing start_datetime
        assert processed["start_datetime"] is None

    def test_post_process_coarsest_precision_second_vs_minute(self, time_normalizer):
        """Test post-processing with different precisions (second vs minute)."""
        result = {
            "start_datetime": "1995-08-29T08:55:30Z",
            "end_datetime": "1995-08-30T00:00:00Z",
            "precision": "second"
        }
        processed = time_normalizer._post_process_time_range(result, "1995-08-29 to 1995-08-30")

        # Start has seconds precision, end has minute precision (00 seconds) -> coarsest is minute
        assert processed["precision"] == "minute"

    def test_post_process_with_iso8601_utc_format(self, time_normalizer):
        """Test post-processing works with both Z and +00:00 UTC formats."""
        result = {
            "start_datetime": "2003-11-03T01:02:20+00:00",
            "end_datetime": "2003-11-03T02:01:00+00:00",
            "precision": "second"
        }
        processed = time_normalizer._post_process_time_range(result, "2003-11-03 01:02:20–02:01 UT")

        # Should work with +00:00 format
        assert processed["precision"] == "minute"
        assert "Z" in processed["start_datetime"]  # Normalized to Z format

    def test_normalize_retries_once_after_validation_error(
        self, time_normalizer, normalization_context
    ):
        """Test normalize retries when the first structured response is missing required fields."""
        invalid_response = self._mock_completion_response(
            '{"precision":"second","is_approximate":false,"original_text":"2014-08-30 14:40:22 UT"}'
        )
        valid_response = self._mock_completion_response(
            '{"start_datetime":"2014-08-30T14:40:22Z","end_datetime":"2014-08-30T14:40:22Z","precision":"second","is_approximate":false,"original_text":"2014-08-30 14:40:22 UT"}'
        )
        time_normalizer.llm_client.completion = MagicMock(
            side_effect=[invalid_response, valid_response]
        )

        result = time_normalizer.normalize(normalization_context)

        assert time_normalizer.llm_client.completion.call_count == 2
        assert result["start_datetime"] == "2014-08-30T14:40:22Z"
        assert result["end_datetime"] == "2014-08-30T14:40:22Z"
        assert result["precision"] == "second"

    def test_normalize_raises_after_retry_exhausted(
        self, time_normalizer, normalization_context
    ):
        """Test normalize still raises when structured output is invalid on every attempt."""
        invalid_response = self._mock_completion_response(
            '{"precision":"second","is_approximate":false,"original_text":"2014-08-30 14:40:22 UT"}'
        )
        time_normalizer.llm_client.completion = MagicMock(
            side_effect=[invalid_response, invalid_response]
        )

        with pytest.raises(ValidationError):
            time_normalizer.normalize(normalization_context)

        assert time_normalizer.llm_client.completion.call_count == 2
