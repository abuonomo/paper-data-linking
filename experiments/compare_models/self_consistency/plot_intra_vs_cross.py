#!/usr/bin/env python3
"""Reproduce the per_model_self_consistency.pdf style figure for our test set.

Reuses the Jaccard-similarity computation from
`viz/export_viz_data.py::compute_case_metrics` (so our metric matches the
production figure exactly) but pulls per-model intra-consistency values out
of the per-case metrics, which the existing summary.json only averages.

The plotting style mirrors
`paper-data-linking/docs/technical_report/exporters/model_comparison.py::_create_per_model_figure`
(two panels: full range + zoomed 75-100, GPT marker as filled circle and
Bedrock as X, horizontal connector, y=x diagonal).
"""

import importlib.util
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import experiments.compare_models.handlers  # noqa: F401 — register handlers

# Load export_viz_data and patch its globals for our test set / model config
spec = importlib.util.spec_from_file_location(
    "export_viz_data",
    Path(__file__).parent / "viz" / "export_viz_data.py",
)
evd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evd)

TEST_SET_TAG = "test_set_helio_v2_2026_04_06"
MODELS = [
    "openai/gpt-5.4",
    "bedrock/converse/openai.gpt-oss-120b-1:0",
]

# Add mission_validation to the configs (not present in the original test set)
evd.TEST_SET_TAG = TEST_SET_TAG
evd.MODELS = MODELS
evd.CALL_TYPES = list(evd.CALL_TYPES) + ["mission_validation"]
evd.HANDLER_MAP = {**evd.HANDLER_MAP, "mission_validation": "MissionValidationHandler"}
evd.RESPONSE_KEYS = {**evd.RESPONSE_KEYS, "mission_validation": "validation_result"}
evd.TASK_TYPES = {**evd.TASK_TYPES, "mission_validation": "binary"}

# is_null_response in export_viz_data doesn't have a branch for mission_validation;
# binary task has no null answer so we patch with constant False.
_orig_is_null = evd.is_null_response
def _is_null(output_content, call_type):
    if call_type == "mission_validation":
        return False
    # Strip reasoning wrapper before delegating to the original null check
    return _orig_is_null(_strip_reasoning(output_content or ""), call_type)


# gpt-oss-120b wraps its answer in <reasoning>...</reasoning><answer>.
# The handlers' parse_response treats the whole string as the answer and
# returns garbage, killing both intra and cross agreement metrics.
# Wrap each handler's parse_response to strip the wrapper first.
import re as _re

