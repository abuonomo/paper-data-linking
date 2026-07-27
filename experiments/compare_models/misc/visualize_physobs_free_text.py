#!/usr/bin/env python3
"""
Visualize physobs_free_text self-consistency results.
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Dict, Any

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def load_results(result_dir: Path) -> List[Dict[str, Any]]:
    """Load all bedrock result files from directory."""
    files = sorted(result_dir.glob("bedrock_*.jsonl"))

    all_runs = []
    for f in files:
        run_results = []
        with open(f) as file:
            for line in file:
                run_results.append(json.loads(line))
        all_runs.append(run_results)

    return all_runs


def calculate_fleiss_kappa(runs: List[Dict[str, Any]]) -> tuple:
    """Calculate Fleiss' Kappa for self-consistency."""
    # Group by case ID
    cases_by_id = defaultdict(list)
    for run in runs:
        for result in run:
            case_id = result.get('original_id')
            parsed = result.get('parsed_response')
            if parsed:
                obs = parsed.get('physical_observable')
                cases_by_id[case_id].append(obs)

    # Calculate Fleiss' Kappa
    n = len(cases_by_id)  # number of items
    k = len(runs)  # number of raters

    # Count agreements
    P_values = []
    for responses in cases_by_id.values():
        if len(responses) < 2:
            continue

        # Count occurrences of each response
        counts = Counter(responses)
        # Calculate P_i = (sum of n_j^2 - n*k) / (n*k*(k-1))
        # where n_j is count of response j
        sum_squares = sum(count**2 for count in counts.values())
        P_i = (sum_squares - k) / (k * (k - 1))
        P_values.append(P_i)

    P_bar = np.mean(P_values) if P_values else 0

    # Calculate P_e (expected agreement)
    all_responses = []
    for responses in cases_by_id.values():
        all_responses.extend(responses)

    response_props = Counter(all_responses)
    total = len(all_responses)
    P_e = sum((count / total) ** 2 for count in response_props.values())

    # Fleiss' Kappa
    if P_e == 1:
        kappa = 1.0
    else:
        kappa = (P_bar - P_e) / (1 - P_e)

    return kappa, P_bar, P_e, len(P_values)


def calculate_parse_rate(runs: List[Dict[str, Any]]) -> tuple:
    """Calculate parse success rate across all runs."""
    total = 0
    parsed = 0

    for run in runs:
        for result in run:
            total += 1
            if result.get('parsed_response'):
                parsed += 1

    return parsed, total, parsed / total if total > 0 else 0


def get_response_distribution(runs: List[Dict[str, Any]]) -> Counter:
    """Get distribution of all responses."""
    all_responses = []

    for run in runs:
        for result in run:
            parsed = result.get('parsed_response')
            if parsed:
                obs = parsed.get('physical_observable')
                all_responses.append(obs)

    return Counter(all_responses)


def calculate_costs(runs: List[Dict[str, Any]]) -> tuple:
    """Calculate total costs and tokens."""
    total_cost = 0
    total_tokens = 0

    for run in runs:
        for result in run:
            total_cost += result.get('estimated_cost_usd', 0)
            total_tokens += result.get('total_tokens', 0)

    return total_cost, total_tokens


