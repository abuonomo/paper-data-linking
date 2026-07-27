import pytest
from paper_data_linking.linkers.general.normalizers.physobs_normalizer import PhysObsNormalizer
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestPhysObsNormalizerIntegration:
    """Integration tests that actually call the LLM with real data."""

    @pytest.mark.integration
    @pytest.mark.parametrize("instrument_code,data_file", [
        ("LASCO", "3_aia_secchi_lasco_normalization_context.json"),
        ("SECCHI", "3_aia_secchi_lasco_normalization_context.json"),
        ("AIA", "3_aia_secchi_lasco_normalization_context.json"),
    ])
    def test_physobs_selection_from_structured_data(
        self, instrument_code, data_file, normalization_contexts_from_test_data, llm_pipeline_config
    ):
        """Test physobs selection with real LLM call using normalization test data.

        Parameterized to test multiple instruments and their physobs selections.
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
        normalizer = PhysObsNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting {instrument_name}: {period_name}")

        # Call the physobs normalizer (will actually call LLM)
        result = normalizer.normalize(context)

        print(f"PhysObs normalizer result: {result}")

        # Verify the result structure
        assert result is not None
        assert "physical_observable" in result
        assert "original_text" in result

        # Verify the original_text matches the input
        assert result["original_text"] == context.period_data.physical_observable

        # The chosen physobs can be either a valid string or None (for UNCERTAIN)
        chosen_physobs = result["physical_observable"]
        print(f"✓ {instrument_code}: Selected physobs '{chosen_physobs}'")




if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "-m", "integration", "-s"])
