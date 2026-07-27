"""Tests for resolve_observatory in utils/resolver.py."""
import pytest
from vso_query_builder.utils.resolver import resolve_observatory


@pytest.mark.django_db
class TestResolveObservatory:

    @pytest.fixture(autouse=True)
    def setup_catalog(self, vso_datasource, observatory_factory, instrument_factory):
        self.obs_soho = observatory_factory("SOHO")
        self.obs_stereo = observatory_factory("STEREO_A")
        instrument_factory(self.obs_soho, "LASCO")
        instrument_factory(self.obs_soho, "EIT")
        instrument_factory(self.obs_stereo, "SECCHI")

    def test_explicit_source_returns_uppercased(self):
        result, reason = resolve_observatory("anything", explicit_source="soho")
        assert result == "SOHO"
        assert reason == "explicit"

    def test_unique_instrument_returns_observatory(self):
        result, reason = resolve_observatory("LASCO")
        assert result == "SOHO"
        assert reason == "lookup-unique"

    def test_unknown_instrument_returns_none(self):
        result, reason = resolve_observatory("NONEXISTENT")
        assert result is None
        assert reason == "lookup-none"

    def test_ambiguous_instrument_returns_none(self, instrument_factory):
        # Create a second LASCO on STEREO_A to make it ambiguous
        instrument_factory(self.obs_stereo, "LASCO")

        result, reason = resolve_observatory("LASCO")
        assert result is None
        assert reason == "ambiguous"

    def test_case_insensitive_lookup(self):
        result, reason = resolve_observatory("lasco")
        assert result == "SOHO"
        assert reason == "lookup-unique"

    def test_result_is_uppercased(self):
        result, _ = resolve_observatory("SECCHI")
        assert result == result.upper()