def create_visualizations(result_dir: Path, output_dir: Path):
    """Create comprehensive visualizations."""
    output_dir.mkdir(exist_ok=True)

    # Load results
    print("Loading results...")
    runs = load_results(result_dir)

    if not runs:
        print(f"No result files found in {result_dir}")
        return

    print(f"Loaded {len(runs)} runs")

    # Calculate metrics
    kappa, P_bar, P_e, n_cases = calculate_fleiss_kappa(runs)
    parsed, total, parse_rate = calculate_parse_rate(runs)
    response_dist = get_response_distribution(runs)
    total_cost, total_tokens = calculate_costs(runs)

    # Print summary
    print("\n" + "="*80)
    print("PHYSOBS FREE-TEXT SELF-CONSISTENCY ANALYSIS")
    print("="*80)
    print(f"Model: Bedrock GPT-OSS 120B")
    print(f"Runs: {len(runs)}")
    print(f"Cases per run: {len(runs[0]) if runs else 0}")
    print(f"\nFleiss' Kappa: {kappa:.3f}")
    print(f"  - Observer agreement (P̄): {P_bar:.3f}")
    print(f"  - Expected agreement (Pe): {P_e:.3f}")
    print(f"  - Cases analyzed: {n_cases}")
    print(f"\nParse Success Rate: {parse_rate*100:.1f}% ({parsed}/{total})")
    print(f"Total Cost: ${total_cost:.4f}")
    print(f"Total Tokens: {total_tokens:,}")
    print(f"\nTop 10 Responses:")
    for obs, count in response_dist.most_common(10):
        print(f"  {obs}: {count}")
    print("="*80)

    # Create figure with 3 subplots
    fig = plt.figure(figsize=(18, 6))

    # 1. Fleiss' Kappa visualization
    ax1 = plt.subplot(1, 3, 1)

    # Kappa interpretation ranges
    ranges = [
        (0.0, 0.2, "Slight", "#d32f2f"),
        (0.2, 0.4, "Fair", "#f57c00"),
        (0.4, 0.6, "Moderate", "#fbc02d"),
        (0.6, 0.8, "Substantial", "#7cb342"),
        (0.8, 1.0, "Almost Perfect", "#388e3c")
    ]

    # Draw interpretation scale
    for i, (low, high, label, color) in enumerate(ranges):
        ax1.barh(0, high - low, left=low, height=0.3, color=color, alpha=0.7)
        ax1.text((low + high) / 2, 0.4, label, ha='center', va='bottom', fontsize=8)

    # Draw kappa value
    ax1.plot([kappa, kappa], [-0.2, 0.2], 'k-', linewidth=3)
    ax1.plot(kappa, 0, 'ko', markersize=12)
    ax1.text(kappa, -0.3, f'κ = {kappa:.3f}', ha='center', va='top', fontsize=12, fontweight='bold')

    ax1.set_xlim(0, 1)
    ax1.set_ylim(-0.5, 0.5)
    ax1.set_xlabel("Fleiss' Kappa", fontsize=12)
    ax1.set_title("Self-Consistency (Fleiss' Kappa)", fontsize=14, fontweight='bold')
    ax1.set_yticks([])
    ax1.grid(axis='x', alpha=0.3)

    # 2. Parse success rate
    ax2 = plt.subplot(1, 3, 2)

    success = parsed
    failure = total - parsed

    bars = ax2.bar(['Success', 'Failure'], [success, failure], color=['#388e3c', '#d32f2f'])
    ax2.set_ylabel('Count', fontsize=12)
    ax2.set_title(f'Parse Success Rate: {parse_rate*100:.1f}%', fontsize=14, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)

    # Add value labels
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontsize=11, fontweight='bold')

    # 3. Top responses distribution
    ax3 = plt.subplot(1, 3, 3)

    top_n = 15
    top_responses = response_dist.most_common(top_n)
    labels = [obs[:30] + '...' if len(obs) > 30 else obs for obs, _ in top_responses]
    counts = [count for _, count in top_responses]

    bars = ax3.barh(range(len(labels)), counts, color='#1976d2')
    ax3.set_yticks(range(len(labels)))
    ax3.set_yticklabels(labels, fontsize=9)
    ax3.set_xlabel('Frequency', fontsize=12)
    ax3.set_title(f'Top {top_n} Responses', fontsize=14, fontweight='bold')
    ax3.invert_yaxis()
    ax3.grid(axis='x', alpha=0.3)

    # Add value labels
    for i, (bar, count) in enumerate(zip(bars, counts)):
        width = bar.get_width()
        ax3.text(width, i, f' {count}', ha='left', va='center', fontsize=9)

    plt.tight_layout()

    # Save
    output_file = output_dir / "physobs_free_text_analysis.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"\nVisualization saved to: {output_file}")

    plt.close()


if __name__ == "__main__":
    result_dir = Path("experiments/compare_models/prompt_experiments/physobs_free_text_bedrock_120b_full")
    output_dir = Path("experiments/compare_models/prompt_experiments/physobs_free_text_bedrock_120b_full")

    create_visualizations(result_dir, output_dir)
