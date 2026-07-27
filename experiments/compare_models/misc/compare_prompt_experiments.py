#!/usr/bin/env python3
"""
Compare results across different prompt experiments.

Analyzes how different system prompts affect model decisions and alignment.
"""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def extract_decision(text):
    """Extract VALID/INVALID decision from model output."""
    if not text:
        return None

    # Format 1: "FINAL DECISION: valid/invalid"
    m = re.search(r'FINAL\s+DECISION:\s*(valid|invalid)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    # Format 2: "CONCLUSION: VALID/INVALID"
    m = re.search(r'CONCLUSION:\s*(VALID|INVALID)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    # Format 3: JSON with "decision" key
    try:
        data = json.loads(text)
        if 'decision' in data:
            return data['decision'].lower()
    except:
        pass

    return None


def load_experiment_results(experiment_dir):
    """Load all results from an experiment directory."""
    experiment_dir = Path(experiment_dir)

    results_by_model = {}
    for jsonl_file in experiment_dir.glob('*.jsonl'):
        if jsonl_file.name == 'system_prompt.xml':
            continue

        results = []
        with open(jsonl_file) as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))

        if results:
            model_name = results[0].get('model_name', 'unknown')
            results_by_model[model_name] = results

    return results_by_model


def extract_xml_field(text, field):
    """Extract field from XML in user message."""
    if not text:
        return None
    match = re.search(f'<{field}>(.*?)</{field}>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def compare_experiments(experiment_dirs, output_file):
    """Compare results across multiple experiments."""

    # Load all experiments
    experiments = {}
    for exp_name, exp_dir in experiment_dirs.items():
        print(f"Loading experiment '{exp_name}' from {exp_dir}")
        experiments[exp_name] = load_experiment_results(exp_dir)
        for model, results in experiments[exp_name].items():
            print(f"  {model}: {len(results)} cases")

    # Get all models and cases
    all_models = set()
    for exp in experiments.values():
        all_models.update(exp.keys())
    all_models = sorted(all_models)

    # Get number of cases (should be same for all)
    num_cases = len(next(iter(next(iter(experiments.values())).values())))

    print(f"\nAnalyzing {num_cases} cases across {len(experiments)} experiments")
    print(f"Models: {', '.join(all_models)}\n")

    # Compare case by case
    case_comparisons = []

    for case_idx in range(num_cases):
        case_data = {
            'case_index': case_idx + 1,
            'experiments': {}
        }

        # Get user prompt info (same across all experiments)
        first_exp = next(iter(experiments.values()))
        first_model = next(iter(first_exp.values()))
        if case_idx < len(first_model):
            case = first_model[case_idx]
            user_msg = None
            for msg in case.get('input_messages', []):
                if msg.get('role') == 'user':
                    user_msg = msg.get('content')
                    break

            if user_msg:
                case_data['original_name'] = extract_xml_field(user_msg, 'name')
                case_data['original_context'] = extract_xml_field(user_msg, 'context')
                case_data['matched_instrument'] = extract_xml_field(user_msg, 'instrument')
                case_data['matched_mission'] = extract_xml_field(user_msg, 'mission')

        # Collect decisions from each experiment
        for exp_name, exp_results in experiments.items():
            case_data['experiments'][exp_name] = {}

            for model in all_models:
                if model in exp_results and case_idx < len(exp_results[model]):
                    result = exp_results[model][case_idx]
                    decision = extract_decision(result.get('output_content', ''))
                    case_data['experiments'][exp_name][model] = {
                        'decision': decision,
                        'output': result.get('output_content', '')
                    }

        case_comparisons.append(case_data)

    # Calculate alignment metrics
    print("\n" + "="*80)
    print("ALIGNMENT METRICS")
    print("="*80)

    for exp_name in experiments.keys():
        print(f"\nExperiment: {exp_name}")

        # Count agreements within this experiment
        agreements = 0
        for case in case_comparisons:
            decisions = [
                data['decision']
                for model, data in case['experiments'][exp_name].items()
                if data['decision'] is not None
            ]
            if len(set(decisions)) == 1:
                agreements += 1

        print(f"  Model agreement: {agreements}/{num_cases} ({100*agreements/num_cases:.1f}%)")

    # Generate HTML report
    generate_html_report(case_comparisons, experiments, all_models, output_file)


def generate_html_report(case_comparisons, experiments, models, output_file):
    """Generate HTML comparison report."""

    experiment_names = list(experiments.keys())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prompt Experiment Comparison</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1800px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .case {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .case-header {{
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 15px;
            margin-bottom: 15px;
        }}
        .case-header h2 {{
            margin: 0;
            color: #2196F3;
        }}
        .case-info {{
            background: #f9f9f9;
            padding: 15px;
            border-left: 4px solid #2196F3;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        .experiment-section {{
            margin-bottom: 30px;
        }}
        .experiment-title {{
            font-weight: 600;
            font-size: 18px;
            color: #1976D2;
            margin-bottom: 15px;
            padding: 10px;
            background: #E3F2FD;
            border-radius: 4px;
        }}
        .model-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .model-result {{
            background: #fafafa;
            padding: 15px;
            border-radius: 8px;
            border: 2px solid #e0e0e0;
        }}
        .model-result.valid {{
            border-color: #4CAF50;
        }}
        .model-result.invalid {{
            border-color: #f44336;
        }}
        .model-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .model-name {{
            font-weight: 600;
            font-size: 13px;
            color: #333;
        }}
        .decision-badge {{
            padding: 3px 10px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .decision-badge.valid {{
            background: #4CAF50;
            color: white;
        }}
        .decision-badge.invalid {{
            background: #f44336;
            color: white;
        }}
        .decision-badge.none {{
            background: #999;
            color: white;
        }}
        .alignment-indicator {{
            margin-top: 15px;
            padding: 10px;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 600;
        }}
        .alignment-indicator.aligned {{
            background: #E8F5E9;
            color: #2E7D32;
        }}
        .alignment-indicator.disagreement {{
            background: #FFEBEE;
            color: #C62828;
        }}
        .model-output {{
            font-size: 12px;
            line-height: 1.4;
            color: #666;
            max-height: 200px;
            overflow-y: auto;
            margin-top: 10px;
            padding: 8px;
            background: white;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
        }}
    </style>
</head>
<body>
    <h1>🔬 Prompt Experiment Comparison</h1>

    <div class="summary">
        <h2>Experiments Compared</h2>
        <ul>
"""

    for exp_name in experiment_names:
        html += f"            <li><strong>{exp_name}</strong></li>\n"

    html += f"""
        </ul>
        <p><strong>Models tested:</strong> {', '.join(models)}</p>
        <p><strong>Total cases:</strong> {len(case_comparisons)}</p>
    </div>

    <h2>Case-by-Case Comparison</h2>
"""

    # Add each case
    for case in case_comparisons:
        html += f"""
    <div class="case">
        <div class="case-header">
            <h2>Case {case['case_index']}</h2>
        </div>

        <div class="case-info">
            <div style="font-weight: 600; margin-bottom: 8px;">{case.get('original_name', 'N/A')}</div>
            <div style="font-size: 13px; color: #666; margin-bottom: 10px;">{case.get('original_context', '')[:200]}...</div>
            <div style="font-size: 12px; color: #888;">
                <strong>Instrument:</strong> {case.get('matched_instrument', 'N/A')}<br>
                <strong>Mission:</strong> {case.get('matched_mission', 'N/A')}
            </div>
        </div>
"""

        # Show results for each experiment
        for exp_name in experiment_names:
            exp_data = case['experiments'].get(exp_name, {})

            # Check if all models agree in this experiment
            decisions = [data['decision'] for data in exp_data.values() if data['decision'] is not None]
            aligned = len(set(decisions)) == 1 if decisions else False

            html += f"""
        <div class="experiment-section">
            <div class="experiment-title">{exp_name}</div>

            <div class="model-grid">
"""

            for model in models:
                model_data = exp_data.get(model, {})
                decision = model_data.get('decision', 'none')
                output = model_data.get('output', '')

                html += f"""
                <div class="model-result {decision if decision else 'none'}">
                    <div class="model-header">
                        <div class="model-name">{model}</div>
                        <div class="decision-badge {decision if decision else 'none'}">{decision if decision else 'N/A'}</div>
                    </div>
                </div>
"""

            html += """
            </div>
"""

            alignment_class = "aligned" if aligned else "disagreement"
            alignment_text = "✓ All models aligned" if aligned else "✗ Models disagree"

            html += f"""
            <div class="alignment-indicator {alignment_class}">
                {alignment_text}
            </div>
        </div>
"""

        html += """
    </div>
"""

    html += f"""
    <div style="color: #999; font-size: 14px; text-align: right; margin-top: 20px;">
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</body>
</html>
"""

    # Write file
    with open(output_file, 'w') as f:
        f.write(html)

    print(f"\nHTML report generated: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Compare results across prompt experiments',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python compare_prompt_experiments.py \\
    --experiments baseline=experiments/compare_models/prompt_experiments/baseline \\
                  strict=experiments/compare_models/prompt_experiments/strict \\
    --output experiments/compare_models/results/prompt_comparison.html
        """
    )

    parser.add_argument('--experiments', nargs='+', required=True,
                       help='Experiments to compare in format name=path (e.g., baseline=path/to/baseline)')
    parser.add_argument('--output', required=True,
                       help='Output HTML file path')

    args = parser.parse_args()

    # Parse experiment arguments
    experiment_dirs = {}
    for exp_arg in args.experiments:
        if '=' not in exp_arg:
            print(f"Error: Experiment must be in format name=path, got: {exp_arg}")
            sys.exit(1)

        name, path = exp_arg.split('=', 1)
        if not Path(path).exists():
            print(f"Error: Experiment directory not found: {path}")
            sys.exit(1)

        experiment_dirs[name] = path

    # Run comparison
    compare_experiments(experiment_dirs, args.output)


if __name__ == '__main__':
    main()
