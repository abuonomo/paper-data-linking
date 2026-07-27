#!/usr/bin/env python3
"""Export substitution-decision data for the interactive D3 page.

Reuses the Jaccard pipeline from export_viz_data.py and the kappa
computations from analyze_helio_v2_report.py / plot_substitution_decision_kappa.py
so the interactive numbers match the static plots exactly.

Output: viz/data/substitution.json
  {
    test_set,
    models: {gpt-5.4: slug, gpt-oss-120b: slug},
    call_types: [
      {
        call_type, display_name, task_type, n_total, n_substantive,
        null_rate_gpt, null_rate_oss,
        metrics: {
          all: {gpt_intra_jaccard, oss_intra_jaccard, cross_jaccard,
                gpt_intra_kappa, oss_intra_kappa, cross_kappa},
          substantive: { same keys },
        },
        per_case: [
          {case_id, gpt_intra_jaccard, oss_intra_jaccard, cross_jaccard,
           is_null_both, is_substantive},
        ],
      }
    ]
  }
"""

import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Register handlers so CallTypeRegistry is populated
import experiments.compare_models.handlers  # noqa: F401

from experiments.compare_models.self_consistency.analyze_helio_v2_report import (
    CALL_TYPE_HANDLER,
    fleiss_kappa,
    is_null_canonical,
    try_parse,
)
from experiments.compare_models.self_consistency.plot_substitution_decision_kappa import (
    cohens_kappa,
    modal,
    is_all_null,
)

TEST_SET_TAG = "test_set_helio_v2_2026_04_06"
RESULTS_DIR = REPO_ROOT / "experiments" / "compare_models" / "self_consistency" / "results" / TEST_SET_TAG
OUT_FILE = Path(__file__).parent / "data" / "substitution.json"

MODEL_SLUGS = {
    "gpt-5.4": "openai_gpt-5_4",
    "gpt-oss-120b": "bedrock_converse_openai_gpt-oss-120b-1_0",
}

CALL_TYPE_NAMES = {
    'mission_identification': 'Mission ID',
    'physobs_normalization': 'Physical Observable',
    'time_normalization': 'Time Range',
    'detector_normalization': 'Detector',
    'instrument_selection': 'Instrument Selection',
    'mission_selection': 'Mission Selection',
    'cadence_normalization': 'Cadence',
    'wavelength_normalization': 'Wavelength',
    'instrument_validation': 'Instrument Validation',
    'mission_validation': 'Mission Validation',
}

TASK_TYPES = {
    'instrument_validation': 'binary',
    'mission_validation': 'binary',
    'mission_selection': 'set',
    'instrument_selection': 'set',
    'mission_identification': 'set',
    'wavelength_normalization': 'set',
    'cadence_normalization': 'set',
    'physobs_normalization': 'single',
    'detector_normalization': 'single',
    'time_normalization': 'single',
}


def load_runs(call_type, model_slug):
    base = RESULTS_DIR / model_slug / call_type
    if not base.exists():
        return {}
    cases = defaultdict(list)
    for run_dir in sorted(base.glob("run*")):
        files = list(run_dir.glob("*.jsonl"))
        if not files:
            continue
        with open(files[0]) as f:
            for line in f:
                rec = json.loads(line)
                cid = rec.get("original_id") or rec.get("case_index")
                if cid is None:
                    continue
                canonical, ok = try_parse(call_type, rec.get("output_content", ""))
                cases[cid].append(canonical if ok else f"__parse_error__{rec.get('custom_id', '')}")
    return {cid: r for cid, r in cases.items() if len(r) == 5}


def pairwise_jaccard_runs(runs_a, runs_b=None):
    """Mean pairwise Jaccard (as %). If runs_b is None, compute intra (within runs_a)."""
    if runs_b is None:
        pairs = [(runs_a[i], runs_a[j]) for i in range(len(runs_a))
                 for j in range(i + 1, len(runs_a))]
    else:
        pairs = [(a, b) for a in runs_a for b in runs_b]
    if not pairs:
        return float("nan")
    # Canonical strings: equality → 1, otherwise 0 (since we canonicalised to one
    # comparable form per response already; tokenising into sets here just
    # complicates things). Jaccard reduces to mean exact-match.
    return float(np.mean([1.0 if a == b else 0.0 for a, b in pairs])) * 100


