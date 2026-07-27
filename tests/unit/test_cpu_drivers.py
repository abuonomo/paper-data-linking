"""Idempotent fan-out drivers for the CPU regime (skip-if-done)."""

from datetime import datetime
import pytz
import pytest
from unittest.mock import patch

from django.contrib.postgres.fields.ranges import DateTimeTZRange
from vso_query_builder import tasks

pytestmark = pytest.mark.django_db


def _du(pa, inst, y):
    from vso_query_builder.models import DatasetUsage
    win = DateTimeTZRange(datetime(y, 1, 1, tzinfo=pytz.UTC),
                          datetime(y, 1, 2, tzinfo=pytz.UTC), bounds="[]")
    return DatasetUsage.objects.create(
        paper=pa.paper, instrument=inst, paper_analysis=pa, observation_window=win)


@patch("vso_query_builder.tasks.group")
def test_submit_batch_analysis_skips_already_analyzed(
        mock_group, observatory_factory, instrument_factory, paper_analysis_factory):
    from vso_query_builder.models import DatasetUsageAnalysis
    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    pa = paper_analysis_factory(configuration_name="cfg")
    du_done = _du(pa, inst, 2003)
    _du(pa, inst, 2004)  # not analyzed
    DatasetUsageAnalysis.objects.create(
        dataset_usage=du_done, python_snippet="x", analyzer_outputs={},
        is_valid_syntax=True)

    res = tasks.submit_batch_analysis(configuration_name="cfg", only_missing=True)
    assert res["submitted"] == 1  # only the un-analyzed DU

    res_all = tasks.submit_batch_analysis(configuration_name="cfg", only_missing=False)
    assert res_all["submitted"] == 2  # force re-run covers both


@patch("vso_query_builder.tasks.group")
def test_submit_batch_extraction_skips_papers_with_text_or_no_pdf(mock_group, paper_factory):
    from django.core.files.base import ContentFile
    with_pdf_no_text = paper_factory(bibcode="2026a", full_text="")
    with_pdf_no_text.pdf.save("a.pdf", ContentFile(b"%PDF-1.4"), save=True)
    with_pdf_and_text = paper_factory(bibcode="2026b", full_text="already extracted")
    with_pdf_and_text.pdf.save("b.pdf", ContentFile(b"%PDF-1.4"), save=True)
    paper_factory(bibcode="2026c", full_text="")  # no PDF -> excluded

    res = tasks.submit_batch_extraction(only_missing=True)
    assert res["submitted"] == 1  # only the pdf-present, text-missing paper


@patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
@patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
def test_analyze_skips_execution_when_disabled(
        mock_gen, mock_reg, observatory_factory, instrument_factory, paper_analysis_factory):
    """run_execution=False keeps snippet + syntax but skips the live Fido execution."""
    from unittest.mock import MagicMock
    from vso_query_builder.tasks import analyze_dataset_usage
    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    pa = paper_analysis_factory(configuration_name="cfg")
    du = _du(pa, inst, 2003)
    mock_gen.return_value.generate_snippet.return_value = "query = 1"
    syntax = MagicMock()
    syntax.return_value.analyze_snippet.return_value = {"is_valid": True}
    execm = MagicMock()
    mock_reg.get_available_analyzers_for_data_source.return_value = {
        "QuerySyntax": syntax, "QueryExecution": execm}

    analyze_dataset_usage(str(du.id), run_execution=False)
    syntax.return_value.analyze_snippet.assert_called_once()
    execm.return_value.analyze_snippet.assert_not_called()
