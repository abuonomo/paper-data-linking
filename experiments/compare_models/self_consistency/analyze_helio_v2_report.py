#!/usr/bin/env python3
"""Generate the self-consistency report for test_set_helio_v2_2026_04_06.

For each (call_type, model) in the batch results directory, compute:
  - Fleiss' kappa across 5 runs
  - Parse rate (fraction of cases where response_format validates OR output is non-empty)
  - Perfect-consistency percentage
  - Realized cost (sum of per-request estimated_cost_usd from result JSONLs)

Writes a markdown report at
experiments/compare_models/test_set_helio_v2_2026_04_06_self_consistency_report.md
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Register handlers so we can use their parse_response methods
import experiments.compare_models.handlers  # noqa: F401
from experiments.compare_models.core.registry import CallTypeRegistry

# Map call_type -> handler class name (same as submit script)
CALL_TYPE_HANDLER = {
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

TEST_SET = "test_set_helio_v2_2026_04_06"
RESULTS_DIR = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'results' / TEST_SET
REPORT_PATH = REPO_ROOT / 'experiments' / 'compare_models' / f"{TEST_SET}_self_consistency_report.md"


def normalize_response(resp: str) -> str:
    return (resp or "").strip().lower()


def _normalize_iso_datetime(value):
    """Canonicalize ISO datetime strings so minor surface differences don't
    show up as disagreement. Specifically:
      - Strip trailing 'Z' (treat all times as UTC).
      - Strip trailing '+00:00' (equivalent to UTC).
      - Lowercase.
    """
    if not isinstance(value, str):
        return value
    v = value.strip()
    if v.endswith('+00:00'):
        v = v[:-6]
    if v.endswith('Z') or v.endswith('z'):
        v = v[:-1]
    return v.lower()


def normalize_parsed(parsed) -> str:
    """Convert a handler's parse_response result to a comparable canonical string."""
    if parsed is None:
        return ""
    if isinstance(parsed, dict):
        # mission_identification: compare on sorted set of indices + UNKNOWN flag
        if 'mission_indices' in parsed:
            if parsed.get('is_unknown'):
                return "UNKNOWN"
            return ",".join(str(i) for i in sorted(set(parsed['mission_indices'])))
        # Drop raw_response (contains surface-text variation from the model).
        # For time_normalization, also fall back to 'start'/'end' keys that
        # Bedrock produces when no response_format schema is enforced.
        # Drop fields that don't affect the actual parsed time range:
        # - raw_response: surface-text variation
        # - original_text: models echo different portions of the input (GPT
        #   trims to just the date, OSS echoes the full input) and use
        #   different Unicode whitespace — not a semantic difference
        # - is_approximate: prompt doesn't define what counts as approximate,
        #   so models disagree on edge cases ("~14:25", "during quiet times")
        #   without any difference in the parsed datetimes
        # - error_message: free-text string that varies in wording
        _drop = {'raw_response', 'original_text', 'is_approximate', 'error_message'}
        d = {k: v for k, v in parsed.items() if k not in _drop}
        if d.get('start_datetime') is None and 'raw_response' in parsed:
            try:
                raw = json.loads(parsed['raw_response'])
                if isinstance(raw, dict):
                    if 'start' in raw and d.get('start_datetime') is None:
                        d['start_datetime'] = raw.get('start')
                    if 'end' in raw and d.get('end_datetime') is None:
                        d['end_datetime'] = raw.get('end')
            except Exception:
                pass
        # Canonicalize time_normalization's datetime strings so `2020-01-01T00:00:00`
        # and `2020-01-01T00:00:00Z` compare equal (trailing-Z is just the UTC marker).
        if 'start_datetime' in d:
            d['start_datetime'] = _normalize_iso_datetime(d.get('start_datetime'))
        if 'end_datetime' in d:
            d['end_datetime'] = _normalize_iso_datetime(d.get('end_datetime'))
        # When both datetimes are null (error/unparseable case), precision
        # becomes meaningless — any `year`/`minute`/`unknown`/None is the
        # same "I couldn't parse the dates" answer.
        if ('start_datetime' in d and 'end_datetime' in d
                and d.get('start_datetime') is None and d.get('end_datetime') is None):
            if 'precision' in d:
                d['precision'] = None
            if 'is_approximate' in d:
                d['is_approximate'] = None
        return json.dumps(d, sort_keys=True).lower()
    if isinstance(parsed, str):
        return parsed.strip().lower()
    return str(parsed).strip().lower()


