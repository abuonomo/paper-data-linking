"""
Calculate and visualize Fleiss' Kappa for all self-consistency experiments.
"""
import json
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np


def calculate_fleiss_kappa(responses):
    """Calculate Fleiss' Kappa for multiple raters."""
    n_cases = len(responses)
    n_raters = len(responses[0]) if responses else 0

    if n_cases == 0 or n_raters == 0:
        return 0.0

    # Get all unique categories (convert all to strings, handle None as PARSE_ERROR)
    all_categories = set()
    for case_responses in responses:
        for r in case_responses:
            if r is None:
                all_categories.add('PARSE_ERROR')
            else:
                all_categories.add(str(r))

    categories = sorted(all_categories)
    n_categories = len(categories)

    if n_categories <= 1:
        return 1.0

    # Build matrix
    matrix = np.zeros((n_cases, n_categories))
    cat_to_idx = {cat: idx for idx, cat in enumerate(categories)}

    for i, case_responses in enumerate(responses):
        for response in case_responses:
            # Convert to string for lookup
            response_str = 'PARSE_ERROR' if response is None else str(response)
            j = cat_to_idx[response_str]
            matrix[i, j] += 1

    # Calculate Fleiss' Kappa
    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1))
    P_bar = np.mean(P_i)
    P_j = np.sum(matrix, axis=0) / (n_cases * n_raters)
    P_e = np.sum(P_j ** 2)

    if P_e == 1.0:
        return 1.0

    kappa = (P_bar - P_e) / (1 - P_e)
    return kappa


def load_experiment_runs(base_path, pattern):
    """Load all JSONL files matching pattern."""
    jsonl_files = sorted(Path(base_path).glob(pattern))
    runs = []
    for f in jsonl_files:
        with open(f) as file:
            runs.append([json.loads(line) for line in file])
    return runs


def extract_responses(runs_data, response_key='normalized_value'):
    """Extract responses from runs data."""
    if not runs_data:
        return []

    n_cases = len(runs_data[0])
    responses_by_case = []

    for case_idx in range(n_cases):
        case_responses = []
        for run in runs_data:
            if case_idx >= len(run):
                continue
            case = run[case_idx]

            # Try different response extraction methods
            parsed = case.get('parsed_response')
            if parsed is None:
                response = 'PARSE_ERROR'
            elif isinstance(parsed, dict):
                # Try different keys
                if 'detector' in parsed:
                    response = parsed['detector']
                elif 'physobs' in parsed:
                    response = parsed['physobs']
                elif response_key in parsed:
                    response = parsed[response_key]
                elif 'valid' in parsed:
                    response = str(parsed['valid'])
                else:
                    response = str(parsed)
            else:
                response = str(parsed)

            case_responses.append(response)

        if case_responses:
            responses_by_case.append(case_responses)

    return responses_by_case


