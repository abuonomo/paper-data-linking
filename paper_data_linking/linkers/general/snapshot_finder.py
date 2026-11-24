# paper_data_linking/linkers/general/snapshot_finder.py
"""File-backed instrument finder for runs with no database.

A snapshot is the frozen output of another finder's own methods (in practice
``DjangoInstrumentFinder`` on prod, written by ``manage.py export_catalog_snapshot``).
Freezing the method results, rather than re-deriving them from raw rows, keeps the
prompt text and the numbered candidate lists the same as the source finder produced
when the snapshot was taken.

List order needs care. The database finder's queries carry no ORDER BY, so the order
of a numbered instrument list is whatever the query plan yields, and it differs
between queries. The snapshot therefore records the order the source returned for each
data system and for each single mission within it (the common grounding query). A
query for several missions at once is answered in the data system's recorded order,
which is deterministic here but not guaranteed to match the database.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from .catalogue_models import CatalogueEntry, Mission
from .finders import AbstractInstrumentFinder

SNAPSHOT_SCHEMA = 1
SNAPSHOT_ENV_VAR = "PDL_CATALOG_SNAPSHOT"
DEFAULT_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data_assets" / "catalog" / "catalog_snapshot.json"
)

_BODY_KEYS = ("data_systems", "unique_missions", "missions_by_data_system", "instruments", "instrument_order")
# Per-instrument keys that are not CatalogueEntry fields (database ids for scoring/import).
_ID_KEYS = ("instrument_id", "observatory_id")

IdLookup = Callable[[CatalogueEntry], Optional[Dict[str, str]]]


def snapshot_hash(snapshot: dict) -> str:
    """SHA-256 over the catalog content only, so re-exporting an unchanged catalog
    gives the same hash whatever the export time."""
    body = {k: snapshot[k] for k in _BODY_KEYS if k in snapshot}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _key(entry: CatalogueEntry) -> Tuple[str, str, Optional[str]]:
    return (entry.data_system, entry.mission_code, entry.instrument_code)


def build_snapshot(finder, id_lookup: Optional[IdLookup] = None) -> dict:
    """Freeze ``finder``'s method results into a JSON-serializable snapshot.

    ``id_lookup`` may return ``{"instrument_id": ..., "observatory_id": ...}`` for an
    entry; those ids let offline results be scored against database-keyed references.
    """
    data_systems = list(finder.get_available_data_systems())
    instruments = []
    for entry in finder.catalog:
        row = entry.model_dump()
        if id_lookup is not None:
            row.update(id_lookup(entry) or {})
        instruments.append(row)
    position = {_key(e): i for i, e in enumerate(finder.catalog)}
    missions_by_ds = {ds: finder.get_missions_for_data_system(ds) for ds in data_systems}
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_systems": data_systems,
        "unique_missions": [m.model_dump() for m in finder.get_unique_missions()],
        "missions_by_data_system": {ds: [m.model_dump() for m in missions] for ds, missions in missions_by_ds.items()},
        "instruments": instruments,
        # Positions in "instruments", in the order the source finder returned them.
        "instrument_order": {
            "by_data_system": {
                ds: [position[_key(e)] for e in finder.get_catalog_for_data_system(ds)] for ds in data_systems
            },
            "by_mission": {
                ds: {
                    m.mission_name: [
                        position[_key(e)]
                        for e in finder.get_instruments_for_missions_and_data_system([m.mission_name], ds)
                    ]
                    for m in missions
                }
                for ds, missions in missions_by_ds.items()
            },
        },
    }
    snapshot["content_hash"] = snapshot_hash(snapshot)
    return snapshot


class SnapshotInstrumentFinder(AbstractInstrumentFinder):
    """Serves the grounder from a catalog snapshot held in memory. Read-only and
    safe to share between threads."""

    def __init__(self, snapshot: Union[dict, str, Path, None] = None):
        if snapshot is None:
            snapshot = os.environ.get(SNAPSHOT_ENV_VAR) or DEFAULT_SNAPSHOT_PATH
        if not isinstance(snapshot, dict):
            path = Path(snapshot)
            if not path.exists():
                raise FileNotFoundError(
                    f"Catalog snapshot not found at {path}. Export one with "
                    f"`manage.py export_catalog_snapshot` and pass its path or set {SNAPSHOT_ENV_VAR}."
                )
            with open(path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        if snapshot.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError(
                f"Unsupported catalog snapshot schema {snapshot.get('schema')!r}; expected {SNAPSHOT_SCHEMA}"
            )
        expected = snapshot.get("content_hash")
        actual = snapshot_hash(snapshot)
        if expected and expected != actual:
            raise ValueError("Catalog snapshot content does not match its content_hash; the file was edited or truncated")

        self.version: str = actual
        self.exported_at: Optional[str] = snapshot.get("exported_at")
        self._data_systems: List[str] = list(snapshot["data_systems"])
        self._unique_missions = [Mission(**m) for m in snapshot["unique_missions"]]
        self._missions_by_ds = {
            ds: [Mission(**m) for m in missions]
            for ds, missions in snapshot["missions_by_data_system"].items()
        }
        self._catalog: List[CatalogueEntry] = []
        self._ids: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in snapshot["instruments"]:
            ids = {k: str(row[k]) for k in _ID_KEYS if row.get(k) is not None}
            entry = CatalogueEntry(**{k: v for k, v in row.items() if k not in _ID_KEYS})
            self._catalog.append(entry)
            if ids:
                self._ids[_key(entry)] = ids
        order = snapshot.get("instrument_order") or {}
        self._by_ds: Dict[str, List[CatalogueEntry]] = {
            ds: [self._catalog[i] for i in idx] for ds, idx in (order.get("by_data_system") or {}).items()
        }
        self._by_mission: Dict[Tuple[str, str], List[CatalogueEntry]] = {
            (ds, name): [self._catalog[i] for i in idx]
            for ds, missions in (order.get("by_mission") or {}).items()
            for name, idx in missions.items()
        }

    @property
    def catalog(self) -> List[CatalogueEntry]:
        return self._catalog

    def find_candidates(self, query_embedding: np.ndarray, top_k: int) -> Tuple[List[CatalogueEntry], List[float]]:
        raise NotImplementedError("Catalog snapshots carry no embeddings; grounding does not use them")

    def get_instrument_by_codes(self, mission_code: str, instrument_code: str) -> CatalogueEntry | None:
        mission_code, instrument_code = mission_code.upper(), instrument_code.upper()
        for entry in self._catalog:
            if entry.mission_code == mission_code and entry.instrument_code == instrument_code:
                return entry
        return None

    def get_unique_missions(self) -> List[Mission]:
        return self._unique_missions

    def get_instruments_for_missions(self, mission_names: List[str]) -> List[CatalogueEntry]:
        if not mission_names:
            return []
        names = set(mission_names)
        return [e for e in self._catalog if e.mission_name in names]

    def get_available_data_systems(self) -> List[str]:
        return self._data_systems

    def get_catalog_for_data_system(self, data_system: str) -> List[CatalogueEntry]:
        if not data_system:
            return []
        if data_system in self._by_ds:
            return self._by_ds[data_system]
        return [e for e in self._catalog if e.data_system == data_system]

    def get_missions_for_data_system(self, data_system: str) -> List[Mission]:
        if not data_system:
            return []
        return self._missions_by_ds.get(data_system, [])

    def get_instruments_for_missions_and_data_system(self, mission_names: List[str], data_system: str) -> List[CatalogueEntry]:
        if not mission_names or not data_system:
            return []
        names = set(mission_names)
        if len(names) == 1 and (data_system, mission_names[0]) in self._by_mission:
            return self._by_mission[(data_system, mission_names[0])]
        return [e for e in self.get_catalog_for_data_system(data_system) if e.mission_name in names]

    def database_ids(self, data_system: str, mission_code: str, instrument_code: str) -> Optional[Dict[str, str]]:
        """The source database's ids for an instrument, when the snapshot recorded them."""
        return self._ids.get((data_system, mission_code, instrument_code))
