"""Run state as append-only JSONL shards in the output directory.

    results/part-<worker>.jsonl    one line per finished paper (the deliverable)
    step1/part-<worker>.jsonl      step-1 answers, written as soon as they pass their checks
    failures/part-<worker>.jsonl   papers that will not be retried, with the reason
    calls/part-<worker>.jsonl[.gz] per-call log
    index/<kind>/part-<worker>.jsonl  which paper is where in results/, step1/ and failures/

Each worker process appends to its own part files, so there is no cross-process
locking. A paper is finished once its line is in results/ or failures/; a process
killed mid-write leaves at most one torn last line, which readers skip.

A result line carries a paper's whole output (tens of kilobytes), so finding out
which papers are finished by parsing results/ means reading the entire run. The
index holds one short line per record instead. It is only a cache: every index line
says how far into its shard it reaches, and whatever lies beyond that is read from
the shard itself, so a missing or short index costs time and never correctness.
"""

import gzip
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

RESULTS, STEP1, FAILURES, CALLS, INDEX = "results", "step1", "failures", "calls", "index"


def index_path(shard: Path) -> Path:
    return shard.parent.parent / INDEX / shard.parent.name / shard.name


def _entry(record: Dict[str, Any], start: int, end: int) -> Dict[str, Any]:
    """The index line for a record occupying bytes ``start``..``end`` of its shard."""
    entry = {"bibcode": record["bibcode"], "config": record.get("config"), "start": start, "end": end}
    if record.get("reason") is not None:
        entry["reason"] = record["reason"]
    return entry


