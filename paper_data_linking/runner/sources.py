"""Where paper text comes from.

A source is anything with ``iter_papers()`` yielding ``PaperRecord``s. Two are built in
(JSONL files, a directory of .txt files). A site with its own text store writes a small
class and names it on the command line as ``package.module:factory``; see
``runner/example_source.py`` at the repository root.
"""

import gzip
import importlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class PaperRecord:
    bibcode: str
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)
    # Set by the scheduler, not by sources.
    step1: Optional[str] = None
    attempts: int = 0


@runtime_checkable
class PaperSource(Protocol):
    def iter_papers(self) -> Iterator[PaperRecord]:
        """Yield every paper once. Called once per run; order does not matter."""
        ...

    # Optional: ``iter_ids() -> Iterator[str]`` yielding the same papers' bibcodes
    # without their text. The runner counts them while it works, to report the percent
    # done and the time left. A source without it runs the same, with no total shown
    # unless ``--total`` is given.


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


class JsonlSource:
    """One JSON object per line with ``bibcode`` and ``text``; other keys are kept as
    ``meta``. ``path`` is a .jsonl / .jsonl.gz file or a directory of them."""

    def __init__(self, path: str, id_field: str = "bibcode", text_field: str = "text"):
        self.path = Path(path)
        self.id_field = id_field
        self.text_field = text_field
        if not self.path.exists():
            raise FileNotFoundError(f"Paper source not found: {self.path}")

    def _files(self):
        if self.path.is_dir():
            return sorted(p for p in self.path.iterdir() if p.name.endswith((".jsonl", ".jsonl.gz")))
        return [self.path]

    def _rows(self, warn: bool = True) -> Iterator[Dict[str, Any]]:
        for file in self._files():
            with _open_text(file) as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        for key in (self.id_field, self.text_field):
                            if key not in row:
                                raise KeyError(key)
                    except (ValueError, KeyError, TypeError) as e:
                        if warn:
                            logger.warning("Skipping %s line %d: %s", file.name, lineno, e)
                        continue
                    yield row

    def iter_papers(self) -> Iterator[PaperRecord]:
        for row in self._rows():
            meta = {k: v for k, v in row.items() if k not in (self.id_field, self.text_field)}
            yield PaperRecord(bibcode=str(row[self.id_field]), text=row[self.text_field] or "", meta=meta)

    def iter_ids(self) -> Iterator[str]:
        # The same lines iter_papers accepts, so the count matches what will be processed.
        for row in self._rows(warn=False):
            yield str(row[self.id_field])


class DirSource:
    """A directory of ``<bibcode>.txt`` files (searched recursively)."""

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.is_dir():
            raise NotADirectoryError(f"Paper source directory not found: {self.path}")

    def iter_papers(self) -> Iterator[PaperRecord]:
        for file in sorted(self.path.rglob("*.txt")):
            yield PaperRecord(bibcode=file.stem, text=file.read_text(encoding="utf-8", errors="replace"))

    def iter_ids(self) -> Iterator[str]:
        for file in sorted(self.path.rglob("*.txt")):
            yield file.stem


BUILTIN_SOURCES = {"jsonl": JsonlSource, "dir": DirSource}


def load_source(kind: str, path: Optional[str] = None, options: Optional[Dict[str, str]] = None) -> PaperSource:
    """Build a source. ``kind`` is a built-in name or ``package.module:factory``;
    the factory is called with ``path`` (when given) and ``options`` as keyword arguments."""
    options = options or {}
    if kind in BUILTIN_SOURCES:
        if not path:
            raise ValueError(f"--papers is required for the '{kind}' source")
        return BUILTIN_SOURCES[kind](path, **options)
    if ":" not in kind:
        raise ValueError(f"Unknown source '{kind}'. Use one of {sorted(BUILTIN_SOURCES)} or 'package.module:factory'.")
    module_name, attr = kind.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attr)
    source = factory(path, **options) if path else factory(**options)
    if not isinstance(source, PaperSource):
        raise TypeError(f"{kind} did not return an object with iter_papers()")
    return source
