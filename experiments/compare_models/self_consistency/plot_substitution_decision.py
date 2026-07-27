#!/usr/bin/env python3
"""Substitution-decision quadrant plot: can gpt-oss-120b replace gpt-5.4?

X-axis: cross-model substantive agreement (per-case mean Jaccard between
    gpt-5.4 runs and gpt-oss-120b runs, restricted to cases where at least
    one model returned a non-null answer in at least one run).
Y-axis: gpt-oss-120b substantive intra-agreement (mean pairwise Jaccard
    across its own 5 runs, restricted to the same substantive case set).

Reuses Jaccard computation from viz/export_viz_data.py via the same
monkey-patches plot_intra_vs_cross.py applies (reasoning-strip + tolerant
verdict regex), so numbers are consistent with the production tooling.

Decision regions:
  Top-right     (>=0.9, >=0.9): SWAP FREELY     — answers rarely change, oss is stable
  Bottom-right  (cross>=0.9, intra<0.9): SWAP IF COST MATTERS — oss matches by luck
  Top-left      (cross<0.9, intra>=0.9): NEEDS JUDGE — oss reliably picks a different answer
  Bottom-left   (<0.9, <0.9): DON'T SWAP        — oss is unreliable AND disagrees
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Reuse the patched evd module from plot_intra_vs_cross
from experiments.compare_models.self_consistency import plot_intra_vs_cross as piv

evd = piv.evd
MODELS = piv.MODELS
TEST_SET_TAG = piv.TEST_SET_TAG
CALL_TYPE_NAMES = piv.CALL_TYPE_NAMES

OUT_BASENAME = REPO_ROOT / "experiments" / "compare_models" / f"{TEST_SET_TAG}_substitution_decision"
THRESHOLD = 0.90  # 90% — both axes


def jacc(a, b):
    return evd.jaccard_similarity(a, b)


def substantive_metrics(case_metrics):
    """For each call type, restrict to cases where at least one run from
    either model produced a non-null answer, then compute:
      - cross-model mean per-pair Jaccard
      - gpt-oss-120b intra mean pairwise Jaccard

    Returns: list of (call_type, x, y, n_substantive)
    """
    rows = []
    gpt, oss = MODELS

    for ct in evd.CALL_TYPES:
        cases = case_metrics.get(ct, {})
        cross_jaccs = []
        intra_jaccs = []
        n_sub = 0

        for case_id, cm in cases.items():
            gpt_runs = cm["models"].get(gpt, {}).get("num_runs", 0)
            oss_runs = cm["models"].get(oss, {}).get("num_runs", 0)
            if gpt_runs == 0 or oss_runs == 0:
                continue

            # Pull raw run sets out of the original all_data structure
            cmg = cm["models"][gpt]
            cmo = cm["models"][oss]

            # cross_model_agreement_non_null is already computed and
            # excludes pairs where either side was null. Use it as our
            # "substantive cross-model" signal at the case level.
            cross = cm.get("cross_model_agreement_non_null")
            if cross is None:
                continue  # case where every run on at least one side was null
            cross_jaccs.append(cross)

            # For intra we need the actual response sets — pull them via
            # the same case_id from the upstream all_data
            n_sub += 1

        # For the intra metric, recompute against all_data directly
        # (case_metrics throws away the per-run sets after summarising).
        # We instead reuse models[oss]['self_consistency'], filtered to
        # cases that contributed a substantive cross point above.
        substantive_case_ids = {
            cid for cid, cm in cases.items()
            if cm.get("cross_model_agreement_non_null") is not None
            and cm["models"].get(oss, {}).get("num_runs", 0) > 0
        }
        oss_intra_vals = [
            cases[cid]["models"][oss]["self_consistency"]
            for cid in substantive_case_ids
        ]

        x = float(np.mean(cross_jaccs)) * 100 if cross_jaccs else float("nan")
        y = float(np.mean(oss_intra_vals)) * 100 if oss_intra_vals else float("nan")
        rows.append((ct, x, y, len(substantive_case_ids)))
    return rows


def quadrant_label(x, y, thresh=THRESHOLD * 100):
    if x >= thresh and y >= thresh:
        return "swap-freely"
    if x >= thresh and y < thresh:
        return "swap-if-cost"
    if x < thresh and y >= thresh:
        return "needs-judge"
    return "dont-swap"


REGION_COLORS = {
    "swap-freely": "#9fd49f",      # green
    "swap-if-cost": "#ffe599",     # amber
    "needs-judge": "#cfe2f3",      # light blue
    "dont-swap": "#f4cccc",        # red
}
REGION_TITLES = {
    "swap-freely": "SWAP FREELY",
    "swap-if-cost": "SWAP IF COST MATTERS",
    "needs-judge": "NEEDS GROUND-TRUTH JUDGE",
    "dont-swap": "DON'T SWAP",
}


def plot(rows):
    fig, ax = plt.subplots(figsize=(12, 10))

    thresh = THRESHOLD * 100
    # Plot the four region rectangles
    ax.add_patch(Rectangle((thresh, thresh), 100 - thresh, 100 - thresh,
                           facecolor=REGION_COLORS["swap-freely"], alpha=0.45,
                           edgecolor='none', zorder=0))
    ax.add_patch(Rectangle((thresh, 0), 100 - thresh, thresh,
                           facecolor=REGION_COLORS["swap-if-cost"], alpha=0.45,
                           edgecolor='none', zorder=0))
    ax.add_patch(Rectangle((0, thresh), thresh, 100 - thresh,
                           facecolor=REGION_COLORS["needs-judge"], alpha=0.45,
                           edgecolor='none', zorder=0))
    ax.add_patch(Rectangle((0, 0), thresh, thresh,
                           facecolor=REGION_COLORS["dont-swap"], alpha=0.45,
                           edgecolor='none', zorder=0))

    # Region title labels (corners)
    ax.text(thresh + (100 - thresh) / 2, 99.7, REGION_TITLES["swap-freely"],
            ha='center', va='top', fontsize=11, fontweight='bold', color='#2d662d', zorder=1)
    ax.text(thresh + (100 - thresh) / 2, 0.5, REGION_TITLES["swap-if-cost"],
            ha='center', va='bottom', fontsize=11, fontweight='bold', color='#7d5b00', zorder=1)
    ax.text(thresh / 2, 99.7, REGION_TITLES["needs-judge"],
            ha='center', va='top', fontsize=11, fontweight='bold', color='#1c3a5e', zorder=1)
    ax.text(thresh / 2, 0.5, REGION_TITLES["dont-swap"],
            ha='center', va='bottom', fontsize=11, fontweight='bold', color='#7a1f1f', zorder=1)

    # Threshold lines
    ax.axvline(thresh, color='black', linestyle='--', linewidth=1.2, alpha=0.6)
    ax.axhline(thresh, color='black', linestyle='--', linewidth=1.2, alpha=0.6)

    # Diagonal reference (cross == intra)
    ax.plot([0, 100], [0, 100], color='gray', linestyle=':', linewidth=1, alpha=0.5)

    # Plot each call type
    for ct, x, y, n in rows:
        if np.isnan(x) or np.isnan(y):
            continue
        region = quadrant_label(x, y)
        ax.scatter(x, y, s=180, color='#222222', edgecolor='black',
                   linewidths=1.2, alpha=0.95, zorder=5)
        # Label
        label = CALL_TYPE_NAMES.get(ct, ct)
        # Offset labels in different directions to avoid overlap
        offset = (8, 8)
        ax.annotate(f"{label}\nN={n}", (x, y), textcoords="offset points",
                    xytext=offset, fontsize=9, fontweight='bold', zorder=6,
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                              edgecolor='gray', alpha=0.85))

    ax.set_xlim(0, 102)
    ax.set_ylim(0, 102)
    ax.set_aspect('equal', adjustable='box')
    ax.grid(True, alpha=0.25, zorder=1)
    ax.set_xlabel('Cross-model substantive agreement\n'
                  '(gpt-5.4 vs gpt-oss-120b — fraction of substantive run-pairs that match)',
                  fontsize=12)
    ax.set_ylabel('gpt-oss-120b substantive intra-agreement\n'
                  '(mean pairwise Jaccard across its own 5 runs)',
                  fontsize=12)
    ax.set_title(
        f"Can gpt-oss-120b replace gpt-5.4? — substitution decision quadrant\n"
        f"({TEST_SET_TAG}, threshold = {int(THRESHOLD*100)}% on each axis)",
        fontsize=13, fontweight='bold'
    )
    plt.tight_layout()
    return fig


def main():
    print(f"Loading {TEST_SET_TAG} ...")
    all_data = evd.load_all_results()
    case_metrics = evd.compute_case_metrics(all_data)
    rows = substantive_metrics(case_metrics)
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    print()
    print(f"{'call_type':30s}  {'cross':>6s}  {'oss-intra':>9s}  {'N':>4s}  region")
    for ct, x, y, n in rows:
        if np.isnan(x) or np.isnan(y):
            print(f"{ct:30s}    n/a       n/a   {n:4d}  (no substantive cases)")
            continue
        print(f"{ct:30s}  {x:6.1f}  {y:9.1f}  {n:4d}  {quadrant_label(x, y)}")

    fig = plot(rows)
    out_pdf = OUT_BASENAME.with_suffix(".pdf")
    out_png = OUT_BASENAME.with_suffix(".png")
    fig.savefig(out_pdf, bbox_inches='tight')
    fig.savefig(out_png, bbox_inches='tight', dpi=150)
    plt.close(fig)
    print(f"\nSaved {out_pdf}")
    print(f"Saved {out_png}")


if __name__ == "__main__":
    main()
