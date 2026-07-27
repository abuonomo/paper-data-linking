#!/usr/bin/env python3
"""Sample N cases from a call_type's LLM call dump, filtering to cases where
the production run produced a substantive (non-null) output. Excludes IDs
already present in an existing sample file so this can be used to "top up"
an existing sample with additional substantive cases.

Usage:
    sample_substantive_jsonl.py <src> <dst> <n> <seed> [--exclude <existing.jsonl>]

Example:
    python scripts/sample_substantive_jsonl.py \
        inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06.jsonl \
        inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06_substantive_100_seed43.jsonl \
        100 43 \
        --exclude inputs/test_set/cadence_normalization_test_set_helio_v2_2026_04_06_sampled_100_seed42.jsonl
"""

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Register handlers so try_parse / is_null_canonical have them available
import experiments.compare_models.handlers  # noqa: F401
from experiments.compare_models.self_consistency.analyze_helio_v2_report import (
    is_null_canonical,
    try_parse,
)


def _load_valid(path: Path):
    """Yield (record, raw_line) for every valid JSON line (no null bytes)."""
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or "\x00" in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield rec, line


def _infer_call_type(path: Path) -> str:
    """Extract call_type from filename, e.g.
    'cadence_normalization_test_set_helio_v2_2026_04_06.jsonl' -> 'cadence_normalization'"""
    name = path.stem
    for marker in ("_test_set_", "_helio_", "_sampled_", "_substantive_"):
        if marker in name:
            return name.split(marker)[0]
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    parser.add_argument("n", type=int)
    parser.add_argument("seed", type=int)
    parser.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        help="JSONL file whose 'id' entries should be excluded from the pool (can repeat)",
    )
    parser.add_argument(
        "--call-type",
        type=str,
        default=None,
        help="Override call_type (otherwise inferred from src filename)",
    )
    args = parser.parse_args()

    call_type = args.call_type or _infer_call_type(args.src)
    print(f"Call type: {call_type}")

    # Collect IDs to exclude
    excluded_ids = set()
    for exc_path in args.exclude:
        for rec, _ in _load_valid(exc_path):
            rid = rec.get("id") or rec.get("original_id")
            if rid:
                excluded_ids.add(rid)
        print(f"Excluded {len(excluded_ids)} IDs from {exc_path}")

    # Filter src to substantive, non-excluded cases
    substantive_lines = []
    total, filtered_null, filtered_parse, filtered_excluded = 0, 0, 0, 0
    for rec, raw in _load_valid(args.src):
        total += 1
        rid = rec.get("id") or rec.get("original_id")
        if rid and rid in excluded_ids:
            filtered_excluded += 1
            continue
        output = rec.get("output_content") or ""
        canonical, did_parse = try_parse(call_type, output)
        if not did_parse:
            filtered_parse += 1
            continue
        if is_null_canonical(call_type, canonical):
            filtered_null += 1
            continue
        substantive_lines.append(raw + "\n")

    print(
        f"Pool: {len(substantive_lines)} substantive "
        f"(from {total} total; {filtered_null} null, "
        f"{filtered_parse} parse-error, {filtered_excluded} excluded)"
    )

    if len(substantive_lines) < args.n:
        print(
            f"WARNING: requested {args.n} but only {len(substantive_lines)} "
            f"available; writing all of them."
        )

    random.Random(args.seed).shuffle(substantive_lines)
    sampled = substantive_lines[: args.n]

    args.dst.parent.mkdir(parents=True, exist_ok=True)
    with open(args.dst, "w") as f:
        f.writelines(sampled)
    print(f"Wrote {len(sampled)} cases to {args.dst}")


if __name__ == "__main__":
    main()
