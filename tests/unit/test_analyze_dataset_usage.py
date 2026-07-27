"""Tests for analyze_dataset_usage and analyze_paper_dataset_usages tasks."""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from psycopg2.extras import DateTimeTZRange
import pytz


@pytest.mark.django_db
class TestAnalyzeDatasetUsage:

    @pytest.fixture
    def dataset_usage(self, vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
        from vso_query_builder.models import DatasetUsage

        obs = observatory_factory("SOHO")
        inst = instrument_factory(obs, "LASCO")
        pa = paper_analysis_factory()

        start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
        return DatasetUsage.objects.create(
            paper=pa.paper,
            instrument=inst,
            paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds="[]"),
        )

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_happy_path_creates_analysis(self, mock_gen_cls, mock_registry, dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "result = Fido.search(...)"
        mock_gen_cls.return_value = mock_gen

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_snippet.return_value = {
            "is_valid": True,
            "syntax_error": "",
        }
        mock_registry.get_available_analyzers_for_data_source.return_value = {
            "QuerySyntax": type(mock_analyzer),
        }
        # Make the class() call return the mock instance
        type(mock_analyzer).__call__ = lambda self: mock_analyzer
        mock_registry.get_available_analyzers_for_data_source.return_value = {
            "QuerySyntax": MagicMock(return_value=mock_analyzer),
        }

        result = analyze_dataset_usage(str(dataset_usage.id))

        assert "Completed" in result
        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=dataset_usage)
        assert analysis.python_snippet == "result = Fido.search(...)"
        assert analysis.is_valid_syntax is True

    def test_nonexistent_usage_returns_not_found(self):
        from vso_query_builder.tasks import analyze_dataset_usage

        fake_id = str(uuid.uuid4())
        result = analyze_dataset_usage(fake_id)
        assert "not found" in result

    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_unsupported_datasource_returns_skipped(self, mock_gen_cls, dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from paper_data_linking.analyzers.snippet_generator_registry import UnsupportedDataSourceError

        mock_gen = MagicMock()
        mock_gen.generate_snippet.side_effect = UnsupportedDataSourceError("Unknown source")
        mock_gen_cls.return_value = mock_gen

        result = analyze_dataset_usage(str(dataset_usage.id))
        assert "Skipped" in result

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_analyzer_failure_captured_in_results(self, mock_gen_cls, mock_registry, dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "result = Fido.search(...)"
        mock_gen_cls.return_value = mock_gen

        failing_analyzer = MagicMock()
        failing_analyzer.analyze_snippet.side_effect = RuntimeError("Boom")
        mock_registry.get_available_analyzers_for_data_source.return_value = {
            "QueryExecution": MagicMock(return_value=failing_analyzer),
        }

        result = analyze_dataset_usage(str(dataset_usage.id))
        assert "Completed" in result

        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=dataset_usage)
        assert "error" in analysis.analyzer_outputs["QueryExecution"]
        assert "Boom" in analysis.analyzer_outputs["QueryExecution"]["error"]

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_updates_existing_analysis(self, mock_gen_cls, mock_registry, dataset_usage):
        """Second call updates existing DatasetUsageAnalysis rather than creating a duplicate."""
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "snippet_v1"
        mock_gen_cls.return_value = mock_gen
        mock_registry.get_available_analyzers_for_data_source.return_value = {}

        analyze_dataset_usage(str(dataset_usage.id))
        assert DatasetUsageAnalysis.objects.count() == 1

        # Second run with updated snippet
        mock_gen.generate_snippet.return_value = "snippet_v2"
        analyze_dataset_usage(str(dataset_usage.id))

        assert DatasetUsageAnalysis.objects.count() == 1
        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=dataset_usage)
        assert analysis.python_snippet == "snippet_v2"

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_execution_results_saved(self, mock_gen_cls, mock_registry, dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "snippet"
        mock_gen_cls.return_value = mock_gen

        exec_analyzer = MagicMock()
        exec_analyzer.analyze_snippet.return_value = {
            "execution_successful": True,
            "execution_error": "",
            "total_results_found": 42,
        }
        syntax_analyzer = MagicMock()
        syntax_analyzer.analyze_snippet.return_value = {
            "is_valid": True,
            "syntax_error": "",
        }
        mock_registry.get_available_analyzers_for_data_source.return_value = {
            "QuerySyntax": MagicMock(return_value=syntax_analyzer),
            "QueryExecution": MagicMock(return_value=exec_analyzer),
        }

        analyze_dataset_usage(str(dataset_usage.id))

        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=dataset_usage)
        assert analysis.is_valid_syntax is True
        assert analysis.execution_successful is True
        assert analysis.total_results_found == 42

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_no_analyzers_still_creates_record(self, mock_gen_cls, mock_registry, dataset_usage):
        """Even with no registered analyzers, a DatasetUsageAnalysis with the snippet is created."""
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "snippet"
        mock_gen_cls.return_value = mock_gen
        mock_registry.get_available_analyzers_for_data_source.return_value = {}

        result = analyze_dataset_usage(str(dataset_usage.id))

        assert "Completed" in result
        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=dataset_usage)
        assert analysis.python_snippet == "snippet"
        assert analysis.is_valid_syntax is False
        assert analysis.execution_successful is False


