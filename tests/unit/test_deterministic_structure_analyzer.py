"""Tests for DeterministicStructureAnalyzer."""

from unittest.mock import Mock, patch

import pytest

from paper_data_linking.config.settings import LLMPipelineConfig, get_llm_configuration
from paper_data_linking.linkers.general.deterministic_structure_analyzer import (
    DeterministicStructureAnalyzer,
)
from paper_data_linking.linkers.general.schemas.structured_instruments import (
    DataCollectionPeriod,
    Instrument,
    StructuredInstrumentDetails,
)
from paper_data_linking.linkers.general.structured_instruments_analyzer import (
    StructuredInstrumentsOutput,
)
from paper_data_linking.linkers.general.validators.pipeline import PipelineResult


@pytest.fixture
def llm_config():
    return get_llm_configuration("standard")


@pytest.fixture
def mock_client():
    return Mock()


def _parsed_result(n_instruments=1):
    instruments = []
    for i in range(n_instruments):
        instruments.append(
            Instrument(
                name=f"Instrument {i}",
                general_comments="",
                general_quotes=[],
                data_collection_periods=[
                    DataCollectionPeriod(
                        period_name="P1",
                        time_range="2020-01-01",
                        time_quotes=[],
                        wavelengths=None,
                        wavelength_quotes=[],
                        physical_observable="obs",
                        physobs_quotes=[],
                        general_quotes=[],
                        additional_comments=None,
                    )
                ],
            )
        )
    return StructuredInstrumentDetails(
        paper_summary="test",
        instruments=instruments,
    )


def _pipeline_result(structured):
    return PipelineResult(
        structured=structured,
        total_issues_found=0,
        total_issues_fixed=0,
        total_llm_calls=0,
        all_skipped=True,
    )


class TestForward:
    def test_happy_path(self, mock_client, llm_config):
        parsed = _parsed_result(n_instruments=2)

        with patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.parse_instrument_markdown",
            return_value=parsed,
        ), patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.StructureValidatorPipeline"
        ) as MockPipeline:
            MockPipeline.return_value.run.return_value = _pipeline_result(parsed)

            analyzer = DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config=llm_config
            )
            result = analyzer.forward("some markdown")

        assert result.success is True
        assert result.metadata["method"] == "parser"
        assert result.metadata["parser_instruments_count"] == 2

    def test_zero_instruments_returns_empty(self, mock_client, llm_config):
        empty_parsed = _parsed_result(n_instruments=0)

        with patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.parse_instrument_markdown",
            return_value=empty_parsed,
        ), patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.StructureValidatorPipeline"
        ) as MockPipeline:
            MockPipeline.return_value.run.return_value = _pipeline_result(empty_parsed)

            analyzer = DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config=llm_config
            )
            result = analyzer.forward("bad markdown")

        assert result.success is True
        assert result.metadata["parser_instruments_count"] == 0
        assert result.metadata["instruments_count"] == 0

    def test_parser_exception_propagates(self, mock_client, llm_config):
        with patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.parse_instrument_markdown",
            side_effect=ValueError("parse error"),
        ):
            analyzer = DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config=llm_config
            )
            with pytest.raises(ValueError, match="parse error"):
                analyzer.forward("garbage")

    def test_metadata_fields(self, mock_client, llm_config):
        parsed = _parsed_result(n_instruments=1)

        with patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.parse_instrument_markdown",
            return_value=parsed,
        ), patch(
            "paper_data_linking.linkers.general.deterministic_structure_analyzer.StructureValidatorPipeline"
        ) as MockPipeline:
            MockPipeline.return_value.run.return_value = _pipeline_result(parsed)

            analyzer = DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config=llm_config
            )
            result = analyzer.forward("md")

        meta = result.metadata
        assert "method" in meta
        assert "parser_instruments_count" in meta
        assert "validator_issues_found" in meta
        assert "validator_issues_fixed" in meta
        assert "validator_llm_calls" in meta
        assert "validator_all_skipped" in meta
        assert "instruments_count" in meta
        assert "total_data_periods" in meta

    def test_requires_llm_config(self, mock_client):
        with pytest.raises(ValueError, match="llm_config is required"):
            DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config=None
            )

    def test_requires_pipeline_config_type(self, mock_client):
        with pytest.raises(ValueError, match="LLMPipelineConfig"):
            DeterministicStructureAnalyzer(
                llm_client=mock_client, llm_config={"not": "right"}
            )