def _dumps(record: Dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _open_append(path: Path):
    # A previous process may have died mid-line; start on a fresh line.
    torn = path.exists() and path.stat().st_size > 0 and not _ends_with_newline(path)
    f = open(path, "ab")
    if torn:
        f.write(b"\n")
        f.flush()
    return f


class ShardWriter:
    """Appends JSON lines to one file; safe to share between threads."""

    def __init__(self, directory: Path, label: str, compress: bool = False, fsync: bool = True, index: bool = False):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"part-{label}.jsonl{'.gz' if compress else ''}"
        self._lock = threading.Lock()
        self._fsync = fsync and not compress
        self._compress = compress
        self._unflushed = 0
        self._f = gzip.open(self.path, "ab") if compress else _open_append(self.path)
        self._index = None
        if index and not compress:
            self._size = self.path.stat().st_size
            self._index = self._open_index()

    def _open_index(self):
        """The index file, brought up to date with the shard. A process killed between
        writing a record and its index line leaves the index short, and a directory
        written before the index existed has none."""
        path = index_path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _, covered = _indexed(self.path)
        if covered > self._size:
            # It reaches past the end of the shard, so it describes some other file.
            covered = 0
        if covered == 0:
            path.unlink(missing_ok=True)
        f = _open_append(path)
        if covered < self._size:
            for entry in _scan(self.path, covered):
                f.write(_dumps(entry))
            # Says the shard is covered to here even when the tail held no usable record.
            f.write(_dumps({"end": self._size}))
            f.flush()
        return f

    def write(self, record: Dict[str, Any]) -> None:
        line = _dumps(record)
        with self._lock:
            self._f.write(line)
            if self._compress:
                # A sync flush keeps everything written so far readable if the process is killed.
                self._unflushed += 1
                if self._unflushed >= 200:
                    self._f.flush()
                    self._unflushed = 0
            else:
                self._f.flush()
                if self._fsync:
                    os.fsync(self._f.fileno())
            if self._index is not None:
                # After the record is on disk, so the index never names a record that is not there.
                start, self._size = self._size, self._size + len(line)
                if "bibcode" in record:
                    self._index.write(_dumps(_entry(record, start, self._size)))
                    self._index.flush()

    def close(self) -> None:
        with self._lock:
            self._f.close()
            if self._index is not None:
                self._index.close()


def _ends_with_newline(path: Path) -> bool:
    with open(path, "rb") as f:
        f.seek(-1, os.SEEK_END)
        return f.read(1) == b"\n"


def _read_jsonl(path: Path) -> Iterator[Any]:
    """Every parseable line of one file. Torn or truncated tails are skipped."""
    if path.name.endswith(".gz"):
        opener = lambda: gzip.open(path, "rt", encoding="utf-8")
    else:
        opener = lambda: open(path, "r", encoding="utf-8", errors="replace")
    try:
        with opener() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except (EOFError, OSError):
        # A gzip stream cut off by a kill: everything before the cut was yielded.
        return


def read_shards(out_dir: Path, kind: str) -> Iterator[Dict[str, Any]]:
    """Every parseable record of one kind. Torn or truncated tails are skipped."""
    directory = Path(out_dir) / kind
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.name.endswith((".jsonl", ".jsonl.gz")):
            yield from _read_jsonl(path)


def _scan(shard: Path, start: int = 0) -> Iterator[Dict[str, Any]]:
    """Index entries for a shard's records from byte ``start`` on, made by parsing them."""
    with open(shard, "rb") as f:
        f.seek(start)
        pos = start
        for raw in f:
            begin, pos = pos, pos + len(raw)
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if isinstance(record, dict) and "bibcode" in record:
                yield _entry(record, begin, pos)


def _indexed(shard: Path) -> Tuple[List[Dict[str, Any]], int]:
    """A shard's index entries and the byte offset up to which they cover it."""
    entries: List[Dict[str, Any]] = []
    covered = 0
    path = index_path(shard)
    if path.exists():
        for row in _read_jsonl(path):
            if not isinstance(row, dict) or not isinstance(row.get("end"), int):
                continue
            covered = max(covered, row["end"])
            if "bibcode" in row:
                entries.append(row)
    return entries, covered


def read_index(out_dir: Path, kind: str) -> Iterator[Dict[str, Any]]:
    """For every record of one kind: ``bibcode``, ``config``, ``reason`` (failures) and
    where it is (``path``, ``start``, ``end``). Records the index covers are not parsed;
    the rest of each shard is. Safe to call while a run is writing."""
    directory = Path(out_dir) / kind
    if not directory.is_dir():
        return
    for shard in sorted(directory.iterdir()):
        if not shard.name.endswith(".jsonl"):
            continue
        # Index first, size second: a record is on disk before its index line is written,
        # so a size read afterwards is never behind the index.
        entries, covered = _indexed(shard)
        size = shard.stat().st_size
        if covered > size:
            # It reaches past the end of the shard, so it describes some other file.
            entries, covered = [], 0
        for entry in entries:
            entry["path"] = shard
            yield entry
        if covered < size:
            for entry in _scan(shard, covered):
                entry["path"] = shard
                yield entry


class RunState:
    """What a previous run in this output directory already settled, for one config."""

    def __init__(self, out_dir: Path, config_name: str, retry_failed: bool = False):
        self.out_dir = Path(out_dir)
        self.config_name = config_name
        self.done: Set[str] = {e["bibcode"] for e in read_index(self.out_dir, RESULTS) if e.get("config") == config_name}
        self.failed: Set[str] = set()
        if not retry_failed:
            self.failed = {
                e["bibcode"] for e in read_index(self.out_dir, FAILURES) if e.get("config") == config_name
            } - self.done
        self._step1: Optional[Dict[str, Tuple[Path, int, int]]] = None

    def settled(self, bibcode: str) -> bool:
        return bibcode in self.done or bibcode in self.failed

    def step1_for(self, bibcode: str) -> Optional[str]:
        """A checkpointed step-1 answer for a paper that never reached results/."""
        if self._step1 is None:
            # Only where each unfinished paper's answer is; the text is read when asked for.
            self._step1 = {
                e["bibcode"]: (e["path"], e["start"], e["end"])
                for e in read_index(self.out_dir, STEP1)
                if e.get("config") == self.config_name and e["bibcode"] not in self.done
            }
        where = self._step1.get(bibcode)
        if where is None:
            return None
        path, start, end = where
        try:
            with open(path, "rb") as f:
                f.seek(start)
                return json.loads(f.read(end - start))["instruments_details"]
        except (OSError, ValueError, KeyError):
            return None  # step 1 simply runs again
