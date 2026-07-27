#!/usr/bin/env python3
"""
Simple model output comparison tool
Compares model outputs to baseline (gpt5_output.jsonl) for start_datetime and end_datetime
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

def parse_json_output(output: str) -> Dict[str, Any]:
    """Parse JSON output to extract start_datetime, end_datetime, and precision"""
    if not output or output.strip() == "":
        return {"start_datetime": None, "end_datetime": None, "precision": None}

    try:
        # Clean up JSON formatting
        clean_output = output.strip()
        if clean_output.startswith('```json'):
            clean_output = clean_output.replace('```json', '').replace('```', '').strip()
        elif clean_output.startswith('```'):
            clean_output = clean_output.replace('```', '').strip()

        data = json.loads(clean_output)
        return {
            "start_datetime": data.get("start_datetime"),
            "end_datetime": data.get("end_datetime"),
            "precision": data.get("precision")
        }
    except (json.JSONDecodeError, ValueError):
        return {"start_datetime": None, "end_datetime": None, "precision": None}

def truncate_datetime_to_precision(datetime_str: Optional[str], precision: str) -> Optional[str]:
    """Truncate datetime string to specified precision level"""
    if not datetime_str or not precision:
        return datetime_str

    # Map precision to datetime format truncation
    truncate_map = {
        "year": 4,      # YYYY
        "month": 7,     # YYYY-MM
        "day": 10,      # YYYY-MM-DD
        "hour": 13,     # YYYY-MM-DDTHH
        "minute": 16,   # YYYY-MM-DDTHH:MM
        "second": 19    # YYYY-MM-DDTHH:MM:SS
    }

    if precision in truncate_map:
        return datetime_str[:truncate_map[precision]]
    return datetime_str

def compare_datetimes(baseline_dt: Optional[str], model_dt: Optional[str],
                     baseline_precision: Optional[str], model_precision: Optional[str]) -> Dict[str, Any]:
    """Compare two datetime strings considering precision"""

    # Handle null cases
    if baseline_dt is None and model_dt is None:
        return {"match": True, "precision_match": baseline_precision == model_precision}
    if baseline_dt is None or model_dt is None:
        return {"match": False, "precision_match": baseline_precision == model_precision}

    # Simple string comparison for precision match
    precision_match = baseline_precision == model_precision

    # If precisions are the same, just compare datetime strings directly
    if precision_match:
        return {"match": baseline_dt == model_dt, "precision_match": True}

    # If precisions differ, find the coarser (less precise) precision for comparison
    precision_order = {"year": 1, "month": 2, "day": 3, "hour": 4, "minute": 5, "second": 6}
    baseline_level = precision_order.get(baseline_precision, 0)
    model_level = precision_order.get(model_precision, 0)

    if baseline_level == 0 or model_level == 0:
        # If we can't determine precision, do exact match
        return {"match": baseline_dt == model_dt, "precision_match": False}

    # Use the coarser precision (lower number) for comparison
    if baseline_level <= model_level:
        comparison_precision = baseline_precision
    else:
        comparison_precision = model_precision

    # Truncate both datetimes to the coarser precision
    baseline_truncated = truncate_datetime_to_precision(baseline_dt, comparison_precision)
    model_truncated = truncate_datetime_to_precision(model_dt, comparison_precision)

    return {
        "match": baseline_truncated == model_truncated,
        "precision_match": False  # Since precisions are different
    }

def main():
    """Main comparison function"""
    data_dir = Path("data")
    baseline_file = data_dir / "gpt5_output.jsonl"

    # Create results directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # Load baseline data
    print(f"Loading baseline from {baseline_file}")
    baseline_data = {}
    with open(baseline_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                baseline_data[line_num] = parse_json_output(data.get('output_content', ''))
            except json.JSONDecodeError:
                print(f"Error parsing baseline line {line_num}")
                continue

    print(f"Loaded {len(baseline_data)} baseline entries")

    # Find all other model output files
    model_files = [f for f in data_dir.glob("*.jsonl") if f.name != "gpt5_output.jsonl"]

    results = []

    # Compare each model file
    for model_file in model_files:
        print(f"Comparing {model_file.name}...")

        with open(model_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    model_name = data.get('model_name', 'unknown')  # Get model name from file content
                    # Now both files use 'output_content' field
                    model_output = parse_json_output(data.get('output_content', ''))

                    # Get corresponding baseline
                    if line_num not in baseline_data:
                        print(f"No baseline for line {line_num}")
                        continue

                    baseline = baseline_data[line_num]

                    # Compare start_datetime
                    start_comparison = compare_datetimes(
                        baseline["start_datetime"], model_output["start_datetime"],
                        baseline["precision"], model_output["precision"]
                    )

                    # Compare end_datetime
                    end_comparison = compare_datetimes(
                        baseline["end_datetime"], model_output["end_datetime"],
                        baseline["precision"], model_output["precision"]
                    )

                    # Overall correctness
                    correct = start_comparison["match"] and end_comparison["match"]
                    precision_match = start_comparison["precision_match"] and end_comparison["precision_match"]

                    results.append({
                        "line_number": line_num,
                        "model_name": model_name,
                        "correct": correct,
                        "precision_match": precision_match,
                        "start_match": start_comparison["match"],
                        "end_match": end_comparison["match"],
                        "baseline_start": baseline["start_datetime"],
                        "baseline_end": baseline["end_datetime"],
                        "baseline_precision": baseline["precision"],
                        "model_start": model_output["start_datetime"],
                        "model_end": model_output["end_datetime"],
                        "model_precision": model_output["precision"]
                    })

                except json.JSONDecodeError:
                    print(f"Error parsing {model_file.name} line {line_num}")
                    continue

    # Create summary DataFrame
    df = pd.DataFrame(results)

    # Save all results to organized results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed results
    detailed_file = results_dir / f"detailed_comparison_{timestamp}.csv"
    df.to_csv(detailed_file, index=False)
    print(f"Detailed results saved to {detailed_file}")

    # Create condensed summary
    summary_data = []
    print("\n=== COMPARISON SUMMARY ===")
    for model in df['model_name'].unique():
        model_df = df[df['model_name'] == model]
        total = len(model_df)
        correct = model_df['correct'].sum()
        precision_match = model_df['precision_match'].sum()
        start_matches = model_df['start_match'].sum()
        end_matches = model_df['end_match'].sum()

        # Condensed summary data
        summary_data.append({
            'model': model,
            'total': total,
            'correct': correct,
            'accuracy_%': round(correct/total*100, 1) if total > 0 else 0,
            'precision_match_%': round(precision_match/total*100, 1) if total > 0 else 0,
            'start_matches': start_matches,
            'end_matches': end_matches
        })

        print(f"\n{model}:")
        print(f"  Accuracy: {correct}/{total} ({correct/total*100:.1f}%)")
        print(f"  Precision matches: {precision_match}/{total} ({precision_match/total*100:.1f}%)")

    # Save condensed summary
    summary_df = pd.DataFrame(summary_data)
    summary_file = results_dir / f"summary_{timestamp}.csv"
    summary_df.to_csv(summary_file, index=False)
    print(f"\nCondensed summary saved to {summary_file}")

    # Create a single comprehensive report file
    report_file = results_dir / f"comparison_report_{timestamp}.txt"
    with open(report_file, "w") as f:
        f.write(f"MODEL COMPARISON REPORT - {timestamp}\n")
        f.write("=" * 60 + "\n\n")

        f.write("SUMMARY TABLE:\n")
        f.write("-" * 60 + "\n")
        f.write(f"{'Model':<15} {'Accuracy':<12} {'Precision':<12} {'Total':<8}\n")
        f.write("-" * 60 + "\n")

        for _, row in summary_df.iterrows():
            f.write(f"{row['model']:<15} {row['correct']}/{row['total']} ({row['accuracy_%']:.1f}%){'':<2} {row['precision_match_%']:.1f}%{'':<8} {row['total']:<8}\n")

        f.write(f"\nDetailed results: {detailed_file.name}\n")
        f.write(f"Summary data: {summary_file.name}\n")

    print(f"Comprehensive report saved to {report_file}")
    print(f"\nAll results saved to: {results_dir}/")

    return summary_df

if __name__ == "__main__":
    main()