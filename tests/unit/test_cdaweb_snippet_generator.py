"""Tests for CDAWeb snippet generator."""
import pytest
from unittest.mock import MagicMock, patch
from paper_data_linking.analyzers.cdaweb_snippet_generator import CDAWebDatasetUsageSnippetGenerator
from paper_data_linking.analyzers.snippet_generator_registry import DataSourceSnippetGeneratorRegistry


class TestCDAWebSnippetGeneratorRegistration:

    def test_registered_in_registry(self):
        info = DataSourceSnippetGeneratorRegistry.get_info("cdaweb")
        assert info is not None
        assert info.class_ref is CDAWebDatasetUsageSnippetGenerator

    def test_data_sources(self):
        info = DataSourceSnippetGeneratorRegistry.get_info("cdaweb")
        assert "cdaweb" in info.data_sources


class TestGetImports:

    def test_returns_sunpy_import(self):
        gen = CDAWebDatasetUsageSnippetGenerator()
        imports = gen._get_imports()
        assert "sunpy" in imports
        assert "Fido" in imports
        assert "attrs" in imports


class TestExtractParameters:

    @pytest.fixture
    def mock_usage(self):
        """Create a mock DatasetUsage with the attributes the generator reads."""
        from psycopg2.extras import DateTimeTZRange
        from datetime import datetime
        import pytz

        usage = MagicMock()
        usage.instrument.short_name = "MAG"
        usage.instrument.observatory.short_name = "ACE"
        usage.instrument.observatory.datasource.slug = "cdaweb"
        usage.observation_window = DateTimeTZRange(
            datetime(2003, 1, 1, tzinfo=pytz.UTC),
            datetime(2003, 1, 15, tzinfo=pytz.UTC),
            bounds="[]",
        )
        usage.extra_params = {}
        return usage

    def test_extracts_instrument_id(self, mock_usage):
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["instrument_id"] == "MAG"

    def test_extracts_observatory(self, mock_usage):
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["observatory_name"] == "ACE"

    def test_extracts_dates(self, mock_usage):
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["start_date"] == "2003/01/01"
        assert params["end_date"] == "2003/01/15"
        assert params["start_date_iso"] == "2003-01-01"
        assert params["end_date_iso"] == "2003-01-15"

    def test_same_day_range_extends_end(self, mock_usage):
        """When start == end, end_date should be extended by 1 day."""
        from psycopg2.extras import DateTimeTZRange
        from datetime import datetime
        import pytz

        mock_usage.observation_window = DateTimeTZRange(
            datetime(2003, 1, 1, tzinfo=pytz.UTC),
            datetime(2003, 1, 1, tzinfo=pytz.UTC),
            bounds="[]",
        )
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["end_date_iso"] == "2003-01-02"

    def test_cadences_extracted_from_extra_params(self, mock_usage):
        mock_usage.extra_params = {"cadence": {"cadences": ["PT1H"]}}
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["cadences"] == ["PT1H"]

    def test_no_cadences_when_missing(self, mock_usage):
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = gen._extract_parameters(mock_usage)
        assert params["cadences"] is None


