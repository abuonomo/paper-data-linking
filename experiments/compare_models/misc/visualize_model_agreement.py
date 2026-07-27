#!/usr/bin/env python3
"""
Visualize model agreement rates across call types.

Creates charts showing where models agree/disagree to identify which call types
are most sensitive to model choice.
"""
import json
import sys
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.core.registry import CallTypeRegistry
import experiments.compare_models.handlers  # Import to trigger registration


def load_jsonl(file_path: Path) -> list:
    """Load JSONL file into list of dicts."""
    results = []
    with open(file_path) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def calculate_agreement_matrix(experiment_dir: Path):
    """Calculate agreement rates for all model pairs across all call types."""

    # Load all results grouped by call_type and model
    all_results = defaultdict(lambda: defaultdict(list))

    result_files = sorted(experiment_dir.glob("*.jsonl"))

    for result_file in result_files:
        results = load_jsonl(result_file)
        if not results:
            continue

        call_type = results[0].get('call_type')
        model_name = results[0].get('model_name')

        if not call_type or not model_name:
            continue

        all_results[call_type][model_name] = results

    # Calculate agreement rates for each call type and model pair
    agreement_data = []

    for call_type in sorted(all_results.keys()):
        model_results = all_results[call_type]

        # Get handler
        try:
            handler = CallTypeRegistry.get(call_type)
        except KeyError:
            print(f"Warning: No handler for {call_type}, skipping")
            continue

        models = sorted(model_results.keys())

        # Calculate pairwise agreements
        for i, model1 in enumerate(models):
            for model2 in models[i+1:]:
                results1 = model_results[model1]
                results2 = model_results[model2]

                agreements = 0
                total = 0

                for r1 in results1:
                    case_idx = r1['case_index']
                    r2 = next((r for r in results2 if r['case_index'] == case_idx), None)

                    if r2 is None:
                        continue

                    parsed1 = r1.get('parsed_response')
                    parsed2 = r2.get('parsed_response')

                    if parsed1 is None or parsed2 is None:
                        continue

                    total += 1

                    try:
                        comparison = handler.compare_responses(parsed1, parsed2)
                        if comparison.agree:
                            agreements += 1
                    except Exception:
                        continue

                if total > 0:
                    agreement_rate = agreements / total * 100

                    # Simplify model names
                    m1_short = model1.split('/')[-1]
                    m2_short = model2.split('/')[-1]

                    agreement_data.append({
                        'call_type': call_type,
                        'model_pair': f"{m1_short} vs {m2_short}",
                        'model1': m1_short,
                        'model2': m2_short,
                        'agreement_rate': agreement_rate,
                        'disagreement_rate': 100 - agreement_rate,
                        'total_cases': total
                    })

    return agreement_data


