import pytest
from unittest.mock import Mock, MagicMock
from paper_data_linking.linkers.general.normalizers.detector_normalizer import DetectorNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestDetectorNormalizer:
    """Unit tests for DetectorNormalizer."""

    @pytest.fixture
    def llm_config(self):
        """Fixture providing a mock LLM config for detector normalizer."""
        from paper_data_linking.config.settings import get_llm_configuration
        return get_llm_configuration("standard")

    @pytest.fixture
    def detector_normalizer(self, llm_config):
        """Fixture providing a DetectorNormalizer instance."""
        llm_client = LiteLLMClient()
        return DetectorNormalizer(llm_client=llm_client, llm_config=llm_config)

    def test_build_detector_context_with_all_fields(self, detector_normalizer):
        """Test context building organizes detector-relevant information with structural clarity."""
        period = InternalDataCollectionPeriod(
            period_name="CME detection and height-time extension",
            additional_comments="LASCO is a multi-detector system with C2 (outer coronagraph) being the primary imaging detector used in this analysis",
            physical_observable="White-light CME front and core height–time measurements; typical flux rope CME morphology",
            general_quotes=[
                "WL images of the outer corona (2.2-6 R⊙) from the Large Angle and Spectrometric Coronograph (LASCO; Brueckner et al. 1995) C2 coronagraph on board the SOHO mission.",
                "Around 05:36 UT a WL CME emerges in the LASCO C2 coronagraph."
            ]
        )

        grounding_result = GroundingResult(
            matched_instrument_code="LASCO",
            matched_instrument_name="Large Angle and Spectrometric Coronagraph",
            matched_mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            reasoning="White-light coronagraph for CME detection and kinematics"
        )

        context = NormalizationContext(
            instrument_code="LASCO",
            instrument_name="Large Angle and Spectrometric Coronagraph (LASCO C2) on board SOHO",
            instrument_general_comments="LASCO C2 white-light imaging was used to detect the CME, determine its appearance time, and extend height–time measurements of the erupting flux rope/CME core beyond the AIA FOV. LASCO C2 cadence was 12 minutes; pixel size 12 arcsec.",
            data_system="vso",
            period_name="CME detection and height-time extension",
            period_data=period,
            grounding_result=grounding_result
        )

        result = detector_normalizer._build_detector_context(context)

        # Should contain all major sections
        assert "Instrument: Large Angle and Spectrometric Coronagraph (LASCO C2) on board SOHO" in result
        assert "Matched: Large Angle and Spectrometric Coronagraph (Solar and Heliospheric Observatory)" in result
        assert "Purpose: White-light coronagraph for CME detection and kinematics" in result
        assert "Period: CME detection and height-time extension" in result
        assert "LASCO C2 white-light imaging was used to detect the CME" in result
        assert "C2 (outer coronagraph)" in result
        assert "WL images of the outer corona" in result

    def test_parse_detector_response_exact_match(self, detector_normalizer):
        """Test parsing detector response when response is exactly a candidate."""
        candidates = ["C1", "C2", "C3"]
        response_text = "C2"

        result = detector_normalizer._parse_detector_response(response_text, candidates)

        assert result == "C2"

    def test_parse_detector_response_uncertain(self, detector_normalizer):
        """Test parsing when LLM returns UNCERTAIN."""
        candidates = ["C1", "C2", "C3"]
        response_text = "UNCERTAIN"

        result = detector_normalizer._parse_detector_response(response_text, candidates)

        assert result is None

    def test_parse_detector_response_uncertain_lowercase(self, detector_normalizer):
        """Test parsing handles uncertain in any case."""
        candidates = ["EUVI", "COR1", "COR2"]
        response_text = "uncertain"

        result = detector_normalizer._parse_detector_response(response_text, candidates)

        assert result is None

    def test_parse_detector_response_no_match(self, detector_normalizer):
        """Test parsing when response doesn't match any candidate."""
        candidates = ["C1", "C2", "C3"]
        response_text = "HI1"

        result = detector_normalizer._parse_detector_response(response_text, candidates)

        assert result is None

    def test_parse_detector_response_with_whitespace(self, detector_normalizer):
        """Test parsing strips whitespace from response."""
        candidates = ["C1", "C2", "C3"]
        response_text = "  C2  \n"

        result = detector_normalizer._parse_detector_response(response_text, candidates)

        assert result == "C2"

    def test_handle_no_candidates(self, detector_normalizer):
        """Test handling when no detector candidates exist for the instrument."""
        raw_detector_context = "Some detector context for instrument with no candidates"
        instrument_code = "UNKNOWN_INST"

        result = detector_normalizer._handle_no_candidates(raw_detector_context, instrument_code)

        # Should return NormalizedDetector dict with detector=None
        assert isinstance(result, dict)
        assert result["detector"] is None
        assert result["original_text"] == raw_detector_context

    def test_handle_single_candidate(self, detector_normalizer):
        """Test handling when exactly one detector candidate exists (detector is implied)."""
        raw_detector_context = "Context for single detector instrument like AIA"
        instrument_code = "AIA"

        result = detector_normalizer._handle_single_candidate(raw_detector_context, instrument_code)

        # Should return NormalizedDetector dict with detector=None since single detector is implied
        assert isinstance(result, dict)
        assert result["detector"] is None
        assert result["original_text"] == raw_detector_context

    def test_handle_multiple_candidates_valid_detector(self, detector_normalizer):
        """Test handling multiple candidates when LLM returns a valid detector."""
        raw_detector_context = "Context mentioning C2 coronagraph observations"
        instrument_code = "LASCO"
        candidates = ["C1", "C2", "C3"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="C2"))]
        detector_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = detector_normalizer._handle_multiple_candidates(
            raw_detector_context, instrument_code, candidates
        )

        # Should return the valid detector
        assert isinstance(result, dict)
        assert result["detector"] == "C2"
        assert result["original_text"] == raw_detector_context
        # Verify LLM was called
        detector_normalizer.llm_client.completion.assert_called_once()

    def test_handle_multiple_candidates_uncertain(self, detector_normalizer):
        """Test handling multiple candidates when LLM returns UNCERTAIN."""
        raw_detector_context = "Ambiguous context about detector"
        instrument_code = "LASCO"
        candidates = ["C1", "C2", "C3"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="UNCERTAIN"))]
        detector_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = detector_normalizer._handle_multiple_candidates(
            raw_detector_context, instrument_code, candidates
        )

        # Should return None when uncertain
        assert isinstance(result, dict)
        assert result["detector"] is None
        assert result["original_text"] == raw_detector_context

    def test_handle_multiple_candidates_invalid_detector(self, detector_normalizer):
        """Test handling multiple candidates when LLM returns an invalid detector."""
        raw_detector_context = "Context about detector"
        instrument_code = "LASCO"
        candidates = ["C1", "C2", "C3"]

        # Mock the LLM response with an invalid detector
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="INVALID_DETECTOR"))]
        detector_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = detector_normalizer._handle_multiple_candidates(
            raw_detector_context, instrument_code, candidates
        )

        # Should return None and log warning about invalid response
        assert isinstance(result, dict)
        assert result["detector"] is None
        assert result["original_text"] == raw_detector_context

    def test_handle_multiple_candidates_validation_catches_mismatch(self, detector_normalizer):
        """Test that validation catches when parser returns detector not in candidates."""
        raw_detector_context = "Context about detector"
        instrument_code = "LASCO"
        candidates = ["C1", "C2", "C3"]

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="C2"))]
        detector_normalizer.llm_client.completion = Mock(return_value=mock_response)

        # Mock the parser to return a detector NOT in candidates (defensive test)
        detector_normalizer._parse_detector_response = Mock(return_value="INVALID")

        result = detector_normalizer._handle_multiple_candidates(
            raw_detector_context, instrument_code, candidates
        )

        # Validation should catch the mismatch and set detector to None
        assert isinstance(result, dict)
        assert result["detector"] is None
        assert result["original_text"] == raw_detector_context