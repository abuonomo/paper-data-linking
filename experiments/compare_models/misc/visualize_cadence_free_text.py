"""
Visualize cadence_normalization self-consistency results.
"""
import json
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
import numpy as np

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


def extract_responses(runs, field='cadences'):
    """Extract responses organized by case index."""
    if not runs:
        return []

    n_cases = len(runs[0])
    responses_by_case = []

    for case_idx in range(n_cases):
        case_responses = []
        for run in runs:
            case = run[case_idx]
            parsed = case.get('parsed_response')

            if parsed and field in parsed:
                cadences = parsed[field]
                # Normalize to tuple for comparison
                if isinstance(cadences, list):
                    response = tuple(sorted(cadences)) if cadences else 'NONE'
                else:
                    response = cadences
            else:
                response = 'PARSE_ERROR'

            case_responses.append(response)

        responses_by_case.append(case_responses)

    return responses_by_case


def calculate_fleiss_kappa(responses_by_case):
    """
    Calculate Fleiss' Kappa for multi-rater agreement.
    """
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

    # Build matrix: rows = cases, columns = categories
    # matrix[i][j] = number of raters who assigned category j to case i
    matrix = np.zeros((n_cases, n_categories), dtype=int)

    for case_idx, responses in enumerate(responses_by_case):
        for response in responses:
            cat_idx = cat_to_idx[response]
            matrix[case_idx][cat_idx] += 1

    # Calculate P_i (proportion of agreement for each case)
    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1))
    P_bar = np.mean(P_i)

    # Calculate P_j (proportion of all assignments to category j)
    P_j = np.sum(matrix, axis=0) / (n_cases * n_raters)
    P_e_bar = np.sum(P_j ** 2)

    # Fleiss' Kappa
    if P_e_bar == 1.0:
        return 1.0

    kappa = (P_bar - P_e_bar) / (1 - P_e_bar)
    return kappa


