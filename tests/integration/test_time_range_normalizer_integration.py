import pytest
from paper_data_linking.linkers.general.normalizers.time_range_normalizer import TimeRangeNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestTimeRangeNormalizerIntegration:
    """Integration tests that call the LLM with real time range data."""

    @pytest.mark.integration
    @pytest.mark.parametrize("raw_time,expected_precision", [
        ("2003-11-03 01:02:20–02:01 UT", "minute"),  # Coarsest of second and minute
        ("2000-05-05", "day"),  # Single date should be day precision
        ("1995-08-29 08:55:00 to 09:15:00 UT", "minute"),  # Both with seconds, should be minute
    ])
    def test_time_range_normalization_with_precision(
        self, raw_time, expected_precision, llm_pipeline_config
    ):
        """Test time range normalization with LLM, verifying post-processing.

        Tests:
        1. Coarsest precision selection (minute vs second → minute)
        2. Single date handling (2000-05-05 → full day span)
        3. Precision consistency
        """
        period = InternalDataCollectionPeriod(
            period_name="Test period",
            time_range=raw_time,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="TEST",
            matched_instrument_name="Test Instrument",
            matched_mission_name="Test Mission",
            data_system="vso",
            reasoning="Test time range"
        )

        context = NormalizationContext(
            instrument_code="TEST",
            instrument_name="Test Instrument",
            data_system="vso",
            period_name="Test period",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = TimeRangeNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting time range: {raw_time}")

        # Call the normalizer (will actually call LLM)
        result = normalizer.normalize(context)

        print(f"Time range normalization result: {result}")

        # Verify result structure
        assert result is not None
        assert "start_datetime" in result
        assert "end_datetime" in result
        assert "precision" in result
        assert "original_text" in result

        # Verify precision is coarsest
        assert result["precision"] == expected_precision, \
            f"Expected precision '{expected_precision}', got '{result['precision']}'"

        # Verify start and end are ISO 8601 format
        assert "T" in result["start_datetime"]
        assert "T" in result["end_datetime"]
        assert "Z" in result["start_datetime"]
        assert "Z" in result["end_datetime"]

        # For single-date inputs, verify they span a full day
        if expected_precision == "day" and len(raw_time.split()) == 1:
            # Single date should have end = next day at midnight
            assert result["end_datetime"].split("T")[0] > result["start_datetime"].split("T")[0]
            print(f"✓ Single date properly expanded: {result['start_datetime']} → {result['end_datetime']}")

        print(f"✓ Time range normalized with precision: {result['precision']}")


if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration", "-s"])
