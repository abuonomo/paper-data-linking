"""
Visualize mission_selection self-consistency results across 5 runs.
"""
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any
import matplotlib.pyplot as plt
import numpy as np

def calculate_fleiss_kappa(responses: List[List[Any]]) -> float:
    """Calculate Fleiss' Kappa for multiple raters."""
    n_cases = len(responses)
    n_raters = len(responses[0]) if responses else 0

    if n_cases == 0 or n_raters == 0:
        return 0.0

    # Get all unique categories (convert all to strings)
    all_categories = set()
    for case_responses in responses:
        for r in case_responses:
            if r is None:
                all_categories.add('PARSE_ERROR')
            elif isinstance(r, tuple):
                # Convert tuple of mission indices to string
                all_categories.add(str(sorted(list(r))))
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
            if response is None:
                response_str = 'PARSE_ERROR'
            elif isinstance(response, tuple):
                response_str = str(sorted(list(response)))
            else:
                response_str = str(response)
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
    experiment_dir = Path("experiments/compare_models/prompt_experiments/bedrock_120b_mission_selection_full")

    # Find all JSONL files
    jsonl_files = sorted(experiment_dir.glob("bedrock_openai.gpt-oss-120b-1_0_*.jsonl"))

    if not jsonl_files:
        print(f"Error: No JSONL files found in {experiment_dir}")
        return

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
                is_ambiguous = parsed.get('is_ambiguous', False)
                if is_ambiguous:
                    response = 'AMBIGUOUS'
                else:
                    mission_indices = parsed.get('mission_indices', [])
                    response = tuple(sorted(mission_indices)) if mission_indices else 'EMPTY'
            else:
                response = 'PARSE_ERROR'
            case_responses.append(response)
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

    # Categorize disagreements
    ambiguous_involved = sum(1 for responses in responses_by_case
                            if len(set(responses)) > 1 and 'AMBIGUOUS' in responses)
    different_indices = sum(1 for responses in responses_by_case
                           if len(set(responses)) > 1 and 'AMBIGUOUS' not in responses and 'PARSE_ERROR' not in responses)
    parse_errors = sum(1 for responses in responses_by_case
                      if len(set(responses)) > 1 and 'PARSE_ERROR' in responses)

    print(f"\nDisagreement Types:")
    print(f"  AMBIGUOUS vs specific: {ambiguous_involved} cases")
    print(f"  Different mission indices: {different_indices} cases")
    print(f"  Parse errors: {parse_errors} cases")

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
        (0.8, 1.0, 'Almost\\nPerfect', '#ccffcc'),
    ]

    for start, end, label, color in regions:
        if start >= -0.2:
            ax1.axvspan(start, end, alpha=0.3, color=color)
            mid = (start + end) / 2
            ax1.text(mid, 0.5, label, ha='center', va='center', fontsize=10, fontweight='bold')

    # Mark actual kappa
    ax1.axvline(kappa, color='red', linewidth=3, label=f'Kappa = {kappa:.3f}')
    ax1.plot(kappa, 0.5, 'ro', markersize=15, zorder=5)

    ax1.set_xlabel("Fleiss' Kappa", fontsize=12, fontweight='bold')
    ax1.set_title(f'Self-Consistency Score\\n({len(runs_data)} runs, {n_cases} cases)', fontsize=12, fontweight='bold')
    ax1.set_yticks([])
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(axis='x', alpha=0.3)

    # Panel 2: Agreement breakdown
    ax2 = axes[1]
    categories = ['Perfect\\nAgreement', 'AMBIGUOUS\\nvs Specific', 'Different\\nIndices', 'Parse\\nErrors']
    values = [perfect_agreement, ambiguous_involved, different_indices, parse_errors]
    colors_agree = ['#4CAF50', '#FFC107', '#FF9800', '#f44336']

    bars = ax2.bar(categories, values, color=colors_agree, alpha=0.7, edgecolor='black')
    ax2.set_ylabel('Number of Cases', fontsize=12, fontweight='bold')
    ax2.set_title(f'Agreement Breakdown\\n({100*perfect_agreement/n_cases:.1f}% perfect agreement)',
                  fontsize=12, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)

    # Add value labels on bars
    for bar, value in zip(bars, values):
        if value > 0:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{value}\n({100*value/n_cases:.1f}%)',
                    ha='center', va='bottom', fontsize=9, fontweight='bold')

    # Panel 3: Top mission patterns
    ax3 = axes[2]

    # Convert tuples to readable strings for display
    display_counts = []
    for response, count in response_counts.most_common(15):
        if isinstance(response, tuple):
            label = str(list(response))
        else:
            label = str(response)
        # Truncate long labels
        if len(label) > 30:
            label = label[:27] + '...'
        display_counts.append((label, count))

    labels = [label for label, _ in display_counts]
    counts = [count for _, count in display_counts]

    bars = ax3.barh(range(len(labels)), counts, color='steelblue', alpha=0.7, edgecolor='black')
    ax3.set_yticks(range(len(labels)))
    ax3.set_yticklabels(labels, fontsize=8)
    ax3.set_xlabel(f'Frequency (across all {len(runs_data)} runs)', fontsize=12, fontweight='bold')
    ax3.set_title('Top 15 Mission Response Patterns', fontsize=12, fontweight='bold')
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
    output_path = experiment_dir / "mission_selection_analysis.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_path}")


if __name__ == "__main__":
    main()
