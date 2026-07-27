"""
Export self-consistency results to JSON for D3 visualization.

Transforms JSONL experiment results into hierarchical JSON structure:
- summary.json: Call type metrics for scatter plot
- {call_type}/cases.json: Per-case data with run summaries
- {call_type}/cases/{case_id}.json: Full prompts/outputs for drill-down

Usage:
    python export_viz_data.py
"""

import json
import sys
import importlib
from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations
import numpy as np

# Compute repo root from this file's location
REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# Output directory
OUTPUT_DIR = Path(__file__).parent / 'data'

# Input directory (source of truth for prompts)
INPUT_DIR = REPO_ROOT / 'inputs' / 'test_set'

# ============================================================================
# CONFIGURATION - Must match model_comparison_analysis.ipynb
# ============================================================================

TEST_SET_TAG = 'test_set_2025_11_26'
SAMPLE_SIZE = 100
NUM_RUNS = 5

MODELS = [
    'openai/gpt-5',
    'bedrock/openai.gpt-oss-120b-1:0',
]

def model_slug(model_name):
    return model_name.replace('/', '_').replace(':', '_').replace('.', '_')

CALL_TYPES = [
    'instrument_validation',
    'wavelength_normalization',
    'physobs_normalization',
    'mission_selection',
    'instrument_selection',
    'detector_normalization',
    'time_normalization',
    'cadence_normalization',
    'mission_identification',
]

HANDLER_MAP = {
    'detector_normalization': 'DetectorNormalizationFreeTextV2Handler',
    'cadence_normalization': 'CadenceNormalizationFreeTextHandler',
    'physobs_normalization': 'PhysObsNormalizationFreeTextV2Handler',
    'wavelength_normalization': 'WavelengthNormalizationSimpleHandler',
    'time_normalization': 'TimeNormalizationHandler',
    'mission_identification': 'MissionIdentificationHandler',
    'mission_selection': 'MissionSelectionHandler',
    'instrument_selection': 'InstrumentSelectionHandler',
    'instrument_validation': 'InstrumentValidationHandler',
}

RESPONSE_KEYS = {
    'detector_normalization': 'detector',
    'cadence_normalization': 'cadences',
    'physobs_normalization': 'physical_observable',
    'wavelength_normalization': 'wavelengths',
    'time_normalization': ('start_datetime', 'end_datetime'),
    'mission_identification': 'mission_indices',
    'mission_selection': 'mission_indices',
    'instrument_selection': 'instrument_indices',
    'instrument_validation': 'validation_result',
}

TASK_TYPES = {
    'instrument_validation': 'binary',
    'detector_normalization': 'single',
    'physobs_normalization': 'single',
    'time_normalization': 'single',
    'wavelength_normalization': 'set',
    'cadence_normalization': 'set',
    'mission_selection': 'set',
    'instrument_selection': 'set',
    'mission_identification': 'set',
}

RESULTS_DIR = Path(__file__).parent.parent / 'results'

# ============================================================================
# NULL DETECTION
# ============================================================================

def is_null_response(output_content: str, call_type: str) -> bool:
    """
    Determine if a response is effectively "null" (no meaningful answer).

    Each call type has different null patterns:
    - physobs_normalization: 'UNCERTAIN'
    - wavelength_normalization: 'not_applicable', 'none', 'null', ''
    - cadence_normalization: 'none', 'null', '', empty
    - detector_normalization: 'none', 'null', 'uncertain', '', empty
    - mission_identification: contains 'unknown', empty, '[]'
    - time_normalization: JSON with null/missing start_datetime and end_datetime
    - instrument_validation: boolean task, no null
    - mission_selection: 'none', 'null', 'unknown', empty
    - instrument_selection: 'none', 'null', empty
    """
    text = output_content.strip()
    text_lower = text.lower()

    if call_type == 'physobs_normalization':
        return text.upper() == 'UNCERTAIN'

    elif call_type == 'wavelength_normalization':
        return text_lower in ['not_applicable', 'none', 'null', 'n/a', '']

    elif call_type == 'cadence_normalization':
        return text_lower in ['none', 'null', 'n/a', ''] or text == ''

    elif call_type == 'detector_normalization':
        return text_lower in ['none', 'null', 'n/a', 'uncertain', ''] or text == ''

    elif call_type == 'mission_identification':
        return 'unknown' in text_lower or text == '' or text == '[]'

    elif call_type == 'time_normalization':
        try:
            data = json.loads(text)
            start = data.get('start_datetime')
            end = data.get('end_datetime')
            return (not start or start == 'null') and (not end or end == 'null')
        except:
            return text == '' or text_lower in ['none', 'null']

    elif call_type == 'instrument_validation':
        # Boolean task - no null equivalent
        return False

    elif call_type == 'mission_selection':
        return text_lower in ['none', 'null', 'unknown', ''] or text == '[]'

    elif call_type == 'instrument_selection':
        return text_lower in ['none', 'null', ''] or text == '[]'

    return False