def _strip_reasoning(text: str) -> str:
    """Strip <reasoning>...</reasoning> wrappers and markdown code fences.

    gpt-oss-120b wraps answers in <reasoning>...</reasoning><answer>, and
    sometimes wraps JSON in ```json ... ``` code fences.
    """
    if '</reasoning>' in text:
        text = text.split('</reasoning>', 1)[1]
    elif text.lstrip().startswith('<reasoning>'):
        return ''
    text = text.strip()
    # Strip markdown code fence if it wraps a JSON object
    import re
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```', text)
    if m:
        return m.group(1).strip()
    # Also strip leading headings/prose before a bare JSON object
    m = re.search(r'(\{[\s\S]*\})\s*$', text)
    if m and text.lstrip().startswith(('**', '#', '-')):
        return m.group(1).strip()
    return text


_VERDICT_RE = re.compile(r'FINAL\s+DECISION[:\*\s]*(valid|invalid)', re.IGNORECASE)


def is_null_canonical(call_type: str, canonical: str) -> bool:
    """Is this canonical answer the model's "I don't know / not applicable" refusal?

    Binary-classification call types (instrument_validation, mission_validation)
    never have a null option. Selection indices of 0 could mean "no match" but
    we conservatively treat them as substantive picks.
    """
    if not canonical:
        return False
    c = canonical.strip().lower()
    if call_type == 'mission_identification':
        return c == 'unknown'
    if call_type == 'cadence_normalization':
        return c == '{"cadences": []}'
    if call_type == 'detector_normalization':
        return '"detector": "uncertain"' in c
    if call_type == 'physobs_normalization':
        return '"physical_observable": "uncertain"' in c
    if call_type == 'wavelength_normalization':
        return '"type": "not_applicable"' in c
    if call_type == 'time_normalization':
        # error=true OR both start and end are null
        if '"error": true' in c:
            return True
        if '"start_datetime": null' in c and '"end_datetime": null' in c:
            return True
        return False
    # instrument_validation, mission_validation, mission_selection,
    # instrument_selection: treat every parsed answer as substantive
    return False


def try_parse(call_type: str, output_content: str):
    """Use the registered handler.parse_response() to extract the canonical answer.

    Returns (canonical_string, did_parse: bool).
    """
    if not output_content or not output_content.strip():
        return "", False
    # Strip gpt-oss-120b reasoning wrapper if present
    content = _strip_reasoning(output_content)
    if not content.strip():
        return "", False
    handler_class = CALL_TYPE_HANDLER.get(call_type)
    if handler_class is None:
        return content.strip().lower(), True
    handler = CallTypeRegistry.get_by_class_name(handler_class)
    parsed = handler.parse_response(content)
    if parsed is None:
        # Fallback for validation call types: the handler's regex doesn't
        # tolerate `**FINAL DECISION:** valid` (space between ** and the verdict).
        # About 6% of bedrock gpt-oss-120b outputs hit this format.
        if call_type in ('instrument_validation', 'mission_validation'):
            m = _VERDICT_RE.search(content)
            if m:
                return m.group(1).lower(), True
        return "", False
    return normalize_parsed(parsed), True


def fleiss_kappa(responses_by_case: dict) -> float:
    """Compute Fleiss' kappa across cases. responses_by_case: {case_id: [resp1, ..., respN]}"""
    n_cases = len(responses_by_case)
    if n_cases == 0:
        return float('nan')
    n_raters = len(next(iter(responses_by_case.values())))

    all_responses = set()
    for responses in responses_by_case.values():
        all_responses.update(responses)
    categories = sorted(all_responses)
    if len(categories) == 0:
        return float('nan')
    cat_idx = {c: i for i, c in enumerate(categories)}

    matrix = np.zeros((n_cases, len(categories)), dtype=int)
    for i, (_, responses) in enumerate(sorted(responses_by_case.items())):
        for r in responses:
            matrix[i, cat_idx[r]] += 1

    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1)) if n_raters > 1 else np.ones(n_cases)
    P_bar = float(np.mean(P_i))
    p_j = np.sum(matrix, axis=0) / (n_cases * n_raters)
    P_e = float(np.sum(p_j ** 2))
    if P_e >= 1.0:
        return 1.0
    return (P_bar - P_e) / (1 - P_e)


def analyze_call_type(call_type_dir: Path, call_type: str):
    """Analyze one (model, call_type) result set."""
    run_dirs = sorted(call_type_dir.glob("run*"))
    if not run_dirs:
        return None

    n_runs = len(run_dirs)
    cases = defaultdict(list)   # case_id -> list of normalized responses
    parse_stats = defaultdict(lambda: {'ok': 0, 'total': 0})  # case_id -> counts
    total_cost = 0.0
    total_tokens = 0

    for run_dir in run_dirs:
        jsonl_files = sorted(run_dir.glob("*.jsonl"))
        if not jsonl_files:
            continue
        for jsonl_file in jsonl_files:
            with open(jsonl_file) as f:
                for line in f:
                    rec = json.loads(line)
                    case_id = rec.get('original_id') or rec.get('case_index')
                    if case_id is None:
                        continue
                    output = rec.get('output_content') or rec.get('response') or ''
                    canonical, did_parse = try_parse(call_type, output)
                    parse_stats[case_id]['total'] += 1
                    if did_parse:
                        parse_stats[case_id]['ok'] += 1
                    # Use canonical parsed form so kappa reflects semantic agreement,
                    # not surface-text variation.
                    norm = canonical if did_parse else f"__parse_error_{rec.get('custom_id', '')}"
                    cases[case_id].append(norm)
                    total_cost += rec.get('estimated_cost_usd', 0) or 0
                    total_tokens += rec.get('total_tokens', 0) or 0

    # Only cases with all n_runs responses
    complete = {cid: resps for cid, resps in cases.items() if len(resps) == n_runs}

    # Parse rate: fraction of (case, run) pairs where parse succeeded
    total_attempts = sum(s['total'] for s in parse_stats.values())
    total_ok = sum(s['ok'] for s in parse_stats.values())
    parse_rate = total_ok / total_attempts if total_attempts else float('nan')

    # Perfect consistency
    n_perfect = sum(1 for resps in complete.values() if len(set(resps)) == 1)

    kappa = fleiss_kappa(complete)

    # Substantive-only view: drop cases where every run returned the null/refusal
    substantive = {
        cid: resps for cid, resps in complete.items()
        if not all(is_null_canonical(call_type, r) for r in resps)
    }
    null_only_cases = len(complete) - len(substantive)
    sub_kappa = fleiss_kappa(substantive) if substantive else float('nan')
    sub_perfect = sum(1 for resps in substantive.values() if len(set(resps)) == 1)
    sub_perfect_pct = (sub_perfect / len(substantive) * 100) if substantive else float('nan')

    # Also count "null rate" — fraction of individual responses that were null
    null_resp_count = sum(
        1 for resps in complete.values() for r in resps if is_null_canonical(call_type, r)
    )
    total_resp_count = sum(len(resps) for resps in complete.values())
    null_rate = (null_resp_count / total_resp_count) if total_resp_count else float('nan')

    return {
        'n_runs': n_runs,
        'total_cases': len(cases),
        'complete_cases': len(complete),
        'parse_rate': parse_rate,
        'kappa': kappa,
        'perfect_pct': (n_perfect / len(complete) * 100) if complete else float('nan'),
        'null_rate': null_rate,
        'null_only_cases': null_only_cases,
        'substantive_cases': len(substantive),
        'substantive_kappa': sub_kappa,
        'substantive_perfect_pct': sub_perfect_pct,
        'total_cost_usd': total_cost,
        'total_tokens': total_tokens,
    }


def main():
    if not RESULTS_DIR.exists():
        print(f"No results at {RESULTS_DIR}")
        sys.exit(1)

    # Discover models and call types
    models = sorted([d.name for d in RESULTS_DIR.iterdir() if d.is_dir()])
    print(f"Models found: {models}")

    results = {}  # (model, call_type) -> metrics
    for model_slug in models:
        model_dir = RESULTS_DIR / model_slug
        for ct_dir in sorted(model_dir.iterdir()):
            if not ct_dir.is_dir():
                continue
            ct = ct_dir.name
            print(f"Analyzing {model_slug} / {ct}...")
            metrics = analyze_call_type(ct_dir, ct)
            if metrics is None:
                print(f"  no runs found")
                continue
            results[(model_slug, ct)] = metrics
            print(f"  kappa={metrics['kappa']:.3f} parse_rate={metrics['parse_rate']:.3f} "
                  f"perfect={metrics['perfect_pct']:.1f}% N={metrics['complete_cases']}")

    # Build report
    all_call_types = sorted({ct for _, ct in results.keys()})
    all_models = sorted({m for m, _ in results.keys()})

    lines = []
    lines.append(f"# Self-Consistency Analysis: {TEST_SET}\n")
    lines.append(f"**Test set**: `{TEST_SET}` (200 heliophysics papers)\n")
    lines.append(f"**Runs per case**: 5 (temperature=1.0, reasoning_effort=high)\n")
    lines.append(f"**Sample size**: 100 cases per call type (seed=42)\n")
    lines.append(f"**Models analyzed**: {', '.join(all_models)}\n")
    lines.append("")
    lines.append("## Summary Table\n")

    # Build a table with one row per call_type
    header = ["Call Type"]
    for m in all_models:
        header.extend([f"{m} κ", f"{m} perfect%"])
    header.append("N")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")

    for ct in all_call_types:
        row = [ct]
        n_val = None
        for m in all_models:
            r = results.get((m, ct))
            if r is None:
                row.extend(["-", "-"])
            else:
                row.append(f"{r['kappa']:.3f}")
                row.append(f"{r['perfect_pct']:.1f}%")
                n_val = r['complete_cases']
        row.append(str(n_val) if n_val is not None else "-")
        lines.append("| " + " | ".join(row) + " |")

    # Substantive-only view
    lines.append("\n## Substantive-Only View\n")
    lines.append("Same metric, but cases where every run returned the model's null/refusal answer "
                 "(e.g. `UNKNOWN`, `uncertain`, `not_applicable`, empty cadence list, "
                 "null time range) are dropped. This strips out degenerate agreement on refusal "
                 "so the kappa reflects only cases where the model actually tried to answer.\n")
    lines.append("*Note*: `instrument_validation`, `mission_validation`, `mission_selection`, and "
                 "`instrument_selection` have no natural null answer, so their numbers are identical "
                 "to the main table.\n")
    header = ["Call Type"]
    for m in all_models:
        header.extend([f"{m} κ (sub)", f"{m} perfect% (sub)", f"{m} null%"])
    header.append("N sub")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for ct in all_call_types:
        row = [ct]
        n_sub = None
        for m in all_models:
            r = results.get((m, ct))
            if r is None:
                row.extend(["-", "-", "-"])
            else:
                sk = r['substantive_kappa']
                sp = r['substantive_perfect_pct']
                row.append(f"{sk:.3f}" if sk == sk else "n/a")
                row.append(f"{sp:.1f}%" if sp == sp else "n/a")
                row.append(f"{r['null_rate']*100:.1f}%")
                n_sub = r['substantive_cases']
        row.append(str(n_sub) if n_sub is not None else "-")
        lines.append("| " + " | ".join(row) + " |")

    # Hotspots (single model view since only one model has results)
    lines.append("\n## Reliability Hotspots\n")
    for m in all_models:
        ct_metrics = [(ct, results[(m, ct)]) for ct in all_call_types if (m, ct) in results]
        if not ct_metrics:
            continue
        sorted_by_kappa = sorted(ct_metrics, key=lambda x: x[1]['kappa'])
        lines.append(f"### {m}\n")
        lines.append(f"**Lowest kappa (least self-consistent)**:\n")
        for ct, r in sorted_by_kappa[:3]:
            lines.append(f"- `{ct}`: κ={r['kappa']:.3f}, parse_rate={r['parse_rate']*100:.1f}%, perfect={r['perfect_pct']:.1f}%")
        lines.append("")
        lines.append(f"**Lowest parse rate**:\n")
        sorted_by_parse = sorted(ct_metrics, key=lambda x: x[1]['parse_rate'])
        for ct, r in sorted_by_parse[:3]:
            lines.append(f"- `{ct}`: parse_rate={r['parse_rate']*100:.1f}%, κ={r['kappa']:.3f}")
        lines.append("")

    # Cost totals
    lines.append("## Realized Cost & Tokens (from retrieved results)\n")
    lines.append("| Model | Total cost (USD) | Total tokens |")
    lines.append("|---|---|---|")
    for m in all_models:
        total_cost = sum(results[(m, ct)]['total_cost_usd'] for ct in all_call_types if (m, ct) in results)
        total_tokens = sum(results[(m, ct)]['total_tokens'] for ct in all_call_types if (m, ct) in results)
        lines.append(f"| {m} | ${total_cost:.2f} | {total_tokens:,} |")
    lines.append("")

    # Deviations
    lines.append("## Deviations from Plan\n")
    lines.append("- **Bedrock configuration dropped**: The `bedrock-120b-high` side of the A/B "
                 "comparison could not be submitted because `litellm.acreate_file()` does not "
                 "support the `bedrock` provider. Bedrock batch inference uses a different API "
                 "(S3 + `create_model_invocation_job`) that litellm has not implemented. All 9 "
                 "Bedrock batch submissions failed at the upload step; only `standard-gpt54` "
                 "(openai/gpt-5.4) results are available. The side-by-side comparison the plan "
                 "called for is therefore not possible from this run.")
    lines.append("- **`reasoning_effort` fix**: `prepare_batch_file` was patched to forward "
                 "`reasoning_effort` in the per-request body (previously silently dropped). "
                 "All batches ran with `reasoning_effort=high`.")
    lines.append("- **Registry fix**: `CallTypeRegistry.register()` was made idempotent "
                 "(last-registered wins) so that `WavelengthNormalizationHandler` and "
                 "`WavelengthNormalizationSimpleHandler`, which share the same `call_type_name`, "
                 "can coexist in `handlers/__init__.py`. Without this, `batch_runner.py` could "
                 "not be imported at all.")
    lines.append("- **Added 10th call type**: `mission_validation` was added at user request "
                 "(not in the original plan) since it had 2970 calls in the test set.")
    lines.append("- **Sandbox filesystem write corruption**: intermittent contiguous null-byte "
                 "blocks in large batch JSONL files (~8MB). Worked around with a fallback cost "
                 "estimate in the driver; batches uploaded to OpenAI were healthy (OpenAI would "
                 "have rejected corrupt JSONL).")
    lines.append("")

    # Per-call-type detail
    lines.append("## Per-Call-Type Detail\n")
    for ct in all_call_types:
        lines.append(f"### {ct}\n")
        for m in all_models:
            r = results.get((m, ct))
            if r is None:
                continue
            lines.append(f"**{m}**:")
            lines.append(f"- Fleiss' kappa: `{r['kappa']:.4f}`")
            lines.append(f"- Parse rate: `{r['parse_rate']*100:.2f}%`")
            lines.append(f"- Perfect consistency: `{r['perfect_pct']:.1f}%`")
            lines.append(f"- Complete cases: {r['complete_cases']}/{r['total_cases']}")
            lines.append(f"- Total cost: ${r['total_cost_usd']:.4f}")
            lines.append(f"- Total tokens: {r['total_tokens']:,}")
            lines.append("")

    with open(REPORT_PATH, 'w') as f:
        f.write("\n".join(lines))
    print(f"\nReport written: {REPORT_PATH}")


if __name__ == '__main__':
    main()
