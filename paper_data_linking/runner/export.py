"""Turn a run's result shards into what may leave the machine.

Result lines contain paper-derived text (the step-1 form, quotes, comments). What can
be shared depends on each paper's license, so exporting is a separate, explicit step
with four levels:

    tuples     (bibcode, data system, mission, instrument, time window). No paper text.
    redacted   the normalized structure with quotes, comments and free-text "original"
               strings removed: instruments, windows and normalized parameter values.
    full       the result lines as written.
    du-tuples  rows keyed by the source database's ids, the format the existing
               scoring scripts read (needs a catalog snapshot that recorded ids).
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Set, TextIO

from dateutil import parser as date_parser

from .store import RESULTS, read_shards

LEVELS = ("tuples", "redacted", "full", "du-tuples")
_PERIOD_METADATA = {"period_name", "additional_comments", "time_range", "supporting_quotes"}


def iter_usage_tuples(normalized: Optional[dict]) -> Iterator[Dict[str, Any]]:
    """The (instrument, window) pairs a normalized result yields, by the same rules
    ``_upsert_dataset_usages_from_normalized`` applies when it creates DatasetUsages:
    a grounded instrument with a data system, and a period whose normalized time range
    parses and is not reversed. Duplicates within a paper collapse."""
    seen = set()
    for inst in (normalized or {}).get("instruments") or []:
        name_norm = (inst.get("name") or {}).get("normalized")
        if not isinstance(name_norm, dict):
            continue
        inst_code = name_norm.get("matched_instrument_code")
        mission_code = name_norm.get("matched_mission_code")
        data_system = name_norm.get("data_system")
        if not data_system or not inst_code:
            continue
        for period in inst.get("data_collection_periods") or []:
            tr = (period.get("time_range") or {}).get("normalized") or {}
            start_iso, end_iso = tr.get("start_datetime"), tr.get("end_datetime")
            if not start_iso or not end_iso:
                continue
            try:
                start = date_parser.isoparse(start_iso).astimezone(timezone.utc)
                end = date_parser.isoparse(end_iso).astimezone(timezone.utc)
            except Exception:
                continue
            if start > end:
                continue
            key = (data_system, mission_code, inst_code, start, end)
            if key in seen:
                continue
            seen.add(key)
            yield {
                "data_system": data_system, "mission_code": mission_code, "instrument_code": inst_code,
                "start": start, "end": end, "precision": tr.get("precision"), "is_approximate": tr.get("is_approximate"),
            }


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pg_range(start: datetime, end: datetime) -> str:
    """Postgres ``tstzrange::text`` for an inclusive UTC range, as the reference dumps print it."""
    def fmt(dt: datetime) -> str:
        text = dt.strftime("%Y-%m-%d %H:%M:%S")
        if dt.microsecond:
            text += f".{dt.microsecond:06d}".rstrip("0")
        return text + "+00"
    return f'["{fmt(start)}","{fmt(end)}"]'


# Codes, units, ISO datetimes and durations are short; anything longer is prose.
_MAX_VALUE_CHARS = 64


def _strip_free_text(value: Any) -> Any:
    """Blank ``original_text`` and any long string anywhere inside a normalized value."""
    if isinstance(value, dict):
        return {k: "" if k == "original_text" else _strip_free_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_free_text(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
        return ""
    return value


def redact_normalized(normalized: Optional[dict]) -> dict:
    """The normalized structure without quotes, comments, summaries or the free-text
    ``original`` strings; codes, windows and normalized parameter values are kept."""
    out = {"instruments": []}
    for inst in (normalized or {}).get("instruments") or []:
        periods = []
        for period in inst.get("data_collection_periods") or []:
            kept: Dict[str, Any] = {"period_name": None, "additional_comments": None, "supporting_quotes": None}
            for key, value in period.items():
                if key in ("period_name", "additional_comments", "supporting_quotes"):
                    continue
                if isinstance(value, dict) and "normalized" in value:
                    kept[key] = {"original": "", "normalized": _strip_free_text(value["normalized"])}
            periods.append(kept)
        name = inst.get("name") or {}
        out["instruments"].append({
            "name": {"original": "", "normalized": copy.deepcopy(name.get("normalized"))},
            "general_comments": None,
            "supporting_quotes": None,
            "data_collection_periods": periods,
        })
    return out


def load_allowlist(path: Optional[str]) -> Optional[Set[str]]:
    if not path:
        return None
    return {line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()}


def export(
    out_dir: str,
    level: str,
    stream: TextIO,
    config_name: Optional[str] = None,
    allowlist: Optional[Set[str]] = None,
    finder=None,
    paper_ids: Optional[Dict[str, str]] = None,
    config_label: Optional[str] = None,
) -> Dict[str, int]:
    """Write one JSON line per row to ``stream``. Returns counts."""
    if level not in LEVELS:
        raise ValueError(f"Unknown export level '{level}'; choose from {LEVELS}")
    if level == "du-tuples" and finder is None:
        raise ValueError("du-tuples needs a catalog snapshot with database ids")
    counts = {"papers": 0, "rows": 0, "skipped_not_allowed": 0, "skipped_no_ids": 0}
    seen: Set[str] = set()
    for result in read_shards(Path(out_dir), RESULTS):
        bibcode = result["bibcode"]
        if config_name and result.get("config") != config_name:
            continue
        if bibcode in seen:  # a paper finished twice across interrupted runs: first wins
            continue
        seen.add(bibcode)
        if allowlist is not None and bibcode not in allowlist:
            counts["skipped_not_allowed"] += 1
            continue
        counts["papers"] += 1
        normalized = result.get("normalized_instrument_details")
        if level == "full":
            rows = [result]
        elif level == "redacted":
            rows = [{"bibcode": bibcode, "config": result.get("config"), "versions": result.get("versions"),
                     "normalized_instrument_details": redact_normalized(normalized)}]
        elif level == "tuples":
            rows = [{"bibcode": bibcode, "data_system": t["data_system"], "mission_code": t["mission_code"],
                     "instrument_code": t["instrument_code"], "start": _iso(t["start"]), "end": _iso(t["end"]),
                     "precision": t["precision"], "is_approximate": t["is_approximate"]}
                    for t in iter_usage_tuples(normalized)]
        else:
            rows = []
            for t in iter_usage_tuples(normalized):
                ids = finder.database_ids(t["data_system"], t["mission_code"], t["instrument_code"])
                if not ids:
                    counts["skipped_no_ids"] += 1
                    continue
                rows.append({
                    "cfg": config_label or result.get("config"),
                    "paper_id": (paper_ids or {}).get(bibcode, bibcode),
                    "obs": ids["observatory_id"], "inst": ids["instrument_id"],
                    "window": _pg_range(t["start"], t["end"]),
                })
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        counts["rows"] += len(rows)
    return counts


def load_paper_ids(path: Optional[str]) -> Optional[Dict[str, str]]:
    """A bibcode -> paper id map from a JSON object written in either direction."""
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # Bibcodes are 19 characters starting with a year; ids are not.
    looks_like_bibcode = lambda s: len(s) == 19 and s[:4].isdigit()
    if data and not looks_like_bibcode(next(iter(data))):
        data = {v: k for k, v in data.items()}
    return data