# Sample size and seed for input file naming
SAMPLE_SIZE = 100
RANDOM_SEED = 42


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_input_messages_map(call_type):
    """
    Load input messages from the source input file.

    Returns dict mapping case_id -> input_messages.
    This is the source of truth for prompts, independent of output format.
    """
    input_file = INPUT_DIR / f"{call_type}_{TEST_SET_TAG}_sampled_{SAMPLE_SIZE}_seed{RANDOM_SEED}.jsonl"

    if not input_file.exists():
        print(f"Warning: Input file not found: {input_file}")
        return {}

    input_messages_map = {}
    with open(input_file) as f:
        for line in f:
            data = json.loads(line)
            case_id = data.get('id')
            input_messages = data.get('input_messages', [])
            if case_id and input_messages:
                input_messages_map[case_id] = input_messages

    return input_messages_map

def jaccard_similarity(set1, set2):
    """Calculate Jaccard similarity between two sets."""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def extract_comparable_value(parsed, call_type):
    """Extract comparable value from parsed response as frozenset."""
    if parsed is None:
        return frozenset(['PARSE_ERROR'])

    response_key = RESPONSE_KEYS.get(call_type)

    if isinstance(response_key, tuple):
        values = tuple(parsed.get(field) for field in response_key)
        return frozenset([values])

    if isinstance(parsed, dict):
        response_val = parsed.get(response_key)
    else:
        response_val = parsed

    if response_val is None:
        return frozenset(['NONE'])
    elif isinstance(response_val, (list, tuple)):
        return frozenset(str(v) for v in response_val)
    else:
        return frozenset([str(response_val)])


def load_handler(call_type):
    """Load the handler class for parsing responses."""
    handler_class_name = HANDLER_MAP[call_type]
    handlers_module = importlib.import_module('experiments.compare_models.handlers')
    handler_class = getattr(handlers_module, handler_class_name)
    return handler_class()


def bootstrap_confidence_interval(data, n_bootstrap=1000, confidence=0.95):
    """Calculate bootstrap confidence interval for the mean."""
    data = np.array(data)
    n = len(data)
    if n < 2:
        return (float(np.mean(data)), float(np.mean(data)), float(np.mean(data)))

    rng = np.random.default_rng(42)
    bootstrap_means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(data, size=n, replace=True)
        bootstrap_means.append(np.mean(sample))

    alpha = (1 - confidence) / 2
    lower = np.percentile(bootstrap_means, alpha * 100)
    upper = np.percentile(bootstrap_means, (1 - alpha) * 100)

    return (float(np.mean(data)), float(lower), float(upper))


# ============================================================================
# DATA LOADING
# ============================================================================

def load_all_results():
    """
    Load all results from JSONL files.

    Returns:
        dict: {model: {call_type: {case_id: {runs: [...], ...}}}}
    """
    all_data = {}

    for model in MODELS:
        slug = model_slug(model)
        all_data[model] = {}

        for call_type in CALL_TYPES:
            handler = load_handler(call_type)
            cases = defaultdict(lambda: {'runs': []})

            for run in range(1, NUM_RUNS + 1):
                exp_dir = RESULTS_DIR / TEST_SET_TAG / slug / call_type / f"run{run}"
                jsonl_files = list(exp_dir.glob('*.jsonl'))

                if not jsonl_files:
                    continue

                with open(jsonl_files[0]) as f:
                    for line in f:
                        data = json.loads(line)
                        case_id = data.get('original_id', str(data.get('case_index')))
                        output_content = data.get('output_content', '')

                        try:
                            parsed = handler.parse_response(output_content)
                        except:
                            parsed = None

                        response_set = extract_comparable_value(parsed, call_type)

                        cases[case_id]['runs'].append({
                            'run': run,
                            'output_content': output_content,
                            'parsed': parsed,
                            'response_set': response_set,
                            'is_null': is_null_response(output_content, call_type),
                            'prompt_tokens': data.get('prompt_tokens', 0),
                            'completion_tokens': data.get('completion_tokens', 0),
                            'estimated_cost_usd': data.get('estimated_cost_usd', 0),
                            'duration_ms': data.get('duration_ms', 0),
                            'input_messages': data.get('input_messages', []),
                        })

            all_data[model][call_type] = dict(cases)

    return all_data


