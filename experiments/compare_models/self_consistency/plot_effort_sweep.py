#!/usr/bin/env python3
"""Plot the gpt-oss-120b reasoning-effort sweep: intra-model Fleiss kappa at
low/medium/high per call type, with the kappa=0.80 threshold.

Reads effort_sweep_summary.json (written by analyze_effort_sweep.py) and writes
docs/technical_report/figures/effort_sweep_kappa.{pdf,png}.

mission_identification is plotted but hatched + annotated: its kappa is a
list-length / instruction-following artifact (see paper text), not a reliability
signal, because the stage emits a variable-length 10-candidate ranking.
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
TEST_SET = "test_set_helio_v2_2026_04_06"
SUMMARY = (REPO_ROOT / "experiments" / "compare_models" / "self_consistency"
           / "results" / TEST_SET / "effort_sweep_summary.json")
FIG_DIR = REPO_ROOT / "docs" / "technical_report" / "figures"
THRESHOLD = 0.80
EFFORTS = ["low", "medium", "high"]
# Sequential single-hue (light->dark purple) to signal effort is ORDINAL and that
# this is one model varied by effort -- deliberately unlike the categorical
# blue/orange/teal palette of the cross-MODEL substitution figure.
COLORS = {"low": "#cbb8e0", "medium": "#9070b8", "high": "#4a2d7a"}
# Cross-effort agreement (vs high): distinct slate hue + hatch, so the two panels
# don't read as the same quantity.
CROSS_COLORS = {"low": "#9fc0d4", "medium": "#3a6b8a"}
ARTIFACT = {"mission_identification"}  # kappa misleading (variable-length list)

plt.rcParams.update({"font.size": 11})


def main():
    if not SUMMARY.exists():
        sys.exit(f"No summary at {SUMMARY} — run analyze_effort_sweep.py first.")
    rows = json.load(open(SUMMARY))

    # Sort: well-behaved stages by mean kappa desc; artifact rows pinned to bottom.
    def keyf(r):
        ks = [r["kappa_intra"].get(e) for e in EFFORTS if r["kappa_intra"].get(e) == r["kappa_intra"].get(e)]
        mean = sum(ks) / len(ks) if ks else 0
        return (r["call_type"] in ARTIFACT, -mean)
    rows = sorted(rows, key=keyf)

    labels = [r["call_type"].replace("_", " ") for r in rows]
    y = np.arange(len(rows))

    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13, 7), sharey=True,
        gridspec_kw={"width_ratios": [3, 2], "wspace": 0.08})

    def _xerr(metric, ci_key, eff):
        """Asymmetric x-error from the stored 95% bootstrap CI."""
        lo, hi = [], []
        for r in rows:
            v = r[metric].get(eff, float("nan"))
            c = r.get(ci_key, {}).get(eff, [float("nan"), float("nan")])
            if v == v and c[0] == c[0]:
                lo.append(max(0.0, v - c[0])); hi.append(max(0.0, c[1] - v))
            else:
                lo.append(0.0); hi.append(0.0)
        return [lo, hi]

    ekw = dict(elinewidth=0.7, capsize=2, ecolor="0.25")

    # --- Left panel: self-consistency (intra-kappa) by effort, 3 bars ---
    h = 0.26
    for i, eff in enumerate(EFFORTS):
        offset = (i - 1) * h
        vals = [r["kappa_intra"].get(eff, float("nan")) for r in rows]
        bars = axL.barh(y - offset, vals, height=h, label=eff,
                        color=COLORS[eff], edgecolor="black", linewidth=0.4,
                        xerr=_xerr("kappa_intra", "kappa_intra_ci", eff), error_kw=ekw)
        for b, r in zip(bars, rows):
            if r["call_type"] in ARTIFACT:
                b.set_hatch("xx")
    axL.axvline(THRESHOLD, ls="--", color="black", lw=1)
    axL.text(THRESHOLD + 0.01, len(rows) - 0.4, r"$\kappa=0.80$", fontsize=9, va="center")
    axL.set_yticks(y); axL.set_yticklabels(labels); axL.invert_yaxis()
    axL.set_xlabel(r"intra-model Fleiss' $\kappa$ (5 runs)")
    axL.set_xlim(0, 1.0)
    axL.set_title("Self-consistency by reasoning effort", fontsize=11)
    axL.legend(title="effort", loc="lower left", framealpha=0.95, fontsize=9)

    # --- Right panel: agreement with GPT-5.4 at each effort (the substitution metric) ---
    for i, eff in enumerate(EFFORTS):
        offset = (i - 1) * h
        vals = [r["kappa_vs_gpt5"].get(eff, float("nan")) for r in rows]
        bars = axR.barh(y - offset, vals, height=h, label=eff,
                        color=COLORS[eff], edgecolor="black", linewidth=0.4, hatch="//",
                        xerr=_xerr("kappa_vs_gpt5", "kappa_vs_gpt5_ci", eff), error_kw=ekw)
        for b, r in zip(bars, rows):
            if r["call_type"] in ARTIFACT:
                b.set_hatch("xx")
    axR.axvline(THRESHOLD, ls="--", color="black", lw=1)
    axR.text(THRESHOLD + 0.01, len(rows) - 0.4, r"$\kappa=0.80$", fontsize=9, va="center")
    axR.set_xlabel(r"Cohen's $\kappa$ vs GPT-5.4")
    axR.set_xlim(0, 1.0)
    axR.set_title("Substitutability (agreement with GPT-5.4)", fontsize=11)

    fig.suptitle("gpt-oss-120b reasoning-effort sweep (test_set_helio_v2_2026_04_06)",
                 fontsize=12, y=1.00)

    # Flag the artifact row on the left panel
    for i, r in enumerate(rows):
        if r["call_type"] in ARTIFACT:
            axL.text(0.03, i + 0.32, "list-length artifact (see text)", fontsize=7.5,
                     style="italic", va="center", color="dimgray")

    plt.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / "effort_sweep_kappa"
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"Wrote {out}.pdf / .png")


if __name__ == "__main__":
    main()
