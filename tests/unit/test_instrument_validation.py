"""Unit tests for instrument validation in InstrumentGrounder."""

import pytest
from unittest.mock import Mock
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.catalogue_models import CatalogueEntry


class TestInstrumentValidation:
    """Unit tests for instrument validation logic."""

    @pytest.fixture
    def grounder(self):
        """Create an InstrumentGrounder instance with mocked dependencies."""
        grounder = InstrumentGrounder.__new__(InstrumentGrounder)
        grounder.llm_client = Mock()
        grounder.llm_config = Mock()
        # to_kwargs() is **-unpacked at call sites; a Mock can't be.
        for cfg in (grounder.llm_config.instrument_grounding.validation,
                    grounder.llm_config.instrument_grounding.mission_validation):
            cfg.to_kwargs.side_effect = lambda **kw: {"temperature": 1.0, **kw}
        return grounder

    def test_parse_validation_response_valid(self, grounder):
        """Test parsing a valid validation response."""
        response = """
        VALIDATION ANALYSIS:
        - Name/Type alignment: Instrument names match → pass
        - Mission reference match: SOHO is correct → pass

        FINAL DECISION: valid
        """

        result = grounder._parse_validation_response(response)
        assert result["decision"] == "valid"

    def test_parse_validation_response_invalid(self, grounder):
        """Test parsing an invalid validation response."""
        response = """
        VALIDATION ANALYSIS:
        - Name/Type alignment: Names don't match → fail

        FINAL DECISION: invalid
        """

        result = grounder._parse_validation_response(response)
        assert result["decision"] == "invalid"

    def test_parse_validation_response_case_insensitive(self, grounder):
        """Test that parsing handles different cases."""
        response = """
        VALIDATION ANALYSIS:
        - Name/Type alignment: Match → PASS

        FINAL DECISION: VALID
        """

        result = grounder._parse_validation_response(response)
        assert result["decision"] == "valid"

    def test_parse_validation_response_with_markdown(self, grounder):
        """Test parsing handles markdown asterisks."""
        response = """
        **VALIDATION ANALYSIS:**
        - **Name/Type alignment**: Names match → pass

        **FINAL DECISION: valid**
        """

        result = grounder._parse_validation_response(response)
        assert result["decision"] == "valid"

    def test_parse_validation_response_missing_decision_defaults_invalid(self, grounder):
        """Test that missing FINAL DECISION defaults to invalid (conservative)."""
        response = """
        VALIDATION ANALYSIS:
        - Name/Type alignment: Match → pass
        """

        result = grounder._parse_validation_response(response)
        assert result["decision"] == "invalid"

    def test_validate_single_catalogue_entry_valid(self, grounder):
        """Test validation when LLM returns valid."""
        instrument_entry = {
            "name": "LASCO C2",
            "general_comments": "White-light coronagraph",
            "data_collection_periods": []
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="LASCO",
            instrument_name="Large Angle and Spectrometric Coronagraph",
            mission_code="SOHO",
            mission_name="Solar and Heliospheric Observatory",
            data_system="vso"
        )

        # Mock LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        assert result is True

    def test_validate_single_catalogue_entry_invalid(self, grounder):
        """Test validation when LLM returns invalid."""
        instrument_entry = {
            "name": "STEREO-A EUVI",
            "general_comments": "EUV imaging",
            "data_collection_periods": []
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="EUVI",
            instrument_name="Extreme Ultraviolet Imager",
            mission_code="STEREO-B",
            mission_name="STEREO Behind",
            data_system="vso"
        )

        # Mock LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: invalid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        assert result is False

    def test_validate_single_catalogue_entry_llm_error_returns_false(self, grounder):
        """Test that LLM errors result in conservative rejection."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}
        catalogue_entry = CatalogueEntry(
            instrument_code="TEST",
            instrument_name="Test Instrument",
            mission_code="TEST",
            mission_name="Test Mission",
            data_system="vso"
        )

        # Mock LLM to raise an exception
        grounder.llm_client.completion = Mock(side_effect=Exception("API Error"))

        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        assert result is False

    def test_validate_single_catalogue_entry_parse_error_returns_false(self, grounder):
        """Test that unparseable responses result in conservative rejection."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}
        catalogue_entry = CatalogueEntry(
            instrument_code="TEST",
            instrument_name="Test Instrument",
            mission_code="TEST",
            mission_name="Test Mission",
            data_system="vso"
        )

        # Mock LLM response with unparseable content
        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="This is garbage"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        assert result is False

    def test_validate_catalogue_entries_filters_invalid(self, grounder):
        """Test that _validate_catalogue_entries filters out invalid entries."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}

        valid_entry = CatalogueEntry(
            instrument_code="VALID",
            instrument_name="Valid Instrument",
            mission_code="VALID",
            mission_name="Valid Mission",
            data_system="vso"
        )

        invalid_entry = CatalogueEntry(
            instrument_code="INVALID",
            instrument_name="Invalid Instrument",
            mission_code="INVALID",
            mission_name="Invalid Mission",
            data_system="vso"
        )

        # Mock validation to return True for valid, False for invalid
        def mock_validate(_, cat_entry):
            return cat_entry.instrument_code == "VALID"

        grounder._validate_single_catalogue_entry = Mock(side_effect=mock_validate)

        result = grounder._validate_catalogue_entries(instrument_entry, [valid_entry, invalid_entry])

        assert len(result) == 1
        assert result[0].instrument_code == "VALID"

    def test_validate_catalogue_entries_empty_returns_none(self, grounder):
        """Test that empty list returns None."""
        result = grounder._validate_catalogue_entries({"name": "Test"}, [])
        assert result is None

    def test_validate_catalogue_entries_all_rejected_returns_none(self, grounder):
        """Test that when all entries are rejected, returns None."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}
        entries = [
            CatalogueEntry(
                instrument_code="TEST1",
                instrument_name="Test 1",
                mission_code="TEST",
                mission_name="Test",
                data_system="vso"
            )
        ]

        grounder._validate_single_catalogue_entry = Mock(return_value=False)
        result = grounder._validate_catalogue_entries(instrument_entry, entries)
        assert result is None

    def test_validation_prompt_includes_instrument_description(self, grounder):
        """Test that the validation prompt includes the catalogue entry's description."""
        instrument_entry = {
            "name": "MWO magnetograms",
            "general_comments": "Synoptic magnetogram data",
            "data_collection_periods": []
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="60-ft_SHG",
            instrument_name="60-ft SHG",
            mission_code="MtWilson",
            mission_name="MtWilson",
            data_system="vso",
            description="Mt Wilson 60-foot tower spectroheliograph producing Ca II K intensity images"
        )

        # Mock LLM response
        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: invalid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)

        # Check prompt_context passed to completion includes description
        call_kwargs = grounder.llm_client.completion.call_args
        prompt_context = call_kwargs.kwargs.get('prompt_context', {})
        assert prompt_context['matched_instrument_description'] == catalogue_entry.description

        # Check the user message sent to LLM contains the description
        messages = call_kwargs.kwargs.get('messages', [])
        user_msg = messages[1]['content']
        assert "spectroheliograph" in user_msg

    def test_validation_prompt_includes_all_periods(self, grounder):
        """Test that all data collection periods are included, not just the first."""
        instrument_entry = {
            "name": "AIA",
            "general_comments": "SDO/AIA EUV imaging",
            "data_collection_periods": [
                {
                    "time_range": "2010-2012",
                    "physical_observable": "intensity",
                    "wavelengths": "171 Angstroms",
                },
                {
                    "time_range": "2013-2015",
                    "physical_observable": "intensity",
                    "wavelengths": "304 Angstroms",
                    "additional_comments": "Used for flare analysis",
                },
            ]
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="AIA",
            instrument_name="Atmospheric Imaging Assembly",
            mission_code="SDO",
            mission_name="Solar Dynamics Observatory",
            data_system="vso",
            description="The AIA provides full-disk images of the solar corona"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)

        call_kwargs = grounder.llm_client.completion.call_args
        prompt_context = call_kwargs.kwargs.get('prompt_context', {})
        period_infos = prompt_context['period_infos']

        # Both periods should be present
        assert len(period_infos) == 2
        assert "171 Angstroms" in period_infos[0]
        assert "304 Angstroms" in period_infos[1]
        assert "flare analysis" in period_infos[1]

        # Check user message contains info from both periods
        user_msg = call_kwargs.kwargs['messages'][1]['content']
        assert "171 Angstroms" in user_msg
        assert "304 Angstroms" in user_msg

    def test_validation_prompt_includes_wavelengths(self, grounder):
        """Test that wavelength info from data collection periods is passed to template."""
        instrument_entry = {
            "name": "EIT",
            "general_comments": "EUV Imaging",
            "data_collection_periods": [
                {
                    "time_range": "1996-2010",
                    "wavelengths": "195 Angstroms",
                    "physical_observable": "intensity",
                }
            ]
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="EIT",
            instrument_name="Extreme ultraviolet Imaging Telescope",
            mission_code="SOHO",
            mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            description="The EIT images the solar transition region and corona"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)

        call_kwargs = grounder.llm_client.completion.call_args
        user_msg = call_kwargs.kwargs['messages'][1]['content']
        assert "195 Angstroms" in user_msg

    def test_validation_prompt_empty_description_handled(self, grounder):
        """Test that empty description doesn't break the template."""
        instrument_entry = {
            "name": "Test",
            "general_comments": "Test comments",
            "data_collection_periods": []
        }

        catalogue_entry = CatalogueEntry(
            instrument_code="TEST",
            instrument_name="Test Instrument",
            mission_code="TEST",
            mission_name="Test Mission",
            data_system="vso",
            description=""
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        assert result is True
