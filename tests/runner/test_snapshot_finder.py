import json

import pytest

from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder, build_snapshot, snapshot_hash


def test_serves_every_method_the_grounder_calls(snapshot):
    finder = SnapshotInstrumentFinder(snapshot)
    assert finder.get_available_data_systems() == ["vso", "cdaweb"]
    assert [m.mission_name for m in finder.get_unique_missions()] == ["SOHO", "SDO", "Wind"]
    assert finder.get_unique_missions()[0].description == "Solar and Heliospheric Observatory"
    assert [m.mission_code for m in finder.get_missions_for_data_system("cdaweb")] == ["SPASE://WIND"]
    assert [e.instrument_code for e in finder.get_instruments_for_missions(["SOHO"])] == ["EIT", "LASCO"]
    assert [e.instrument_code for e in finder.get_instruments_for_missions_and_data_system(["SOHO", "Wind"], "cdaweb")] == ["MFI"]
    assert finder.get_instruments_for_missions([]) == []
    assert finder.get_missions_for_data_system("") == []
    assert finder.get_instrument_by_codes("soho", "lasco").instrument_code == "LASCO"
    assert finder.database_ids("cdaweb", "spase://Wind", "MFI") == {"instrument_id": "4", "observatory_id": "obs-wind"}


def test_rebuilding_from_a_finder_reproduces_the_snapshot(snapshot):
    finder = SnapshotInstrumentFinder(snapshot)
    rebuilt = build_snapshot(finder, id_lookup=lambda e: finder.database_ids(e.data_system, e.mission_code, e.instrument_code))
    assert rebuilt["instruments"] == snapshot["instruments"]
    assert rebuilt["unique_missions"] == snapshot["unique_missions"]
    assert SnapshotInstrumentFinder(rebuilt).version == rebuilt["content_hash"]


def test_recorded_query_order_is_served_back(snapshot):
    snapshot["instrument_order"] = {
        "by_data_system": {"vso": [2, 1, 0], "cdaweb": [3]},
        "by_mission": {"vso": {"SOHO": [1, 0], "SDO": [2]}, "cdaweb": {"Wind": [3]}},
    }
    snapshot["content_hash"] = snapshot_hash(snapshot)
    finder = SnapshotInstrumentFinder(snapshot)
    codes = lambda entries: [e.instrument_code for e in entries]
    assert codes(finder.get_catalog_for_data_system("vso")) == ["AIA", "LASCO", "EIT"]
    assert codes(finder.get_instruments_for_missions_and_data_system(["SOHO"], "vso")) == ["LASCO", "EIT"]
    assert codes(finder.get_instruments_for_missions_and_data_system(["SOHO", "SDO"], "vso")) == ["AIA", "LASCO", "EIT"]
    rebuilt = build_snapshot(finder)
    assert rebuilt["instrument_order"] == snapshot["instrument_order"]


def test_edited_snapshot_is_rejected(snapshot, tmp_path):
    snapshot["instruments"][0]["description"] = "tampered"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="content_hash"):
        SnapshotInstrumentFinder(str(path))
    snapshot["content_hash"] = snapshot_hash(snapshot)
    assert SnapshotInstrumentFinder(snapshot).catalog[0].description == "tampered"


def test_missing_snapshot_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="export_catalog_snapshot"):
        SnapshotInstrumentFinder(str(tmp_path / "absent.json"))