@pytest.mark.django_db
class TestAnalyzePaperDatasetUsages:

    @pytest.fixture
    def paper_with_usages(self, vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
        from vso_query_builder.models import DatasetUsage

        obs = observatory_factory("SOHO")
        inst = instrument_factory(obs, "LASCO")
        pa = paper_analysis_factory()

        start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2003, 1, 2, tzinfo=pytz.UTC)

        du1 = DatasetUsage.objects.create(
            paper=pa.paper, instrument=inst, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds="[]"),
        )
        du2 = DatasetUsage.objects.create(
            paper=pa.paper, instrument=inst, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds="[]"),
        )
        return {"paper": pa.paper, "paper_analysis": pa, "usages": [du1, du2]}

    @patch("vso_query_builder.tasks.chord")
    @patch("vso_query_builder.tasks.group")
    @patch("vso_query_builder.tasks.analyze_dataset_usage")
    def test_dispatches_analyses_for_unanalyzed_usages(self, mock_analyze, mock_group, mock_chord, paper_with_usages):
        from vso_query_builder.tasks import analyze_paper_dataset_usages

        pa = paper_with_usages["paper_analysis"]
        result = analyze_paper_dataset_usages({
            "success": True,
            "paper_id": str(paper_with_usages["paper"].id),
            "paper_analysis_id": str(pa.id),
        })

        assert result["success"] is True
        assert result["action"] == "analyzed"
        assert result["total_usages"] == 2
        mock_chord.return_value.apply_async.assert_called_once()

    @patch("vso_query_builder.tasks.group")
    @patch("vso_query_builder.tasks.analyze_dataset_usage")
    def test_skips_when_previous_step_failed(self, mock_analyze, mock_group, paper_with_usages):
        from vso_query_builder.tasks import analyze_paper_dataset_usages

        result = analyze_paper_dataset_usages({
            "success": False,
            "paper_id": str(paper_with_usages["paper"].id),
            "error": "previous step failed",
        })

        assert result["success"] is False
        mock_group.assert_not_called()

    @patch("vso_query_builder.tasks.group")
    @patch("vso_query_builder.tasks.analyze_dataset_usage")
    def test_skips_already_analyzed_usages(self, mock_analyze, mock_group, paper_with_usages):
        from vso_query_builder.tasks import analyze_paper_dataset_usages
        from vso_query_builder.models import DatasetUsageAnalysis

        # Create analysis for one usage so it's already analyzed
        du1 = paper_with_usages["usages"][0]
        DatasetUsageAnalysis.objects.create(
            dataset_usage=du1,
            python_snippet="existing",
        )

        pa = paper_with_usages["paper_analysis"]
        result = analyze_paper_dataset_usages({
            "success": True,
            "paper_id": str(paper_with_usages["paper"].id),
            "paper_analysis_id": str(pa.id),
        })

        assert result["success"] is True
        assert result["total_usages"] == 1  # only 1 unanalyzed

    @patch("vso_query_builder.tasks.group")
    @patch("vso_query_builder.tasks.analyze_dataset_usage")
    def test_all_analyzed_returns_skipped(self, mock_analyze, mock_group, paper_with_usages):
        from vso_query_builder.tasks import analyze_paper_dataset_usages
        from vso_query_builder.models import DatasetUsageAnalysis

        for du in paper_with_usages["usages"]:
            DatasetUsageAnalysis.objects.create(
                dataset_usage=du,
                python_snippet="existing",
            )

        pa = paper_with_usages["paper_analysis"]
        result = analyze_paper_dataset_usages({
            "success": True,
            "paper_id": str(paper_with_usages["paper"].id),
            "paper_analysis_id": str(pa.id),
        })

        assert result["success"] is True
        assert result["action"] == "skipped"
