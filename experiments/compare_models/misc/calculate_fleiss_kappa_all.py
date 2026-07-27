#!/usr/bin/env python3
"""Calculate Fleiss' kappa for all self-consistency experiments and plot results.

Fleiss' kappa measures inter-rater agreement for multiple raters (runs) classifying
items (test cases) into categories (unique responses).
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns


def load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load all records from a JSONL file."""
    records = []
    with open(filepath) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def normalize_response(response: str) -> str:
    """Normalize response text for comparison."""
    return response.strip().lower()


def calculate_fleiss_kappa(responses_by_case: Dict[str, List[str]]) -> Dict[str, Any]:
    """Calculate Fleiss' kappa for agreement across multiple runs.

    Args:
        responses_by_case: Dict mapping case_id to list of normalized responses

    Returns:
        Dict with kappa, p_observed, p_expected, and details
    """
    n_cases = len(responses_by_case)
    n_raters = len(next(iter(responses_by_case.values())))  # Number of runs

    # Build category mapping
    all_responses = set()
    for responses in responses_by_case.values():
        all_responses.update(responses)

    categories = sorted(all_responses)
    n_categories = len(categories)
    category_to_idx = {cat: idx for idx, cat in enumerate(categories)}

    # Build matrix: rows=cases, cols=categories, values=count of raters choosing that category
    matrix = np.zeros((n_cases, n_categories), dtype=int)

    for i, (case_id, responses) in enumerate(sorted(responses_by_case.items())):
        for response in responses:
            cat_idx = category_to_idx[response]
            matrix[i, cat_idx] += 1

    # Calculate P_i (proportion of agreement for case i)
    # P_i = (sum_j n_ij * (n_ij - 1)) / (n * (n - 1))
    # where n_ij is the number of raters assigning case i to category j
    P_i = np.sum(matrix * (matrix - 1), axis=1) / (n_raters * (n_raters - 1))

    # Calculate P_bar (mean proportion of agreement across all cases)
    P_bar = np.mean(P_i)

    # Calculate P_e (expected agreement by chance)
    # P_e = sum_j p_j^2, where p_j is the proportion of all assignments to category j
    p_j = np.sum(matrix, axis=0) / (n_cases * n_raters)
    P_e = np.sum(p_j ** 2)

    # Calculate Fleiss' kappa
    if P_e == 1.0:
        kappa = 1.0  # Perfect agreement
    else:
        kappa = (P_bar - P_e) / (1 - P_e)

    return {
        'kappa': kappa,
        'p_observed': P_bar,
        'p_expected': P_e,
        'n_cases': n_cases,
        'n_raters': n_raters,
        'n_categories': n_categories,
        'categories': categories
    }


def analyze_experiment(base_name: str, base_dir: Path) -> Dict:
    """Analyze a single self-consistency experiment."""
    run_dirs = sorted(base_dir.glob(f"{base_name}_run*"))

    if not run_dirs:
        return {'error': f'No run directories found for {base_name}'}

    # Load all runs
    cases_by_id = defaultdict(list)

    for run_dir in run_dirs:
        jsonl_files = list(run_dir.glob("*.jsonl"))
        if not jsonl_files:
            continue

        jsonl_file = jsonl_files[0]
        records = load_jsonl(jsonl_file)

        for record in records:
            case_id = record.get('original_id') or record.get('case_index')

            # Skip errors
            if 'error' in record:
                continue

            # Prefer parsed_response for structured outputs (e.g., instrument_validation)
            # Otherwise use full output_content
            response = record.get('parsed_response') or record.get('output_content') or record.get('response', '')
            if not response:
                continue

            cases_by_id[case_id].append(normalize_response(response))

    # Filter to only cases with complete data from all runs
    n_runs = len(run_dirs)
    complete_cases = {
        case_id: responses
        for case_id, responses in cases_by_id.items()
        if len(responses) == n_runs
    }

    if not complete_cases:
        return {'error': 'No complete cases found'}

    # Calculate Fleiss' kappa
    kappa_results = calculate_fleiss_kappa(complete_cases)

    # Add summary statistics
    n_perfect = sum(1 for responses in complete_cases.values() if len(set(responses)) == 1)

    return {
        'experiment_name': base_name,
        'n_runs': n_runs,
        'total_cases': len(cases_by_id),
        'complete_cases': len(complete_cases),
        'perfect_consistency': n_perfect,
        'perfect_consistency_pct': n_perfect / len(complete_cases) * 100,
        **kappa_results
    }


