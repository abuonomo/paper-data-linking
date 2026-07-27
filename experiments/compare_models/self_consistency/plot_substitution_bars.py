#!/usr/bin/env python3
"""Grouped-bar substitution-decision figure.

For each call type, three bars on the same κ axis:
  - gpt-5.4 internal stability (Fleiss' κ across its 5 runs)
  - gpt-oss-120b internal stability (Fleiss' κ across its 5 runs)
  - cross-model agreement (single-run pairwise Cohen's κ between models)

Sorted so the highest weakest-link sits at the top. A swap is safe when
**all three bars** clear the κ = 0.80 line; the shortest bar in each
group is the dimension that would bottleneck the swap.

Output:
  experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_bars.{png,pdf}
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.patches import Patch

# Paper-friendly styling: minimal grid, clean spines, colorblind-safe palette.
sns.set_style("whitegrid")
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#888",
    "axes.linewidth": 0.8,
    "axes.labelcolor": "#222",
    "axes.titleweight": "bold",
    "grid.color": "#e5e5e5",
    "grid.linewidth": 0.6,
    "xtick.color": "#444",
    "ytick.color": "#444",
})

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import experiments.compare_models.handlers  # noqa: F401

from experiments.compare_models.self_consistency.analyze_helio_v2_report import (
    CALL_TYPE_HANDLER,
)
from experiments.compare_models.self_consistency.plot_substitution_decision_kappa import (
    CALL_TYPE_NAMES,
    compute,
)

TEST_SET_TAG = "test_set_helio_v2_2026_04_06"
OUT_BASENAME = (
    REPO_ROOT
    / "experiments"
    / "compare_models"
    / f"{TEST_SET_TAG}_substitution_bars"
)
THRESHOLD = 0.80

# Okabe-Ito palette — colorblind-safe, scientific-publishing standard.
COLOR_GPT = "#0072B2"    # blue  — gpt-5.4 intra
COLOR_OSS = "#E69F00"    # orange — gpt-oss-120b intra
COLOR_CROSS = "#009E73"  # bluish-green — cross-model


def build_rows():
    rows = []
    for ct in sorted(CALL_TYPE_HANDLER):
        r = compute(ct)
        if r is None:
            continue
        rows.append(
            dict(
                ct=ct,
                name=CALL_TYPE_NAMES.get(ct, ct),
                gpt=r["gpt_intra_k"],
                oss=r["oss_intra_k"],
                cross=r["cross_k"],
                gpt_ci=r["gpt_intra_ci"],
                oss_ci=r["oss_intra_ci"],
                cross_ci=r["cross_ci"],
                n=r["n"],
            )
        )
    # Best at top: sort descending by min(three kappas) — the weakest link.
    rows.sort(key=lambda r: min(r["gpt"], r["oss"], r["cross"]), reverse=True)
    return rows


def plot(rows):
    n = len(rows)
    fig, ax = plt.subplots(figsize=(13, 11))

    # Landis-Koch background tinting — muted so it doesn't compete with bars
    ax.axvspan(-0.1, 0.6, facecolor="#fde8e8", alpha=0.35, zorder=0)
    ax.axvspan(0.6, 0.8, facecolor="#fdf3e0", alpha=0.35, zorder=0)
    ax.axvspan(0.8, 1.05, facecolor="#e4efe3", alpha=0.25, zorder=0)

    # Reference lines
    ax.axvline(
        THRESHOLD, color="black", linestyle="--", linewidth=1.4,
        alpha=0.75, zorder=2,
    )
    ax.axvline(
        0.6, color="#666", linestyle=":", linewidth=1.1, alpha=0.55, zorder=2,
    )
    ax.axvline(0, color="#bbb", linewidth=0.6, zorder=1)

    # Geometry: 3 bars per call type, grouped
    row_spacing = 1.3
    y_positions = np.arange(n) * row_spacing
    bar_h = 0.30
    offset = bar_h * 1.05  # gap between bars within a group

    gpt_y = y_positions + offset
    oss_y = y_positions
    cross_y = y_positions - offset

    gpt_vals = [r["gpt"] for r in rows]
    oss_vals = [r["oss"] for r in rows]
    cross_vals = [r["cross"] for r in rows]
    gpt_cis = [r["gpt_ci"] for r in rows]
    oss_cis = [r["oss_ci"] for r in rows]
    cross_cis = [r["cross_ci"] for r in rows]

    def _err(vals, cis):
        """Convert list of (lo, hi) CIs to matplotlib xerr array (lower, upper) offsets."""
        lower = np.array([max(0.0, v - ci[0]) for v, ci in zip(vals, cis)])
        upper = np.array([max(0.0, ci[1] - v) for v, ci in zip(vals, cis)])
        return np.array([lower, upper])

    for y, vals, cis, color in [
        (gpt_y,   gpt_vals,   gpt_cis,   COLOR_GPT),
        (oss_y,   oss_vals,   oss_cis,   COLOR_OSS),
        (cross_y, cross_vals, cross_cis, COLOR_CROSS),
    ]:
        ax.barh(
            y, vals, height=bar_h * 0.94,
            color=color, edgecolor="black", linewidth=0.6,
            xerr=_err(vals, cis),
            error_kw=dict(ecolor="#222", elinewidth=1.0, capsize=3, capthick=0.9),
            zorder=3,
        )

    # Y-axis labels: call-type name + N
    ax.set_yticks(y_positions)
    ax.set_yticklabels(
        [f"{r['name']}\n(N={r['n']})" for r in rows],
        fontsize=10.5,
    )
    ax.invert_yaxis()  # best at top

    ax.set_xlim(-0.05, 1.12)
    # Give extra headroom above and below for annotations
    ax.set_ylim(
        y_positions[-1] + offset + bar_h * 2.5,   # bottom (for LK region labels)
        y_positions[0]  - offset - bar_h * 3.5,   # top (for threshold labels)
    )
    ax.set_xlabel("Fleiss' / Cohen's κ", fontsize=12, fontweight="bold")
    ax.set_title(
        "Substitution decision — kappa breakdown per call type\n"
        f"{TEST_SET_TAG}   •   safe swap = all three bars clear κ = 0.80"
        "   •   error bars: 95% bootstrap CI",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax.grid(axis="x", alpha=0.3, zorder=1)

    # Text annotations on the reference lines (above the top row, in the headroom)
    top_y = y_positions[0] - offset - bar_h * 1.8
    ax.text(
        THRESHOLD + 0.005, top_y, "  κ = 0.80  decision threshold",
        fontsize=10, fontweight="bold", color="#111",
        va="center", ha="left",
    )
    ax.text(
        0.6 + 0.005, top_y, "  κ = 0.60  substantial",
        fontsize=9, color="#444", va="center", ha="left",
    )

    # Landis-Koch region labels along the bottom
    bot_y = y_positions[-1] + offset + bar_h * 1.9
    ax.text(0.3, bot_y, "< 0.6 reinspect",
            fontsize=9, color="#7a1f1f", va="center", ha="center",
            fontweight="bold", alpha=0.8)
    ax.text(0.7, bot_y, "0.6–0.8 substantial",
            fontsize=9, color="#7d5b00", va="center", ha="center",
            fontweight="bold", alpha=0.8)
    ax.text(0.93, bot_y, "≥ 0.80 almost perfect",
            fontsize=9, color="#2d662d", va="center", ha="center",
            fontweight="bold", alpha=0.8)

    # Legend
    legend_handles = [
        Patch(facecolor=COLOR_GPT, edgecolor="black",
              label="gpt-5.4  intra-κ  (self-consistency)"),
        Patch(facecolor=COLOR_OSS, edgecolor="black",
              label="gpt-oss-120b  intra-κ  (self-consistency)"),
        Patch(facecolor=COLOR_CROSS, edgecolor="black",
              label="cross  κ  (single-run gpt-5.4 ↔ gpt-oss-120b)"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper center", bbox_to_anchor=(0.5, -0.06),
        ncol=3, fontsize=10, framealpha=0.96,
    )

    plt.tight_layout()
    return fig


def main():
    rows = build_rows()
    print(f"{'call_type':26s}  {'κ gpt':>7s}  {'κ oss':>7s}  {'κ cross':>8s}  {'min':>6s}  {'N':>4s}")
    for r in rows:
        m = min(r["gpt"], r["oss"], r["cross"])
        print(f"{r['ct']:26s}  {r['gpt']:7.3f}  {r['oss']:7.3f}  {r['cross']:8.3f}  {m:6.3f}  {r['n']:4d}")

    fig = plot(rows)
    out_png = OUT_BASENAME.with_suffix(".png")
    out_pdf = OUT_BASENAME.with_suffix(".pdf")
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"\nSaved {out_png}")
    print(f"Saved {out_pdf}")


if __name__ == "__main__":
    main()
