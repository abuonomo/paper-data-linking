"""Merge and deduplicate bibcode files.

Outputs JSONL with source provenance: {"bibcode": "...", "sources": ["helio_keywords", "SOHO"]}
Source names are derived from input filenames (strip _bibcodes.txt suffix).
"""

import argparse
import json
from pathlib import Path


def _source_name(filepath: Path) -> str:
    """Derive a source tag from a bibcode filename."""
    name = filepath.stem  # e.g. "SOHO_bibcodes" or "helio_keywords_bibcodes"
    if name.endswith("_bibcodes"):
        name = name[: -len("_bibcodes")]
    return name


def merge_bibcode_files(input_files: list[Path], output_file: Path) -> int:
    """Merge bibcode files into JSONL with source provenance tracking.

    Each output line: {"bibcode": "...", "sources": ["source1", "source2"]}
    """
    bibcode_sources: dict[str, set[str]] = {}

    for f in input_files:
        source = _source_name(f)
        for line in f.read_text().splitlines():
            bibcode = line.strip()
            if bibcode:
                bibcode_sources.setdefault(bibcode, set()).add(source)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as out:
        for bibcode in sorted(bibcode_sources):
            record = {
                "bibcode": bibcode,
                "sources": sorted(bibcode_sources[bibcode]),
            }
            out.write(json.dumps(record) + "\n")

    return len(bibcode_sources)


def main():
    parser = argparse.ArgumentParser(description="Merge and deduplicate bibcode files")
    parser.add_argument("files", nargs="+", type=Path, help="Input bibcode text files")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output JSONL file")
    args = parser.parse_args()

    count = merge_bibcode_files(args.files, args.output)
    print(f"Merged {len(args.files)} files -> {count} unique bibcodes -> {args.output}")


if __name__ == "__main__":
    main()
