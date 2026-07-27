#!/usr/bin/env python3
"""Analyze the gpt-oss-120b reasoning-effort sweep (low / medium / high).

Two metrics per call type, each with a 95% bootstrap CI (resampling cases),
reusing the helpers from analyze_helio_v2_report.py:

  1. kappa_intra(effort)   — Fleiss' kappa across the 5 runs at that effort
                             (self-consistency / reliability at this effort).
  2. kappa_vs_gpt5(effort) — Cohen's kappa (all 5x5 run pairs per shared case)
                             between GPT-OSS-120B at that effort and GPT-5.4: the
                             substitution question — can the cheaper open model
                             replace GPT-5.4 at this effort? GPT-5.4 is the
                             high-effort reference of Section "Self-Consistency".

Results trees (written by retrieve_helio_v2_batches.py):
  results/<test_set>/<slug>_low|_medium/<call_type>/run{1..5}/   (fresh post-fix)
  results/<test_set>/<slug>/<call_type>/run{1..5}/               (high; base tree)
  results/<test_set>/<slug>/openai_gpt-5_4/<call_type>/...        (GPT-5.4 reference)

HIGH and the GPT-5.4 reference for the two prompt-fixed stages (mission_validation,
mission_identification) come from post-fix tags via OVERRIDE_TAG; low/medium and the
other 8 stages use the base tag. All trees must be present locally.

Run:  uv run python experiments/compare_models/self_consistency/analyze_effort_sweep.py
"""
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from experiments.compare_models.self_consistency.batch_runner import model_slug, RESULTS_BASE
from experiments.compare_models.self_consistency.analyze_helio_v2_report import (
    try_parse, fleiss_kappa, is_null_canonical,
)

TEST_SET = "test_set_helio_v2_2026_04_06"
MODEL = "bedrock/converse/openai.gpt-oss-120b-1:0"
EFFORTS = ["low", "medium", "high"]
RESULTS_DIR = RESULTS_BASE / TEST_SET


def slug_for(effort: str) -> str:
    """Result-tree slug for an effort. 'high' uses the plain slug (original run);
    low/medium use the '_<effort>' suffix that retrieve writes."""
    base = model_slug(MODEL)
    return base if effort == "high" else f"{base}_{effort}"


GPT5_SLUG = "openai_gpt-5_4"  # cross-model substitution reference (GPT-5.4 at high)

# Two call types' base-tree data predates a prompt fix (commit 2026-04-17); the
# canonical post-fix re-run (BOTH models) lives under a different test-set tag.
# Use that tag for those stages so prompts match for both gpt-oss-high and the
# GPT-5.4 reference. low/medium were generated fresh post-fix in the base tree,
# and the other 8 stages' prompts are unchanged, so they use the base tag.
OVERRIDE_TAG = {
    "mission_validation": f"{TEST_SET}_mvfix2",
    "mission_identification": f"{TEST_SET}_midfix",
}


def _tag_for(call_type: str) -> str:
    return OVERRIDE_TAG.get(call_type, TEST_SET)


def gptoss_high_dir(call_type: str) -> Path:
    return RESULTS_BASE / _tag_for(call_type) / model_slug(MODEL) / call_type


def gpt5_dir(call_type: str) -> Path:
    return RESULTS_BASE / _tag_for(call_type) / GPT5_SLUG / call_type


def load_cases(call_type_dir: Path, call_type: str):
    """Load {case_id: [canonical answer per run]} for the COMPLETE, SUBSTANTIVE
    cases (drops cases where every run was the null/refusal answer). Also returns
    n_runs and summed tokens/cost. Mirrors analyze_call_type's loading."""
    run_dirs = sorted(call_type_dir.glob("run*"))
    if not run_dirs:
        return {}, 0, 0, 0.0
    n_runs = len(run_dirs)
    cases = defaultdict(list)
    tokens, cost = 0, 0.0
    for run_dir in run_dirs:
        for jf in sorted(run_dir.glob("*.jsonl")):
            with open(jf) as f:
                for line in f:
                    rec = json.loads(line)
                    cid = rec.get("original_id") or rec.get("case_index")
                    if cid is None:
                        continue
                    out = rec.get("output_content") or rec.get("response") or ""
                    canon, ok = try_parse(call_type, out)
                    cases[cid].append(canon if ok else f"__parse_error_{rec.get('custom_id', '')}")
                    tokens += rec.get("total_tokens", 0) or 0
                    cost += rec.get("estimated_cost_usd", 0) or 0
    complete = {c: r for c, r in cases.items() if len(r) == n_runs}
    substantive = {
        c: r for c, r in complete.items()
        if not all(is_null_canonical(call_type, x) for x in r)
    }
    return substantive, n_runs, tokens, cost


def cohen_kappa_pairwise(a: dict, b: dict):
    """Cohen's kappa between two conditions over ALL pairwise (a_run, b_run)
    observations per shared case (matches the paper's cross-model methodology:
    5x5 = 25 observations per case). Returns (kappa, n_shared_cases)."""
    shared = sorted(set(a) & set(b))
    xa, xb = [], []
    for cid in shared:
        for x in a[cid]:
            for y in b[cid]:
                xa.append(x); xb.append(y)
    n = len(xa)
    if n == 0:
        return float("nan"), 0
    po = sum(1 for x, y in zip(xa, xb) if x == y) / n
    ca, cb = Counter(xa), Counter(xb)
    cats = set(xa) | set(xb)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    if pe >= 1.0:
        return 1.0, len(shared)
    return (po - pe) / (1 - pe), len(shared)


