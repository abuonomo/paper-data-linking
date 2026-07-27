#!/usr/bin/env python3
"""Re-run Bedrock time_normalization via LIVE (non-batch) calls to match prod.

The batch path skipped the response_format -> tool_use translation that
prod applies in live calls. This script makes the same calls prod does:
litellm.acompletion with response_format=NormalizedTimeRange, temperature=1.0,
max_tokens=30000, no reasoning_effort (matching time_range_normalizer.py).

Usage:
    # default: the original random-sampled 100 cases
    python rerun_bedrock_time_normalization_live.py

    # or a different sample variant (e.g. the substantive top-up)
    python rerun_bedrock_time_normalization_live.py \
        --sample-variant substantive_100_seed43

Results are written into the analyzer's expected directory layout. When
a --sample-variant is passed, results are appended (not replaced) so
multiple variants can be merged for analysis.
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import litellm
import experiments.compare_models.handlers  # noqa: F401
from experiments.compare_models.core.registry import CallTypeRegistry
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedTimeRange

litellm.drop_params = True
litellm.suppress_debug_info = True

TEST_SET = "test_set_helio_v2_2026_04_06"
CALL_TYPE = "time_normalization"
MODEL = "bedrock/converse/openai.gpt-oss-120b-1:0"
MODEL_SLUG = "bedrock_converse_openai_gpt-oss-120b-1_0"
NUM_RUNS = 5
CONCURRENCY = 20

PROMPT_PATH = REPO_ROOT / "paper_data_linking/linkers/general/prompts/time_normalization/system.xml"
RESULTS_BASE = REPO_ROOT / "experiments" / "compare_models" / "self_consistency" / "results" / TEST_SET / MODEL_SLUG / CALL_TYPE


async def call_one(sem, handler, system_prompt, case_id, user_msg, run, reasoning_effort=None):
    async with sem:
        try:
            kwargs = dict(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=1.0,
                max_tokens=30000,
                response_format=NormalizedTimeRange,
            )
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            resp = await litellm.acompletion(**kwargs)
            content = resp.choices[0].message.content
            usage = resp.usage
            return {
                "original_id": case_id,
                "call_type": CALL_TYPE,
                "model_name": MODEL,
                "created_at": datetime.now().isoformat(),
                "provider": "bedrock",
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "output_content": content,
                "run": run,
            }
        except Exception as e:
            return {
                "original_id": case_id,
                "call_type": CALL_TYPE,
                "model_name": MODEL,
                "created_at": datetime.now().isoformat(),
                "provider": "bedrock",
                "output_content": "",
                "run": run,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-variant",
        default="sampled_100_seed42",
        help="Input-file suffix (default: sampled_100_seed42, original random sample).",
    )
    parser.add_argument(
        "--reasoning-effort", default="high", choices=["low", "medium", "high"],
        help="Reasoning effort. 'high' writes to the plain slug; low/medium to "
             "'<slug>_<effort>' (matches the batched call types).",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete existing results for this call type before writing. "
             "Only safe for the original variant; DO NOT use when topping up.",
    )
    args = parser.parse_args()

    # Effort-namespaced result tree (mirrors the batched call types): 'high' uses
    # the plain slug; low/medium use '<slug>_<effort>'.
    slug = MODEL_SLUG if args.reasoning_effort == "high" else f"{MODEL_SLUG}_{args.reasoning_effort}"
    results_base = (REPO_ROOT / "experiments" / "compare_models" / "self_consistency"
                    / "results" / TEST_SET / slug / CALL_TYPE)

    input_path = (
        REPO_ROOT / "inputs" / "test_set"
        / f"{CALL_TYPE}_{TEST_SET}_{args.sample_variant}.jsonl"
    )
    if not input_path.exists():
        sys.exit(f"ERROR: input file not found: {input_path}")

    system_prompt = PROMPT_PATH.read_text()
    handler = CallTypeRegistry.get_by_class_name("TimeNormalizationHandler")

    cases = []
    with open(input_path) as f:
        for line in f:
            case = json.loads(line)
            case_id = case.get("id", f"case_{len(cases)}")
            user_msg = None
            if "input_messages" in case:
                for m in case["input_messages"]:
                    if m.get("role") == "user":
                        user_msg = m.get("content")
                        break
            elif "raw_inputs" in case:
                user_msg = handler.render_user_message(case)
            if user_msg:
                cases.append((case_id, user_msg))

    print(f"Variant: {args.sample_variant}")
    print(f"Loaded {len(cases)} cases from {input_path.name}.")
    print(f"Firing {len(cases) * NUM_RUNS} live calls with concurrency {CONCURRENCY}.")

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        call_one(sem, handler, system_prompt, case_id, user_msg, run,
                 reasoning_effort=args.reasoning_effort)
        for run in range(1, NUM_RUNS + 1)
        for case_id, user_msg in cases
    ]
    results = await asyncio.gather(*tasks)

    if args.wipe:
        if results_base.exists():
            print(f"Wiping {results_base}")
            shutil.rmtree(results_base)

    by_run = {}
    for r in results:
        by_run.setdefault(r["run"], []).append(r)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ok = 0
    errors = 0
    for run, recs in sorted(by_run.items()):
        out_dir = results_base / f"run{run}"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Include variant in filename so the two sets are distinguishable on disk.
        out_file = out_dir / f"{MODEL_SLUG}_live_{args.sample_variant}_{timestamp}.jsonl"
        with open(out_file, "w") as f:
            for rec in recs:
                f.write(json.dumps(rec) + "\n")
                if rec.get("error"):
                    errors += 1
                else:
                    ok += 1
        print(f"  run{run}: {len(recs)} results -> {out_file}")

    print(f"\nDone. OK: {ok}, Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
    # litellm's async client can leave aiohttp connectors open, which leaves the
    # process hung after all results are written/flushed. Force a clean exit so
    # callers (e.g. a sequential sweep loop) don't block forever on a finished run.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
