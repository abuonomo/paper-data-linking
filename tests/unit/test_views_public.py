"""Tests for public (no-auth) API views."""
import pytest
from datetime import datetime
from django.urls import reverse
from psycopg2.extras import DateTimeTZRange
import pytz


@pytest.fixture
def validated_usage_data(vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    """Create a paper with approved dataset usages."""
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
        validation_status="approved",
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

    # The public views read the precomputed Paper usage rollups, which in
    # production are maintained by the beat-scheduled refresh — mirror that
    # data path here instead of leaving the counters at zero.
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


@pytest.fixture
def mission_only_data(vso_datasource, observatory_factory, paper_analysis_factory):
    """Create a paper with mission_only mention and no dataset usages."""
    from vso_query_builder.models import InstrumentMention

    obs = observatory_factory("STEREO_A", name="STEREO-A")
    pa = paper_analysis_factory()
    paper = pa.paper

    mention = InstrumentMention.objects.create(
        paper_analysis=pa,
        matched_observatory=obs,
        match_level=InstrumentMention.MATCH_LEVEL_MISSION_ONLY,
    )

    return {
        "paper": paper,
        "paper_analysis": pa,
        "mention": mention,
        "observatory": obs,
    }


@pytest.fixture
def unresolved_mentions_data(vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    """Create a paper with instrument_no_time and partial mentions."""
    from vso_query_builder.models import InstrumentMention

    obs = observatory_factory("SOHO")
    inst_lasco = instrument_factory(obs, "LASCO")
    inst_eit = instrument_factory(obs, "EIT")
    pa = paper_analysis_factory()

    InstrumentMention.objects.create(
        paper_analysis=pa,
        matched_instrument=inst_lasco,
        match_level=InstrumentMention.MATCH_LEVEL_INSTRUMENT_NO_TIME,
    )
    InstrumentMention.objects.create(
        paper_analysis=pa,
        matched_instrument=inst_eit,
        match_level=InstrumentMention.MATCH_LEVEL_PARTIAL,
    )

    return {
        "paper": pa.paper,
    }


@pytest.mark.django_db
class TestPublicPaperValidatedUsagesView:

    def test_returns_usages_for_bibcode(self, client, validated_usage_data):
        bibcode = validated_usage_data["paper"].bibcode
        url = reverse("public-paper-validated-usages", kwargs={"bibcode": bibcode})
        response = client.get(url)
        assert response.status_code == 200
        assert "paper" in response.data
        assert "usages" in response.data
        assert len(response.data["usages"]) >= 1

    def test_404_for_nonexistent_bibcode(self, client):
        url = reverse("public-paper-validated-usages", kwargs={"bibcode": "NONEXISTENT"})
        response = client.get(url)
        assert response.status_code == 404

    def test_include_unvalidated_param(self, client, validated_usage_data):
        bibcode = validated_usage_data["paper"].bibcode
        url = reverse("public-paper-validated-usages", kwargs={"bibcode": bibcode})
        response = client.get(url, {"include_unvalidated": "true"})
        assert response.status_code == 200

    def test_includes_mission_only_mentions(self, client, mission_only_data):
        bibcode = mission_only_data["paper"].bibcode
        url = reverse("public-paper-validated-usages", kwargs={"bibcode": bibcode})
        response = client.get(url)
        assert response.status_code == 200
        assert response.data["mission_mentions_count"] == 1
        assert response.data["mission_mentions"][0]["match_level"] == "mission_only"
        assert response.data["mission_mentions"][0]["observatory"]["short_name"] == "STEREO_A"

    def test_includes_instrument_no_time_and_partial_mentions(self, client, unresolved_mentions_data):
        bibcode = unresolved_mentions_data["paper"].bibcode
        url = reverse("public-paper-validated-usages", kwargs={"bibcode": bibcode})
        response = client.get(url)
        assert response.status_code == 200
        levels = {m["match_level"] for m in response.data["mission_mentions"]}
        assert "instrument_no_time" in levels
        assert "partial" in levels


@pytest.mark.django_db
class TestPublicValidatedPapersListView:

    def test_returns_validated_papers(self, client, validated_usage_data):
        url = reverse("public-validated-papers")
        response = client.get(url)
        assert response.status_code == 200
        # Paginated response
        results = response.data.get("results", response.data)
        assert len(results) >= 1

    def test_filters_by_missions(self, client, validated_usage_data):
        url = reverse("public-validated-papers")
        response = client.get(url, {"missions": "SOHO"})
        assert response.status_code == 200

    def test_filters_by_instruments(self, client, validated_usage_data):
        url = reverse("public-validated-papers")
        response = client.get(url, {"instruments": "LASCO"})
        assert response.status_code == 200

    def test_filters_by_date_range(self, client, validated_usage_data):
        url = reverse("public-validated-papers")
        response = client.get(url, {
            "start_date": "2003-01-01",
            "end_date": "2003-12-31",
        })
        assert response.status_code == 200

    def test_text_search(self, client, validated_usage_data):
        bibcode = validated_usage_data["paper"].bibcode
        url = reverse("public-validated-papers")
        response = client.get(url, {"q": bibcode[:10]})
        assert response.status_code == 200

    def test_mission_filter_includes_mission_only_papers(self, client, mission_only_data):
        url = reverse("public-validated-papers")
        response = client.get(url, {"missions": "STEREO_A"})
        assert response.status_code == 200
        results = response.data.get("results", response.data)
        paper = next((r for r in results if r["bibcode"] == mission_only_data["paper"].bibcode), None)
        assert paper is not None
        assert paper.get("mission_only_match_count", 0) >= 1
        assert paper.get("has_matching_dataset_usage") is False

    def test_mission_only_papers_not_shown_without_mission_filter(self, client, mission_only_data):
        url = reverse("public-validated-papers")
        response = client.get(url)
        assert response.status_code == 200
        results = response.data.get("results", response.data)
        assert all(r["bibcode"] != mission_only_data["paper"].bibcode for r in results)

    def test_mission_only_papers_hidden_when_validation_status_filter_set(self, client, mission_only_data):
        url = reverse("public-validated-papers")
        response = client.get(url, {"missions": "STEREO_A", "validation_status": "approved"})
        assert response.status_code == 200
        results = response.data.get("results", response.data)
        assert all(r["bibcode"] != mission_only_data["paper"].bibcode for r in results)


@pytest.mark.django_db
class TestPublicValidatedPapersCSVView:

    def test_returns_csv_stream(self, client, validated_usage_data):
        url = reverse("public-validated-papers-csv")
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"] == "text/csv"
        content = b"".join(response.streaming_content).decode()
        assert "Bibcode" in content

    def test_mission_filter_includes_mission_only_papers(self, client, mission_only_data):
        url = reverse("public-validated-papers-csv")
        response = client.get(url, {"missions": "STEREO_A"})
        assert response.status_code == 200
        content = b"".join(response.streaming_content).decode()
        assert mission_only_data["paper"].bibcode in content

    def test_validation_status_filter_excludes_mission_only_papers(self, client, mission_only_data):
        url = reverse("public-validated-papers-csv")
        response = client.get(url, {"missions": "STEREO_A", "validation_status": "approved"})
        assert response.status_code == 200
        content = b"".join(response.streaming_content).decode()
        assert mission_only_data["paper"].bibcode not in content


@pytest.mark.django_db
class TestPublicPapersFilterOptionsView:

    def test_returns_filter_options(self, client, validated_usage_data):
        url = reverse("public-papers-filter-options")
        response = client.get(url)
        assert response.status_code == 200
        assert "missions" in response.data or "missions_by_datasource" in response.data
        assert "date_range" in response.data

    def test_includes_mission_only_missions(self, client, mission_only_data):
        url = reverse("public-papers-filter-options")
        response = client.get(url)
        assert response.status_code == 200
        missions = response.data["missions_by_datasource"]["vso"]["missions"]
        mission = next((m for m in missions if m["short_name"] == "STEREO_A"), None)
        assert mission is not None
        assert mission["mission_only_paper_count"] >= 1


@pytest.mark.django_db
class TestUsageByMissionAPIView:

    def test_returns_mission_data(self, client, validated_usage_data):
        url = reverse("usage-by-mission")
        response = client.get(url)
        assert response.status_code == 200
        assert "dates" in response.data
        assert "missions" in response.data
        assert "data" in response.data


@pytest.mark.django_db
class TestMissionLaunchesView:

    def test_returns_json(self, client):
        url = reverse("mission-launches")
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestSolarEventsView:

    def test_returns_json(self, client):
        url = reverse("solar-events")
        response = client.get(url)
        assert response.status_code == 200
