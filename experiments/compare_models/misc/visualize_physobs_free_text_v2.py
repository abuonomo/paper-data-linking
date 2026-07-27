"""
Visualize physobs_free_text_v2 self-consistency results across 5 runs.
"""
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any
import matplotlib.pyplot as plt
import numpy as np

def calculate_fleiss_kappa(responses: List[List[str]]) -> float:
    """Calculate Fleiss' Kappa for multiple raters."""
    n_cases = len(responses)
    n_raters = len(responses[0]) if responses else 0

    if n_cases == 0 or n_raters == 0:
        return 0.0

    # Get all unique categories
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


def load_run_data(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Load data from a JSONL file."""
    with open(jsonl_path) as f:
        return [json.loads(line) for line in f]


def main():
    experiment_dir = Path("experiments/compare_models/prompt_experiments/physobs_free_text_v2_bedrock_120b_full")

    # Find all JSONL files
    jsonl_files = sorted(experiment_dir.glob("bedrock_openai.gpt-oss-120b-1_0_*.jsonl"))

    print(f"Loading {len(jsonl_files)} runs...")

    # Load all runs
    runs_data = [load_run_data(f) for f in jsonl_files]

    # Verify all runs have same number of cases
    n_cases = len(runs_data[0])
    if not all(len(run) == n_cases for run in runs_data):
        print("Error: Runs have different number of cases")
        for i, run in enumerate(runs_data):
            print(f"  Run {i+1}: {len(run)} cases")
        return

    print(f"Loaded {len(runs_data)} runs with {n_cases} cases each")

    # Count parse success across all runs
    total_responses = sum(len(run) for run in runs_data)
    successful_parses = sum(
        1 for run in runs_data
        for case in run
        if case.get('parsed_response') is not None
    )
    parse_rate = successful_parses / total_responses if total_responses > 0 else 0

    print(f"\nParse Success: {successful_parses}/{total_responses} ({100*parse_rate:.1f}%)")

    # Organize responses by case
    responses_by_case = []
    for case_idx in range(n_cases):
        case_responses = []
        for run in runs_data:
            parsed = run[case_idx].get('parsed_response')
            if parsed:
                physobs = parsed.get('physical_observable', 'PARSE_ERROR')
            else:
                physobs = 'PARSE_ERROR'
            case_responses.append(physobs)
        responses_by_case.append(case_responses)

    # Calculate Fleiss' Kappa
    kappa = calculate_fleiss_kappa(responses_by_case)
    print(f"\nFleiss' Kappa: {kappa:.3f}")

    # Count response frequencies across all runs
    all_responses = []
    for case_responses in responses_by_case:
        all_responses.extend(case_responses)

    response_counts = Counter(all_responses)

    # Agreement analysis
    perfect_agreement = sum(1 for responses in responses_by_case if len(set(responses)) == 1)
    some_disagreement = n_cases - perfect_agreement

    print(f"\nAgreement Analysis:")
    print(f"  Perfect agreement ({len(runs_data)}/{len(runs_data)}): {perfect_agreement}/{n_cases} ({100*perfect_agreement/n_cases:.1f}%)")
    print(f"  Some disagreement: {some_disagreement}/{n_cases} ({100*some_disagreement/n_cases:.1f}%)")

    # Create visualization
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Panel 1: Fleiss' Kappa scale
    ax1 = axes[0]
    ax1.set_xlim(-0.2, 1.0)
    ax1.set_ylim(0, 1)

    # Kappa interpretation regions
    regions = [
        (-1.0, 0.0, 'Poor', '#ffcccc'),
        (0.0, 0.2, 'Slight', '#ffe6cc'),
        (0.2, 0.4, 'Fair', '#fff4cc'),
        (0.4, 0.6, 'Moderate', '#ffffcc'),
        (0.6, 0.8, 'Substantial', '#e6f7ff'),
        (0.8, 1.0, 'Almost\nPerfect', '#ccffcc'),
    ]

    for start, end, label, color in regions:
        if start >= -0.2:
            ax1.axvspan(start, end, alpha=0.3, color=color)
            mid = (start + end) / 2
            ax1.text(mid, 0.5, label, ha='center', va='center', fontsize=10, fontweight='bold')

    # Mark actual kappa
    ax1.axvline(kappa, color='red', linewidth=3, label=f'Kappa = {kappa:.3f}')
    ax1.plot(kappa, 0.5, 'ro', markersize=15, zorder=5)

    ax1.set_xlabel('Fleiss\' Kappa', fontsize=12, fontweight='bold')
    ax1.set_title(f'Self-Consistency Score - V2\n({len(runs_data)} runs, {n_cases} cases)', fontsize=12, fontweight='bold')
    ax1.set_yticks([])
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(axis='x', alpha=0.3)

    # Panel 2: Parse success rate
    ax2 = axes[1]
    categories = ['Parse\nSuccess', 'Parse\nFailure']
    values = [successful_parses, total_responses - successful_parses]
    colors_parse = ['#4CAF50', '#f44336']

    bars = ax2.bar(categories, values, color=colors_parse, alpha=0.7, edgecolor='black')
    ax2.set_ylabel('Number of Responses', fontsize=12, fontweight='bold')
    ax2.set_title(f'Parse Success Rate\n{successful_parses}/{total_responses} ({100*parse_rate:.1f}%)',
                  fontsize=12, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)

    # Add value labels on bars
    for bar, value in zip(bars, values):
        if value > 0:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{value}\n({100*value/total_responses:.1f}%)',
                    ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Panel 3: Top physobs responses
    ax3 = axes[2]

    # Get top 15 responses
    top_responses = response_counts.most_common(15)
    labels = [resp for resp, _ in top_responses]
    counts = [count for _, count in top_responses]

    # Truncate long labels
    labels_display = [label[:30] + '...' if len(label) > 30 else label for label in labels]

    bars = ax3.barh(range(len(labels_display)), counts, color='steelblue', alpha=0.7, edgecolor='black')
    ax3.set_yticks(range(len(labels_display)))
    ax3.set_yticklabels(labels_display, fontsize=8)
    ax3.set_xlabel(f'Frequency (across all {len(runs_data)} runs)', fontsize=12, fontweight='bold')
    ax3.set_title('Top 15 PhysObs Responses', fontsize=12, fontweight='bold')
    ax3.invert_yaxis()
    ax3.grid(axis='x', alpha=0.3)

    # Add value labels
    for bar, count in zip(bars, counts):
        width = bar.get_width()
        ax3.text(width, bar.get_y() + bar.get_height()/2.,
                f' {count}',
                ha='left', va='center', fontsize=8, fontweight='bold')

    plt.tight_layout()

    # Save figure
    output_path = experiment_dir / "physobs_free_text_v2_analysis.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()
