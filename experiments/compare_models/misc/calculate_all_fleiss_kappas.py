"""
Calculate Fleiss' Kappa for all self-consistency experiments and create summary bar chart.
"""
import json
from pathlib import Path
from collections import Counter
import numpy as np
import matplotlib.pyplot as plt

def load_experiment_runs(experiment_dir: str, file_pattern: str):
    """Load all JSONL run files from an experiment directory."""
    exp_path = Path(experiment_dir)
    if not exp_path.exists():
        return []

    jsonl_files = sorted(exp_path.glob(file_pattern))
    runs = []

    for f in jsonl_files:
        with open(f) as file:
            runs.append([json.loads(line) for line in file])

    return runs


def extract_responses(runs, field_extractor):
    """Extract responses organized by case index using custom field extractor."""
    if not runs:
        return []

    n_cases = len(runs[0])
    responses_by_case = []

    for case_idx in range(n_cases):
        case_responses = []
        for run in runs:
            case = run[case_idx]
            response = field_extractor(case)
            case_responses.append(response)

        responses_by_case.append(case_responses)

    return responses_by_case


def calculate_fleiss_kappa(responses_by_case):
    """Calculate Fleiss' Kappa for multi-rater agreement."""
    if not responses_by_case:
        return 0.0

    n_cases = len(responses_by_case)
    n_raters = len(responses_by_case[0])

    # Get all unique categories
    all_categories = set()
    for responses in responses_by_case:
        all_categories.update(responses)

    # Convert all to strings for consistent sorting
    categories = sorted(list(all_categories), key=str)
    n_categories = len(categories)

    # Create category index mapping
    cat_to_idx = {cat: idx for idx, cat in enumerate(categories)}

    # Build matrix
    matrix = np.zeros((n_cases, n_categories), dtype=int)

    for case_idx, responses in enumerate(responses_by_case):
        for response in responses:
            cat_idx = cat_to_idx[response]
            matrix[case_idx][cat_idx] += 1

    # Calculate P_i
    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1))
    P_bar = np.mean(P_i)

    # Calculate P_j
    P_j = np.sum(matrix, axis=0) / (n_cases * n_raters)
    P_e_bar = np.sum(P_j ** 2)

    # Fleiss' Kappa
    if P_e_bar == 1.0:
        return 1.0

    kappa = (P_bar - P_e_bar) / (1 - P_e_bar)
    return kappa


# Field extractors for different call types
def extract_cadence(case):
    parsed = case.get('parsed_response')
    if parsed and 'cadences' in parsed:
        cadences = parsed['cadences']
        if isinstance(cadences, list):
            return tuple(sorted(cadences)) if cadences else 'NONE'
        return cadences
    return 'PARSE_ERROR'


def extract_detector(case):
    parsed = case.get('parsed_response')
    if parsed and 'detector' in parsed:
        det = parsed['detector']
        if det:
            # Normalize case
            return det.upper()
        return 'NONE'
    return 'PARSE_ERROR'


def extract_physobs(case):
    parsed = case.get('parsed_response')
    if parsed and 'physical_observable' in parsed:
        obs = parsed['physical_observable']
        # Normalize case variations
        if obs:
            return obs.lower()
        return 'NONE'
    return 'PARSE_ERROR'


def extract_mission_selection(case):
    parsed = case.get('parsed_response')
    if parsed and 'mission_index' in parsed:
        return str(parsed['mission_index'])
    return 'PARSE_ERROR'


def extract_time(case):
    parsed = case.get('parsed_response')
    if parsed:
        start = parsed.get('start_datetime')
        end = parsed.get('end_datetime')
        return f"{start}|{end}"
    return 'PARSE_ERROR'


def extract_instrument_validation(case):
    parsed = case.get('parsed_response')
    if isinstance(parsed, dict):
        return parsed.get('result', 'PARSE_ERROR')
    elif isinstance(parsed, str):
        return parsed
    return 'PARSE_ERROR'


def extract_mission_identification(case):
    parsed = case.get('parsed_response')
    if parsed and 'mission_indices' in parsed:
        indices = parsed['mission_indices']
        return tuple(sorted(indices)) if indices else 'NONE'
    return 'PARSE_ERROR'


# Experiment configurations
EXPERIMENTS = {
    'cadence_norm_v2': {
        'name': 'Cadence\nNormalization\n(V2)',
        'dir': 'experiments/compare_models/prompt_experiments/bedrock_120b_cadence_free_text_full',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_cadence
    },
    'detector_norm_v2': {
        'name': 'Detector\nNormalization\n(V2)',
        'dir': 'experiments/compare_models/prompt_experiments/detector_free_text_v2_bedrock_120b_full',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_detector
    },
    'physobs_norm_v2': {
        'name': 'PhysObs\nNormalization\n(V2)',
        'dir': 'experiments/compare_models/prompt_experiments/physobs_free_text_v2_bedrock_120b_full',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_physobs
    },
    'mission_selection': {
        'name': 'Mission\nSelection',
        'dir': 'experiments/compare_models/prompt_experiments/bedrock_120b_mission_selection_full',
        'pattern': 'bedrock_converse_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_mission_selection
    },
    'time_norm': {
        'name': 'Time\nNormalization',
        'dir_pattern': 'experiments/compare_models/prompt_experiments/bedrock_120b_time_norm_run*',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_time
    },
    'instrument_validation': {
        'name': 'Instrument\nValidation',
        'dir_pattern': 'experiments/compare_models/prompt_experiments/bedrock_120b_instrument_validation_run*',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_instrument_validation
    },
    'mission_identification': {
        'name': 'Mission\nIdentification',
        'dir_pattern': 'experiments/compare_models/prompt_experiments/bedrock_120b_mission_identification_run*',
        'pattern': 'bedrock_openai.gpt-oss-120b-1_0_*.jsonl',
        'extractor': extract_mission_identification
    }
}


