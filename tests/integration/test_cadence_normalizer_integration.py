import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock
from paper_data_linking.linkers.general.normalizers.cadence_normalizer import CadenceNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod


@pytest.mark.integration
class TestCadenceNormalizer:

    @pytest.fixture
    def mock_llm_config(self):
        """Create a mock LLM config with normalization.cadence attributes."""
        config = MagicMock()
        config.normalization.cadence.model = "gpt-4"
        config.normalization.cadence.temperature = 0.0
        return config

    @pytest.fixture
    def normalizer(self, mock_llm_config):
        """Create a CadenceNormalizer instance for testing."""
        return CadenceNormalizer(llm_config=mock_llm_config)

    def test_normalizer_initialization(self, normalizer):
        """Test that the normalizer can be initialized properly."""
        assert normalizer is not None
        assert isinstance(normalizer, CadenceNormalizer)

    def load_mock_instrument_details(self, file_name):
        path = Path(__file__).parent.parent / "data" / "normalization_test_data" / file_name
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            pytest.fail(f"Unexpected error reading '{path}': {e}")

    @pytest.mark.parametrize("input_file, expected", [
        ("1_normalization_context.json", ['PT12S/PT16S']),
        ("2_normalization_context.json", [])
    ])
    def test_normalizer(self, normalizer, input_file, expected):
        """Test the CadenceNormalizer using mock instrument details loaded from a file.

        NOTE: This test calls the real LLM and requires API keys.
        """
        instrument_details = self.load_mock_instrument_details(input_file)

        # Iterate over instruments and their data collection periods
        for instrument in instrument_details["instruments"]:
            for period in instrument.get("data_collection_periods", []):
                # Create a NormalizationContext for each period
                period_data = InternalDataCollectionPeriod(
                    period_name=period.get("period_name", ""),
                    time_range=period.get("time_range"),
                    time_quotes=period.get("time_quotes", []),
                    wavelengths=period.get("wavelengths"),
                    wavelength_quotes=period.get("wavelength_quotes", []),
                    physical_observable=period.get("physical_observable"),
                    physobs_quotes=period.get("physobs_quotes", []),
                    general_quotes=period.get("general_quotes", []),
                    additional_comments=period.get("additional_comments")
                )

                context = NormalizationContext(
                    period_data=period_data,
                    instrument_code=instrument.get("name", ""),
                    all_periods_data=instrument.get("data_collection_periods", ""),
                    instrument_name=instrument.get("name", ""),
                    instrument_general_comments=instrument.get("general_comments", ""),
                    data_system="cdaweb",
                    period_name=period.get("period_name", ""),
                    grounding_result=GroundingResult(reasoning="Mock reasoning")
                )

                # Run the normalizer
                result = normalizer.normalize(context)

                print(f"Result {result}")

                assert result["cadences"] == expected