def _ci(samples):
    arr = np.asarray([s for s in samples if s == s])  # drop NaN
    if len(arr) == 0:
        return (float("nan"), float("nan"))
    return (round(float(np.percentile(arr, 2.5)), 3), round(float(np.percentile(arr, 97.5)), 3))


def bootstrap_intra(cases, n_boot=2000, seed=42):
    """95% bootstrap CI for Fleiss' kappa, resampling cases with replacement."""
    ids = list(cases)
    if len(ids) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n = len(ids)
    out = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        out.append(fleiss_kappa({i: cases[ids[j]] for i, j in enumerate(idx)}))
    return _ci(out)


def bootstrap_cross(a, b, n_boot=2000, seed=42):
    """95% bootstrap CI for cross-model Cohen's kappa, resampling shared cases."""
    shared = sorted(set(a) & set(b))
    if len(shared) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n = len(shared)
    out = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        aa = {i: a[shared[j]] for i, j in enumerate(idx)}
        bb = {i: b[shared[j]] for i, j in enumerate(idx)}
        out.append(cohen_kappa_pairwise(aa, bb)[0])
    return _ci(out)


def main():
    if not RESULTS_DIR.exists():
        print(f"No results at {RESULTS_DIR}")
        sys.exit(1)

    # low/medium gpt-oss trees (base tag, fresh post-fix runs)
    low_med = {e: (RESULTS_DIR / slug_for(e)) for e in ("low", "medium")}
    low_med = {e: d for e, d in low_med.items() if d.exists()}
    print(f"Effort trees present: {sorted(['high'] + list(low_med))}")

    call_types = sorted({ct.name for d in low_med.values() for ct in d.iterdir() if ct.is_dir()})

    hdr = (f"{'call_type':24s} "
           f"{'κi_low':>7s} {'κi_med':>7s} {'κi_high':>8s}  "
           f"{'κg_low':>7s} {'κg_med':>7s} {'κg_high':>8s}  {'N':>4s}")
    print("\n" + hdr)
    print("-" * len(hdr))
    print("  (κi = self-consistency; κg = agreement with GPT-5.4 — the substitution metric)")

    rows = []
    for ct in call_types:
        # gpt-oss cases per effort: low/medium from base tag; high from (possibly
        # overridden) post-fix tag. GPT-5.4 reference from the matching tag.
        gptoss = {}
        for e in ("low", "medium"):
            d = low_med.get(e)
            if d and (d / ct).exists():
                gptoss[e] = load_cases(d / ct, ct)
        if gptoss_high_dir(ct).exists():
            gptoss["high"] = load_cases(gptoss_high_dir(ct), ct)
        gpt5_cases = load_cases(gpt5_dir(ct), ct)[0] if gpt5_dir(ct).exists() else {}

        def ki(e):
            return fleiss_kappa(gptoss[e][0]) if e in gptoss and gptoss[e][0] else float("nan")

        def kg(e):  # agreement of gpt-oss@effort with GPT-5.4 (substitution)
            if e in gptoss and gptoss[e][0] and gpt5_cases:
                return cohen_kappa_pairwise(gptoss[e][0], gpt5_cases)[0]
            return float("nan")

        def tok(e):
            return gptoss[e][2] if e in gptoss else 0

        n = len(gptoss.get("high", ({},))[0]) or (len(gptoss[list(gptoss)[0]][0]) if gptoss else 0)
        f = lambda v: "  -  " if v != v else f"{v:.3f}"
        print(f"{ct:24s} "
              f"{f(ki('low')):>7s} {f(ki('medium')):>7s} {f(ki('high')):>8s}  "
              f"{f(kg('low')):>7s} {f(kg('medium')):>7s} {f(kg('high')):>8s}  {n:>4d}")
        # 95% bootstrap CIs (resample cases) for each reported kappa
        ci_intra = {e: (bootstrap_intra(gptoss[e][0]) if e in gptoss and gptoss[e][0]
                        else (float("nan"), float("nan"))) for e in EFFORTS}
        ci_gpt5 = {e: (bootstrap_cross(gptoss[e][0], gpt5_cases)
                       if e in gptoss and gptoss[e][0] and gpt5_cases
                       else (float("nan"), float("nan"))) for e in EFFORTS}
        rows.append({
            "call_type": ct,
            "kappa_intra": {e: ki(e) for e in EFFORTS},
            "kappa_intra_ci": ci_intra,
            "kappa_vs_gpt5": {e: kg(e) for e in EFFORTS},
            "kappa_vs_gpt5_ci": ci_gpt5,
            "tokens": {e: tok(e) for e in EFFORTS},
            "n": n,
        })

    out = RESULTS_DIR / "effort_sweep_summary.json"
    with open(out, "w") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {out}")
    print("\nReading guide: κi_* = gpt-oss self-consistency at that effort. κg_* = agreement "
          "with GPT-5.4 at that effort (the substitution question). A stage is safe to run "
          "at a cheaper effort when both stay high there.")


if __name__ == "__main__":
    main()
