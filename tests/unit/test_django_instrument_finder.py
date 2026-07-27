"""Tests for DjangoInstrumentFinder."""
import pytest
from vso_query_builder.finders import DjangoInstrumentFinder


@pytest.fixture
def populated_catalog(vso_datasource, observatory_factory, instrument_factory):
    """Create instruments for finder testing."""
    soho = observatory_factory("SOHO")
    stereo = observatory_factory("STEREO_A", name="STEREO-A")
    lasco = instrument_factory(soho, "LASCO", full_name="Large Angle Spectrometric Coronagraph")
    eit = instrument_factory(soho, "EIT", full_name="Extreme ultraviolet Imaging Telescope")
    secchi = instrument_factory(stereo, "SECCHI", full_name="Sun Earth Connection Coronal and Heliospheric Investigation")

    return {
        "soho": soho,
        "stereo": stereo,
        "lasco": lasco,
        "eit": eit,
        "secchi": secchi,
        "datasource": vso_datasource,
    }


@pytest.mark.django_db
class TestDjangoInstrumentFinderCatalog:

    def test_catalog_returns_all_instruments(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.catalog
        assert len(catalog) == 3
        codes = {entry.instrument_code for entry in catalog}
        assert "LASCO" in codes
        assert "EIT" in codes
        assert "SECCHI" in codes

    def test_catalog_entries_have_mission_info(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.catalog
        lasco = next(e for e in catalog if e.instrument_code == "LASCO")
        assert lasco.mission_code == "SOHO"
        assert lasco.data_system == "vso"


@pytest.mark.django_db
class TestGetInstrumentByCodes:

    def test_finds_existing_instrument(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        entry = finder.get_instrument_by_codes("SOHO", "LASCO")
        assert entry is not None
        assert entry.instrument_code == "LASCO"
        assert entry.mission_code == "SOHO"

    def test_returns_none_for_nonexistent(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        entry = finder.get_instrument_by_codes("SOHO", "NONEXISTENT")
        assert entry is None

    def test_case_insensitive_instrument_code(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        entry = finder.get_instrument_by_codes("SOHO", "lasco")
        assert entry is not None
        assert entry.instrument_code == "LASCO"


@pytest.mark.django_db
class TestGetUniqueMissions:

    def test_returns_distinct_missions(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        missions = finder.get_unique_missions()
        names = {m.mission_code for m in missions}
        assert "SOHO" in names
        assert "STEREO_A" in names
        assert len(missions) == 2


@pytest.mark.django_db
class TestGetAvailableDataSystems:

    def test_returns_datasource_slugs(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        systems = finder.get_available_data_systems()
        assert "vso" in systems


@pytest.mark.django_db
class TestGetCatalogForDataSystem:

    def test_filters_by_datasource(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.get_catalog_for_data_system("vso")
        assert len(catalog) == 3

    def test_empty_for_unknown_system(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.get_catalog_for_data_system("nonexistent")
        assert len(catalog) == 0

    def test_empty_for_falsy_system(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.get_catalog_for_data_system("")
        assert len(catalog) == 0


@pytest.mark.django_db
class TestGetMissionsForDataSystem:

    def test_returns_missions_for_datasource(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        missions = finder.get_missions_for_data_system("vso")
        codes = {m.mission_code for m in missions}
        assert "SOHO" in codes
        assert "STEREO_A" in codes

    def test_empty_for_falsy_system(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        missions = finder.get_missions_for_data_system("")
        assert len(missions) == 0


@pytest.mark.django_db
class TestGetInstrumentsForMissions:

    def test_filters_by_mission_names(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.get_instruments_for_missions(["SOHO"])
        codes = {e.instrument_code for e in catalog}
        assert "LASCO" in codes
        assert "EIT" in codes
        assert "SECCHI" not in codes

    def test_empty_for_empty_list(self, populated_catalog):
        finder = DjangoInstrumentFinder()
        catalog = finder.get_instruments_for_missions([])
        assert len(catalog) == 0