def main():
    base_dir = Path("experiments/compare_models/prompt_experiments")

    # Find all experiments with multiple runs
    all_dirs = [d.name for d in base_dir.iterdir() if d.is_dir()]
    base_names = set()
    for dirname in all_dirs:
        if '_run' in dirname:
            base_name = dirname.rsplit('_run', 1)[0]
            base_names.add(base_name)

    if not base_names:
        print(f"No self-consistency experiments found in {base_dir}")
        return

    # Analyze all experiments
    results = []
    for base_name in sorted(base_names):
        print(f"Analyzing {base_name}...")
        result = analyze_experiment(base_name, base_dir)

        if 'error' in result:
            print(f"  Error: {result['error']}")
            continue

        results.append(result)

        # Print summary
        print(f"  Fleiss' kappa: {result['kappa']:.4f}")
        print(f"  Complete cases: {result['complete_cases']}/{result['total_cases']}")
        print(f"  Perfect consistency: {result['perfect_consistency_pct']:.1f}%")
        print()

    if not results:
        print("No valid results to plot")
        return

    # Create comprehensive plot
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Sort by kappa for plotting
    results_sorted = sorted(results, key=lambda x: x['kappa'], reverse=True)

    # Plot 1: Fleiss' kappa by experiment
    ax1 = axes[0, 0]
    exp_names = [r['experiment_name'].replace('_', '\n') for r in results_sorted]
    kappas = [r['kappa'] for r in results_sorted]
    colors = ['green' if k > 0.8 else 'orange' if k > 0.6 else 'red' for k in kappas]

    bars = ax1.barh(exp_names, kappas, color=colors, alpha=0.7, edgecolor='black')
    ax1.set_xlabel("Fleiss' Kappa", fontsize=12, fontweight='bold')
    ax1.set_title("Self-Consistency Agreement (Fleiss' Kappa)\nAcross All Experiments",
                  fontsize=14, fontweight='bold')
    ax1.axvline(x=0.8, color='green', linestyle='--', alpha=0.5, label='Excellent (>0.8)')
    ax1.axvline(x=0.6, color='orange', linestyle='--', alpha=0.5, label='Good (>0.6)')
    ax1.set_xlim(0, 1.0)
    ax1.legend()
    ax1.grid(axis='x', alpha=0.3)

    # Add kappa values on bars
    for i, (bar, kappa) in enumerate(zip(bars, kappas)):
        ax1.text(kappa + 0.02, i, f'{kappa:.3f}',
                va='center', fontsize=10, fontweight='bold')

    # Plot 2: Perfect consistency percentage
    ax2 = axes[0, 1]
    perfect_pcts = [r['perfect_consistency_pct'] for r in results_sorted]
    bars2 = ax2.barh(exp_names, perfect_pcts, color='skyblue', alpha=0.7, edgecolor='black')
    ax2.set_xlabel("Perfect Consistency %", fontsize=12, fontweight='bold')
    ax2.set_title("Perfect Consistency Rate\n(All Runs Identical)",
                  fontsize=14, fontweight='bold')
    ax2.set_xlim(0, 100)
    ax2.grid(axis='x', alpha=0.3)

    # Add percentages on bars
    for i, (bar, pct) in enumerate(zip(bars2, perfect_pcts)):
        ax2.text(pct + 1, i, f'{pct:.1f}%',
                va='center', fontsize=10, fontweight='bold')

    # Plot 3: Observed vs Expected Agreement
    ax3 = axes[1, 0]
    p_observed = [r['p_observed'] for r in results_sorted]
    p_expected = [r['p_expected'] for r in results_sorted]

    x = np.arange(len(exp_names))
    width = 0.35

    bars3a = ax3.barh(x - width/2, p_observed, width, label='Observed',
                      color='steelblue', alpha=0.7, edgecolor='black')
    bars3b = ax3.barh(x + width/2, p_expected, width, label='Expected (chance)',
                      color='lightcoral', alpha=0.7, edgecolor='black')

    ax3.set_yticks(x)
    ax3.set_yticklabels(exp_names)
    ax3.set_xlabel("Agreement Proportion", fontsize=12, fontweight='bold')
    ax3.set_title("Observed vs Expected Agreement", fontsize=14, fontweight='bold')
    ax3.legend()
    ax3.set_xlim(0, 1.0)
    ax3.grid(axis='x', alpha=0.3)

    # Plot 4: Summary statistics table
    ax4 = axes[1, 1]
    ax4.axis('off')

    # Create table data
    table_data = []
    for r in results_sorted:
        table_data.append([
            r['experiment_name'][:30],
            f"{r['kappa']:.3f}",
            f"{r['perfect_consistency_pct']:.1f}%",
            f"{r['complete_cases']}/{r['total_cases']}",
            str(r['n_runs'])
        ])

    table = ax4.table(
        cellText=table_data,
        colLabels=['Experiment', 'Kappa', 'Perfect %', 'Cases', 'Runs'],
        cellLoc='left',
        loc='center',
        colWidths=[0.35, 0.15, 0.15, 0.15, 0.10]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)

    # Style header
    for i in range(5):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')

    # Color code kappa values
    for i, r in enumerate(results_sorted):
        kappa = r['kappa']
        if kappa > 0.8:
            table[(i+1, 1)].set_facecolor('#c8e6c9')
        elif kappa > 0.6:
            table[(i+1, 1)].set_facecolor('#ffe0b2')
        else:
            table[(i+1, 1)].set_facecolor('#ffcdd2')

    ax4.set_title("Summary Statistics", fontsize=14, fontweight='bold', pad=20)

    # Overall figure title
    fig.suptitle('Self-Consistency Analysis: Fleiss\' Kappa Across All Experiments',
                 fontsize=16, fontweight='bold', y=0.995)

    plt.tight_layout()

    # Save plot
    output_path = Path("experiments/compare_models/fleiss_kappa_all_experiments.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\nPlot saved to: {output_path}")

    # Also save results as JSON
    json_path = Path("experiments/compare_models/fleiss_kappa_results.json")
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {json_path}")

    plt.show()


if __name__ == '__main__':
    main()