def compute_case_metrics(all_data):
    """
    Compute self-consistency and cross-model metrics per case.

    Returns:
        dict: {call_type: {case_id: {metrics...}}}
    """
    metrics = {}

    for call_type in CALL_TYPES:
        metrics[call_type] = {}

        # Get all case IDs across both models
        all_case_ids = set()
        for model in MODELS:
            all_case_ids.update(all_data[model][call_type].keys())

        for case_id in all_case_ids:
            case_metrics = {
                'case_id': case_id,
                'call_type': call_type,
                'task_type': TASK_TYPES[call_type],
                'models': {},
            }

            # Self-consistency per model
            for model in MODELS:
                model_data = all_data[model][call_type].get(case_id, {})
                runs = model_data.get('runs', [])

                if len(runs) >= 2:
                    response_sets = [r['response_set'] for r in runs]
                    pairwise_jaccards = []
                    for i in range(len(response_sets)):
                        for j in range(i + 1, len(response_sets)):
                            pairwise_jaccards.append(jaccard_similarity(response_sets[i], response_sets[j]))

                    mean_jaccard = np.mean(pairwise_jaccards) if pairwise_jaccards else 1.0
                    all_same = all(rs == response_sets[0] for rs in response_sets)

                    # Get majority response
                    set_counts = Counter(tuple(sorted(rs)) for rs in response_sets)
                    majority = frozenset(set_counts.most_common(1)[0][0])
                else:
                    mean_jaccard = 1.0 if runs else 0.0
                    all_same = True
                    majority = runs[0]['response_set'] if runs else frozenset()

                case_metrics['models'][model] = {
                    'self_consistency': float(mean_jaccard),
                    'all_same': all_same,
                    'majority_response': list(majority),
                    'num_runs': len(runs),
                }

            # Cross-model agreement (pairwise)
            model1, model2 = MODELS[0], MODELS[1]
            runs1 = all_data[model1][call_type].get(case_id, {}).get('runs', [])
            runs2 = all_data[model2][call_type].get(case_id, {}).get('runs', [])

            if runs1 and runs2:
                cross_jaccards = []
                cross_jaccards_non_null = []
                both_null_count = 0
                any_null_count = 0

                for r1 in runs1:
                    for r2 in runs2:
                        jac = jaccard_similarity(r1['response_set'], r2['response_set'])
                        cross_jaccards.append(jac)

                        r1_null = r1.get('is_null', False)
                        r2_null = r2.get('is_null', False)

                        if r1_null and r2_null:
                            both_null_count += 1
                        if r1_null or r2_null:
                            any_null_count += 1
                        else:
                            cross_jaccards_non_null.append(jac)

                case_metrics['cross_model_agreement'] = float(np.mean(cross_jaccards))
                case_metrics['cross_model_std'] = float(np.std(cross_jaccards))
                case_metrics['cross_model_agreement_non_null'] = float(np.mean(cross_jaccards_non_null)) if cross_jaccards_non_null else None
                case_metrics['both_null_pairs'] = both_null_count
                case_metrics['any_null_pairs'] = any_null_count
                case_metrics['total_pairs'] = len(cross_jaccards)
            else:
                case_metrics['cross_model_agreement'] = None
                case_metrics['cross_model_std'] = None
                case_metrics['cross_model_agreement_non_null'] = None
                case_metrics['both_null_pairs'] = 0
                case_metrics['any_null_pairs'] = 0
                case_metrics['total_pairs'] = 0

            metrics[call_type][case_id] = case_metrics

    return metrics