class TestBuildSunpyScripts:

    def test_builds_script_for_single_dataset(self):
        gen = CDAWebDatasetUsageSnippetGenerator()
        datasets = [{"product_key": "AC_H0_MFI", "name": "ACE MFI 16-sec data"}]
        params = {
            "instrument_id": "MAG",
            "observatory_name": "ACE",
            "start_date": "2003/01/01",
            "end_date": "2003/01/15",
        }
        script = gen._build_sunpy_scripts(datasets, params)
        assert "AC_H0_MFI" in script
        assert "Fido.search" in script
        assert "a.cdaweb.Dataset" in script
        assert "a.Time" in script

    def test_builds_script_for_multiple_datasets(self):
        gen = CDAWebDatasetUsageSnippetGenerator()
        datasets = [
            {"product_key": "AC_H0_MFI", "name": "ACE MFI 16-sec"},
            {"product_key": "AC_H1_MFI", "name": "ACE MFI 4-min"},
        ]
        params = {
            "instrument_id": "MAG",
            "observatory_name": "ACE",
            "start_date": "2003/01/01",
            "end_date": "2003/01/15",
        }
        script = gen._build_sunpy_scripts(datasets, params)
        assert "dataset_1" in script
        assert "dataset_2" in script
        assert "AC_H0_MFI" in script
        assert "AC_H1_MFI" in script

    def test_includes_comment_with_instrument_and_time(self):
        gen = CDAWebDatasetUsageSnippetGenerator()
        datasets = [{"product_key": "AC_H0_MFI", "name": "ACE MFI"}]
        params = {
            "instrument_id": "MAG",
            "observatory_name": "ACE",
            "start_date": "2003/01/01",
            "end_date": "2003/01/15",
        }
        script = gen._build_sunpy_scripts(datasets, params)
        assert "MAG" in script
        assert "ACE" in script
        assert "2003/01/01" in script


class TestBuildNoDatasetsFoundSnippet:

    def test_includes_instrument_info(self):
        gen = CDAWebDatasetUsageSnippetGenerator()
        params = {
            "instrument_id": "MAG",
            "observatory_name": "ACE",
            "start_date": "2003/01/01",
            "end_date": "2003/01/15",
        }
        snippet = gen._build_no_datasets_found_snippet(params)
        assert "No CDAWeb datasets found" in snippet
        assert "MAG" in snippet
        assert "ACE" in snippet


class TestGenerateSnippet:

    @pytest.fixture
    def mock_usage(self):
        from psycopg2.extras import DateTimeTZRange
        from datetime import datetime
        import pytz

        usage = MagicMock()
        usage.instrument.short_name = "MAG"
        usage.instrument.observatory.short_name = "ACE"
        usage.instrument.observatory.datasource.slug = "cdaweb"
        usage.observation_window = DateTimeTZRange(
            datetime(2003, 1, 1, tzinfo=pytz.UTC),
            datetime(2003, 1, 15, tzinfo=pytz.UTC),
            bounds="[]",
        )
        usage.extra_params = {}
        return usage

    def test_wrong_datasource_returns_comment(self, mock_usage):
        mock_usage.instrument.observatory.datasource.slug = "vso"
        gen = CDAWebDatasetUsageSnippetGenerator()
        result = gen.generate_snippet(mock_usage)
        assert "Unsupported datasource" in result

    @patch.object(CDAWebDatasetUsageSnippetGenerator, "_discover_datasets_via_hdpws")
    def test_no_datasets_returns_not_found_snippet(self, mock_discover, mock_usage):
        mock_discover.return_value = []
        gen = CDAWebDatasetUsageSnippetGenerator()
        result = gen.generate_snippet(mock_usage)
        assert "No CDAWeb datasets found" in result

    @patch.object(CDAWebDatasetUsageSnippetGenerator, "_discover_datasets_via_hdpws")
    def test_with_datasets_returns_sunpy_script(self, mock_discover, mock_usage):
        mock_discover.return_value = [
            {"product_key": "AC_H0_MFI", "name": "ACE MFI 16-sec data"}
        ]
        gen = CDAWebDatasetUsageSnippetGenerator()
        result = gen.generate_snippet(mock_usage)
        assert "from sunpy.net import Fido" in result
        assert "AC_H0_MFI" in result

    @patch.object(CDAWebDatasetUsageSnippetGenerator, "_discover_datasets_via_hdpws")
    def test_exclude_imports(self, mock_discover, mock_usage):
        mock_discover.return_value = [
            {"product_key": "AC_H0_MFI", "name": "ACE MFI"}
        ]
        gen = CDAWebDatasetUsageSnippetGenerator()
        result = gen.generate_snippet(mock_usage, include_imports=False)
        assert "from sunpy" not in result
        assert "AC_H0_MFI" in result
