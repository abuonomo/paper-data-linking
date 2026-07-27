#!/usr/bin/env python3
"""Substitution-decision kappa plot with Landis-Koch band coloring.

Background: each cell colored by the Landis-Koch interpretation band of
min(cross_kappa, oss_intra_kappa) — the weakest-link kappa. A swap is safe
only when *both* cross-model and intra-model kappa clear the bar, so the
binding constraint is the minimum.

Decision threshold: dashed lines at κ=0.8 on each axis define the
"SWAP FREELY" top-right quadrant. Call-type points labeled with their
numeric kappa so the reader can read exact values without hovering.

Two panels:
  - left: full range (-0.05 to 1.02) showing all 10 call types + the
    mission_identification outlier
  - right: zoomed top quadrant (0.65 to 1.00) where 8 of 10 points cluster

Requires results under experiments/compare_models/self_consistency/results/
and the per-call-type handlers from experiments.compare_models.handlers.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.lines import Line2D

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import experiments.compare_models.handlers  # noqa: F401

from experiments.compare_models.self_consistency.analyze_helio_v2_report import (
    CALL_TYPE_HANDLER,
    fleiss_kappa,
    is_null_canonical,
    try_parse,
)

TEST_SET_TAG = "test_set_helio_v2_2026_04_06"
RESULTS_DIR = REPO_ROOT / "experiments" / "compare_models" / "self_consistency" / "results" / TEST_SET_TAG
MODEL_SLUGS = {
    "gpt-5.4": "openai_gpt-5_4",
    "gpt-oss-120b": "bedrock_converse_openai_gpt-oss-120b-1_0",
}
THRESHOLD = 0.8

OUT_BASENAME = REPO_ROOT / "experiments" / "compare_models" / f"{TEST_SET_TAG}_substitution_decision_kappa"

CALL_TYPE_NAMES = {
    "mission_identification": "Mission ID",
    "physobs_normalization": "Physical Observable",
    "time_normalization": "Time Range",
    "detector_normalization": "Detector",
    "instrument_selection": "Instrument Selection",
    "mission_selection": "Mission Selection",
    "cadence_normalization": "Cadence",
    "wavelength_normalization": "Wavelength",
    "instrument_validation": "Instrument Validation",
    "mission_validation": "Mission Validation",
}

# Landis-Koch bands with conventional red→green ramp.
LK_BANDS = [
    (-np.inf, 0.0, "#9a9a9a", "< 0 worse than chance"),
    (0.0, 0.2, "#d73027", "0.0–0.2 slight"),
    (0.2, 0.4, "#fc8d59", "0.2–0.4 fair"),
    (0.4, 0.6, "#fee090", "0.4–0.6 moderate"),
    (0.6, 0.8, "#d9ef8b", "0.6–0.8 substantial"),
    (0.8, 1.0 + 1e-9, "#1a9850", "0.8–1.0 almost perfect"),
]
LK_BOUNDS = [b[0] for b in LK_BANDS] + [LK_BANDS[-1][1]]
LK_COLORS = [b[2] for b in LK_BANDS]
LK_CMAP = ListedColormap(LK_COLORS)
LK_NORM = BoundaryNorm(LK_BOUNDS, LK_CMAP.N)


# ---------------------------------------------------------------------------
# Data loading / metric computation (unchanged from previous version)
# ---------------------------------------------------------------------------


def load_runs(call_type, model_slug):
    base = RESULTS_DIR / model_slug / call_type
    if not base.exists():
        return {}
    cases = defaultdict(list)
    for run_dir in sorted(base.glob("run*")):
        files = sorted(run_dir.glob("*.jsonl"))
        if not files:
            continue
        for jsonl_file in files:
            with open(jsonl_file) as f:
                for line in f:
                    rec = json.loads(line)
                    cid = rec.get("original_id") or rec.get("case_index")
                    if cid is None:
                        continue
                    canonical, ok = try_parse(call_type, rec.get("output_content", ""))
                    cases[cid].append(canonical if ok else f"__parse_error__{rec.get('custom_id', '')}")
    return {cid: r for cid, r in cases.items() if len(r) == 5}


def cohens_kappa(rater1, rater2):
    assert len(rater1) == len(rater2)
    n = len(rater1)
    if n == 0:
        return float("nan")
    cats = sorted(set(rater1) | set(rater2))
    c2i = {c: i for i, c in enumerate(cats)}
    mat = np.zeros((len(cats), len(cats)), dtype=int)
    for r1, r2 in zip(rater1, rater2):
        mat[c2i[r1], c2i[r2]] += 1
    po = np.trace(mat) / n
    row = mat.sum(axis=1) / n
    col = mat.sum(axis=0) / n
    pe = float(np.sum(row * col))
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def cohens_kappa_single_run(gpt_runs_by_case, oss_runs_by_case):
    """Cross-model κ for the production scenario where each request is run once.

    Builds the full pairwise confusion: every (gpt_run_i, oss_run_j) pair
    across all cases contributes one observation (25 per case × |cases|).
    This captures what a single production run of one model would look
    like compared to a single run of the other — unlike the modal-vs-modal
    version which hides within-model noise.
    """
    r1, r2 = [], []
    for cid in set(gpt_runs_by_case) & set(oss_runs_by_case):
        for g in gpt_runs_by_case[cid]:
            for o in oss_runs_by_case[cid]:
                r1.append(g)
                r2.append(o)
    if not r1:
        return float("nan")
    return cohens_kappa(r1, r2)


def modal(runs):
    return Counter(runs).most_common(1)[0][0]


def is_all_null(call_type, runs):
    return all(is_null_canonical(call_type, r) for r in runs)


def _bootstrap_kappas(gpt_sub, oss_sub, n_boot=2000, seed=42):
    """Bootstrap 95% CIs for the three κ values by resampling cases with
    replacement. Returns {key: (lo, hi)} for each κ we report."""
    rng = np.random.default_rng(seed)
    case_ids = list(gpt_sub.keys())
    n = len(case_ids)
    if n == 0:
        return {k: (float("nan"), float("nan")) for k in ("gpt_intra", "oss_intra", "cross")}

    gpt_samples, oss_samples, cross_samples = [], [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        resampled_ids = [case_ids[i] for i in idx]
        # Keys must be unique for dict-based κ helpers; re-key to index.
        gpt_b = {i: gpt_sub[cid] for i, cid in enumerate(resampled_ids)}
        oss_b = {i: oss_sub[cid] for i, cid in enumerate(resampled_ids)}
        gpt_samples.append(fleiss_kappa(gpt_b))
        oss_samples.append(fleiss_kappa(oss_b))
        cross_samples.append(cohens_kappa_single_run(gpt_b, oss_b))

    def ci(arr):
        arr = np.asarray(arr)
        arr = arr[~np.isnan(arr)]
        if len(arr) == 0:
            return (float("nan"), float("nan"))
        return (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))

    return {
        "gpt_intra": ci(gpt_samples),
        "oss_intra": ci(oss_samples),
        "cross": ci(cross_samples),
    }


def compute(call_type, n_boot=2000):
    gpt = load_runs(call_type, MODEL_SLUGS["gpt-5.4"])
    oss = load_runs(call_type, MODEL_SLUGS["gpt-oss-120b"])
    common = sorted(set(gpt) & set(oss))
    sub_ids = [
        cid for cid in common
        if not (is_all_null(call_type, gpt[cid])
                and is_all_null(call_type, oss[cid]))
    ]
    if not sub_ids:
        return None
    gpt_sub = {cid: gpt[cid] for cid in sub_ids}
    oss_sub = {cid: oss[cid] for cid in sub_ids}
    # Single-run cross κ — the production-relevant measure. Each inference
    # is one call in production; we should compare single gpt run vs
    # single oss run pairwise, not collapse each model to its 5-run modal.
    cross_k = cohens_kappa_single_run(gpt_sub, oss_sub)
    # Kept around for reference (not shown in the plot any more)
    modal_cross_k = cohens_kappa(
        [modal(gpt[cid]) for cid in sub_ids],
        [modal(oss[cid]) for cid in sub_ids],
    )
    oss_intra = fleiss_kappa(oss_sub)
    gpt_intra = fleiss_kappa(gpt_sub)
    cis = _bootstrap_kappas(gpt_sub, oss_sub, n_boot=n_boot) if n_boot else None
    return {
        "n": len(sub_ids),
        "cross_k": cross_k,
        "modal_cross_k": modal_cross_k,
        "oss_intra_k": oss_intra,
        "gpt_intra_k": gpt_intra,
        "gpt_intra_ci": cis["gpt_intra"] if cis else None,
        "oss_intra_ci": cis["oss_intra"] if cis else None,
        "cross_ci": cis["cross"] if cis else None,
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def paint_background(ax, xlim, ylim, resolution=300):
    """Paint the Landis-Koch heatmap: color = band of min(x, y)."""
    xs = np.linspace(xlim[0], xlim[1], resolution)
    ys = np.linspace(ylim[0], ylim[1], resolution)
    X, Y = np.meshgrid(xs, ys)
    min_kappa = np.minimum(X, Y)
    ax.pcolormesh(X, Y, min_kappa, cmap=LK_CMAP, norm=LK_NORM,
                  shading="auto", alpha=0.55, zorder=0, rasterized=True)


def draw_decision_lines(ax, xlim, ylim):
    ax.axvline(THRESHOLD, color="black", linestyle="--", linewidth=1.3, alpha=0.75, zorder=2)
    ax.axhline(THRESHOLD, color="black", linestyle="--", linewidth=1.3, alpha=0.75, zorder=2)
    # y = x reference
    dlo = max(xlim[0], ylim[0])
    dhi = min(xlim[1], ylim[1])
    ax.plot([dlo, dhi], [dlo, dhi], color="gray", linestyle=":", linewidth=1, alpha=0.5, zorder=1)


def plot_numbered(ax, pts, show_outlier_label=False):
    """Plot each point as a numbered marker. No per-point text labels —
    identity is resolved via the side legend table.

    pts: list of dicts with keys {ct, x, y, n, rank}
    show_outlier_label: if True, still draw a text label for the outlier
                        call-type (Mission ID) since it's visually alone.
    """
    for p in pts:
        ax.scatter(p["x"], p["y"], s=360, color="white", edgecolor="black",
                   linewidth=1.4, zorder=5)
        ax.text(p["x"], p["y"], str(p["rank"]),
                ha="center", va="center", fontsize=11, fontweight="bold",
                color="#222", zorder=6)
        if show_outlier_label and p["ct"] == "mission_identification":
            ax.annotate(
                f"Mission ID  (κ_cross={p['x']:.2f})",
                xy=(p["x"], p["y"]),
                xytext=(22, 0), textcoords="offset points",
                fontsize=10, fontweight="bold", ha="left", va="center",
                zorder=7,
                bbox=dict(boxstyle="round,pad=0.35",
                          facecolor="white", edgecolor="#555", alpha=0.95),
                arrowprops=dict(arrowstyle="-", color="#555", linewidth=0.8,
                                shrinkA=2, shrinkB=8),
            )




def lk_band_for_kappa(k):
    """Return the Landis-Koch color for a kappa value."""
    for lo, hi, color, _ in LK_BANDS:
        if lo <= k < hi:
            return color
    return "#cccccc"


def plot(rows):
    fig = plt.figure(figsize=(20, 9))
    # Three columns: full panel, zoom panel, legend table
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.0, 1.05], wspace=0.25)
    ax_full = fig.add_subplot(gs[0, 0])
    ax_zoom = fig.add_subplot(gs[0, 1])
    ax_legend = fig.add_subplot(gs[0, 2])
    ax_legend.axis("off")

    # rows: list of (call_type, cross_k, oss_intra_k, n, gpt_intra_k)
    sorted_rows = sorted(
        [r for r in rows if not np.isnan(r[1]) and not np.isnan(r[2])],
        key=lambda r: (-r[1], -r[2]),
    )
    pts = []
    for i, row in enumerate(sorted_rows, start=1):
        ct, x, y, n = row[:4]
        gpt_intra = row[4] if len(row) > 4 else float("nan")
        pts.append(dict(ct=ct, x=x, y=y, n=n, gpt_intra=gpt_intra, rank=i))

    # --- Full range panel ----------------------------------------------------
    full_xlim = (-0.05, 1.03)
    full_ylim = (-0.05, 1.03)
    paint_background(ax_full, full_xlim, full_ylim)
    draw_decision_lines(ax_full, full_xlim, full_ylim)

    zoom_xlim = (0.65, 1.02)
    zoom_ylim = (0.65, 1.02)
    ax_full.add_patch(plt.Rectangle(
        (zoom_xlim[0], zoom_ylim[0]),
        zoom_xlim[1] - zoom_xlim[0], zoom_ylim[1] - zoom_ylim[0],
        fill=False, edgecolor="#c62828", linewidth=1.6, linestyle="--", zorder=3,
    ))
    ax_full.annotate(
        "zoomed →",
        xy=(zoom_xlim[1], (zoom_ylim[0] + zoom_ylim[1]) / 2),
        xytext=(6, 0), textcoords="offset points",
        color="#c62828", fontsize=10, fontweight="bold", va="center", ha="left", zorder=4,
    )

    plot_numbered(ax_full, pts, show_outlier_label=True)

    ax_full.set_xlim(full_xlim)
    ax_full.set_ylim(full_ylim)
    ax_full.set_aspect("equal", adjustable="box")
    ax_full.set_xlabel("Single-run cross-model agreement   Cohen's κ\n(one gpt-5.4 run vs one gpt-oss-120b run, pairwise)", fontsize=11)
    ax_full.set_ylabel("Candidate internal stability   Fleiss' κ\n(gpt-oss-120b across its 5 runs)", fontsize=11)
    ax_full.set_title("Full range", fontsize=12, fontweight="bold")
    ax_full.grid(alpha=0.2, zorder=1)

    # --- Zoomed panel --------------------------------------------------------
    paint_background(ax_zoom, zoom_xlim, zoom_ylim)
    draw_decision_lines(ax_zoom, zoom_xlim, zoom_ylim)

    zoom_pts = [p for p in pts if zoom_xlim[0] <= p["x"] <= zoom_xlim[1]
                               and zoom_ylim[0] <= p["y"] <= zoom_ylim[1]]
    plot_numbered(ax_zoom, zoom_pts)

    ax_zoom.set_xlim(zoom_xlim)
    ax_zoom.set_ylim(zoom_ylim)
    ax_zoom.set_aspect("equal", adjustable="box")
    ax_zoom.set_xlabel("Single-run cross-model agreement   Cohen's κ", fontsize=11)
    ax_zoom.set_ylabel("Candidate internal stability   Fleiss' κ", fontsize=11)
    ax_zoom.set_title("Top quadrant (0.65–1.00)", fontsize=12, fontweight="bold")
    ax_zoom.grid(alpha=0.2, zorder=1)

    # --- Legend / data table -------------------------------------------------
    ax_legend.set_xlim(0, 1)
    ax_legend.set_ylim(0, 1)

    n_rows = len(pts)
    table_top = 0.97
    table_bot = 0.40
    row_h = (table_top - table_bot) / (n_rows + 1)

    header_y = table_top
    col_x = {
        "num":    0.02,
        "name":   0.09,
        "cross":  0.46,
        "gpt":    0.62,
        "oss":    0.78,
        "n":      0.94,
    }

    ax_legend.text(0.5, 0.995, "Call types (sorted by κ_cross)",
                   ha="center", va="top", fontsize=12, fontweight="bold",
                   transform=ax_legend.transAxes)
    # Column headers
    ax_legend.text(col_x["num"],   header_y, "#",             fontsize=10, fontweight="bold", va="center")
    ax_legend.text(col_x["name"],  header_y, "Call type",     fontsize=10, fontweight="bold", va="center")
    ax_legend.text(col_x["cross"], header_y, "κ cross",       fontsize=10, fontweight="bold", va="center", ha="right")
    ax_legend.text(col_x["gpt"],   header_y, "κ intra\ngpt-5.4",  fontsize=9, fontweight="bold", va="center", ha="right")
    ax_legend.text(col_x["oss"],   header_y, "κ intra\n120b",     fontsize=9, fontweight="bold", va="center", ha="right")
    ax_legend.text(col_x["n"],     header_y, "N",             fontsize=10, fontweight="bold", va="center", ha="right")
    ax_legend.plot([0.01, 0.99], [header_y - row_h * 0.5] * 2,
                   color="#999", linewidth=0.8, transform=ax_legend.transAxes)

    for i, p in enumerate(pts):
        y = header_y - row_h * (i + 1)
        # Row tint: verdict based on the weakest of ALL THREE kappas
        # (cross, gpt-intra, oss-intra). Weakest-link logic.
        kappas = [p["x"], p["y"]]
        if not np.isnan(p["gpt_intra"]):
            kappas.append(p["gpt_intra"])
        min_k = min(kappas)
        row_bg = "#e8f5e9" if min_k >= THRESHOLD else "#fff3e0" if min_k >= 0.6 else "#ffebee"

        ax_legend.add_patch(plt.Circle(
            (col_x["num"] + 0.02, y),
            0.012, facecolor="white", edgecolor="black", linewidth=1.2,
            transform=ax_legend.transAxes,
        ))
        ax_legend.text(col_x["num"] + 0.02, y, str(p["rank"]),
                       fontsize=10, fontweight="bold", ha="center", va="center",
                       transform=ax_legend.transAxes)
        ax_legend.add_patch(plt.Rectangle(
            (col_x["name"] - 0.005, y - row_h * 0.38),
            1.0 - col_x["name"] + 0.005, row_h * 0.76,
            facecolor=row_bg, edgecolor="none", alpha=0.55, zorder=0,
            transform=ax_legend.transAxes,
        ))
        ax_legend.text(col_x["name"],  y, CALL_TYPE_NAMES[p["ct"]], fontsize=10, va="center")

        for key, val in [("cross", p["x"]), ("gpt", p["gpt_intra"]), ("oss", p["y"])]:
            if np.isnan(val):
                ax_legend.text(col_x[key], y, "—", fontsize=10, ha="right", va="center",
                               color="#999")
                continue
            color = lk_band_for_kappa(val)
            ax_legend.text(
                col_x[key], y, f"{val:.2f}",
                fontsize=10, fontweight="bold", ha="right", va="center",
                color="#000",
                bbox=dict(boxstyle="round,pad=0.18", facecolor=color,
                          edgecolor="none", alpha=0.85),
            )
        ax_legend.text(col_x["n"], y, str(p["n"]), fontsize=10, ha="right", va="center")

    # Landis-Koch swatch legend below the table
    lk_top = table_bot - 0.04
    ax_legend.text(0.5, lk_top + 0.02, "Kappa color scale (Landis-Koch)",
                   ha="center", va="bottom", fontsize=10, fontweight="bold",
                   transform=ax_legend.transAxes)
    swatch_w = 0.16
    for i, (_, _, color, label) in enumerate(LK_BANDS):
        y_sw = lk_top - 0.05 - (i * 0.05)
        ax_legend.add_patch(plt.Rectangle((0.02, y_sw - 0.015), 0.025, 0.03,
                                          facecolor=color, edgecolor="#666",
                                          linewidth=0.5,
                                          transform=ax_legend.transAxes))
        ax_legend.text(0.06, y_sw, label, fontsize=9, va="center",
                       transform=ax_legend.transAxes)

    # Decision-threshold explanation at the bottom
    ax_legend.text(
        0.5, 0.02,
        "Row tint: green = both κ ≥ 0.80 (safe swap)\n"
        "amber = 0.60–0.80 (substantial)   red = < 0.60 (re-inspect)",
        ha="center", va="bottom", fontsize=9, color="#555",
        transform=ax_legend.transAxes,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fafafa", edgecolor="#ccc"),
    )

    # Background-coloring note at the bottom of the plot panels
    fig.text(
        0.33, 0.015,
        "Background color in plots = Landis-Koch band of min(κ_cross, κ_intra) — "
        "the weakest-link kappa.   Dashed line: κ = 0.80 decision threshold.   "
        "Dotted diagonal: y = x.",
        ha="center", va="bottom", fontsize=9, color="#555",
    )

    fig.suptitle(
        f"Can gpt-oss-120b replace gpt-5.4?   substitution decision (kappa)\n"
        f"{TEST_SET_TAG}   •   κ ≥ 0.80 on both axes → safe swap",
        fontsize=14, fontweight="bold", y=0.99,
    )

    plt.subplots_adjust(bottom=0.08, top=0.9, left=0.05, right=0.98)
    return fig


def main():
    rows = []
    for ct in sorted(CALL_TYPE_HANDLER):
        r = compute(ct)
        if r is None:
            continue
        rows.append((ct, r["cross_k"], r["oss_intra_k"], r["n"], r["gpt_intra_k"]))

    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    print(f"{'call_type':30s}  {'cross_κ':>8s}  {'gpt_intra':>10s}  {'oss_intra':>10s}  {'N':>4s}")
    for ct, x, y, n, g in rows:
        print(f"{ct:30s}  {x:8.3f}  {g:10.3f}  {y:10.3f}  {n:4d}")

    fig = plot(rows)
    out_pdf = OUT_BASENAME.with_suffix(".pdf")
    out_png = OUT_BASENAME.with_suffix(".png")
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"\nSaved {out_pdf}")
    print(f"Saved {out_png}")


if __name__ == "__main__":
    main()
