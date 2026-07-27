"""Tests for serializers."""
import pytest
from datetime import datetime
from psycopg2.extras import DateTimeTZRange
import pytz


@pytest.fixture
def serializer_data(vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    """Create model instances for serializer testing."""
    from vso_query_builder.models import DatasetUsage, SupportQuote

    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO", full_name="Large Angle Spectrometric Coronagraph")
    pa = paper_analysis_factory()

    start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
    du = DatasetUsage.objects.create(
        paper=pa.paper,
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

    return {
        "observatory": obs,
        "instrument": inst,
        "paper_analysis": pa,
        "paper": pa.paper,
        "dataset_usage": du,
        "quote": quote,
    }


@pytest.mark.django_db
class TestPaperSerializer:

    def test_renders_expected_fields(self, serializer_data):
        from vso_query_builder.serializers import PaperSerializer
        data = PaperSerializer(serializer_data["paper"]).data
        assert "id" in data
        assert "bibcode" in data
        assert "created_at" in data

    def test_user_field_is_none_when_no_user(self, serializer_data):
        from vso_query_builder.serializers import PaperSerializer
        data = PaperSerializer(serializer_data["paper"]).data
        # paper_factory creates papers without a user
        assert data["user"] is None


@pytest.mark.django_db
class TestMinimalPaperSerializer:

    def test_renders_only_id_and_bibcode(self, serializer_data):
        from vso_query_builder.serializers import MinimalPaperSerializer
        data = MinimalPaperSerializer(serializer_data["paper"]).data
        assert set(data.keys()) == {"id", "bibcode"}


@pytest.mark.django_db
class TestDatasetUsageListSerializer:

    def test_renders_expected_fields(self, serializer_data):
        from vso_query_builder.serializers import DatasetUsageListSerializer
        du = serializer_data["dataset_usage"]
        data = DatasetUsageListSerializer(du).data
        assert "id" in data
        assert "paper_bibcode" in data
        assert "instrument_name" in data
        assert "observatory_name" in data
        assert "start_time" in data
        assert "end_time" in data

    def test_start_end_times_are_iso(self, serializer_data):
        from vso_query_builder.serializers import DatasetUsageListSerializer
        du = serializer_data["dataset_usage"]
        data = DatasetUsageListSerializer(du).data
        assert data["start_time"] is not None
        assert "2003" in data["start_time"]


@pytest.mark.django_db
class TestDatasetUsageDetailSerializer:

    def test_includes_supporting_quotes(self, serializer_data):
        from vso_query_builder.serializers import DatasetUsageDetailSerializer
        du = serializer_data["dataset_usage"]
        data = DatasetUsageDetailSerializer(du).data
        assert "supporting_quotes" in data
        assert len(data["supporting_quotes"]) >= 1

    def test_includes_instrument_and_observatory(self, serializer_data):
        from vso_query_builder.serializers import DatasetUsageDetailSerializer
        du = serializer_data["dataset_usage"]
        data = DatasetUsageDetailSerializer(du).data
        assert "instrument" in data
        assert "observatory" in data

    def test_duration_hours(self, serializer_data):
        from vso_query_builder.serializers import DatasetUsageDetailSerializer
        du = serializer_data["dataset_usage"]
        data = DatasetUsageDetailSerializer(du).data
        assert "duration_hours" in data
        # 1 day = 24 hours
        assert data["duration_hours"] == pytest.approx(24.0, abs=1.0)


@pytest.mark.django_db
class TestPaperAnalysisSerializer:

    def test_renders_expected_fields(self, serializer_data):
        from vso_query_builder.serializers import PaperAnalysisSerializer
        pa = serializer_data["paper_analysis"]
        data = PaperAnalysisSerializer(pa).data
        assert "id" in data
        assert "paper_bibcode" in data
        assert "configuration_name" in data
        assert "instruments_details" in data


@pytest.mark.django_db
class TestPDFAnnotationsSerializer:

    def test_renders_annotations_structure(self, serializer_data):
        from vso_query_builder.serializers import PDFAnnotationsSerializer
        pa = serializer_data["paper_analysis"]
        data = PDFAnnotationsSerializer(pa).data
        assert "instrumentation_details" in data
        assert "paper_bibcode" in data
        assert "analysis_id" in data


@pytest.mark.django_db
class TestPublicDatasetUsageSerializer:

    def test_renders_public_fields(self, serializer_data):
        from vso_query_builder.serializers import PublicDatasetUsageSerializer
        du = serializer_data["dataset_usage"]
        data = PublicDatasetUsageSerializer(du).data
        assert "id" in data
        assert "validation_status" in data
        assert "instrument" in data
        assert "observatory" in data
        assert "start_time" in data
        assert "end_time" in data
