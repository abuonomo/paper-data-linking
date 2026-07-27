"""Tests for quote_categorization.py."""
import pytest
from vso_query_builder.quote_categorization import (
    categorize_quote_from_parameter,
    create_categorized_quote_usage_links,
)
from vso_query_builder.models import QuoteCategory, QuoteUsageLink


class TestCategorizeQuoteFromParameter:

    def test_empty_string_returns_general(self):
        assert categorize_quote_from_parameter("") == QuoteCategory.GENERAL

    def test_none_returns_general(self):
        assert categorize_quote_from_parameter(None) == QuoteCategory.GENERAL

    def test_general_returns_instrument(self):
        assert categorize_quote_from_parameter("general") == QuoteCategory.INSTRUMENT

    def test_period_time_returns_time_range(self):
        assert categorize_quote_from_parameter("Period 1:time") == QuoteCategory.TIME_RANGE

    def test_period_wavelength_returns_wavelength(self):
        assert categorize_quote_from_parameter("Period 1:wavelength") == QuoteCategory.WAVELENGTH

    def test_period_physobs_returns_physical_observable(self):
        assert categorize_quote_from_parameter("Period 1:physobs") == QuoteCategory.PHYSICAL_OBSERVABLE

    def test_period_general_returns_time_range(self):
        # "Period N:general" maps to TIME_RANGE (legacy behavior for temporal period quotes)
        assert categorize_quote_from_parameter("Period 1:general") == QuoteCategory.TIME_RANGE

    def test_legacy_string_without_colon_returns_time_range(self):
        assert categorize_quote_from_parameter("some legacy value") == QuoteCategory.TIME_RANGE

    def test_case_insensitive(self):
        assert categorize_quote_from_parameter("GENERAL") == QuoteCategory.INSTRUMENT
        assert categorize_quote_from_parameter("Period 1:TIME") == QuoteCategory.TIME_RANGE


@pytest.mark.django_db
class TestCreateCategorizedQuoteUsageLinks:

    def test_creates_links_with_correct_category(
        self, vso_datasource, observatory_factory, instrument_factory,
        paper_analysis_factory,
    ):
        from vso_query_builder.models import DatasetUsage, SupportQuote
        from psycopg2.extras import DateTimeTZRange
        import pytz
        from datetime import datetime

        obs = observatory_factory("SOHO")
        inst = instrument_factory(obs, "LASCO")
        pa = paper_analysis_factory()

        start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
        du = DatasetUsage.objects.create(
            paper=pa.paper, instrument=inst, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds='[]'),
        )
        quote = SupportQuote.objects.create(
            paper_analysis=pa, quote="Observed on Jan 1",
            instrument="LASCO", parameter="Period 1:time",
            page_number=1, y_coord=0.0,
        )

        count = create_categorized_quote_usage_links(du, [quote])

        assert count == 1
        link = QuoteUsageLink.objects.get()
        assert link.quote == quote
        assert link.dataset_usage == du
        assert link.support_category == QuoteCategory.TIME_RANGE

    def test_no_duplicates_on_second_call(
        self, vso_datasource, observatory_factory, instrument_factory,
        paper_analysis_factory,
    ):
        from vso_query_builder.models import DatasetUsage, SupportQuote
        from psycopg2.extras import DateTimeTZRange
        import pytz
        from datetime import datetime

        obs = observatory_factory("SOHO")
        inst = instrument_factory(obs, "LASCO")
        pa = paper_analysis_factory()

        start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
        du = DatasetUsage.objects.create(
            paper=pa.paper, instrument=inst, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds='[]'),
        )
        quote = SupportQuote.objects.create(
            paper_analysis=pa, quote="Observed on Jan 1",
            instrument="LASCO", parameter="general",
            page_number=1, y_coord=0.0,
        )

        create_categorized_quote_usage_links(du, [quote])
        create_categorized_quote_usage_links(du, [quote])

        assert QuoteUsageLink.objects.count() == 1
