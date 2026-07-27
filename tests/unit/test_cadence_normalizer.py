import pytest
from unittest.mock import Mock
from paper_data_linking.linkers.general.normalizers.cadence_normalizer import CadenceNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestCadenceNormalizer:
    """Unit tests for CadenceNormalizer."""

    @pytest.fixture
    def llm_config(self):
        """Fixture providing a mock LLM config for cadence normalizer."""
        from paper_data_linking.config.settings import get_llm_configuration
        return get_llm_configuration("standard")

    @pytest.fixture
    def cadence_normalizer(self, llm_config):
        """Fixture providing a CadenceNormalizer instance."""
        llm_client = LiteLLMClient()
        return CadenceNormalizer(llm_client=llm_client, llm_config=llm_config)

    def test_build_cadence_context(self, cadence_normalizer):
        """Test context building organizes cadence-relevant information with structural clarity."""
        period = InternalDataCollectionPeriod(
            period_name="CME detection",
            additional_comments="LASCO C2 cadence was 12 minutes; pixel size 12 arcsec",
            general_quotes=[
                "The cadence of the STA 195 and LASCO images was 5 and 12 minutes, respectively.",
                "Pixel sizes for AIA, EUVI and LASCO C2 images are 0.6, 1.6 and 12 arcsec respectively."
            ]
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
            instrument_general_comments="LASCO C2 white-light imaging was used to detect the CME. LASCO cadence reduced to 12 minutes for data volume.",
            data_system="vso",
            period_name="CME detection",
            period_data=period,
            grounding_result=grounding_result
        )

        result = cadence_normalizer._build_cadence_context(context)

        # Should contain all sections with newlines
        assert "LASCO C2 white-light imaging" in result
        assert "LASCO C2 cadence was 12 minutes" in result
        assert "The cadence of the STA 195 and LASCO images was 5 and 12 minutes" in result
        assert "\n" in result  # Should have newline separators

    def test_parse_cadence_response_single_cadence(self, cadence_normalizer):
        """Test parsing single ISO 8601 cadence string."""
        response_text = "PT3S"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result == ["PT3S"]

    def test_parse_cadence_response_multiple_cadences(self, cadence_normalizer):
        """Test parsing multiple comma-separated cadences."""
        response_text = "PT3S, PT1M"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result == ["PT3S", "PT1M"]

    def test_parse_cadence_response_cadence_range(self, cadence_normalizer):
        """Test parsing cadence range (e.g., PT12S/PT16S)."""
        response_text = "PT12S/PT16S"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result == ["PT12S/PT16S"]

    def test_parse_cadence_response_none(self, cadence_normalizer):
        """Test parsing when LLM returns NONE."""
        response_text = "NONE"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result is None

    def test_parse_cadence_response_none_lowercase(self, cadence_normalizer):
        """Test parsing handles NONE in any case."""
        response_text = "none"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result is None

    def test_parse_cadence_response_with_whitespace(self, cadence_normalizer):
        """Test parsing strips whitespace from response."""
        response_text = "  PT3S  \n"
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result == ["PT3S"]

    def test_parse_cadence_response_multiple_with_whitespace(self, cadence_normalizer):
        """Test parsing handles whitespace in multi-cadence response."""
        response_text = "  PT3S  ,  PT1M  "
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result == ["PT3S", "PT1M"]

    def test_parse_cadence_response_empty(self, cadence_normalizer):
        """Test parsing empty response returns None."""
        response_text = ""
        result = cadence_normalizer._parse_cadence_response(response_text)
        assert result is None

    def test_handle_cadence_extraction_valid_response(self, cadence_normalizer):
        """Test extraction with valid LLM response."""
        raw_cadence_context = "The cadence was 12 minutes"
        instrument_code = "LASCO"

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="PT12M"))]
        cadence_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = cadence_normalizer._handle_cadence_extraction(raw_cadence_context, instrument_code)

        # Should return the parsed cadence
        assert isinstance(result, dict)
        assert result["cadences"] == ["PT12M"]
        assert result["original_text"] == raw_cadence_context
        # Verify LLM was called
        cadence_normalizer.llm_client.completion.assert_called_once()

    def test_handle_cadence_extraction_none_response(self, cadence_normalizer):
        """Test extraction when LLM returns NONE."""
        raw_cadence_context = "No clear cadence information"
        instrument_code = "UNKNOWN_INST"

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="NONE"))]
        cadence_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = cadence_normalizer._handle_cadence_extraction(raw_cadence_context, instrument_code)

        # Should return None when no cadences found
        assert isinstance(result, dict)
        assert result["cadences"] is None
        assert result["original_text"] == raw_cadence_context

    def test_handle_cadence_extraction_multiple_cadences(self, cadence_normalizer):
        """Test extraction with multiple cadences."""
        raw_cadence_context = "AIA had 1 minute cadence, LASCO had 12 minutes"
        instrument_code = "AIA"

        # Mock the LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="PT1M, PT12M"))]
        cadence_normalizer.llm_client.completion = Mock(return_value=mock_response)

        result = cadence_normalizer._handle_cadence_extraction(raw_cadence_context, instrument_code)

        # Should return list of cadences
        assert isinstance(result, dict)
        assert result["cadences"] == ["PT1M", "PT12M"]
        assert result["original_text"] == raw_cadence_context
