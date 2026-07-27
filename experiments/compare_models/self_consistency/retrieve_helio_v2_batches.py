#!/usr/bin/env python3
"""Poll and retrieve self-consistency batch results for test_set_helio_v2_2026_04_06.

Idempotent: safe to run multiple times. Skips already-retrieved batches.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from experiments.compare_models.self_consistency.batch_runner import (
    check_batch_status as _openai_check_status,
    retrieve_batch_results as _openai_retrieve,
    model_slug,
    RESULTS_BASE,
)
from paper_data_linking.clients.batch_client import BatchClient

_bedrock_client = BatchClient()


async def check_batch_status(batch_id: str, provider: str) -> dict:
    if provider == "bedrock":
        import os
        region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
        return _bedrock_client.check_status(batch_id, provider="bedrock", aws_region_name=region)
    return await _openai_check_status(batch_id, provider)


async def retrieve_batch_results(batch_id: str, provider: str, model: str, test_set: str,
                                 reasoning_effort: str = None) -> dict:
    if provider != "bedrock":
        return await _openai_retrieve(batch_id, provider, model, test_set)

    # Bedrock path — use BatchClient, then write to the same layout as OpenAI
    import os, json
    from datetime import datetime
    region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    results = _bedrock_client.retrieve_results(batch_id, provider="bedrock", aws_region_name=region)

    slug = model_slug(model)
    # Keep effort variants in separate result trees. Sample variants (seed42 /
    # seed43) intentionally merge into one slug; reasoning efforts must NOT — they
    # are distinct conditions. 'high' keeps the plain slug (matches the existing run).
    if reasoning_effort in ('low', 'medium'):
        slug = f"{slug}_{reasoning_effort}"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    # Group by (call_type, run) from recordId = "{call_type}|{case_id}|run{run}"
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in results:
        cid = r.get("custom_id", "")
        try:
            call_type, case_id, run_str = cid.split("|")
            run = int(run_str.replace("run", ""))
        except ValueError:
            continue
        grouped[(call_type, run)].append({
            "original_id": case_id,
            "call_type": call_type,
            "model_name": model,
            "created_at": datetime.now().isoformat(),
            "provider": provider,
            "prompt_tokens": r.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": r.get("usage", {}).get("completion_tokens", 0),
            "total_tokens": r.get("usage", {}).get("total_tokens", 0),
            "output_content": r.get("content", ""),
            "batch_id": batch_id,
            "custom_id": cid,
            "error": r.get("error"),
        })

    written = {}
    for (call_type, run), recs in grouped.items():
        out_dir = RESULTS_BASE / test_set / slug / call_type / f"run{run}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{slug}_batch_{timestamp}.jsonl"
        with open(out_file, 'w') as f:
            for rec in recs:
                f.write(json.dumps(rec) + '\n')
        written[(call_type, run)] = out_file
        print(f"  {call_type}/run{run}: {len(recs)} results -> {out_file}")

    return {"files": written, "total_results": sum(len(r) for r in grouped.values())}

TEST_SET = "test_set_helio_v2_2026_04_06"
MANIFEST_DIR = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'batches' / TEST_SET
MANIFEST_PATH = MANIFEST_DIR / '_manifest.jsonl'


def load_manifest() -> list[dict]:
    """Load manifest entries."""
    if not MANIFEST_PATH.exists():
        print(f"No manifest found at {MANIFEST_PATH}")
        sys.exit(1)
    entries = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def append_to_manifest(entry: dict):
    """Append a retrieval record to the manifest."""
    with open(MANIFEST_PATH, 'a') as f:
        f.write(json.dumps(entry) + '\n')


async def run():
    manifest = load_manifest()

    # Deduplicate: for each (call_type, model, sample_variant), take the latest entry.
    # Legacy entries without sample_variant are treated as 'sampled_100_seed42'.
    latest = {}
    for entry in manifest:
        key = (
            entry.get('call_type'),
            entry.get('model'),
            entry.get('sample_variant', 'sampled_100_seed42'),
        )
        latest[key] = entry

    total = len(latest)
    already_retrieved = sum(1 for e in latest.values() if e.get('retrieved_at'))
    failed = sum(1 for e in latest.values() if e.get('status') == 'failed')

    print(f"Manifest: {total} batches ({already_retrieved} retrieved, {failed} failed)")
    print(f"{'='*80}")

    pending = []
    for key, entry in sorted(latest.items()):
        call_type, model, variant = key
        model_key = entry.get('model_key', '?')
        batch_id = entry.get('batch_id')
        variant_tag = f" [{variant}]" if variant != 'sampled_100_seed42' else ''

        if entry.get('retrieved_at'):
            print(f"  {call_type:30s} × {model_key:20s}{variant_tag} RETRIEVED")
            continue
        if entry.get('status') == 'failed' and not batch_id:
            print(f"  {call_type:30s} × {model_key:20s}{variant_tag} FAILED (no batch_id)")
            continue

        provider = entry.get('provider', 'openai')
        status = await check_batch_status(batch_id, provider)
        print(f"  {call_type:30s} × {model_key:20s} {status['status']:15s} "
              f"({status['completed']}/{status['total']} done, {status['failed']} failed)")

        if status['status'] == 'completed':
            print(f"    Retrieving results...")
            results = await retrieve_batch_results(batch_id, provider, model, TEST_SET,
                                                   reasoning_effort=entry.get('reasoning_effort'))
            print(f"    Retrieved {results['total_results']} results")

            # Mark as retrieved in manifest
            retrieval_entry = {
                **entry,
                'retrieved_at': datetime.now().isoformat(),
                'total_results': results['total_results'],
            }
            append_to_manifest(retrieval_entry)
        elif status['status'] in ('validating', 'in_progress', 'finalizing'):
            pending.append((call_type, model_key, batch_id, status['status']))
        elif status['status'] in ('failed', 'expired', 'cancelled'):
            print(f"    Batch {status['status']}.")
        else:
            pending.append((call_type, model_key, batch_id, status['status']))

    if pending:
        print(f"\n{len(pending)} batches still pending:")
        for ct, mk, bid, st in pending:
            print(f"  {ct} × {mk}: {st} (batch_id={bid})")
        print("\nRe-run this script later to check again.")
    else:
        print("\nAll batches complete (or failed). Ready for Phase 4 analysis.")


def main():
    asyncio.run(run())


if __name__ == '__main__':
    main()
