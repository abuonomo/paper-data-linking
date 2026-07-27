"""Deterministic tests for generic group-level grounding (catalog_source='custom').

These cover the logic that must hold regardless of the (stochastic, temperature-1.0)
LLM grounding decision:
  1. snippet generation bails honestly for custom rows (no broken stub),
  2. the finder surfaces a generic row as its own mission and as the sole match
     when that mission is chosen, without colliding with the specific member,
  3. the seed_generic_instruments command is idempotent and flags rows custom.
"""
import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
import pytz
from psycopg2.extras import DateTimeTZRange


@pytest.fixture
def cdaweb_datasource(db):
    from vso_query_builder.models import DataSource
    return DataSource.objects.get_or_create(
        slug="cdaweb", defaults={"name": "Coordinated Data Analysis Web"}
    )[0]


@pytest.mark.django_db
class TestCustomSnippetGenBranch:
    """A custom (group-level) instrument must skip standard snippet generation."""

    @pytest.fixture
    def custom_dataset_usage(self, cdaweb_datasource, paper_analysis_factory):
        from vso_query_builder.models import Observatory, Instrument, DatasetUsage, CatalogSource

        group_obs = Observatory.objects.create(
            datasource=cdaweb_datasource,
            short_name="spase://SMWG/Observatory/GOES",
            name="GOES",
        )
        generic = Instrument.objects.create(
            observatory=group_obs,
            short_name="spase://SMWG/Instrument/GOES/SEM",
            full_name="SEM (generic GOES)",
            catalog_source=CatalogSource.CUSTOM,
        )
        pa = paper_analysis_factory()
        start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2005, 1, 1, tzinfo=pytz.UTC)
        return DatasetUsage.objects.create(
            paper=pa.paper, instrument=generic, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds="[]"),
        )

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_custom_instrument_skips_standard_generation(self, mock_gen_cls, mock_registry, custom_dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        result = analyze_dataset_usage(str(custom_dataset_usage.id))

        # Standard generator + analyzer registry must NOT be touched.
        mock_gen_cls.assert_not_called()
        mock_registry.get_available_analyzers_for_data_source.assert_not_called()

        assert "Custom grounding" in result
        analysis = DatasetUsageAnalysis.objects.get(dataset_usage=custom_dataset_usage)
        assert analysis.analyzer_outputs == {"custom_grounding": True}
        assert analysis.is_valid_syntax is False
        assert analysis.execution_successful is False
        assert "Custom group-level grounding" in analysis.python_snippet
        assert "ObservatoryGroup" in analysis.python_snippet

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_custom_marker_is_idempotent(self, mock_gen_cls, mock_registry, custom_dataset_usage):
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsageAnalysis

        analyze_dataset_usage(str(custom_dataset_usage.id))
        analyze_dataset_usage(str(custom_dataset_usage.id))

        assert DatasetUsageAnalysis.objects.filter(dataset_usage=custom_dataset_usage).count() == 1

    @patch("vso_query_builder.tasks.DatasetUsageAnalyzerRegistry")
    @patch("vso_query_builder.tasks.DatasetUsageSnippetGenerator")
    def test_standard_instrument_still_generates(self, mock_gen_cls, mock_registry,
                                                 cdaweb_datasource, observatory_factory,
                                                 instrument_factory, paper_analysis_factory):
        """Control: a normal (standard) instrument still routes to the generator."""
        from vso_query_builder.tasks import analyze_dataset_usage
        from vso_query_builder.models import DatasetUsage

        mock_gen = MagicMock()
        mock_gen.generate_snippet.return_value = "result = Fido.search(...)"
        mock_gen_cls.return_value = mock_gen
        mock_registry.get_available_analyzers_for_data_source.return_value = {}

        obs = observatory_factory("spase://SMWG/Observatory/GOES/15", name="GOES-15", datasource=cdaweb_datasource)
        member = instrument_factory(obs, "spase://SMWG/Instrument/GOES/15/SEM")  # default catalog_source=standard
        pa = paper_analysis_factory()
        start = datetime(2013, 1, 1, tzinfo=pytz.UTC)
        end = datetime(2014, 1, 1, tzinfo=pytz.UTC)
        du = DatasetUsage.objects.create(
            paper=pa.paper, instrument=member, paper_analysis=pa,
            observation_window=DateTimeTZRange(start, end, bounds="[]"),
        )

        result = analyze_dataset_usage(str(du.id))
        mock_gen.generate_snippet.assert_called_once()
        assert "Completed" in result


@pytest.mark.django_db
class TestGenericRowFinderBehavior:
    """The generic row becomes its own mission and the sole match when chosen,
    without colliding with the specific numbered member."""

    @pytest.fixture
    def goes_catalog(self, cdaweb_datasource):
        from vso_query_builder.models import Observatory, Instrument, CatalogSource

        member_obs = Observatory.objects.create(
            datasource=cdaweb_datasource,
            short_name="spase://SMWG/Observatory/GOES/15", name="GOES-15",
        )
        member = Instrument.objects.create(
            observatory=member_obs,
            short_name="spase://SMWG/Instrument/GOES/15/SEM", full_name="SEM",
            catalog_source=CatalogSource.STANDARD,
        )
        group_obs = Observatory.objects.create(
            datasource=cdaweb_datasource,
            short_name="spase://SMWG/Observatory/GOES", name="GOES",
        )
        generic = Instrument.objects.create(
            observatory=group_obs,
            short_name="spase://SMWG/Instrument/GOES/SEM", full_name="SEM (generic GOES)",
            catalog_source=CatalogSource.CUSTOM,
        )
        return {"member": member, "generic": generic}

    def test_generic_is_its_own_mission_in_cdaweb_pool(self, goes_catalog):
        from vso_query_builder.finders import DjangoInstrumentFinder
        finder = DjangoInstrumentFinder()
        names = {m.mission_name for m in finder.get_missions_for_data_system("cdaweb")}
        assert "GOES" in names        # the generic group mission
        assert "GOES-15" in names     # the specific member mission

    def test_generic_mission_resolves_only_to_generic(self, goes_catalog):
        from vso_query_builder.finders import DjangoInstrumentFinder
        finder = DjangoInstrumentFinder()
        codes = {e.instrument_code for e in finder.get_instruments_for_missions(["GOES"])}
        assert codes == {"spase://SMWG/Instrument/GOES/SEM"}  # NOT the numbered member

    def test_member_mission_resolves_only_to_member(self, goes_catalog):
        from vso_query_builder.finders import DjangoInstrumentFinder
        finder = DjangoInstrumentFinder()
        codes = {e.instrument_code for e in finder.get_instruments_for_missions(["GOES-15"])}
        assert codes == {"spase://SMWG/Instrument/GOES/15/SEM"}  # NOT the generic

    def test_generic_is_in_cdaweb_pool(self, goes_catalog):
        from vso_query_builder.finders import DjangoInstrumentFinder
        finder = DjangoInstrumentFinder()
        codes = {e.instrument_code for e in finder.get_catalog_for_data_system("cdaweb")}
        assert "spase://SMWG/Instrument/GOES/SEM" in codes


@pytest.mark.django_db
class TestSeedGenericInstrumentsCommand:

    def test_seed_creates_flagged_rows_and_is_idempotent(self, cdaweb_datasource):
        from django.core.management import call_command
        from vso_query_builder.models import Instrument, Observatory, CatalogSource

        call_command("seed_generic_instruments")
        call_command("seed_generic_instruments")  # second run must not duplicate

        group_obs = Observatory.objects.get(short_name="spase://SMWG/Observatory/GOES")
        assert group_obs.name == "GOES"
        assert group_obs.datasource_id == "cdaweb"

        generics = Instrument.objects.filter(short_name="spase://SMWG/Instrument/GOES/SEM")
        assert generics.count() == 1
        gen = generics.get()
        assert gen.catalog_source == CatalogSource.CUSTOM
        assert gen.observatory == group_obs
