"""Fixtures for the standalone runner tests: a small catalog snapshot, paper files and
in-process fake vLLM servers. Nothing here needs Django, a database or a GPU."""

import json
import os
import threading

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ADS_TOKEN", "test")

from paper_data_linking.linkers.general.snapshot_finder import snapshot_hash  # noqa: E402
from paper_data_linking.runner import fake_vllm  # noqa: E402


def _instrument(code, name, mission_code, mission_name, data_system, instrument_id, observatory_id):
    return {
        "instrument_code": code, "instrument_name": name, "mission_code": mission_code, "mission_name": mission_name,
        "data_system": data_system, "description": f"{name} description", "provider": None,
        "instrument_id": str(instrument_id), "observatory_id": observatory_id,
    }


def make_snapshot() -> dict:
    snapshot = {
        "schema": 1,
        "exported_at": "2026-11-14T00:00:00+00:00",
        "data_systems": ["vso", "cdaweb"],
        "unique_missions": [
            {"mission_code": "SOHO", "mission_name": "SOHO", "data_system": "vso", "description": "Solar and Heliospheric Observatory"},
            {"mission_code": "SDO", "mission_name": "SDO", "data_system": "vso", "description": None},
            {"mission_code": "SPASE://WIND", "mission_name": "Wind", "data_system": "cdaweb", "description": "Wind spacecraft"},
        ],
        "missions_by_data_system": {
            "vso": [
                {"mission_code": "SOHO", "mission_name": "SOHO", "data_system": "vso", "description": None},
                {"mission_code": "SDO", "mission_name": "SDO", "data_system": "vso", "description": None},
            ],
            "cdaweb": [{"mission_code": "SPASE://WIND", "mission_name": "Wind", "data_system": "cdaweb", "description": None}],
        },
        "instruments": [
            _instrument("EIT", "Extreme ultraviolet Imaging Telescope", "SOHO", "SOHO", "vso", 1, "obs-soho"),
            _instrument("LASCO", "Large Angle Spectrometric Coronagraph", "SOHO", "SOHO", "vso", 2, "obs-soho"),
            _instrument("AIA", "Atmospheric Imaging Assembly", "SDO", "SDO", "vso", 3, "obs-sdo"),
            _instrument("MFI", "Magnetic Field Investigation", "spase://Wind", "Wind", "cdaweb", 4, "obs-wind"),
        ],
    }
    snapshot["content_hash"] = snapshot_hash(snapshot)
    return snapshot


@pytest.fixture
def snapshot() -> dict:
    return make_snapshot()


@pytest.fixture
def catalog_path(tmp_path, snapshot) -> str:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(snapshot))
    return str(path)


PAPER_TEXTS = [
    "Body. INSTRUMENTS: EIT on board SOHO; AIA on board SDO",   # two grounded instruments
    "Body. INSTRUMENTS: MFI on board Wind",                      # one, in the other data system
    "Body FAKE_NO_INSTRUMENTS",                                  # nothing to ground
    "Body FAKE_EMPTY_ONCE. INSTRUMENTS: LASCO on board SOHO",    # step 1 needs one retry
]


def bibcode(i: int) -> str:
    return f"2020Test..{i:04d}....A"


@pytest.fixture
def write_papers(tmp_path):
    def _write(n: int, name: str = "papers.jsonl") -> str:
        path = tmp_path / name
        with open(path, "w") as f:
            for i in range(n):
                f.write(json.dumps({"bibcode": bibcode(i), "text": f"{PAPER_TEXTS[i % 4]} paper {i}", "journal": "Test"}) + "\n")
        return str(path)
    return _write


@pytest.fixture
def fake_server():
    """Start fake vLLM servers on free ports; yields a factory returning (url, server)."""
    servers = []

    def _start(**state_options):
        server = fake_vllm.serve("127.0.0.1", 0, **state_options)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}", server

    yield _start
    for server in servers:
        server.shutdown()
        server.server_close()
