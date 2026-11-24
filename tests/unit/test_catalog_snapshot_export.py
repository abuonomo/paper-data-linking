"""A catalog snapshot must give the grounder exactly what the database finder gives it."""
import json

import pytest
from django.core.management import call_command

from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder
from vso_query_builder.finders import DjangoInstrumentFinder
from vso_query_builder.models import DataSource


@pytest.fixture
def two_system_catalog(vso_datasource, observatory_factory, instrument_factory):
    cdaweb = DataSource.objects.create(slug="cdaweb", name="CDAWeb")
    soho = observatory_factory("SOHO")
    soho.description = "Solar and Heliospheric Observatory"
    soho.save()
    stereo = observatory_factory("STEREO_A", name="STEREO-A")
    wind = observatory_factory("spase://SMWG/Observatory/Wind", name="Wind", datasource=cdaweb)
    return {
        "lasco": instrument_factory(soho, "LASCO", full_name="Large Angle Spectrometric Coronagraph", description="White-light coronagraph"),
        "eit": instrument_factory(soho, "EIT", full_name="Extreme ultraviolet Imaging Telescope"),
        "secchi": instrument_factory(stereo, "SECCHI", full_name="Sun Earth Connection Coronal and Heliospheric Investigation"),
        "mfi": instrument_factory(wind, "MFI", full_name="Magnetic Field Investigation", description="Fluxgate magnetometer"),
    }


def _dump(items):
    return [item.model_dump() for item in items]


def _unordered(items):
    return sorted(_dump(items), key=lambda d: (d["data_system"], d["mission_code"], d["instrument_code"]))


@pytest.mark.django_db
def test_snapshot_finder_matches_the_database_finder(two_system_catalog, tmp_path):
    out = tmp_path / "catalog_snapshot.json"
    call_command("export_catalog_snapshot", out=str(out))
    snap = SnapshotInstrumentFinder(str(out))
    db = DjangoInstrumentFinder()

    assert snap.get_available_data_systems() == db.get_available_data_systems()
    assert _dump(snap.get_unique_missions()) == _dump(db.get_unique_missions())
    assert _dump(snap.catalog) == _dump(db.catalog)
    for data_system in db.get_available_data_systems():
        assert _dump(snap.get_missions_for_data_system(data_system)) == _dump(db.get_missions_for_data_system(data_system))
        assert _dump(snap.get_catalog_for_data_system(data_system)) == _dump(db.get_catalog_for_data_system(data_system))
        # One mission (the usual grounding query): same instruments in the same order.
        for names in (["SOHO"], ["STEREO-A"], ["Wind"], ["Nonexistent"]):
            assert _dump(snap.get_instruments_for_missions_and_data_system(names, data_system)) == _dump(
                db.get_instruments_for_missions_and_data_system(names, data_system)
            )
        # Several missions: the database promises no order, so only membership is compared.
        names = ["SOHO", "STEREO-A", "Wind"]
        assert _unordered(snap.get_instruments_for_missions_and_data_system(names, data_system)) == _unordered(
            db.get_instruments_for_missions_and_data_system(names, data_system)
        )
    for names in (["SOHO"], ["SOHO", "Wind"], []):
        assert _unordered(snap.get_instruments_for_missions(names)) == _unordered(db.get_instruments_for_missions(names))


@pytest.mark.django_db
def test_snapshot_records_database_ids(two_system_catalog, tmp_path):
    out = tmp_path / "catalog_snapshot.json"
    call_command("export_catalog_snapshot", out=str(out))
    mfi = two_system_catalog["mfi"]
    ids = SnapshotInstrumentFinder(str(out)).database_ids("cdaweb", "spase://SMWG/Observatory/Wind", "MFI")
    assert ids == {"instrument_id": str(mfi.id), "observatory_id": str(mfi.observatory_id)}
    assert len(json.loads(out.read_text())["instruments"]) == 4