def main():
    # Load cadence free text runs
    runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/bedrock_120b_cadence_free_text_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )

    if not runs:
        print("No experiment data found!")
        print("Make sure experiments/compare_models/prompt_experiments/bedrock_120b_cadence_free_text_full/ exists")
        return

    print(f"Loaded {len(runs)} runs with {len(runs[0])} cases each")

    # Extract responses
    responses = extract_responses(runs, 'cadences')

    # Calculate Fleiss' Kappa
    kappa = calculate_fleiss_kappa(responses)

    print(f"\nFleiss' Kappa: {kappa:.3f}")

    # Categorize agreement levels
    agreement_counts = Counter()
    for case_responses in responses:
        unique_responses = len(set(case_responses))
        if unique_responses == 1:
            agreement_counts['Perfect'] += 1
        elif unique_responses == 2:
            agreement_counts['Moderate'] += 1
        else:
            agreement_counts['Poor'] += 1

    total_cases = len(responses)

    # Count parse errors and NONE responses
    parse_error_count = sum(1 for resp in responses if 'PARSE_ERROR' in resp)
    none_count = sum(1 for resp in responses if 'NONE' in resp)

    print(f"\nAgreement breakdown:")
    print(f"  Perfect (5/5): {agreement_counts['Perfect']} ({100*agreement_counts['Perfect']/total_cases:.1f}%)")
    print(f"  Moderate (4/5 or 3/5): {agreement_counts['Moderate']} ({100*agreement_counts['Moderate']/total_cases:.1f}%)")
    print(f"  Poor (<3/5): {agreement_counts['Poor']} ({100*agreement_counts['Poor']/total_cases:.1f}%)")
    print(f"\nParse errors: {parse_error_count} cases")
    print(f"NONE responses: {none_count} cases")

    # Get top response patterns
    response_pattern_counts = Counter()
    for case_responses in responses:
        pattern = tuple(sorted(case_responses, key=str))
        response_pattern_counts[pattern] += 1

    print(f"\nTop 15 response patterns:")
    for pattern, count in response_pattern_counts.most_common(15):
        print(f"  {pattern}: {count} cases")

    # Create visualization
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))

    # Panel 1: Fleiss' Kappa with interpretation
    ax1.barh([0], [kappa], color='steelblue', height=0.3)
    ax1.set_xlim([-0.2, 1.0])
    ax1.set_ylim([-0.5, 0.5])
    ax1.set_xlabel('Fleiss\' Kappa', fontsize=12)
    ax1.set_title(f'Self-Consistency Score\n(5 runs, {total_cases} cases)', fontsize=14, fontweight='bold')
    ax1.set_yticks([])
    ax1.axvline(x=0, color='gray', linestyle='--', alpha=0.3)
    ax1.axvline(x=0.2, color='gray', linestyle='--', alpha=0.3)
    ax1.axvline(x=0.4, color='gray', linestyle='--', alpha=0.3)
    ax1.axvline(x=0.6, color='gray', linestyle='--', alpha=0.3)
    ax1.axvline(x=0.8, color='gray', linestyle='--', alpha=0.3)
    ax1.text(0.1, -0.35, 'Slight', ha='center', fontsize=9, color='gray')
    ax1.text(0.3, -0.35, 'Fair', ha='center', fontsize=9, color='gray')
    ax1.text(0.5, -0.35, 'Moderate', ha='center', fontsize=9, color='gray')
    ax1.text(0.7, -0.35, 'Substantial', ha='center', fontsize=9, color='gray')
    ax1.text(0.9, -0.35, 'Almost\nPerfect', ha='center', fontsize=9, color='gray')
    ax1.text(kappa, 0.15, f'κ = {kappa:.3f}', ha='center', fontsize=12, fontweight='bold')
    ax1.grid(axis='x', alpha=0.3)

    # Panel 2: Agreement breakdown
    categories = ['Perfect\n(5/5)', 'Moderate\n(4/5)', 'Poor\n(<3/5)', 'Parse\nErrors']
    counts = [
        agreement_counts['Perfect'],
        agreement_counts['Moderate'],
        agreement_counts['Poor'],
        parse_error_count
    ]
    colors = ['green', 'orange', 'red', 'gray']

    bars = ax2.bar(categories, counts, color=colors, alpha=0.7)
    ax2.set_ylabel('Number of Cases', fontsize=12)
    ax2.set_title(f'Agreement Breakdown\n({100*(total_cases-parse_error_count-agreement_counts["Poor"])/total_cases:.1f}% perfect/moderate agreement)', fontsize=14, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)

    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}',
                    ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Panel 3: Top response patterns
    top_patterns = response_pattern_counts.most_common(15)
    pattern_labels = []
    pattern_counts_list = []

    for pattern, count in top_patterns:
        # Format pattern for display
        if len(pattern) == 1:
            label = str(pattern[0])
        else:
            # Show unique values in pattern
            unique_vals = sorted(set(pattern), key=str)
            if len(unique_vals) == 1:
                label = f"{unique_vals[0]} (5)"
            else:
                label = f"{len(unique_vals)} variants"

        pattern_labels.append(label[:30])  # Truncate long labels
        pattern_counts_list.append(count)

    y_pos = np.arange(len(pattern_labels))
    ax3.barh(y_pos, pattern_counts_list, color='steelblue', alpha=0.7)
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(pattern_labels, fontsize=9)
    ax3.set_xlabel('Number of Cases', fontsize=12)
    ax3.set_title('Top 15 Response Patterns', fontsize=14, fontweight='bold')
    ax3.invert_yaxis()
    ax3.grid(axis='x', alpha=0.3)

    # Add value labels
    for i, v in enumerate(pattern_counts_list):
        ax3.text(v + 0.5, i, str(v), va='center', fontsize=9)

    plt.tight_layout()

    # Save figure
    output_path = Path("experiments/compare_models/prompt_experiments/bedrock_120b_cadence_free_text_full/cadence_free_text_analysis.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Saved visualization to {output_path}")

    plt.show()


if __name__ == "__main__":
    main()