def compute_metrics(gpt_cases, oss_cases, call_type, substantive_only=False):
    """Return dict of aggregate metrics."""
    common = sorted(set(gpt_cases) & set(oss_cases))
    if substantive_only:
        common = [
            cid for cid in common
            if not (is_all_null(call_type, gpt_cases[cid])
                    and is_all_null(call_type, oss_cases[cid]))
        ]
    if not common:
        return None

    # Intra Jaccard (mean across cases of per-case pairwise Jaccard)
    gpt_intra_j = float(np.mean([pairwise_jaccard_runs(gpt_cases[c]) for c in common]))
    oss_intra_j = float(np.mean([pairwise_jaccard_runs(oss_cases[c]) for c in common]))
    # Cross Jaccard (mean across cases of mean cross-pair Jaccard)
    cross_j = float(np.mean([
        pairwise_jaccard_runs(gpt_cases[c], oss_cases[c]) for c in common
    ]))

    # Intra Fleiss κ
    gpt_intra_k = fleiss_kappa({c: gpt_cases[c] for c in common})
    oss_intra_k = fleiss_kappa({c: oss_cases[c] for c in common})
    # Cross Cohen's κ on per-case modal answers
    cross_k = cohens_kappa(
        [modal(gpt_cases[c]) for c in common],
        [modal(oss_cases[c]) for c in common],
    )

    return {
        "n": len(common),
        "gpt_intra_jaccard": gpt_intra_j,
        "oss_intra_jaccard": oss_intra_j,
        "cross_jaccard": cross_j,
        "gpt_intra_kappa": float(gpt_intra_k),
        "oss_intra_kappa": float(oss_intra_k),
        "cross_kappa": float(cross_k),
    }


def per_case_points(gpt_cases, oss_cases, call_type):
    common = sorted(set(gpt_cases) & set(oss_cases))
    rows = []
    for cid in common:
        g = gpt_cases[cid]
        o = oss_cases[cid]
        null_g = is_all_null(call_type, g)
        null_o = is_all_null(call_type, o)
        rows.append({
            "case_id": cid,
            "gpt_intra_jaccard": pairwise_jaccard_runs(g),
            "oss_intra_jaccard": pairwise_jaccard_runs(o),
            "cross_jaccard": pairwise_jaccard_runs(g, o),
            "is_null_both": null_g and null_o,
            "is_substantive": not (null_g and null_o),
        })
    return rows


def null_rate(cases, call_type):
    if not cases:
        return float("nan")
    total = sum(len(runs) for runs in cases.values())
    nulls = sum(
        1 for runs in cases.values() for r in runs if is_null_canonical(call_type, r)
    )
    return (nulls / total * 100) if total else float("nan")


def main():
    data = {
        "test_set": TEST_SET_TAG,
        "models": MODEL_SLUGS,
        "call_types": [],
    }

    for ct in sorted(CALL_TYPE_HANDLER):
        gpt = load_runs(ct, MODEL_SLUGS["gpt-5.4"])
        oss = load_runs(ct, MODEL_SLUGS["gpt-oss-120b"])
        if not gpt or not oss:
            print(f"SKIP {ct}: missing results")
            continue

        all_m = compute_metrics(gpt, oss, ct, substantive_only=False)
        sub_m = compute_metrics(gpt, oss, ct, substantive_only=True)

        entry = {
            "call_type": ct,
            "display_name": CALL_TYPE_NAMES.get(ct, ct),
            "task_type": TASK_TYPES.get(ct, "unknown"),
            "n_total": all_m["n"] if all_m else 0,
            "n_substantive": sub_m["n"] if sub_m else 0,
            "null_rate_gpt": null_rate(gpt, ct),
            "null_rate_oss": null_rate(oss, ct),
            "metrics": {
                "all": all_m,
                "substantive": sub_m,
            },
            "per_case": per_case_points(gpt, oss, ct),
        }
        data["call_types"].append(entry)
        if all_m:
            print(f"  {ct:30s}  cross_κ={all_m['cross_kappa']:.3f}  "
                  f"oss_intra_κ={all_m['oss_intra_kappa']:.3f}  "
                  f"N={all_m['n']}  (sub N={sub_m['n'] if sub_m else 0})")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {OUT_FILE}")


if __name__ == "__main__":
    main()