_FENCE_RE = _re.compile(r'```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```')
_VERDICT_RE = _re.compile(r'FINAL\s+DECISION[:\*\s]*(valid|invalid)', _re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    if '</reasoning>' in text:
        text = text.split('</reasoning>', 1)[1]
    elif text.lstrip().startswith('<reasoning>'):
        return ''
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


_orig_load_handler = evd.load_handler


def _patched_load_handler(call_type):
    handler = _orig_load_handler(call_type)
    orig = handler.parse_response

    def parse(text):
        stripped = _strip_reasoning(text or "")
        result = orig(stripped)
        # validation handlers' regex misses `**FINAL DECISION:** valid` — fall
        # back to the tolerant regex when the handler returns None.
        if result is None and call_type in ("instrument_validation", "mission_validation"):
            m = _VERDICT_RE.search(stripped)
            if m:
                return m.group(1).lower()
        return result

    handler.parse_response = parse
    return handler


evd.load_handler = _patched_load_handler


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

OUT_BASENAME = REPO_ROOT / "experiments" / "compare_models" / f"{TEST_SET_TAG}_per_model_self_consistency"


def per_model_self_consistency(case_metrics):
    """Compute per-model intra agreement (mean over cases) for each call type.

    Returns: {call_type: {model: float (0-100)}}
    """
    result = {}
    for ct, cases in case_metrics.items():
        per_model = {m: [] for m in MODELS}
        for cm in cases.values():
            for m in MODELS:
                if m in cm["models"]:
                    per_model[m].append(cm["models"][m]["self_consistency"])
        result[ct] = {
            m: float(np.mean(vals)) * 100 if vals else float("nan")
            for m, vals in per_model.items()
        }
    return result


def cross_model_per_call_type(case_metrics):
    """Mean cross-model Jaccard per call type (matches existing summary)."""
    return {
        ct: float(np.mean([
            cm["cross_model_agreement"] for cm in cases.values()
            if cm.get("cross_model_agreement") is not None
        ])) * 100
        for ct, cases in case_metrics.items()
    }


def plot(records):
    """records: list of (call_type, gpt_intra, bedrock_intra, cross)"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    zoom_min = 75

    for ax, xlim, ylim, is_zoomed in [
        (ax1, (0, 102), (0, 102), False),
        (ax2, (zoom_min, 102), (zoom_min, 102), True),
    ]:
        for call_type, gpt_sc, oss_sc, cross in records:
            label = CALL_TYPE_NAMES.get(call_type, call_type)

            ax.scatter(gpt_sc, cross, marker='o', c='blue', s=120,
                       alpha=0.7, edgecolors='black', linewidths=1.5,
                       clip_on=False, zorder=5)
            ax.scatter(oss_sc, cross, marker='X', c='orange', s=150,
                       alpha=0.9, edgecolors='black', linewidths=1,
                       clip_on=False, zorder=6)
            ax.plot([gpt_sc, oss_sc], [cross, cross],
                    color='gray', alpha=0.3, linewidth=1)

            if is_zoomed:
                x_mid = (gpt_sc + oss_sc) / 2
                if call_type == 'cadence_normalization':
                    ax.annotate(label, (min(gpt_sc, oss_sc), cross),
                                textcoords="offset points", xytext=(-8, 0),
                                fontsize=9, ha='right', fontweight='bold')
                else:
                    ax.annotate(label, (x_mid, cross),
                                textcoords="offset points", xytext=(0, 8),
                                fontsize=9, ha='center', fontweight='bold')
            elif call_type == 'mission_identification':
                x_mid = (gpt_sc + oss_sc) / 2
                ax.annotate(label, (x_mid, cross),
                            textcoords="offset points", xytext=(0, 8),
                            fontsize=9, ha='center', fontweight='bold')

        ax.plot([0, 102], [0, 102], color='gray', linestyle=':',
                alpha=0.6, linewidth=1.5)
        ax.axvline(x=100, color='black', linewidth=1, linestyle='-', alpha=0.5)
        ax.axhline(y=100, color='black', linewidth=1, linestyle='-', alpha=0.5)
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_aspect('equal', adjustable='box')
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('Intra-Model Agreement (Jaccard %)', fontsize=11)
        ax.set_ylabel('Cross-Model Agreement (Jaccard %)', fontsize=11)

    rect = Rectangle((zoom_min, zoom_min), 100 - zoom_min, 100 - zoom_min,
                     linewidth=2, edgecolor='red', facecolor='none',
                     linestyle='--', alpha=0.8)
    ax1.add_patch(rect)

    ax1.set_title('Full Range (0-100%)', fontsize=12)
    ax2.set_title('Top Quadrant (75-100%)', fontsize=12)

    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor='blue',
               markersize=10, markeredgecolor='black', label='GPT-5.4'),
        Line2D([0], [0], marker='X', color='w', markerfacecolor='orange',
               markersize=11, markeredgecolor='black', label='Bedrock gpt-oss-120b'),
        Line2D([0], [0], color='gray', linestyle=':', linewidth=1.5, label='y=x'),
    ]
    ax1.legend(handles=legend_elements, loc='lower right', fontsize=9)
    ax2.legend(handles=legend_elements, loc='lower right', fontsize=9)

    fig.suptitle(
        f'Intra-Model Agreement vs Cross-Model Agreement ({TEST_SET_TAG})\n'
        '(Horizontal spread = difference in model reliability)',
        fontsize=13, y=1.02,
    )
    plt.tight_layout()
    return fig


def main():
    print(f"Loading results for {TEST_SET_TAG} ...")
    all_data = evd.load_all_results()
    print("Computing case metrics ...")
    case_metrics = evd.compute_case_metrics(all_data)

    intra = per_model_self_consistency(case_metrics)
    cross = cross_model_per_call_type(case_metrics)

    records = [
        (ct, intra[ct][MODELS[0]], intra[ct][MODELS[1]], cross[ct])
        for ct in evd.CALL_TYPES
        if ct in intra and ct in cross
    ]
    # Sort by descending cross-model agreement (better tasks first)
    records.sort(key=lambda r: r[3], reverse=True)
    for ct, g, o, c in records:
        print(f"  {ct:30s}  gpt={g:5.1f}  oss={o:5.1f}  cross={c:5.1f}")

    fig = plot(records)
    out_pdf = OUT_BASENAME.with_suffix(".pdf")
    out_png = OUT_BASENAME.with_suffix(".png")
    fig.savefig(out_pdf, bbox_inches='tight')
    fig.savefig(out_png, bbox_inches='tight', dpi=150)
    plt.close(fig)
    print(f"\nSaved: {out_pdf}")
    print(f"Saved: {out_png}")


if __name__ == "__main__":
    main()
