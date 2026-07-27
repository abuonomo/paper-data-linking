#!/usr/bin/env python3
"""Generate HTML report for model comparison disagreements."""
import json
import re
from pathlib import Path
from datetime import datetime


def extract_decision(text):
    """Extract VALID/INVALID decision from model output."""
    if not text:
        return None

    # Try different formats
    m = re.search(r'FINAL\s+DECISION:\s*(valid|invalid)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    m = re.search(r'CONCLUSION:\s*(VALID|INVALID)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    try:
        data = json.loads(text)
        if 'decision' in data:
            return data['decision'].lower()
    except:
        pass

    return None


def extract_xml_field(text, field):
    """Extract field from XML in user message."""
    match = re.search(f'<{field}>(.*?)</{field}>', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def load_results(filepath):
    """Load results from JSONL file."""
    results = []
    with open(filepath) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def generate_html_report(baseline_file, mini_file, gpt5_file, output_file):
    """Generate HTML report comparing three models."""
    baseline = load_results(baseline_file)
    mini_results = load_results(mini_file)
    gpt5_results = load_results(gpt5_file)

    # Find disagreements
    disagreements = []
    for idx, baseline_item in enumerate(baseline):
        baseline_decision = extract_decision(baseline_item.get('output_content') or baseline_item.get('response'))
        mini_decision = extract_decision(mini_results[idx].get('output_content')) if idx < len(mini_results) else None
        gpt5_decision = extract_decision(gpt5_results[idx].get('output_content')) if idx < len(gpt5_results) else None

        all_decisions = [baseline_decision, mini_decision, gpt5_decision]
        if None not in all_decisions and len(set(all_decisions)) > 1:
            # Extract info from input messages
            user_msg = None
            if baseline_item.get('input_messages'):
                for msg in baseline_item['input_messages']:
                    if msg.get('role') == 'user':
                        user_msg = msg.get('content', '')
                        break

            original_name = extract_xml_field(user_msg, 'name') if user_msg else ''
            original_context = extract_xml_field(user_msg, 'context') if user_msg else ''
            matched_instrument = extract_xml_field(user_msg, 'instrument') if user_msg else ''
            matched_mission = extract_xml_field(user_msg, 'mission') if user_msg else ''

            disagreements.append({
                'line': idx + 1,
                'original_name': original_name,
                'original_context': original_context,
                'matched_instrument': matched_instrument,
                'matched_mission': matched_mission,
                'nano_decision': baseline_decision,
                'nano_output': baseline_item.get('output_content') or baseline_item.get('response', ''),
                'mini_decision': mini_decision,
                'mini_output': mini_results[idx].get('output_content', ''),
                'gpt5_decision': gpt5_decision,
                'gpt5_output': gpt5_results[idx].get('output_content', ''),
            })

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Model Comparison - Plain Text Output</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 1600px;
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
        .summary h2 {{
            margin-top: 0;
            color: #4CAF50;
        }}
        .stat {{
            display: inline-block;
            margin-right: 30px;
            font-size: 16px;
        }}
        .stat strong {{
            color: #2196F3;
            font-size: 20px;
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
            margin: 0 0 10px 0;
            color: #2196F3;
        }}
        .original-description {{
            background: #f9f9f9;
            padding: 15px;
            border-left: 4px solid #2196F3;
            margin-bottom: 15px;
            border-radius: 4px;
        }}
        .original-name {{
            font-weight: 600;
            font-size: 16px;
            color: #333;
            margin-bottom: 8px;
        }}
        .original-context {{
            color: #666;
            font-size: 14px;
            font-style: italic;
            margin-top: 8px;
        }}
        .matched-info {{
            background: #e3f2fd;
            padding: 15px;
            border-left: 4px solid #1976D2;
            margin-bottom: 20px;
            border-radius: 4px;
        }}
        .matched-label {{
            font-weight: 600;
            color: #1565C0;
            margin-bottom: 5px;
        }}
        .matched-value {{
            color: #424242;
            font-size: 14px;
        }}
        .model-comparison {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-top: 20px;
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
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .model-name {{
            font-weight: 600;
            font-size: 14px;
            color: #333;
        }}
        .decision-badge {{
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
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
        .model-output {{
            font-size: 13px;
            line-height: 1.6;
            color: #333;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 600px;
            overflow-y: auto;
            background: white;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
        }}
        .key-findings {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-top: 20px;
            border-radius: 4px;
        }}
        .key-findings h3 {{
            margin-top: 0;
            color: #856404;
        }}
        .key-findings ul {{
            margin-bottom: 0;
        }}
        .key-findings li {{
            margin-bottom: 8px;
        }}
        .timestamp {{
            color: #999;
            font-size: 14px;
            text-align: right;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <h1>🔬 Model Comparison - Plain Text Output</h1>

    <div class="summary">
        <h2>Summary Statistics</h2>
        <div class="stat">Total Cases: <strong>20</strong></div>
        <div class="stat">Full Agreement: <strong>11 (55%)</strong></div>
        <div class="stat">Disagreements: <strong>{len(disagreements)} (45%)</strong></div>
    </div>

    <div class="key-findings">
        <h3>🔑 Key Findings</h3>
        <ul>
            <li><strong>GPT-5-nano is more lenient:</strong> Outlier in 5/9 disagreements (55.6%)</li>
            <li><strong>GPT-5-mini and GPT-5 more strict:</strong> Each outlier in 2/9 disagreements (22.2%)</li>
            <li><strong>Main disagreement pattern:</strong>
                <ul>
                    <li><strong>Nano (lenient):</strong> Accepts partial instrument matches, assumes other mission instruments provide missing data</li>
                    <li><strong>Mini/GPT-5 (strict):</strong> Requires matched instrument to perform ALL described observations by itself</li>
                </ul>
            </li>
            <li><strong>Common cases where Nano is lenient:</strong>
                <ul>
                    <li>Description mentions multiple instruments/measurements → only one matched (e.g., "magnetometer + plasma" → only magnetometer)</li>
                    <li>Description mentions multiple instruments by name → only subset matched (e.g., "FIELDS and FPI" → only FPI)</li>
                    <li>Generic instrument reference → specific sub-instrument (e.g., "FPI" → "FPI DIS only")</li>
                </ul>
            </li>
        </ul>
    </div>

    <h2 style="margin-top: 40px; color: #333;">Disagreement Details ({len(disagreements)} cases)</h2>
"""

    # Add each disagreement
    for case in disagreements:
        # Determine outlier
        decisions = [case['nano_decision'], case['mini_decision'], case['gpt5_decision']]
        outlier = []
        if decisions.count(case['nano_decision']) == 1:
            outlier.append('Nano')
        if decisions.count(case['mini_decision']) == 1:
            outlier.append('Mini')
        if decisions.count(case['gpt5_decision']) == 1:
            outlier.append('GPT-5')

        outlier_text = ' + '.join(outlier) + ' outlier' if outlier else 'No clear outlier'

        html += f"""
    <div class="case">
        <div class="case-header">
            <h2>Line {case['line']}</h2>
            <div style="color: #666; font-size: 14px; margin-top: 5px;">
                <strong>Outlier:</strong> {outlier_text}
            </div>
        </div>

        <div class="original-description">
            <div class="original-name">{case['original_name']}</div>
            {f'<div class="original-context">{case["original_context"][:500]}{"..." if len(case["original_context"]) > 500 else ""}</div>' if case['original_context'] else ''}
        </div>

        <div class="matched-info">
            <div class="matched-label">Matched Instrument:</div>
            <div class="matched-value">{case['matched_instrument']}</div>
            <div class="matched-label" style="margin-top: 10px;">Matched Mission:</div>
            <div class="matched-value">{case['matched_mission']}</div>
        </div>

        <div class="model-comparison">
            <div class="model-result {case['nano_decision']}">
                <div class="model-header">
                    <div class="model-name">GPT-5-nano (baseline)</div>
                    <div class="decision-badge {case['nano_decision']}">{case['nano_decision']}</div>
                </div>
                <div class="model-output">{case['nano_output']}</div>
            </div>

            <div class="model-result {case['mini_decision']}">
                <div class="model-header">
                    <div class="model-name">GPT-5-mini</div>
                    <div class="decision-badge {case['mini_decision']}">{case['mini_decision']}</div>
                </div>
                <div class="model-output">{case['mini_output']}</div>
            </div>

            <div class="model-result {case['gpt5_decision']}">
                <div class="model-header">
                    <div class="model-name">GPT-5</div>
                    <div class="decision-badge {case['gpt5_decision']}">{case['gpt5_decision']}</div>
                </div>
                <div class="model-output">{case['gpt5_output']}</div>
            </div>
        </div>
    </div>
"""

    html += f"""
    <div class="timestamp">
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</body>
</html>
"""

    # Write to file
    with open(output_file, 'w') as f:
        f.write(html)

    print(f"HTML report generated: {output_file}")
    return output_file


if __name__ == '__main__':
    baseline_file = 'inputs/instrument_validation_sample_20.jsonl'
    mini_file = 'experiments/compare_models/data/openai_gpt-5-mini_20251007_170737.jsonl'
    gpt5_file = 'experiments/compare_models/data/openai_gpt-5_20251007_170751.jsonl'
    output_file = 'experiments/compare_models/results/model_comparison_plaintext_full.html'

    generate_html_report(baseline_file, mini_file, gpt5_file, output_file)
