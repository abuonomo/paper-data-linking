import pytest
from paper_data_linking.linkers.general.normalizers.detector_normalizer import DetectorNormalizer
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestDetectorNormalizerIntegration:
    """Integration tests that actually call the LLM with real data."""

    @pytest.mark.integration
    @pytest.mark.parametrize("instrument_code,expected_detector,data_file", [
        ("LASCO", "C2", "3_aia_secchi_lasco_normalization_context.json"),
        ("SECCHI", "EUVI", "3_aia_secchi_lasco_normalization_context.json"),
        ("AIA", None, "3_aia_secchi_lasco_normalization_context.json"),
    ])
    def test_detector_selection_from_structured_data(
        self, instrument_code, expected_detector, data_file, normalization_contexts_from_test_data, llm_pipeline_config
    ):
        """Test detector selection with real LLM call using normalization test data.

        Parameterized to test multiple instruments and their expected detector selections.
        """

        # Get contexts from test data (includes grounding results)
        contexts = normalization_contexts_from_test_data(data_file)

        # Find the context for the specified instrument
        test_context = None
        for instrument_name, period_name, context in contexts:
            if context.instrument_code == instrument_code:
                test_context = (instrument_name, period_name, context)
                break

        assert test_context is not None, f"{instrument_code} context not found in test data"
        instrument_name, period_name, context = test_context

        llm_client = LiteLLMClient()
        normalizer = DetectorNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting {instrument_name}: {period_name}")

        # Call the detector normalizer (will actually call LLM)
        result = normalizer.normalize(context)

        print(f"Detector normalizer result: {result}")

        # Verify the result structure
        assert result is not None
        assert "detector" in result
        assert "original_text" in result

        # Verify the chosen detector matches expectation
        chosen_detector = result["detector"]
        assert chosen_detector == expected_detector, \
            f"Expected detector '{expected_detector}' for {instrument_code}, but got '{chosen_detector}'"

        print(f"✓ {instrument_code}: Correctly selected detector '{chosen_detector}'")



if __name__ == "__main__":
    # Run integration tests 
    pytest.main([__file__, "-v", "-m", "integration", "-s"])