"""Tests for check_and_* task idempotency and run_normalized_workflow_chain."""
import pytest
from unittest.mock import patch, MagicMock
from vso_query_builder.tasks import (
    check_and_extract_text,
    check_and_analyze_paper,
    check_and_structure_analysis,
    check_and_normalize,
    create_dataset_usages,
    run_normalized_workflow_chain,
)


@pytest.mark.django_db
class TestCheckAndExtractText:

    def test_skips_if_full_text_already_present(self, paper_factory):
        paper = paper_factory(full_text="Already extracted text")
        result = check_and_extract_text(paper.id)

        assert result["success"] is True
        assert result["action"] == "skipped"

    @patch("vso_query_builder.tasks.extract_paper_text_task", return_value=True)
    def test_extracts_if_no_text_and_pdf_exists(self, mock_extract, paper_factory):
        paper = paper_factory(full_text="")
        paper.pdf = "dummy.pdf"
        paper.save()

        result = check_and_extract_text(paper.id)

        assert result["action"] == "extracted"
        mock_extract.assert_called_once_with(paper.id)

    def test_skips_if_no_text_and_no_pdf(self, paper_factory):
        paper = paper_factory(full_text="")
        # pdf is blank by default
        result = check_and_extract_text(paper.id)

        assert result["success"] is True
        assert result["action"] == "skipped"


@pytest.mark.django_db
class TestCheckAndAnalyzePaper:

    def test_skips_if_completed_analysis_exists(self, paper_factory, paper_analysis_factory):
        paper = paper_factory()
        pa = paper_analysis_factory(paper=paper, status="completed")

        result = check_and_analyze_paper(
            {"success": True, "paper_id": str(paper.id)},
            paper.id,
            "standard",
        )

        assert result["success"] is True
        assert result["action"] == "skipped"
        assert result["paper_analysis_id"] == pa.id

    def test_propagates_failure_from_previous_step(self, paper_factory):
        paper = paper_factory()
        prev_result = {"success": False, "error": "text extraction failed"}

        result = check_and_analyze_paper(prev_result, paper.id, "standard")

        assert result["success"] is False
        assert result["error"] == "text extraction failed"

    def test_fails_if_no_text_available(self, paper_factory):
        paper = paper_factory(full_text="")

        result = check_and_analyze_paper(
            {"success": True}, paper.id, "standard"
        )

        assert result["success"] is False
        assert "No text available" in result["error"]


@pytest.mark.django_db
class TestCheckAndStructureAnalysis:

    def test_skips_if_structured_details_already_present(self, paper_analysis_factory):
        pa = paper_analysis_factory(
            structured_instruments_details={"instruments": []}
        )

        result = check_and_structure_analysis(
            {"success": True, "paper_analysis_id": pa.id},
            "standard",
        )

        assert result["success"] is True
        assert result["action"] == "skipped"

    def test_propagates_failure(self):
        result = check_and_structure_analysis(
            {"success": False, "error": "analysis failed"}, "standard"
        )
        assert result["success"] is False

    @patch("vso_query_builder.tasks.analyze_paper_instruments_structure")
    def test_runs_analysis_if_not_structured(self, mock_analyze, paper_analysis_factory):
        pa = paper_analysis_factory(structured_instruments_details=None)
        mock_analyze.return_value = {
            "success": True,
            "paper_analysis_id": str(pa.id),
        }

        result = check_and_structure_analysis(
            {"success": True, "paper_analysis_id": pa.id},
            "standard",
        )

        mock_analyze.assert_called_once_with(pa.id, "standard")


@pytest.mark.django_db
class TestCheckAndNormalize:

    def test_skips_if_normalized_details_already_present(self, paper_analysis_factory):
        pa = paper_analysis_factory(
            normalized_instrument_details={"instruments": []}
        )

        result = check_and_normalize(
            {"success": True, "paper_analysis_id": pa.id},
            "standard",
        )

        assert result["success"] is True
        assert result["action"] == "skipped"

    def test_propagates_failure(self):
        result = check_and_normalize(
            {"success": False, "error": "structure failed"}, "standard"
        )
        assert result["success"] is False


@pytest.mark.django_db
class TestCreateDatasetUsages:

    def test_propagates_failure_from_previous_step(self):
        result = create_dataset_usages(
            {"success": False, "error": "normalization failed"}
        )
        assert result["success"] is False

    def test_fails_if_no_normalized_data(self, paper_analysis_factory):
        pa = paper_analysis_factory(normalized_instrument_details=None)

        result = create_dataset_usages(
            {"success": True, "paper_analysis_id": pa.id}
        )

        assert result["success"] is False
        assert "No normalized data" in result["error"]

    def test_creates_usages_from_normalized_data(
        self, paper_analysis_factory, vso_datasource, observatory_factory, instrument_factory
    ):
        obs = observatory_factory("SOHO")
        instrument_factory(obs, "LASCO")

        pa = paper_analysis_factory(
            normalized_instrument_details={
                "instruments": [{
                    "name": {
                        "original": "LASCO",
                        "normalized": {
                            "matched_instrument_code": "LASCO",
                            "matched_mission_code": "SOHO",
                            "data_system": "vso",
                        },
                    },
                    "data_collection_periods": [{
                        "period_name": "Period 1",
                        "time_range": {
                            "normalized": {
                                "start_datetime": "2003-01-01T00:00:00Z",
                                "end_datetime": "2003-01-02T00:00:00Z",
                            }
                        },
                    }],
                }]
            }
        )

        result = create_dataset_usages(
            {"success": True, "paper_analysis_id": pa.id}
        )

        assert result["success"] is True
        assert result["dataset_usages_created"] == 1


@pytest.mark.django_db
class TestRunNormalizedWorkflowChain:

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_constructs_chain_and_applies(self, mock_config, mock_chain, paper_factory):
        paper = paper_factory()
        mock_config.return_value = MagicMock()
        mock_chain_instance = MagicMock()
        mock_chain_instance.apply_async.return_value = MagicMock(id="chain-123")
        mock_chain.return_value = mock_chain_instance

        result = run_normalized_workflow_chain(paper.id, "standard")

        assert result["success"] is True
        assert result["chain_id"] == "chain-123"
        mock_chain.assert_called_once()
        mock_chain_instance.apply_async.assert_called_once()

    def test_nonexistent_paper_returns_failure(self):
        import uuid
        result = run_normalized_workflow_chain(uuid.uuid4(), "standard")

        assert result["success"] is False
        assert "does not exist" in result["error"]