def main():
    results = {}

    for exp_id, config in EXPERIMENTS.items():
        print(f"\nProcessing {config['name'].replace(chr(10), ' ')}...")

        if 'dir' in config:
            # Single directory
            runs = load_experiment_runs(config['dir'], config['pattern'])
        else:
            # Multiple run directories
            base_path = Path('.')
            run_dirs = sorted(base_path.glob(config['dir_pattern']))
            runs = []
            for run_dir in run_dirs:
                run_files = sorted(run_dir.glob(config['pattern']))
                if run_files:
                    with open(run_files[0]) as f:
                        runs.append([json.loads(line) for line in f])

        if not runs:
            print(f"  ⚠ No data found")
            continue

        print(f"  Loaded {len(runs)} runs with {len(runs[0])} cases each")

        # Extract responses
        responses = extract_responses(runs, config['extractor'])

        # Calculate Fleiss' Kappa
        kappa = calculate_fleiss_kappa(responses)

        # Calculate agreement stats
        perfect = sum(1 for resp in responses if len(set(resp)) == 1)
        moderate = sum(1 for resp in responses if len(set(resp)) == 2)
        poor = sum(1 for resp in responses if len(set(resp)) > 2)

        results[exp_id] = {
            'name': config['name'],
            'kappa': kappa,
            'n_runs': len(runs),
            'n_cases': len(runs[0]),
            'perfect': perfect,
            'moderate': moderate,
            'poor': poor
        }

        print(f"  Fleiss' Kappa: {kappa:.3f}")
        print(f"  Perfect agreement: {perfect}/{len(responses)} ({100*perfect/len(responses):.1f}%)")

    # Create visualization
    fig, ax = plt.subplots(figsize=(14, 8))

    # Sort by kappa value
    sorted_results = sorted(results.items(), key=lambda x: x[1]['kappa'], reverse=True)

    names = [r[1]['name'] for r in sorted_results]
    kappas = [r[1]['kappa'] for r in sorted_results]
    perfect_pcts = [100 * r[1]['perfect'] / r[1]['n_cases'] for r in sorted_results]

    x_pos = np.arange(len(names))

    # Color bars by kappa value
    colors = []
    for k in kappas:
        if k >= 0.9:
            colors.append('#2E7D32')  # Dark green - Almost Perfect
        elif k >= 0.8:
            colors.append('#66BB6A')  # Green - Substantial
        elif k >= 0.6:
            colors.append('#FFA726')  # Orange - Moderate
        else:
            colors.append('#EF5350')  # Red - Fair

    bars = ax.bar(x_pos, kappas, color=colors, alpha=0.8, edgecolor='black', linewidth=1.5)

    # Add value labels on bars
    for i, (bar, kappa, perfect_pct) in enumerate(zip(bars, kappas, perfect_pcts)):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                f'κ = {kappa:.3f}\n{perfect_pct:.0f}% perfect',
                ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_xlabel('LLM Call Type', fontsize=14, fontweight='bold')
    ax.set_ylabel('Fleiss\' Kappa', fontsize=14, fontweight='bold')
    ax.set_title('Self-Consistency Scores Across LLM Call Types\n(5 runs, 100 cases each)',
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(names, fontsize=11, ha='center')
    ax.set_ylim([0, 1.05])
    ax.grid(axis='y', alpha=0.3, linestyle='--')

    # Add interpretation guide
    ax.axhline(y=0.8, color='gray', linestyle='--', alpha=0.3, linewidth=1)
    ax.axhline(y=0.6, color='gray', linestyle='--', alpha=0.3, linewidth=1)
    ax.text(len(names) - 0.5, 0.9, 'Almost Perfect', fontsize=9, color='gray', style='italic')
    ax.text(len(names) - 0.5, 0.7, 'Substantial', fontsize=9, color='gray', style='italic')
    ax.text(len(names) - 0.5, 0.5, 'Moderate', fontsize=9, color='gray', style='italic')

    plt.tight_layout()

    # Save figure
    output_path = Path('experiments/compare_models/all_fleiss_kappas.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Saved visualization to {output_path}")

    # Print summary table
    print("\n" + "="*80)
    print("SUMMARY TABLE")
    print("="*80)
    print(f"{'Call Type':<35} {'Kappa':>8} {'Perfect':>10} {'Moderate':>10} {'Poor':>8}")
    print("-"*80)
    for exp_id, data in sorted_results:
        name = data['name'].replace('\n', ' ')
        print(f"{name:<35} {data['kappa']:>8.3f} {data['perfect']:>4}/{data['n_cases']:<3} {data['moderate']:>4}/{data['n_cases']:<3} {data['poor']:>4}/{data['n_cases']:<3}")

    plt.show()


if __name__ == "__main__":
    main()
