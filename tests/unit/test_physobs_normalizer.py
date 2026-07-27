import pytest
from unittest.mock import Mock
from paper_data_linking.linkers.general.normalizers.physobs_normalizer import PhysObsNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestPhysObsNormalizer:
    """Unit tests for PhysObsNormalizer."""

    @pytest.fixture
    def llm_config(self):
        """Fixture providing a mock LLM config for physobs normalizer."""
        from paper_data_linking.config.settings import get_llm_configuration
        return get_llm_configuration("standard")

    @pytest.fixture
    def physobs_normalizer(self, llm_config):
        """Fixture providing a PhysObsNormalizer instance."""
        llm_client = LiteLLMClient()
        return PhysObsNormalizer(llm_client=llm_client, llm_config=llm_config)

    def test_build_physobs_context(self, physobs_normalizer):
        """Test context building uses minimal context - just physical_observable field."""
        period = InternalDataCollectionPeriod(
            period_name="CME detection",
            physical_observable="White-light CME front and core height–time measurements",
            additional_comments="Some additional comments",
            general_quotes=["Some quote from the paper"]
        )

        grounding_result = GroundingResult(
            matched_instrument_code="LASCO",
            matched_instrument_name="Large Angle and Spectrometric Coronagraph",
            matched_mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            reasoning="White-light coronagraph for CME detection"
        )

        context = NormalizationContext(
            instrument_code="LASCO",
            instrument_name="Large Angle and Spectrometric Coronagraph",
            instrument_general_comments="LASCO C2 white-light imaging",
            data_system="vso",
            period_name="CME detection",
            period_data=period,
            grounding_result=grounding_result
        )

        result = physobs_normalizer._build_physobs_context(context)

        # Should only contain the physical_observable field
        assert result == "White-light CME front and core height–time measurements"
        # Should NOT contain other fields
        assert "additional_comments" not in result
        assert "general_quotes" not in result

    def test_parse_physobs_response_exact_match(self, physobs_normalizer):
        """Test parsing physobs response when response is exactly a candidate."""
        candidates = ["intensity", "magnetic_field", "dopplergram"]
        response_text = "intensity"

        result = physobs_normalizer._parse_physobs_response(response_text, candidates)

        assert result == "intensity"

    def test_parse_physobs_response_uncertain(self, physobs_normalizer):
        """Test parsing when LLM returns UNCERTAIN."""
        candidates = ["intensity", "magnetic_field", "dopplergram"]
        response_text = "UNCERTAIN"

        result = physobs_normalizer._parse_physobs_response(response_text, candidates)

        assert result is None

    def test_parse_physobs_response_uncertain_lowercase(self, physobs_normalizer):
        """Test parsing handles uncertain in any case."""
        candidates = ["intensity", "magnetic_field", "dopplergram"]
        response_text = "uncertain"

        result = physobs_normalizer._parse_physobs_response(response_text, candidates)

        assert result is None

    def test_parse_physobs_response_no_match(self, physobs_normalizer):
        """Test parsing when response doesn't match any candidate."""
        candidates = ["intensity", "magnetic_field", "dopplergram"]
        response_text = "velocity"

        result = physobs_normalizer._parse_physobs_response(response_text, candidates)

        assert result is None

    def test_parse_physobs_response_with_whitespace(self, physobs_normalizer):
        """Test parsing strips whitespace from response."""
        candidates = ["intensity", "magnetic_field", "dopplergram"]
        response_text = "  intensity  \n"

        result = physobs_normalizer._parse_physobs_response(response_text, candidates)

        assert result == "intensity"

    def test_handle_no_candidates(self, physobs_normalizer):
        """Test handling when no physobs candidates exist for the instrument."""
        raw_observable = "Some observable for instrument with no candidates"
        instrument_code = "UNKNOWN_INST"

        result = physobs_normalizer._handle_no_candidates(raw_observable, instrument_code)

        # Should return NormalizedObservable dict with physical_observable=None
        assert isinstance(result, dict)
        assert result["physical_observable"] is None
        assert result["original_text"] == raw_observable

    def test_handle_single_candidate(self, physobs_normalizer):
        """Test handling when exactly one physobs candidate exists."""
        raw_observable = "Context for single physobs instrument"
        instrument_code = "TEST_INST"

        # Mock the instrument_physobs dict to have a single candidate
        physobs_normalizer._instrument_physobs = {"TEST_INST": ["intensity"]}

        result = physobs_normalizer._handle_single_candidate(raw_observable, instrument_code)

        # Should return NormalizedObservable dict with the single physobs
        assert isinstance(result, dict)
        assert result["physical_observable"] == "intensity"
        assert result["original_text"] == raw_observable

    def test_handle_multiple_candidates_valid_physobs(self, physobs_normalizer):
        """Test handling multiple candidates when LLM returns a valid physobs."""
        raw_observable = "Context mentioning magnetic field observations"
        instrument_code = "TEST_INST"
        candidates = ["intensity", "magnetic_field", "dopplergram"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="magnetic_field"))]
        physobs_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = physobs_normalizer._handle_multiple_candidates(
            raw_observable, instrument_code, candidates
        )

        # Should return the valid physobs
        assert isinstance(result, dict)
        assert result["physical_observable"] == "magnetic_field"
        assert result["original_text"] == raw_observable
        # Verify LLM was called
        physobs_normalizer.llm_client.completion.assert_called_once()

    def test_handle_multiple_candidates_uncertain(self, physobs_normalizer):
        """Test handling multiple candidates when LLM returns UNCERTAIN."""
        raw_observable = "Ambiguous context about observable"
        instrument_code = "TEST_INST"
        candidates = ["intensity", "magnetic_field", "dopplergram"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="UNCERTAIN"))]
        physobs_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = physobs_normalizer._handle_multiple_candidates(
            raw_observable, instrument_code, candidates
        )

        # Should return None when uncertain
        assert isinstance(result, dict)
        assert result["physical_observable"] is None
        assert result["original_text"] == raw_observable

    def test_handle_multiple_candidates_invalid_physobs(self, physobs_normalizer):
        """Test handling multiple candidates when LLM returns an invalid physobs."""
        raw_observable = "Context about observable"
        instrument_code = "TEST_INST"
        candidates = ["intensity", "magnetic_field", "dopplergram"]

        # Mock the LLM response with an invalid physobs
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="INVALID_PHYSOBS"))]
        physobs_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = physobs_normalizer._handle_multiple_candidates(
            raw_observable, instrument_code, candidates
        )

        # Should return None and log warning about invalid response
        assert isinstance(result, dict)
        assert result["physical_observable"] is None
        assert result["original_text"] == raw_observable

    def test_handle_multiple_candidates_validation_catches_mismatch(self, physobs_normalizer):
        """Test that validation catches when parser returns physobs not in candidates."""
        raw_observable = "Context about observable"
        instrument_code = "TEST_INST"
        candidates = ["intensity", "magnetic_field", "dopplergram"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="magnetic_field"))]
        physobs_normalizer.llm_client.completion = Mock(return_value=mock_response)

        # Mock the parser to return a physobs NOT in candidates (defensive test)
        physobs_normalizer._parse_physobs_response = Mock(return_value="INVALID")

        result = physobs_normalizer._handle_multiple_candidates(
            raw_observable, instrument_code, candidates
        )

        # Validation should catch the mismatch and set physobs to None
        assert isinstance(result, dict)
        assert result["physical_observable"] is None
        assert result["original_text"] == raw_observable
