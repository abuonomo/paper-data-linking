#!/usr/bin/env python3
"""Submit self-consistency batches for test_set_helio_v2_2026_04_06.

9 call types × 2 models = 18 batches.
Resumable: skips already-submitted batches from the manifest.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Compute repo root and add to path
REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from experiments.compare_models.self_consistency.batch_runner import (
    prepare_batch_file,
    submit_batch,
    estimate_batch_cost,
)

TEST_SET = "test_set_helio_v2_2026_04_06"

# Copied verbatim from self_consistency_experiments.ipynb cell 2
CALL_TYPE_CONFIG = {
    'instrument_validation': {
        'prompt': 'paper_data_linking/linkers/general/prompts/validation/system.xml',
        'handler': 'InstrumentValidationHandler',
    },
    'wavelength_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml',
        'handler': 'WavelengthNormalizationSimpleHandler',
    },
    'physobs_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml',
        'handler': 'PhysObsNormalizationFreeTextV2Handler',
    },
    'mission_selection': {
        'prompt': 'paper_data_linking/linkers/general/prompts/mission_selection/system.xml',
        'handler': 'MissionSelectionHandler',
    },
    'instrument_selection': {
        'prompt': 'paper_data_linking/linkers/general/prompts/instrument_selection/system.xml',
        'handler': 'InstrumentSelectionHandler',
    },
    'detector_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/detector_normalization/system.xml',
        'handler': 'DetectorNormalizationFreeTextV2Handler',
    },
    'time_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/time_normalization/system.xml',
        'handler': 'TimeNormalizationHandler',
    },
    'cadence_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/cadence_normalization/system.xml',
        'handler': 'CadenceNormalizationFreeTextHandler',
    },
    'mission_identification': {
        'prompt': 'paper_data_linking/linkers/general/prompts/mission_identification/system.xml',
        'handler': 'MissionIdentificationHandler',
    },
    'mission_validation': {
        'prompt': 'paper_data_linking/linkers/general/prompts/mission_validation/system.xml',
        'handler': 'MissionValidationHandler',
    },
}

MODELS = {
    'standard-gpt54': 'openai/gpt-5.4',
    'bedrock-120b-high': 'bedrock/converse/openai.gpt-oss-120b-1:0',
}

REASONING_EFFORT = 'high'

MANIFEST_DIR = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'batches' / TEST_SET
MANIFEST_PATH = MANIFEST_DIR / '_manifest.jsonl'


def load_manifest() -> list[dict]:
    """Load existing manifest entries."""
    if not MANIFEST_PATH.exists():
        return []
    entries = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def already_submitted(
    manifest: list[dict], call_type: str, model: str,
    sample_variant: str = "sampled_100_seed42",
) -> bool:
    """Check if a (call_type, model, sample_variant) triple is already in the
    manifest with a non-failed batch. Legacy entries (no sample_variant field)
    are treated as belonging to the original 'sampled_100_seed42' variant."""
    for entry in manifest:
        if entry.get('call_type') != call_type or entry.get('model') != model:
            continue
        entry_variant = entry.get('sample_variant', 'sampled_100_seed42')
        if entry_variant != sample_variant:
            continue
        if entry.get('status') != 'failed':
            return True
    return False


def append_to_manifest(entry: dict):
    """Atomically append one entry to the manifest JSONL."""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, 'a') as f:
        f.write(json.dumps(entry) + '\n')


async def run(
    dry_run: bool = False,
    confirm: bool = False,
    single: tuple = None,
    sample_variant: str = "sampled_100_seed42",
    reasoning_effort: str = REASONING_EFFORT,
    model_key_filter: str = None,
):
    """Main submission loop.

    Args:
        dry_run: If True, only prepare + estimate, don't submit.
        confirm: Required if total estimated cost > $50.
        single: If set, (call_type, model_key) to run a single batch.
        sample_variant: Suffix of the input file (and manifest key) — e.g.
            "sampled_100_seed42" (default, original random sample) or
            "substantive_100_seed43" (substantive-filtered top-up).
        reasoning_effort: 'low' | 'medium' | 'high'. Artifacts for non-'high'
            efforts are namespaced with a '_<effort>' key so an effort sweep
            never collides with the existing high-effort run (which keeps the
            plain key). Input files are NOT effort-specific.
        model_key_filter: If set, restrict to this single MODELS key (e.g.
            'bedrock-120b-high'). reasoning_effort is a gpt-oss-specific knob,
            so effort sweeps run gpt-oss only — no need to re-run gpt-5.4.
    """
    manifest = load_manifest()

    # Effort-namespaced key for batch files / manifest / retrieval dirs. 'high'
    # reuses the plain key so we don't re-run the existing high-effort batches.
    batch_key = sample_variant if reasoning_effort == 'high' else f"{sample_variant}_{reasoning_effort}"

    # Build the matrix
    models = {model_key_filter: MODELS[model_key_filter]} if model_key_filter else MODELS
    if single:
        ct, mk = single
        matrix = [(ct, mk, MODELS[mk])]
    else:
        matrix = [
            (ct, mk, model)
            for ct in CALL_TYPE_CONFIG
            for mk, model in models.items()
        ]

    # Phase 1: prepare + estimate all
    estimates = []
    prepared = []
    skipped = []

    for call_type, model_key, model in matrix:
        if already_submitted(manifest, call_type, model, sample_variant=batch_key):
            skipped.append((call_type, model_key))
            continue

        # Skip Bedrock time_normalization — the batch API does NOT apply litellm's
        # response_format → tool-use translation, so batched time_normalization
        # outputs diverge from prod. Run it live instead via
        # rerun_bedrock_time_normalization_live.py.
        if call_type == 'time_normalization' and model.startswith('bedrock/'):
            print(f"SKIP {call_type} × {model_key}: Bedrock batch can't apply response_format; "
                  f"use rerun_bedrock_time_normalization_live.py --sample-variant {sample_variant} instead")
            skipped.append((call_type, model_key))
            continue

        # Check sampled file line count for Bedrock minimum
        input_path = REPO_ROOT / 'inputs' / 'test_set' / f"{call_type}_{TEST_SET}_{sample_variant}.jsonl"
        with open(input_path) as f:
            n_cases = sum(1 for _ in f)

        if model.startswith('bedrock/') and n_cases < 20:
            print(f"SKIP {call_type} × {model_key}: only {n_cases} cases (Bedrock minimum 100 requests)")
            skipped.append((call_type, model_key))
            continue

        print(f"\nPreparing: {call_type} × {model_key} ({batch_key}, effort={reasoning_effort})")
        batch_file = prepare_batch_file(
            call_type=call_type,
            test_set=TEST_SET,
            call_type_config=CALL_TYPE_CONFIG[call_type],
            model=model,
            num_runs=5,
            reasoning_effort=reasoning_effort,
            input_path_override=input_path,
            batch_suffix=batch_key,
        )

        try:
            estimate = estimate_batch_cost(batch_file, model, reasoning_effort=reasoning_effort)
        except json.JSONDecodeError:
            # Sandbox filesystem can corrupt large files; fall back to request-count estimate
            with open(batch_file) as bf:
                n_req = sum(1 for _ in bf)
            estimate = {'total_requests': n_req, 'estimated_cost_usd': round(n_req * 0.005, 2),
                        'estimated_input_tokens': 0, 'estimated_output_tokens': 0,
                        'note': 'Fallback estimate (filesystem read error)'}
        print(f"  Estimated cost: ${estimate['estimated_cost_usd']:.2f} ({estimate['total_requests']} requests)")
        estimates.append(estimate)
        prepared.append((call_type, model_key, model, batch_file, estimate))

    if skipped:
        print(f"\nSkipped {len(skipped)} already-submitted batches:")
        for ct, mk in skipped:
            print(f"  {ct} × {mk}")

    total_cost = sum(e['estimated_cost_usd'] for e in estimates)
    print(f"\n{'='*60}")
    print(f"Total estimated cost: ${total_cost:.2f} for {len(prepared)} batches")
    print(f"{'='*60}")

    if dry_run:
        print("\n[DRY RUN] Stopping before submission.")
        return

    if total_cost > 50.0 and not confirm:
        print(f"\nERROR: Estimated cost ${total_cost:.2f} exceeds $50 safety limit.")
        print("Re-run with --confirm to proceed.")
        sys.exit(1)

    # Phase 2: submit
    for call_type, model_key, model, batch_file, estimate in prepared:
        print(f"\nSubmitting: {call_type} × {model_key}")
        try:
            meta = await submit_batch(batch_file, model)
            entry = {
                **meta,
                'call_type': call_type,
                'model_key': model_key,
                'sample_variant': batch_key,
                'reasoning_effort': reasoning_effort,
                'estimated_cost_usd': estimate['estimated_cost_usd'],
                'total_requests': estimate['total_requests'],
            }
            append_to_manifest(entry)
            print(f"  Submitted: {meta['batch_id']}")
        except Exception as e:
            print(f"  ERROR: {e}")
            entry = {
                'call_type': call_type,
                'model': model,
                'model_key': model_key,
                'sample_variant': batch_key,
                'reasoning_effort': reasoning_effort,
                'status': 'failed',
                'error': str(e),
                'created_at': datetime.now().isoformat(),
            }
            append_to_manifest(entry)

    print(f"\nDone. Manifest: {MANIFEST_PATH}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Submit self-consistency batches")
    parser.add_argument('--dry-run', action='store_true', help="Prepare and estimate only, don't submit")
    parser.add_argument('--confirm', action='store_true', help="Confirm submission if cost > $50")
    parser.add_argument('--single', nargs=2, metavar=('CALL_TYPE', 'MODEL_KEY'),
                        help="Submit a single (call_type, model_key) pair")
    parser.add_argument(
        '--sample-variant', default='sampled_100_seed42',
        help="Suffix of the input file and manifest key. Default: sampled_100_seed42 (original). "
             "Use 'substantive_100_seed43' for the substantive-filtered top-up.",
    )
    parser.add_argument(
        '--reasoning-effort', default='high', choices=['low', 'medium', 'high'],
        help="Reasoning effort for the sweep. 'high' reuses the existing run's "
             "plain key; 'low'/'medium' are namespaced '_<effort>'. Default: high.",
    )
    parser.add_argument(
        '--model-key', default=None, choices=list(MODELS.keys()),
        help="Restrict to a single model. Effort sweeps should use "
             "'bedrock-120b-high' (gpt-oss); reasoning_effort is gpt-oss-specific.",
    )
    args = parser.parse_args()

    single = tuple(args.single) if args.single else None
    asyncio.run(run(
        dry_run=args.dry_run,
        confirm=args.confirm,
        single=single,
        sample_variant=args.sample_variant,
        reasoning_effort=args.reasoning_effort,
        model_key_filter=args.model_key,
    ))


if __name__ == '__main__':
    main()