def compute_summary_metrics(case_metrics):
    """
    Compute summary metrics per call type for scatter plot.

    Returns:
        list: [{call_type, self_consistency, cross_model, ...}, ...]
    """
    summary = []

    for call_type in CALL_TYPES:
        cases = case_metrics[call_type]

        # Aggregate self-consistency across all cases and models
        all_sc_values = []
        for case_id, cm in cases.items():
            for model in MODELS:
                if model in cm['models']:
                    all_sc_values.append(cm['models'][model]['self_consistency'])

        # Aggregate cross-model agreement (all pairs)
        cross_values = [cm['cross_model_agreement'] for cm in cases.values()
                       if cm['cross_model_agreement'] is not None]

        # Aggregate cross-model agreement (non-null pairs only)
        cross_values_non_null = [cm['cross_model_agreement_non_null'] for cm in cases.values()
                                  if cm.get('cross_model_agreement_non_null') is not None]

        # Null statistics
        total_both_null = sum(cm.get('both_null_pairs', 0) for cm in cases.values())
        total_any_null = sum(cm.get('any_null_pairs', 0) for cm in cases.values())
        total_pairs = sum(cm.get('total_pairs', 0) for cm in cases.values())

        # Count cases where all pairs are both-null
        cases_all_null = sum(1 for cm in cases.values()
                            if cm.get('both_null_pairs', 0) == cm.get('total_pairs', 1) and cm.get('total_pairs', 0) > 0)

        mean_sc = float(np.mean(all_sc_values)) * 100 if all_sc_values else 0
        mean_cross = float(np.mean(cross_values)) * 100 if cross_values else 0
        mean_cross_non_null = float(np.mean(cross_values_non_null)) * 100 if cross_values_non_null else None

        # Confidence intervals for all pairs
        if all_sc_values:
            _, sc_ci_lower, sc_ci_upper = bootstrap_confidence_interval(all_sc_values)
            sc_ci_lower *= 100
            sc_ci_upper *= 100
        else:
            sc_ci_lower, sc_ci_upper = 0, 0

        if cross_values:
            _, cross_ci_lower, cross_ci_upper = bootstrap_confidence_interval(cross_values)
            cross_ci_lower *= 100
            cross_ci_upper *= 100
        else:
            cross_ci_lower, cross_ci_upper = 0, 0

        # Confidence intervals for non-null pairs
        if cross_values_non_null:
            _, cross_non_null_ci_lower, cross_non_null_ci_upper = bootstrap_confidence_interval(
                [v / 100 for v in cross_values_non_null] if cross_values_non_null else []
            )
            # Values are already percentages, no need to multiply
            cross_non_null_ci_lower = float(np.percentile([v for v in cross_values_non_null], 2.5)) if cross_values_non_null else None
            cross_non_null_ci_upper = float(np.percentile([v for v in cross_values_non_null], 97.5)) if cross_values_non_null else None
        else:
            cross_non_null_ci_lower, cross_non_null_ci_upper = None, None

        summary.append({
            'call_type': call_type,
            'task_type': TASK_TYPES[call_type],
            'self_consistency': mean_sc,
            'sc_ci_lower': sc_ci_lower,
            'sc_ci_upper': sc_ci_upper,
            'cross_model_agreement': mean_cross,
            'cross_ci_lower': cross_ci_lower,
            'cross_ci_upper': cross_ci_upper,
            'cross_model_agreement_non_null': mean_cross_non_null,
            'cross_non_null_ci_lower': cross_non_null_ci_lower,
            'cross_non_null_ci_upper': cross_non_null_ci_upper,
            'num_cases': len(cases),
            'null_stats': {
                'both_null_pairs': total_both_null,
                'any_null_pairs': total_any_null,
                'total_pairs': total_pairs,
                'both_null_pct': total_both_null / total_pairs * 100 if total_pairs > 0 else 0,
                'cases_all_null': cases_all_null,
            },
        })

    return summary


# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

def export_summary(summary, case_metrics, output_dir):
    """Export summary.json for scatter plot, including individual case points."""
    # Build individual case points for scatter plot
    all_cases = []
    for call_type in CALL_TYPES:
        for case_id, cm in case_metrics[call_type].items():
            # Average self-consistency across both models
            sc_values = [cm['models'].get(m, {}).get('self_consistency', 0) for m in MODELS]
            avg_sc = float(np.mean(sc_values)) * 100 if sc_values else 0

            cross = cm.get('cross_model_agreement')
            cross_non_null = cm.get('cross_model_agreement_non_null')
            if cross is not None:
                case_data = {
                    'case_id': case_id,
                    'call_type': call_type,
                    'task_type': TASK_TYPES[call_type],
                    'self_consistency': avg_sc,
                    'cross_model_agreement': float(cross) * 100,
                    'both_null_pairs': cm.get('both_null_pairs', 0),
                    'any_null_pairs': cm.get('any_null_pairs', 0),
                    'total_pairs': cm.get('total_pairs', 0),
                }
                if cross_non_null is not None:
                    case_data['cross_model_agreement_non_null'] = float(cross_non_null) * 100
                all_cases.append(case_data)

    output_path = output_dir / 'summary.json'
    with open(output_path, 'w') as f:
        json.dump({
            'models': MODELS,
            'test_set': TEST_SET_TAG,
            'num_runs': NUM_RUNS,
            'call_types': summary,
            'all_cases': all_cases,
        }, f, indent=2)
    print(f"Exported: {output_path}")


