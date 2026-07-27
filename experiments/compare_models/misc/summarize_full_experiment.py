#!/usr/bin/env python3
"""
Summarize comprehensive model comparison experiment results.

Analyzes results segmented by call type, showing model performance and agreement
rates for each call type separately.
"""
import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.core.registry import CallTypeRegistry
import experiments.compare_models.handlers  # Import to trigger registration


def load_jsonl(file_path: Path) -> List[dict]:
    """Load JSONL file into list of dicts."""
    results = []
    with open(file_path) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def analyze_experiment(experiment_dir: Path):
    """Analyze experiment results segmented by call type."""

    print("="*100)
    print("COMPREHENSIVE MODEL COMPARISON - RESULTS SUMMARY")
    print("="*100)
    print(f"Experiment Directory: {experiment_dir}\n")

    # Load all results and group by call_type and model
    all_results = defaultdict(lambda: defaultdict(list))

    result_files = sorted(experiment_dir.glob("*.jsonl"))

    if not result_files:
        print("ERROR: No result files found!")
        return

    print(f"Loading {len(result_files)} result files...\n")

    for result_file in result_files:
        results = load_jsonl(result_file)
        if not results:
            continue

        # Get call_type and model from first result
        call_type = results[0].get('call_type')
        model_name = results[0].get('model_name')

        if not call_type or not model_name:
            print(f"WARNING: Skipping {result_file.name} - missing call_type or model_name")
            continue

        all_results[call_type][model_name] = results

    # Get all models (should be same across all call types)
    all_models = set()
    for call_type_results in all_results.values():
        all_models.update(call_type_results.keys())
    all_models = sorted(all_models)

    print(f"Found {len(all_results)} call types")
    print(f"Found {len(all_models)} models: {', '.join(all_models)}\n")

    # Analyze each call type
    call_type_summaries = []

    for call_type in sorted(all_results.keys()):
        print("="*100)
        print(f"CALL TYPE: {call_type}")
        print("="*100)

        model_results = all_results[call_type]

        # Get handler for comparisons
        try:
            handler = CallTypeRegistry.get(call_type)
        except KeyError:
            print(f"WARNING: No handler found for {call_type}, skipping agreement analysis")
            handler = None

        # 1. Cost and Performance Summary
        print("\n1. COST & PERFORMANCE")
        print("-" * 100)

        for model_name in all_models:
            if model_name not in model_results:
                print(f"  {model_name}: NO DATA")
                continue

            results = model_results[model_name]

            # Calculate metrics
            total_cost = sum(r.get('estimated_cost_usd', 0) for r in results)
            total_tokens = sum(r.get('total_tokens', 0) for r in results)
            avg_duration = sum(r.get('duration_ms', 0) for r in results if r.get('duration_ms')) / len(results) if results else 0
            success_count = sum(1 for r in results if 'error' not in r)
            parse_success = sum(1 for r in results if r.get('parsed_response') is not None)

            print(f"\n  {model_name}:")
            print(f"    Cases: {len(results)}")
            print(f"    Success Rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
            print(f"    Parse Success: {parse_success}/{len(results)} ({parse_success/len(results)*100:.1f}%)")
            print(f"    Total Cost: ${total_cost:.4f}")
            print(f"    Avg Cost/Case: ${total_cost/len(results):.6f}")
            print(f"    Total Tokens: {total_tokens:,}")
            print(f"    Avg Tokens/Case: {int(total_tokens/len(results)):,}")
            print(f"    Avg Duration: {int(avg_duration):,} ms")

        # 2. Pairwise Agreement Analysis
        if handler and len(model_results) >= 2:
            print("\n2. MODEL AGREEMENT (Pairwise)")
            print("-" * 100)

            model_list = [m for m in all_models if m in model_results]

            for i, model1 in enumerate(model_list):
                for model2 in model_list[i+1:]:
                    results1 = model_results[model1]
                    results2 = model_results[model2]

                    # Align by case_index
                    agreements = 0
                    disagreements = 0
                    total_compared = 0

                    for r1 in results1:
                        case_idx = r1['case_index']
                        r2 = next((r for r in results2 if r['case_index'] == case_idx), None)

                        if r2 is None:
                            continue

                        parsed1 = r1.get('parsed_response')
                        parsed2 = r2.get('parsed_response')

                        # Skip if either failed to parse
                        if parsed1 is None or parsed2 is None:
                            continue

                        total_compared += 1

                        try:
                            comparison = handler.compare_responses(parsed1, parsed2)
                            if comparison.agree:
                                agreements += 1
                            else:
                                disagreements += 1
                        except Exception as e:
                            print(f"    Warning: Comparison failed for case {case_idx}: {e}")
                            continue

                    if total_compared > 0:
                        agreement_rate = agreements / total_compared * 100
                        print(f"\n  {model1} vs {model2}:")
                        print(f"    Agreement: {agreements}/{total_compared} ({agreement_rate:.1f}%)")
                        print(f"    Disagreement: {disagreements}/{total_compared} ({100-agreement_rate:.1f}%)")
                    else:
                        print(f"\n  {model1} vs {model2}: No comparable cases")

        # Store summary for final overview
        call_type_summaries.append({
            'call_type': call_type,
            'num_cases': len(next(iter(model_results.values()))) if model_results else 0,
            'models': len(model_results),
            'total_cost': sum(
                sum(r.get('estimated_cost_usd', 0) for r in results)
                for results in model_results.values()
            )
        })

        print("\n")

    # Final Summary
    print("="*100)
    print("OVERALL EXPERIMENT SUMMARY")
    print("="*100)

    total_cost_all = sum(s['total_cost'] for s in call_type_summaries)
    total_cases_all = sum(s['num_cases'] * s['models'] for s in call_type_summaries)

    print(f"\nTotal Call Types: {len(call_type_summaries)}")
    print(f"Total Models: {len(all_models)}")
    print(f"Total API Calls: {total_cases_all:,}")
    print(f"Total Cost: ${total_cost_all:.2f}")

    print("\nCost Breakdown by Call Type:")
    print("-" * 100)
    for summary in sorted(call_type_summaries, key=lambda x: x['total_cost'], reverse=True):
        print(f"  {summary['call_type']:30s}: ${summary['total_cost']:8.4f} ({summary['num_cases']} cases × {summary['models']} models)")

    print("\nCost Breakdown by Model:")
    print("-" * 100)
    model_costs = defaultdict(float)
    for call_type, model_results in all_results.items():
        for model_name, results in model_results.items():
            total_cost = sum(r.get('estimated_cost_usd', 0) for r in results)
            model_costs[model_name] += total_cost

    for model_name in sorted(model_costs.keys()):
        total = model_costs[model_name]
        pct = total / total_cost_all * 100 if total_cost_all > 0 else 0
        print(f"  {model_name:40s}: ${total:8.2f} ({pct:5.1f}%)")

    print("\n" + "="*100)
    print("Analysis complete!")
    print("="*100)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Summarize comprehensive model comparison experiment results"
    )
    parser.add_argument(
        '--experiment-dir',
        type=Path,
        default=Path('prompt_experiments/full_comparison_20251029'),
        help='Path to experiment directory (default: prompt_experiments/full_comparison_20251029)'
    )

    args = parser.parse_args()

    if not args.experiment_dir.exists():
        print(f"ERROR: Experiment directory not found: {args.experiment_dir}")
        sys.exit(1)

    analyze_experiment(args.experiment_dir)


if __name__ == '__main__':
    main()