def create_visualizations(agreement_data: list, output_dir: Path):
    """Create multiple visualizations of agreement data."""

    # Set style
    sns.set_theme(style="whitegrid")
    plt.rcParams['figure.figsize'] = (16, 10)

    # 1. Heatmap: Agreement rates by call type and model pair
    print("\nGenerating heatmap...")

    # Pivot data for heatmap
    call_types = sorted(set(d['call_type'] for d in agreement_data))
    model_pairs = sorted(set(d['model_pair'] for d in agreement_data))

    heatmap_data = np.zeros((len(call_types), len(model_pairs)))

    for i, call_type in enumerate(call_types):
        for j, model_pair in enumerate(model_pairs):
            match = next((d for d in agreement_data
                         if d['call_type'] == call_type and d['model_pair'] == model_pair), None)
            if match:
                heatmap_data[i, j] = match['agreement_rate']

    fig, ax = plt.subplots(figsize=(12, 10))
    sns.heatmap(heatmap_data,
                xticklabels=model_pairs,
                yticklabels=call_types,
                annot=True,
                fmt='.1f',
                cmap='RdYlGn',
                vmin=0,
                vmax=100,
                cbar_kws={'label': 'Agreement Rate (%)'},
                ax=ax)

    plt.title('Model Agreement Rates by Call Type', fontsize=16, fontweight='bold', pad=20)
    plt.xlabel('Model Pair', fontsize=12, fontweight='bold')
    plt.ylabel('Call Type', fontsize=12, fontweight='bold')
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    plt.tight_layout()

    heatmap_file = output_dir / 'agreement_heatmap.png'
    plt.savefig(heatmap_file, dpi=300, bbox_inches='tight')
    print(f"  Saved: {heatmap_file}")
    plt.close()

    # 2. Bar chart: Average agreement by call type
    print("\nGenerating call type comparison...")

    call_type_avg = defaultdict(list)
    for d in agreement_data:
        call_type_avg[d['call_type']].append(d['agreement_rate'])

    call_type_means = {ct: np.mean(rates) for ct, rates in call_type_avg.items()}
    sorted_call_types = sorted(call_type_means.items(), key=lambda x: x[1], reverse=True)

    fig, ax = plt.subplots(figsize=(14, 8))

    call_types_sorted = [ct for ct, _ in sorted_call_types]
    means = [mean for _, mean in sorted_call_types]

    colors = ['green' if mean >= 80 else 'orange' if mean >= 60 else 'red' for mean in means]

    bars = ax.barh(call_types_sorted, means, color=colors, alpha=0.7)

    # Add value labels
    for i, (bar, mean) in enumerate(zip(bars, means)):
        ax.text(mean + 1, i, f'{mean:.1f}%', va='center', fontweight='bold')

    ax.set_xlabel('Average Agreement Rate (%)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Call Type', fontsize=12, fontweight='bold')
    ax.set_title('Average Model Agreement by Call Type\n(Averaged across all model pairs)',
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xlim(0, 105)
    ax.grid(axis='x', alpha=0.3)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='green', alpha=0.7, label='High Agreement (≥80%)'),
        Patch(facecolor='orange', alpha=0.7, label='Medium Agreement (60-80%)'),
        Patch(facecolor='red', alpha=0.7, label='Low Agreement (<60%)')
    ]
    ax.legend(handles=legend_elements, loc='lower right')

    plt.tight_layout()

    calltype_file = output_dir / 'agreement_by_calltype.png'
    plt.savefig(calltype_file, dpi=300, bbox_inches='tight')
    print(f"  Saved: {calltype_file}")
    plt.close()

    # 3. Bar chart: Agreement by model pair (averaged across call types)
    print("\nGenerating model pair comparison...")

    model_pair_avg = defaultdict(list)
    for d in agreement_data:
        model_pair_avg[d['model_pair']].append(d['agreement_rate'])

    model_pair_means = {pair: np.mean(rates) for pair, rates in model_pair_avg.items()}
    sorted_pairs = sorted(model_pair_means.items(), key=lambda x: x[1], reverse=True)

    fig, ax = plt.subplots(figsize=(10, 6))

    pairs = [pair for pair, _ in sorted_pairs]
    means = [mean for _, mean in sorted_pairs]

    colors = ['steelblue', 'coral', 'mediumseagreen']
    bars = ax.bar(pairs, means, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)

    # Add value labels
    for bar, mean in zip(bars, means):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{mean:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=11)

    ax.set_ylabel('Average Agreement Rate (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Model Pair', fontsize=12, fontweight='bold')
    ax.set_title('Average Agreement Rate by Model Pair\n(Averaged across all call types)',
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_ylim(0, 105)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()

    modelpair_file = output_dir / 'agreement_by_modelpair.png'
    plt.savefig(modelpair_file, dpi=300, bbox_inches='tight')
    print(f"  Saved: {modelpair_file}")
    plt.close()

    # 4. Grouped bar chart: All model pairs for each call type
    print("\nGenerating detailed comparison...")

    fig, ax = plt.subplots(figsize=(16, 10))

    call_types = sorted(set(d['call_type'] for d in agreement_data))
    model_pairs = sorted(set(d['model_pair'] for d in agreement_data))

    x = np.arange(len(call_types))
    width = 0.25

    for i, model_pair in enumerate(model_pairs):
        rates = []
        for call_type in call_types:
            match = next((d for d in agreement_data
                         if d['call_type'] == call_type and d['model_pair'] == model_pair), None)
            rates.append(match['agreement_rate'] if match else 0)

        offset = width * (i - 1)
        ax.bar(x + offset, rates, width, label=model_pair, alpha=0.8)

    ax.set_ylabel('Agreement Rate (%)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Call Type', fontsize=12, fontweight='bold')
    ax.set_title('Model Agreement Rates by Call Type (Detailed View)',
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(call_types, rotation=45, ha='right')
    ax.legend(title='Model Pair', fontsize=10)
    ax.set_ylim(0, 105)
    ax.grid(axis='y', alpha=0.3)

    # Add reference line at 80%
    ax.axhline(y=80, color='green', linestyle='--', alpha=0.5, label='80% threshold')

    plt.tight_layout()

    detailed_file = output_dir / 'agreement_detailed.png'
    plt.savefig(detailed_file, dpi=300, bbox_inches='tight')
    print(f"  Saved: {detailed_file}")
    plt.close()

    # 5. Summary statistics table (as image)
    print("\nGenerating summary table...")

    fig, ax = plt.subplots(figsize=(14, 8))
    ax.axis('tight')
    ax.axis('off')

    # Prepare table data
    table_data = [['Call Type', 'gpt-5 vs gpt-5-mini', 'gpt-5 vs gpt-5-nano', 'gpt-5-mini vs gpt-5-nano', 'Average']]

    for call_type in sorted(call_types):
        row = [call_type.replace('_', ' ').title()]
        rates = []

        for model_pair in model_pairs:
            match = next((d for d in agreement_data
                         if d['call_type'] == call_type and d['model_pair'] == model_pair), None)
            if match:
                rate = match['agreement_rate']
                rates.append(rate)
                row.append(f"{rate:.1f}%")
            else:
                row.append('N/A')

        avg = np.mean(rates) if rates else 0
        row.append(f"{avg:.1f}%")
        table_data.append(row)

    # Add averages row
    avg_row = ['AVERAGE']
    for model_pair in model_pairs:
        rates = [d['agreement_rate'] for d in agreement_data if d['model_pair'] == model_pair]
        avg_row.append(f"{np.mean(rates):.1f}%")
    overall_avg = np.mean([d['agreement_rate'] for d in agreement_data])
    avg_row.append(f"{overall_avg:.1f}%")
    table_data.append(avg_row)

    table = ax.table(cellText=table_data, cellLoc='center', loc='center',
                    colWidths=[0.25, 0.15, 0.15, 0.15, 0.1])

    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)

    # Style header row
    for i in range(len(table_data[0])):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')

    # Style average row
    for i in range(len(avg_row)):
        table[(len(table_data)-1, i)].set_facecolor('#E0E0E0')
        table[(len(table_data)-1, i)].set_text_props(weight='bold')

    # Color code cells
    for i in range(1, len(table_data)-1):
        for j in range(1, len(table_data[0])-1):
            cell_text = table_data[i][j]
            if cell_text != 'N/A':
                rate = float(cell_text.strip('%'))
                if rate >= 80:
                    color = '#C8E6C9'  # light green
                elif rate >= 60:
                    color = '#FFE082'  # light orange
                else:
                    color = '#FFCDD2'  # light red
                table[(i, j)].set_facecolor(color)

    plt.title('Model Agreement Rates Summary Table', fontsize=16, fontweight='bold', pad=20)

    table_file = output_dir / 'agreement_table.png'
    plt.savefig(table_file, dpi=300, bbox_inches='tight')
    print(f"  Saved: {table_file}")
    plt.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Visualize model agreement rates across call types"
    )
    parser.add_argument(
        '--experiment-dir',
        type=Path,
        default=Path('prompt_experiments/full_comparison_20251029'),
        help='Path to experiment directory'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Output directory for visualizations (default: same as experiment-dir)'
    )

    args = parser.parse_args()

    if not args.experiment_dir.exists():
        print(f"ERROR: Experiment directory not found: {args.experiment_dir}")
        sys.exit(1)

    output_dir = args.output_dir or args.experiment_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("="*80)
    print("MODEL AGREEMENT VISUALIZATION")
    print("="*80)
    print(f"Experiment: {args.experiment_dir}")
    print(f"Output: {output_dir}\n")

    print("Calculating agreement rates...")
    agreement_data = calculate_agreement_matrix(args.experiment_dir)

    if not agreement_data:
        print("ERROR: No agreement data calculated!")
        sys.exit(1)

    print(f"Calculated {len(agreement_data)} agreement measurements")

    print("\nCreating visualizations...")
    create_visualizations(agreement_data, output_dir)

    print("\n" + "="*80)
    print("Visualization complete!")
    print("="*80)
    print(f"\nGenerated files in: {output_dir}")
    print("  - agreement_heatmap.png")
    print("  - agreement_by_calltype.png")
    print("  - agreement_by_modelpair.png")
    print("  - agreement_detailed.png")
    print("  - agreement_table.png")


if __name__ == '__main__':
    main()