def export_cases_list(call_type, case_metrics, output_dir):
    """Export cases.json for a call type (case list view)."""
    call_type_dir = output_dir / call_type
    call_type_dir.mkdir(parents=True, exist_ok=True)

    cases_list = []
    for case_id, cm in case_metrics[call_type].items():
        cases_list.append({
            'case_id': case_id,
            'self_consistency': {
                model: cm['models'].get(model, {}).get('self_consistency', 0)
                for model in MODELS
            },
            'cross_model_agreement': cm['cross_model_agreement'],
            'majority_responses': {
                model: cm['models'].get(model, {}).get('majority_response', [])
                for model in MODELS
            },
        })

    # Sort by cross-model agreement ascending (worst first)
    cases_list.sort(key=lambda x: x['cross_model_agreement'] or 0)

    output_path = call_type_dir / 'cases.json'
    with open(output_path, 'w') as f:
        json.dump({
            'call_type': call_type,
            'task_type': TASK_TYPES[call_type],
            'cases': cases_list,
        }, f, indent=2)
    print(f"Exported: {output_path}")


def export_case_detail(call_type, case_id, all_data, case_metrics, input_messages_map, output_dir):
    """Export full case detail with prompts and outputs."""
    cases_dir = output_dir / call_type / 'cases'
    cases_dir.mkdir(parents=True, exist_ok=True)

    cm = case_metrics[call_type][case_id]

    # Get input_messages from the source input file (not from outputs)
    input_messages = input_messages_map.get(case_id, [])

    detail = {
        'case_id': case_id,
        'call_type': call_type,
        'task_type': TASK_TYPES[call_type],
        'cross_model_agreement': cm['cross_model_agreement'],
        'input_messages': input_messages,  # Shared at case level
        'models': {},
    }

    for model in MODELS:
        model_data = all_data[model][call_type].get(case_id, {})
        runs = model_data.get('runs', [])

        detail['models'][model] = {
            'self_consistency': cm['models'].get(model, {}).get('self_consistency', 0),
            'majority_response': cm['models'].get(model, {}).get('majority_response', []),
            'runs': [
                {
                    'run': r['run'],
                    'output_content': r['output_content'],
                    'parsed': r['parsed'],
                    'response_set': list(r['response_set']),
                    'is_null': r.get('is_null', False),
                    'prompt_tokens': r['prompt_tokens'],
                    'completion_tokens': r['completion_tokens'],
                    'estimated_cost_usd': r['estimated_cost_usd'],
                    'duration_ms': r['duration_ms'],
                }
                for r in sorted(runs, key=lambda x: x['run'])
            ],
        }

    # Use safe filename (replace problematic characters)
    safe_case_id = case_id.replace('/', '_').replace('\\', '_')[:50]
    output_path = cases_dir / f'{safe_case_id}.json'
    with open(output_path, 'w') as f:
        json.dump(detail, f, indent=2)


def main():
    """Main export function."""
    print("="*60)
    print("Exporting visualization data...")
    print("="*60)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load all results
    print("\nLoading results...")
    all_data = load_all_results()

    # Compute metrics
    print("Computing metrics...")
    case_metrics = compute_case_metrics(all_data)
    summary = compute_summary_metrics(case_metrics)

    # Export summary
    print("\nExporting files...")
    export_summary(summary, case_metrics, OUTPUT_DIR)

    # Export per-call-type data
    for call_type in CALL_TYPES:
        export_cases_list(call_type, case_metrics, OUTPUT_DIR)

        # Load input messages from source file (not from outputs)
        input_messages_map = load_input_messages_map(call_type)

        # Export individual case details
        for case_id in case_metrics[call_type]:
            export_case_detail(call_type, case_id, all_data, case_metrics, input_messages_map, OUTPUT_DIR)

    # Create index of all case files for lazy loading
    case_index = {}
    for call_type in CALL_TYPES:
        case_index[call_type] = list(case_metrics[call_type].keys())

    with open(OUTPUT_DIR / 'case_index.json', 'w') as f:
        json.dump(case_index, f, indent=2)
    print(f"Exported: {OUTPUT_DIR / 'case_index.json'}")

    print("\n" + "="*60)
    print("Export complete!")
    print(f"Output directory: {OUTPUT_DIR}")
    print("="*60)


if __name__ == '__main__':
    main()
