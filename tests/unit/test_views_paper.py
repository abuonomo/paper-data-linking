"""Tests for paper-related views."""
import pytest
import uuid
from datetime import datetime
from django.urls import reverse
from psycopg2.extras import DateTimeTZRange
import pytz


@pytest.fixture
def paper_with_usages(vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    """Create a paper with analysis and dataset usages."""
    from vso_query_builder.models import DatasetUsage, SupportQuote

    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    pa = paper_analysis_factory()
    paper = pa.paper

    start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
    du = DatasetUsage.objects.create(
        paper=paper,
        instrument=inst,
        paper_analysis=pa,
        observation_window=DateTimeTZRange(start, end, bounds="[]"),
        validation_status="pending",
    )

    quote = SupportQuote.objects.create(
        paper_analysis=pa,
        quote="Observed with LASCO",
        instrument="LASCO",
        parameter="Period 1:time",
        page_number=1,
        y_coord=100.0,
    )
    du.supporting_quotes.add(quote)

    # Queue-stats views read the precomputed Paper usage rollups (beat-refreshed
    # in production) — mirror that data path here.
    from vso_query_builder.management.commands.refresh_paper_usage_stats import (
        refresh_paper_usage_stats)
    refresh_paper_usage_stats()

    return {
        "paper": paper,
        "paper_analysis": pa,
        "dataset_usage": du,
        "quote": quote,
        "observatory": obs,
        "instrument": inst,
    }


@pytest.mark.django_db
class TestPaperDetailView:

    def test_returns_paper_by_uuid(self, client, paper_factory):
        paper = paper_factory()
        url = reverse("paper_detail", kwargs={"pk": paper.id})
        response = client.get(url)
        assert response.status_code == 200
        assert response.data["id"] == str(paper.id)

    def test_404_for_nonexistent(self, client):
        url = reverse("paper_detail", kwargs={"pk": uuid.uuid4()})
        response = client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestListPapersView:

    def test_returns_papers(self, client, paper_factory):
        paper_factory()
        url = reverse("list_papers")
        response = client.get(url)
        assert response.status_code == 200

    def test_search_by_bibcode(self, client, paper_factory):
        paper = paper_factory(bibcode="2003ApJ...595L..97S")
        url = reverse("list_papers")
        response = client.get(url, {"search": "2003ApJ"})
        assert response.status_code == 200

    def test_filter_by_tags(self, client, paper_factory):
        paper = paper_factory(tags=["solar_wind"])
        url = reverse("list_papers")
        response = client.get(url, {"tags": "solar_wind"})
        assert response.status_code == 200


@pytest.mark.django_db
class TestOnePaperAnalysisView:

    def test_returns_analyses(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-analysis", kwargs={"paper_id": paper.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) >= 1

    def test_404_for_nonexistent_paper(self, api_client):
        url = reverse("paper-analysis", kwargs={"paper_id": uuid.uuid4()})
        response = api_client.get(url)
        assert response.status_code == 404

    def test_requires_auth(self, client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-analysis", kwargs={"paper_id": paper.id})
        response = client.get(url)
        assert response.status_code == 401


@pytest.mark.django_db
class TestPaperDatasetUsagesView:

    def test_returns_usages_for_paper(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-dataset-usages", kwargs={"paper_id": paper.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) >= 1

    def test_filters_by_validation_status(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-dataset-usages", kwargs={"paper_id": paper.id})
        response = api_client.get(url, {"validation_status": "pending"})
        assert response.status_code == 200


@pytest.mark.django_db
class TestPaperValidationStatsView:

    def test_returns_stats(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-validation-stats", kwargs={"paper_id": paper.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert "validation_stats" in response.data

    def test_404_for_nonexistent_paper(self, api_client):
        url = reverse("paper-validation-stats", kwargs={"paper_id": uuid.uuid4()})
        response = api_client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestPaperValidationOverviewView:

    def test_returns_overview(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("paper-validation-overview", kwargs={"paper_id": paper.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data) >= 1
        assert "analysis" in response.data[0]
        assert "dataset_usages" in response.data[0]
        assert "validation_stats" in response.data[0]

    def test_404_for_nonexistent_paper(self, api_client):
        url = reverse("paper-validation-overview", kwargs={"paper_id": uuid.uuid4()})
        response = api_client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestPaperValidationQueueView:

    def test_returns_queue(self, api_client, paper_with_usages):
        url = reverse("paper-validation-queue")
        response = api_client.get(url)
        assert response.status_code == 200

    def test_filters_by_status(self, api_client, paper_with_usages):
        url = reverse("paper-validation-queue")
        response = api_client.get(url, {"validation_status": "pending"})
        assert response.status_code == 200

    def test_requires_auth(self, client, paper_with_usages):
        url = reverse("paper-validation-queue")
        response = client.get(url)
        assert response.status_code == 401


@pytest.mark.django_db
class TestPaperValidationQueueStatsView:

    def test_returns_counts(self, api_client, paper_with_usages):
        url = reverse("paper-validation-queue-stats")
        response = api_client.get(url)
        assert response.status_code == 200
        assert "pending" in response.data
        assert "complete" in response.data


@pytest.mark.django_db
class TestNextPaperInQueueView:

    def test_returns_next_paper(self, api_client, paper_with_usages):
        paper = paper_with_usages["paper"]
        url = reverse("next-paper-in-queue", kwargs={"paper_id": paper.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert "next_paper" in response.data


@pytest.mark.django_db
class TestPaperTagsListView:

    def test_returns_tags(self, api_client, paper_factory):
        paper_factory(tags=["solar_wind", "cme"])
        paper_factory(tags=["solar_wind", "flare"])
        url = reverse("paper-tags-list")
        response = api_client.get(url)
        assert response.status_code == 200
        assert "solar_wind" in response.data
        assert "cme" in response.data
        assert "flare" in response.data
