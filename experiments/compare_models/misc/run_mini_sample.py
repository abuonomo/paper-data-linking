#!/usr/bin/env python3
"""
Run a small instrument_validation sample through gpt-5-mini and summarize.

Steps:
1) Export instrument_validation input_messages from DB to inputs/instrument_validation.jsonl
2) Take first N lines to inputs/instrument_validation_N.jsonl
3) Replay prompts with gpt-5-mini into a timestamped JSONL in experiments/compare_models/data
4) Summarize decision presence/counts into experiments/compare_models/results

Usage:
  PYTHONPATH=. python experiments/compare_models/run_mini_sample.py --count 10 --config standard

Notes:
- Set OPENAI_API_KEY in your environment.
- If Django export fails, the script will use an existing inputs/instrument_validation.jsonl (if present).
"""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv, find_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]
# Load environment from top-level .env (OPENAI_API_KEY, etc.)
_env_path = find_dotenv(str(REPO_ROOT / ".env")) or find_dotenv()
if _env_path:
    load_dotenv(_env_path)
else:
    # Fallback: attempt default search
    load_dotenv()
INPUTS_DIR = REPO_ROOT / "inputs"
DATA_DIR = REPO_ROOT / "experiments" / "compare_models" / "data"
RESULTS_DIR = REPO_ROOT / "experiments" / "compare_models" / "results"
RUN_COMPARE = REPO_ROOT / "experiments" / "compare_models" / "run_compare.py"
MANAGE_PY = REPO_ROOT / "api" / "manage.py"


def run(cmd: list[str], env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, env=env, check=check)


def export_inputs(config: str | None) -> Path | None:
    INPUTS_DIR.mkdir(exist_ok=True)
    out = INPUTS_DIR / "instrument_validation.jsonl"
    env = os.environ.copy()
    cmd = [sys.executable, str(MANAGE_PY), "export_llm_calls", "--call-type", "instrument_validation", "--output", str(out)]
    if config:
        cmd.extend(["--config", config])
    try:
        run(cmd, env=env)
        if out.exists() and out.stat().st_size > 0:
            return out
    except subprocess.CalledProcessError as e:
        print(f"WARN: export_llm_calls failed ({e}); will try existing inputs if present.")
    return out if out.exists() and out.stat().st_size > 0 else None


def sample_inputs(src: Path, count: int) -> Path:
    dst = INPUTS_DIR / f"instrument_validation_{count}.jsonl"
    taken = 0
    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            fout.write(line)
            taken += 1
            if taken >= count:
                break
    print(f"Sampled {taken} lines -> {dst}")
    return dst


def replay_mini(sample_file: Path, timeout_sec: float | None = None, max_retries: int | None = None) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    # Single model run (mini)
    cmd = [
        sys.executable,
        str(RUN_COMPARE),
        "--call-type", "instrument_validation",
        "--input", str(sample_file),
        "--models", "openai/gpt-5-mini",
        "--out", str(DATA_DIR),
    ]
    if timeout_sec is not None:
        cmd += ["--timeout-sec", str(timeout_sec)]
    if max_retries is not None:
        cmd += ["--max-retries", str(max_retries)]
    run(cmd, env=env)
    # Collect newly created files (best-effort by timestamp pattern)
    ts_prefix = datetime.now().strftime("%Y%m%d_")
    outs = sorted(DATA_DIR.glob("openai_gpt-5-mini_*.jsonl"))
    if not outs:
        print("WARN: No output files detected; check logs above.")
    return outs


def summarize(others: list[Path]) -> Path | None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    cmd = [sys.executable, str(RUN_COMPARE), "--call-type", "instrument_validation", "--compare", "--others", *map(str, others), "--results", str(RESULTS_DIR)]
    run(cmd, env=env)
    # Return most recent summary file
    summaries = sorted(RESULTS_DIR.glob("summary_instrument_validation_*.json"))
    return summaries[-1] if summaries else None


def main():
    ap = argparse.ArgumentParser(description="Run a small sample on gpt-5-mini and summarize decisions")
    ap.add_argument("--count", type=int, default=10, help="Number of prompts to sample (default: 10)")
    ap.add_argument("--config", type=str, default="standard", help="LLM config filter for export (default: standard)")
    ap.add_argument("--timeout-sec", type=float, default=60.0, help="Per-call timeout seconds (default: 60.0)")
    ap.add_argument("--max-retries", type=int, default=1, help="Max retries per call (default: 1)")
    args = ap.parse_args()

    src = export_inputs(args.config)
    if src is None:
        print("ERROR: Could not export or find inputs/instrument_validation.jsonl. Create it via export_llm_calls and retry.")
        sys.exit(1)

    sample = sample_inputs(src, args.count)
    outs = replay_mini(sample, timeout_sec=args.timeout_sec, max_retries=args.max_retries)
    if not outs:
        print("No outputs to summarize.")
        sys.exit(2)
    summary = summarize(outs)
    print("\nDone.")
    print(f"Outputs: {', '.join(map(str, outs))}")
    if summary:
        print(f"Summary: {summary}")


if __name__ == "__main__":
    main()
