"""Template for a site-specific paper source.

The runner asks a source for (bibcode, text) records and nothing else, so plugging in
another text store means writing one class like this. Put the file on PYTHONPATH (in
the container: mount it under /opt/pdl) and name it on the command line:

    pdl-batch all --source example_source:make_source --source-option root=/mnt/fulltext

`make_source` receives --papers as its first argument when that flag is given, and
every --source-option KEY=VALUE as a keyword argument.
"""

from pathlib import Path
from typing import Iterator

from paper_data_linking.runner.sources import PaperRecord


class ExampleSource:
    """Reads <root>/<bibcode>/fulltext.txt. Replace the body of iter_papers with
    whatever reaches the text: a database cursor, an internal API, an object store."""

    def __init__(self, root: str):
        self.root = Path(root)

    def iter_papers(self) -> Iterator[PaperRecord]:
        # Yield each paper once. Order does not matter, and it is fine to yield papers
        # that were already processed: the runner skips anything it has a result for.
        for path in sorted(self.root.glob("*/fulltext.txt")):
            yield PaperRecord(
                bibcode=path.parent.name,
                text=path.read_text(encoding="utf-8", errors="replace"),
                # Anything in meta is copied into the result line unchanged.
                meta={"source_path": str(path)},
            )

    def iter_ids(self) -> Iterator[str]:
        # Optional. The same papers' bibcodes without their text, so the runner can count
        # them and report the percent done and the time left. Leave it out if listing the
        # papers is expensive, and pass --total instead (or go without a total).
        for path in sorted(self.root.glob("*/fulltext.txt")):
            yield path.parent.name


def make_source(root: str) -> ExampleSource:
    return ExampleSource(root)
