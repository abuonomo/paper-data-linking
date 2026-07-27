#!/usr/bin/env python3
"""Submit self-consistency batches to AWS Bedrock for test_set_helio_v2_2026_04_06.

Bedrock batch API uses S3 + create_model_invocation_job (not the OpenAI-compatible
file upload / batch flow that litellm supports). Uses the existing BatchClient
from paper_data_linking/clients/batch_client.py for the actual submission.

Format required by Bedrock: {"recordId": ..., "modelInput": {...}} JSONL.
Model is specified at job level, not per-record.

Appends to the same _manifest.jsonl as submit_helio_v2_batches.py so the retrieve
script can pick up both provider results.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Register handlers
import experiments.compare_models.handlers  # noqa: F401
from experiments.compare_models.core.registry import CallTypeRegistry
from paper_data_linking.clients.batch_client import BatchClient

TEST_SET = "test_set_helio_v2_2026_04_06"
MODEL_KEY = "bedrock-120b-high"
BEDROCK_MODEL_ID = "openai.gpt-oss-120b-1:0"  # bare Bedrock model ID (no provider prefix, no converse/)
REASONING_EFFORT = "high"
NUM_RUNS = 5

# Same call type config as the OpenAI submit script
CALL_TYPE_CONFIG = {
    'instrument_validation': 'paper_data_linking/linkers/general/prompts/validation/system.xml',
    'wavelength_normalization': 'paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml',
    'physobs_normalization': 'paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml',
    'mission_selection': 'paper_data_linking/linkers/general/prompts/mission_selection/system.xml',
    'instrument_selection': 'paper_data_linking/linkers/general/prompts/instrument_selection/system.xml',
    'detector_normalization': 'paper_data_linking/linkers/general/prompts/detector_normalization/system.xml',
    'time_normalization': 'paper_data_linking/linkers/general/prompts/time_normalization/system.xml',
    'cadence_normalization': 'paper_data_linking/linkers/general/prompts/cadence_normalization/system.xml',
    'mission_identification': 'paper_data_linking/linkers/general/prompts/mission_identification/system.xml',
    'mission_validation': 'paper_data_linking/linkers/general/prompts/mission_validation/system.xml',
}

HANDLER_BY_CALL_TYPE = {
    'instrument_validation': 'InstrumentValidationHandler',
    'wavelength_normalization': 'WavelengthNormalizationSimpleHandler',
    'physobs_normalization': 'PhysObsNormalizationFreeTextV2Handler',
    'mission_selection': 'MissionSelectionHandler',
    'instrument_selection': 'InstrumentSelectionHandler',
    'detector_normalization': 'DetectorNormalizationFreeTextV2Handler',
    'time_normalization': 'TimeNormalizationHandler',
    'cadence_normalization': 'CadenceNormalizationFreeTextHandler',
    'mission_identification': 'MissionIdentificationHandler',
    'mission_validation': 'MissionValidationHandler',
}

MANIFEST_DIR = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'batches' / TEST_SET
MANIFEST_PATH = MANIFEST_DIR / '_manifest.jsonl'
INPUT_BASE = REPO_ROOT / 'inputs' / 'test_set'
BATCH_DIR = MANIFEST_DIR


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    entries = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def already_submitted_bedrock(
    manifest: list[dict], call_type: str,
    sample_variant: str = "sampled_100_seed42",
) -> bool:
    """Has this (call_type, bedrock, sample_variant) triple been successfully submitted?
    Legacy entries without sample_variant are treated as 'sampled_100_seed42'."""
    for entry in manifest:
        if (entry.get('call_type') == call_type
                and entry.get('model_key') == MODEL_KEY
                and entry.get('status') != 'failed'
                and entry.get('batch_id')):
            entry_variant = entry.get('sample_variant', 'sampled_100_seed42')
            if entry_variant == sample_variant:
                return True
    return False


def append_to_manifest(entry: dict):
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def build_bedrock_jsonl(
    call_type: str, sample_variant: str = "sampled_100_seed42",
    reasoning_effort: str = REASONING_EFFORT,
) -> tuple[str, int]:
    """Build Bedrock-format JSONL for one (call_type, bedrock) batch.

    Bedrock format per line: {"recordId": "...", "modelInput": {...}}
    100 cases × 5 runs = 500 records per batch.
    """
    prompt_path = REPO_ROOT / CALL_TYPE_CONFIG[call_type]
    system_prompt = prompt_path.read_text()

    input_path = INPUT_BASE / f"{call_type}_{TEST_SET}_{sample_variant}.jsonl"
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    handler = CallTypeRegistry.get_by_class_name(HANDLER_BY_CALL_TYPE[call_type])

    lines = []
    case_count = 0
    with open(input_path) as f:
        for raw_line in f:
            case = json.loads(raw_line)
            case_id = case.get('id', f'case_{case_count}')

            user_msg = None
            if 'input_messages' in case:
                for m in case.get('input_messages', []):
                    if m.get('role') == 'user':
                        user_msg = m.get('content')
                        break
            elif 'raw_inputs' in case:
                user_msg = handler.render_user_message(case)
            else:
                try:
                    user_msg = handler.render_user_message(case)
                except Exception:
                    user_msg = None

            if not user_msg:
                continue

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            for run in range(1, NUM_RUNS + 1):
                record_id = f"{call_type}|{case_id}|run{run}"
                model_input = {
                    "messages": messages,
                    "temperature": 1.0,
                }
                if reasoning_effort:
                    model_input["reasoning_effort"] = reasoning_effort

                lines.append(json.dumps({
                    "recordId": record_id,
                    "modelInput": model_input,
                }))
            case_count += 1

    return "\n".join(lines), case_count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Submit Bedrock self-consistency batches")
    parser.add_argument('--dry-run', action='store_true', help="Build JSONL but don't submit")
    parser.add_argument('--single', metavar='CALL_TYPE', help="Submit a single call_type")
    parser.add_argument(
        '--sample-variant', default='sampled_100_seed42',
        help="Input-file suffix and manifest key. Default: sampled_100_seed42.",
    )
    parser.add_argument(
        '--reasoning-effort', default='high', choices=['low', 'medium', 'high'],
        help="Reasoning effort. 'high' reuses the existing run's plain key; "
             "'low'/'medium' are namespaced '_<effort>'. Default: high.",
    )
    args = parser.parse_args()

    # 'high' reuses the existing run's plain key (no re-run); low/medium get a
    # '_<effort>' suffix so artifacts/manifest/results never collide.
    batch_key = (args.sample_variant if args.reasoning_effort == 'high'
                 else f"{args.sample_variant}_{args.reasoning_effort}")

    aws_region = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    aws_batch_role_arn = os.environ.get("AWS_BATCH_ROLE_ARN")
    if not aws_batch_role_arn:
        print("ERROR: AWS_BATCH_ROLE_ARN must be set for Bedrock batch submission")
        sys.exit(1)

    manifest = load_manifest()

    call_types = [args.single] if args.single else list(CALL_TYPE_CONFIG.keys())

    client = BatchClient()

    for call_type in call_types:
        if already_submitted_bedrock(manifest, call_type, sample_variant=batch_key):
            print(f"SKIP {call_type} × {MODEL_KEY}: already submitted ({batch_key})")
            continue

        # Skip time_normalization for Bedrock — batch API doesn't apply response_format translation.
        if call_type == 'time_normalization':
            print(f"SKIP {call_type} × {MODEL_KEY}: Bedrock batch can't apply response_format; "
                  f"use rerun_bedrock_time_normalization_live.py --sample-variant {args.sample_variant}")
            continue

        print(f"\nPreparing Bedrock batch: {call_type} × {MODEL_KEY} ({batch_key}, effort={args.reasoning_effort})")
        jsonl_content, case_count = build_bedrock_jsonl(
            call_type, sample_variant=args.sample_variant, reasoning_effort=args.reasoning_effort)
        n_records = jsonl_content.count("\n") + 1 if jsonl_content else 0
        print(f"  Cases: {case_count}, Runs: {NUM_RUNS}, Total records: {n_records}")

        # Write local copy of the batch JSONL for posterity / debugging
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_path = BATCH_DIR / f"{call_type}_bedrock_gpt-oss-120b_{batch_key}_{timestamp}.jsonl"
        BATCH_DIR.mkdir(parents=True, exist_ok=True)
        local_path.write_text(jsonl_content)
        print(f"  Local copy: {local_path}")

        if args.dry_run:
            print("  [DRY RUN] Skipping submission")
            continue

        try:
            result = client.submit(
                jsonl_content=jsonl_content,
                provider="bedrock",
                model_name=BEDROCK_MODEL_ID,
                aws_region_name=aws_region,
                aws_batch_role_arn=aws_batch_role_arn,
            )
            batch_id = result["batch_id"]
            input_uri = result["input_file_id"]
            print(f"  Submitted: {batch_id}")

            entry = {
                "batch_id": batch_id,
                "input_file_id": input_uri,
                "batch_file": str(local_path),
                "model": f"bedrock/converse/{BEDROCK_MODEL_ID}",
                "provider": "bedrock",
                "created_at": datetime.now().isoformat(),
                "status": "submitted",
                "call_type": call_type,
                "model_key": MODEL_KEY,
                "sample_variant": batch_key,
                "reasoning_effort": args.reasoning_effort,
                "total_requests": n_records,
                "aws_region": aws_region,
            }
            append_to_manifest(entry)
        except Exception as e:
            print(f"  ERROR: {e}")
            append_to_manifest({
                "call_type": call_type,
                "model": f"bedrock/converse/{BEDROCK_MODEL_ID}",
                "model_key": MODEL_KEY,
                "sample_variant": batch_key,
                "reasoning_effort": args.reasoning_effort,
                "status": "failed",
                "error": str(e),
                "created_at": datetime.now().isoformat(),
            })

    print(f"\nDone. Manifest: {MANIFEST_PATH}")


if __name__ == '__main__':
    main()