def main():
    experiments = {}

    # Original experiments (run1-5 or run2-5)
    print("Loading original experiments...")

    # Cadence normalization (run1-5)
    runs = []
    for i in range(1, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_cadence_norm_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'cadence_value')
        kappa = calculate_fleiss_kappa(responses)
        experiments['Cadence\n(original)'] = kappa
        print(f"  Cadence: {kappa:.3f} ({len(runs)} runs)")

    # Detector normalization (run2-5)
    runs = []
    for i in range(2, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_detector_norm_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'detector')
        kappa = calculate_fleiss_kappa(responses)
        experiments['Detector\n(original)'] = kappa
        print(f"  Detector: {kappa:.3f} ({len(runs)} runs)")

    # Instrument validation (run1-5)
    runs = []
    for i in range(1, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_instrument_validation_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'valid')
        kappa = calculate_fleiss_kappa(responses)
        experiments['Instrument\nValidation'] = kappa
        print(f"  Instrument Validation: {kappa:.3f} ({len(runs)} runs)")

    # Mission identification (run1-5)
    runs = []
    for i in range(1, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_mission_identification_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'mission_code')
        kappa = calculate_fleiss_kappa(responses)
        experiments['Mission\nIdentification'] = kappa
        print(f"  Mission Identification: {kappa:.3f} ({len(runs)} runs)")

    # PhysObs normalization (run2-5)
    runs = []
    for i in range(2, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_physobs_norm_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'physobs')
        kappa = calculate_fleiss_kappa(responses)
        experiments['PhysObs\n(original)'] = kappa
        print(f"  PhysObs: {kappa:.3f} ({len(runs)} runs)")

    # Time normalization (run2-5)
    runs = []
    for i in range(2, 6):
        dir_path = f"experiments/compare_models/prompt_experiments/bedrock_120b_time_norm_run{i}"
        run_data = load_experiment_runs(dir_path, "bedrock_openai.gpt-oss-120b-1_0_*.jsonl")
        if run_data:
            runs.extend(run_data)
    if runs:
        responses = extract_responses(runs, 'normalized_value')
        kappa = calculate_fleiss_kappa(responses)
        experiments['Time\n(original)'] = kappa
        print(f"  Time: {kappa:.3f} ({len(runs)} runs)")

    # New free-text experiments - pick best variant
    print("\nLoading free-text experiments...")

    # PhysObs - compare v1 and v2, pick best
    physobs_v1_runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/physobs_free_text_bedrock_120b_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )
    physobs_v2_runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/physobs_free_text_v2_bedrock_120b_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )

    physobs_kappas = {}
    if physobs_v1_runs:
        responses = extract_responses(physobs_v1_runs, 'physical_observable')
        kappa_v1 = calculate_fleiss_kappa(responses)
        physobs_kappas['v1'] = kappa_v1
        print(f"  PhysObs free-text v1: {kappa_v1:.3f} ({len(physobs_v1_runs)} runs)")

    if physobs_v2_runs:
        responses = extract_responses(physobs_v2_runs, 'physical_observable')
        kappa_v2 = calculate_fleiss_kappa(responses)
        physobs_kappas['v2'] = kappa_v2
        print(f"  PhysObs free-text v2: {kappa_v2:.3f} ({len(physobs_v2_runs)} runs)")

    if physobs_kappas:
        best_version = max(physobs_kappas, key=physobs_kappas.get)
        experiments['PhysObs\n(best)'] = physobs_kappas[best_version]
        print(f"  → Using PhysObs {best_version}: {physobs_kappas[best_version]:.3f}")

    # Detector - compare v1 and v2, pick best
    detector_v1_runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/detector_free_text_bedrock_120b_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )
    detector_v2_runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/detector_free_text_v2_bedrock_120b_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )

    detector_kappas = {}
    if detector_v1_runs:
        responses = extract_responses(detector_v1_runs, 'detector')
        kappa_v1 = calculate_fleiss_kappa(responses)
        detector_kappas['v1'] = kappa_v1
        print(f"  Detector free-text v1: {kappa_v1:.3f} ({len(detector_v1_runs)} runs)")

    if detector_v2_runs:
        responses = extract_responses(detector_v2_runs, 'detector')
        kappa_v2 = calculate_fleiss_kappa(responses)
        detector_kappas['v2'] = kappa_v2
        print(f"  Detector free-text v2: {kappa_v2:.3f} ({len(detector_v2_runs)} runs)")

    if detector_kappas:
        best_version = max(detector_kappas, key=detector_kappas.get)
        experiments['Detector\n(best)'] = detector_kappas[best_version]
        print(f"  → Using Detector {best_version}: {detector_kappas[best_version]:.3f}")

    # Create visualization
    print("\nCreating visualization...")

    fig, ax = plt.subplots(figsize=(14, 8))

    # Sort experiments by kappa value
    sorted_exps = sorted(experiments.items(), key=lambda x: x[1], reverse=True)
    labels = [name for name, _ in sorted_exps]
    kappas = [kappa for _, kappa in sorted_exps]

    # Color bars based on interpretation
    colors = []
    for kappa in kappas:
        if kappa >= 0.8:
            colors.append('#4CAF50')  # Green - Almost Perfect
        elif kappa >= 0.6:
            colors.append('#8BC34A')  # Light Green - Substantial
        elif kappa >= 0.4:
            colors.append('#FFC107')  # Yellow - Moderate
        elif kappa >= 0.2:
            colors.append('#FF9800')  # Orange - Fair
        else:
            colors.append('#F44336')  # Red - Slight/Poor

    bars = ax.barh(labels, kappas, color=colors, alpha=0.8, edgecolor='black')

    # Add value labels
    for bar, kappa in zip(bars, kappas):
        width = bar.get_width()
        ax.text(width + 0.01, bar.get_y() + bar.get_height()/2.,
                f'{kappa:.3f}',
                ha='left', va='center', fontsize=10, fontweight='bold')

    # Add interpretation regions as vertical spans
    ax.axvspan(0.8, 1.0, alpha=0.1, color='green', label='Almost Perfect')
    ax.axvspan(0.6, 0.8, alpha=0.1, color='lightgreen', label='Substantial')
    ax.axvspan(0.4, 0.6, alpha=0.1, color='yellow', label='Moderate')
    ax.axvspan(0.2, 0.4, alpha=0.1, color='orange', label='Fair')
    ax.axvspan(0.0, 0.2, alpha=0.1, color='red', label='Slight')

    ax.set_xlabel("Fleiss' Kappa", fontsize=14, fontweight='bold')
    ax.set_ylabel("Normalization Task", fontsize=14, fontweight='bold')
    ax.set_title("Self-Consistency Comparison - Best Variants\n(Bedrock GPT-OSS 120B, 5-6 runs per task)",
                 fontsize=16, fontweight='bold')
    ax.set_xlim(0, 1.0)
    ax.grid(axis='x', alpha=0.3)
    ax.legend(loc='lower right', fontsize=10)

    plt.tight_layout()

    output_path = "experiments/compare_models/all_kappas_comparison.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_path}")
    plt.show()

    # Print summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for name, kappa in sorted_exps:
        print(f"{name:30s}: {kappa:.3f}")


if __name__ == "__main__":
    main()
