"""Unit tests for mission validation in InstrumentGrounder."""

import pytest
from unittest.mock import Mock
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.catalogue_models import Mission


class TestMissionValidation:
    """Unit tests for mission validation logic."""

    @pytest.fixture
    def grounder(self):
        """Create an InstrumentGrounder instance with mocked dependencies."""
        grounder = InstrumentGrounder.__new__(InstrumentGrounder)
        grounder.llm_client = Mock()
        grounder.llm_config = Mock()
        # to_kwargs() is **-unpacked at call sites; a Mock can't be, so give the
        # mocked configs a real dict (mirrors LLMCallConfig.to_kwargs output).
        for cfg in (grounder.llm_config.instrument_grounding.validation,
                    grounder.llm_config.instrument_grounding.mission_validation,
                    grounder.llm_config.instrument_grounding.exact_match,
                    grounder.llm_config.instrument_grounding.exact_match_fallback,
                    grounder.llm_config.instrument_grounding.similarity_filter,
                    grounder.llm_config.instrument_grounding.substring_filter):
            cfg.to_kwargs.side_effect = lambda **kw: {"temperature": 1.0, **kw}
        grounder.finder = Mock()
        return grounder

    # --- _parse_mission_validation_response tests ---

    def test_parse_mission_validation_response_valid(self, grounder):
        """Test parsing a valid mission validation response."""
        response = """
        VALIDATION ANALYSIS:
        - Domain alignment: Solar mission matches solar observations → pass
        - Temporal compatibility: Mission operational during described period → pass
        - Explicit mention: Paper mentions SOHO by name → pass
        - Scientific capability: SOHO hosts relevant instruments → pass

        FINAL DECISION: valid
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["decision"] == "valid"
        assert result["criteria"]["domain_alignment"] == "pass"
        assert result["criteria"]["temporal"] == "pass"
        assert result["criteria"]["explicit_mention"] == "pass"
        assert result["criteria"]["capability"] == "pass"

    def test_parse_mission_validation_response_invalid(self, grounder):
        """Test parsing an invalid mission validation response."""
        response = """
        VALIDATION ANALYSIS:
        - Domain alignment: Solar mission for magnetospheric data → fail
        - Temporal compatibility: Compatible → pass
        - Explicit mention: No mention of SOHO → fail
        - Scientific capability: Not relevant → fail

        FINAL DECISION: invalid
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["decision"] == "invalid"
        assert result["criteria"]["domain_alignment"] == "fail"
        assert result["criteria"]["explicit_mention"] == "fail"

    def test_parse_mission_validation_response_case_insensitive(self, grounder):
        """Test that parsing handles different cases."""
        response = """
        VALIDATION ANALYSIS:
        - Domain alignment: Match → PASS
        - Temporal compatibility: Match → PASS
        - Explicit mention: Match → PASS
        - Scientific capability: Match → PASS

        FINAL DECISION: VALID
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["decision"] == "valid"

    def test_parse_mission_validation_response_with_markdown(self, grounder):
        """Test parsing handles markdown asterisks."""
        response = """
        **VALIDATION ANALYSIS:**
        - **Domain alignment**: Solar matches solar → pass
        - **Temporal compatibility**: OK → pass
        - **Explicit mention**: SOHO mentioned → pass
        - **Scientific capability**: OK → pass

        **FINAL DECISION: valid**
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["decision"] == "valid"

    def test_parse_mission_validation_response_missing_decision_defaults_invalid(self, grounder):
        """Test that missing FINAL DECISION defaults to invalid (conservative)."""
        response = """
        VALIDATION ANALYSIS:
        - Domain alignment: Match → pass
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["decision"] == "invalid"

    def test_parse_mission_validation_response_missing_criteria_defaults_fail(self, grounder):
        """Test that missing criteria default to fail (conservative)."""
        response = """
        VALIDATION ANALYSIS:
        - Domain alignment: Match → pass

        FINAL DECISION: valid
        """

        result = grounder._parse_mission_validation_response(response)
        assert result["criteria"]["domain_alignment"] == "pass"
        assert result["criteria"]["temporal"] == "fail"
        assert result["criteria"]["explicit_mention"] == "fail"
        assert result["criteria"]["capability"] == "fail"

    # --- _validate_single_mission tests ---

    def test_validate_single_mission_valid(self, grounder):
        """Test validation when LLM returns valid."""
        instrument_entry = {
            "name": "LASCO C2",
            "general_comments": "White-light coronagraph on SOHO",
            "data_collection_periods": []
        }

        mission_obj = Mission(
            mission_code="SOHO",
            mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            description="Solar observatory at L1"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_mission(instrument_entry, mission_obj)
        assert result is True

    def test_validate_single_mission_invalid(self, grounder):
        """Test validation when LLM returns invalid."""
        instrument_entry = {
            "name": "OMNI data",
            "general_comments": "Multi-source solar wind dataset",
            "data_collection_periods": []
        }

        mission_obj = Mission(
            mission_code="SOHO",
            mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            description="Solar observatory at L1"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: invalid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_mission(instrument_entry, mission_obj)
        assert result is False

    def test_validate_single_mission_llm_error_returns_false(self, grounder):
        """Test that LLM errors result in conservative rejection."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}
        mission_obj = Mission(
            mission_code="TEST",
            mission_name="Test Mission",
            data_system="vso"
        )

        grounder.llm_client.completion = Mock(side_effect=Exception("API Error"))

        result = grounder._validate_single_mission(instrument_entry, mission_obj)
        assert result is False

    def test_validate_single_mission_parse_error_returns_false(self, grounder):
        """Test that unparseable responses result in conservative rejection."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}
        mission_obj = Mission(
            mission_code="TEST",
            mission_name="Test Mission",
            data_system="vso"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="This is garbage"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        result = grounder._validate_single_mission(instrument_entry, mission_obj)
        assert result is False

    def test_validate_single_mission_includes_period_infos(self, grounder):
        """Test that data collection periods are passed to the prompt."""
        instrument_entry = {
            "name": "AIA",
            "general_comments": "SDO/AIA imaging",
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
                    "additional_comments": "Flare analysis",
                },
            ]
        }

        mission_obj = Mission(
            mission_code="SDO",
            mission_name="Solar Dynamics Observatory",
            data_system="vso",
            description="Solar observatory in geosynchronous orbit"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        grounder._validate_single_mission(instrument_entry, mission_obj)

        call_kwargs = grounder.llm_client.completion.call_args
        prompt_context = call_kwargs.kwargs.get('prompt_context', {})
        period_infos = prompt_context['period_infos']

        assert len(period_infos) == 2
        assert "171 Angstroms" in period_infos[0]
        assert "304 Angstroms" in period_infos[1]
        assert "Flare analysis" in period_infos[1]

    def test_validate_single_mission_includes_description(self, grounder):
        """Test that mission description is passed to the prompt."""
        instrument_entry = {
            "name": "Test",
            "general_comments": "Test comments",
            "data_collection_periods": []
        }

        mission_obj = Mission(
            mission_code="SOHO",
            mission_name="Solar and Heliospheric Observatory",
            data_system="vso",
            description="Solar observatory at L1 Lagrange point"
        )

        mock_response = Mock()
        mock_response.choices = [Mock(
            message=Mock(content="FINAL DECISION: valid"),
            finish_reason="stop"
        )]
        grounder.llm_client.completion = Mock(return_value=mock_response)

        grounder._validate_single_mission(instrument_entry, mission_obj)

        call_kwargs = grounder.llm_client.completion.call_args
        prompt_context = call_kwargs.kwargs.get('prompt_context', {})
        assert prompt_context['matched_mission_description'] == "Solar observatory at L1 Lagrange point"

        messages = call_kwargs.kwargs.get('messages', [])
        user_msg = messages[1]['content']
        assert "L1 Lagrange point" in user_msg

    # --- _validate_missions tests ---

    def test_validate_missions_filters_invalid(self, grounder):
        """Test that _validate_missions filters out invalid missions."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}

        missions = [
            Mission(mission_code="SOHO", mission_name="SOHO", data_system="vso"),
            Mission(mission_code="SDO", mission_name="SDO", data_system="vso"),
        ]
        grounder.finder.get_unique_missions = Mock(return_value=missions)

        def mock_validate(_, mission_obj):
            return mission_obj.mission_code == "SOHO"

        grounder._validate_single_mission = Mock(side_effect=mock_validate)

        result = grounder._validate_missions(instrument_entry, ["SOHO", "SDO"], "vso")

        assert result == ["SOHO"]

    def test_validate_missions_all_rejected_returns_none(self, grounder):
        """Test that when all missions are rejected, returns None."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}

        missions = [
            Mission(mission_code="SOHO", mission_name="SOHO", data_system="vso"),
        ]
        grounder.finder.get_unique_missions = Mock(return_value=missions)
        grounder._validate_single_mission = Mock(return_value=False)

        result = grounder._validate_missions(instrument_entry, ["SOHO"], "vso")
        assert result is None

    def test_validate_missions_empty_list_returns_none(self, grounder):
        """Test that empty mission list returns None."""
        result = grounder._validate_missions({"name": "Test"}, [], "vso")
        assert result is None

    def test_validate_missions_unknown_mission_passes_through(self, grounder):
        """Test that missions not found in catalogue pass through validation."""
        instrument_entry = {"name": "Test", "general_comments": "Test", "data_collection_periods": []}

        grounder.finder.get_unique_missions = Mock(return_value=[])

        result = grounder._validate_missions(instrument_entry, ["UnknownMission"], "vso")
        assert result == ["UnknownMission"]
