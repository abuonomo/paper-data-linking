#!/usr/bin/env python3
"""Generate HTML report for disagreements in 100-case sample."""
import json
import re
import html
from collections import defaultdict

def extract_decision(text):
    """Extract valid/invalid from response text."""
    m = re.search(r'FINAL\s+DECISION:\s*\*?\*?(valid|invalid)', text, re.IGNORECASE)
    return m.group(1).lower() if m else None

# Load all 4 model results
results_by_model = {}
dir_path = 'experiments/compare_models/prompt_experiments/sample4_100_all_models'

model_files = {
    'nano': 'openai_gpt-5-nano_20251008_170342.jsonl',
    'mini': 'openai_gpt-5-mini_20251008_172702.jsonl',
    'gpt-5': 'openai_gpt-5_20251008_175220.jsonl',
    'bedrock': 'bedrock_converse_openai.gpt-oss-120b-1:0_20251008_175853.jsonl'
}

for model_name, model_file in model_files.items():
    results_by_model[model_name] = {}
    with open(f'{dir_path}/{model_file}') as f:
        for line in f:
            result = json.loads(line)
            case_idx = result['case_index']
            results_by_model[model_name][case_idx] = result

# Find disagreements
disagreements = []
for case_idx in range(1, 101):
    decisions = {
        model: extract_decision(results_by_model[model][case_idx]['output_content'])
        for model in ['nano', 'mini', 'gpt-5', 'bedrock']
    }

    unique_decisions = set(decisions.values())
    if len(unique_decisions) > 1:
        disagreements.append(case_idx)

print(f"Found {len(disagreements)} disagreement cases")

# Generate HTML - start with header
html_content = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Sample 4 (100 cases) - All Disagreements (4 Models)</title>
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    max-width: 1800px;
    margin: 20px auto;
    padding: 20px;
    background: #f5f5f5;
}
.summary {
    background: white;
    padding: 20px;
    border-radius: 8px;
    margin-bottom: 30px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.case {
    background: white;
    padding: 25px;
    margin-bottom: 30px;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
.case-header {
    font-size: 20px;
    font-weight: bold;
    color: #2c3e50;
    margin-bottom: 15px;
    padding-bottom: 10px;
    border-bottom: 2px solid #3498db;
}
.message-section {
    margin: 20px 0;
}
.message-label {
    font-weight: bold;
    color: #34495e;
    margin-bottom: 8px;
}
.message-content {
    background: #f8f9fa;
    padding: 15px;
    border-radius: 4px;
    font-family: 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    white-space: pre-wrap;
    position: relative;
    border: 1px solid #dee2e6;
}
.copy-btn {
    position: absolute;
    top: 10px;
    right: 10px;
    padding: 6px 12px;
    background: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
}
.copy-btn:hover {
    background: #2980b9;
}
.model-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 15px;
    margin-top: 20px;
}
.model-response {
    border-radius: 6px;
    padding: 15px;
    position: relative;
}
.model-response.valid {
    border: 3px solid #27ae60;
    background: #e8f8f0;
}
.model-response.invalid {
    border: 3px solid #e74c3c;
    background: #fdecea;
}
.model-response.outlier {
    border: 3px solid #f39c12;
    background: #fef5e7;
    box-shadow: 0 0 10px rgba(243, 156, 18, 0.3);
}
.model-response.unparseable {
    border: 3px solid #95a5a6;
    background: #ecf0f1;
}
.model-name {
    font-weight: bold;
    font-size: 16px;
    margin-bottom: 10px;
    color: #2c3e50;
}
.decision-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 12px;
    font-weight: bold;
    font-size: 14px;
    margin-left: 8px;
}
.decision-badge.valid {
    background: #27ae60;
    color: white;
}
.decision-badge.invalid {
    background: #e74c3c;
    color: white;
}
.decision-badge.outlier {
    background: #f39c12;
    color: white;
}
.decision-badge.unparseable {
    background: #95a5a6;
    color: white;
}
.response-text {
    background: white;
    padding: 12px;
    border-radius: 4px;
    font-family: 'Monaco', 'Courier New', monospace;
    font-size: 12px;
    white-space: pre-wrap;
    max-height: 400px;
    overflow-y: auto;
    border: 1px solid #ddd;
    margin-top: 10px;
}
.stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 15px;
    margin-top: 15px;
}
.stat-box {
    background: #ecf0f1;
    padding: 15px;
    border-radius: 6px;
    text-align: center;
}
.stat-value {
    font-size: 32px;
    font-weight: bold;
    color: #2c3e50;
}
.stat-label {
    font-size: 14px;
    color: #7f8c8d;
    margin-top: 5px;
}
</style>
</head>
<body>

<div class="summary">
<h1>Sample 4 (100 cases) - Disagreement Analysis</h1>
<p><strong>Total Cases:</strong> 100</p>
<p><strong>Disagreements:</strong> """ + str(len(disagreements)) + """ (""" + str(len(disagreements)) + """%)</p>
<p><strong>4-Model Agreement Rate:</strong> """ + str(100 - len(disagreements)) + """%</p>

<div class="stats">
<div class="stat-box">
    <div class="stat-value">""" + str(len(disagreements)) + """</div>
    <div class="stat-label">Total Disagreements</div>
</div>
<div class="stat-box">
    <div class="stat-value">4</div>
    <div class="stat-label">Models Compared</div>
</div>
<div class="stat-box">
    <div class="stat-value">82%</div>
    <div class="stat-label">Agreement Rate</div>
</div>
<div class="stat-box">
    <div class="stat-value">$1.51</div>
    <div class="stat-label">Total Cost</div>
</div>
</div>

<p style="margin-top: 20px;"><strong>Models:</strong></p>
<ul>
<li><strong>nano:</strong> gpt-5-nano ($0.088, 319K tokens)</li>
<li><strong>mini:</strong> gpt-5-mini ($0.199, 199K tokens)</li>
<li><strong>gpt-5:</strong> gpt-5 ($1.168, 216K tokens)</li>
<li><strong>bedrock:</strong> bedrock/openai.gpt-oss-120b-1:0 ($0.054, 180K tokens)</li>
</ul>
</div>

<script>
function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    const text = element.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = element.previousElementSibling;
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = original, 2000);
    });
}
</script>
"""

# Add each disagreement case
for case_idx in disagreements:
    # Get all results for this case
    case_results = {
        model: results_by_model[model][case_idx]
        for model in ['nano', 'mini', 'gpt-5', 'bedrock']
    }

    # Get decisions
    decisions = {
        model: extract_decision(case_results[model]['output_content'])
        for model in ['nano', 'mini', 'gpt-5', 'bedrock']
    }

    # Find outliers
    decision_counts = defaultdict(list)
    for model, decision in decisions.items():
        decision_counts[decision].append(model)

    outliers = []
    if len(decision_counts) == 2:
        for decision, models in decision_counts.items():
            if len(models) == 1:
                outliers.extend(models)

    # Get system and user messages (from nano, they're all the same)
    nano_result = case_results['nano']
    system_msg = html.escape(nano_result['input_messages'][0]['content'])
    user_msg = html.escape(nano_result['input_messages'][1]['content'])

    html_content += f"""
<div class="case">
<div class="case-header">Case {case_idx}</div>

<div class="message-section">
<div class="message-label">System Message:</div>
<div class="message-content">
<button class="copy-btn" onclick="copyToClipboard('system-{case_idx}')">Copy</button>
<div id="system-{case_idx}">{system_msg}</div>
</div>
</div>

<div class="message-section">
<div class="message-label">User Message:</div>
<div class="message-content">
<button class="copy-btn" onclick="copyToClipboard('user-{case_idx}')">Copy</button>
<div id="user-{case_idx}">{user_msg}</div>
</div>
</div>

<div class="message-section">
<div class="message-label">Model Responses:</div>
<div class="model-grid">
"""

    # Add each model's response
    for model in ['nano', 'mini', 'gpt-5', 'bedrock']:
        decision = decisions[model]
        output = html.escape(case_results[model]['output_content'])

        is_outlier = model in outliers
        css_class = 'outlier' if is_outlier else (decision if decision else 'unparseable')

        badge_class = 'outlier' if is_outlier else (decision if decision else 'unparseable')
        badge_text = f"OUTLIER: {decision.upper() if decision else 'N/A'}" if is_outlier else (decision.upper() if decision else "UNPARSEABLE")

        html_content += f"""
<div class="model-response {css_class}">
<div class="model-name">
{model}
<span class="decision-badge {badge_class}">{badge_text}</span>
</div>
<div class="response-text">
<button class="copy-btn" onclick="copyToClipboard('response-{case_idx}-{model}')">Copy</button>
<div id="response-{case_idx}-{model}">{output}</div>
</div>
</div>
"""

    html_content += """
</div>
</div>
</div>
"""

html_content += """
</body>
</html>
"""

# Write to file
output_path = 'experiments/compare_models/results/sample4_100_disagreements_4models.html'
with open(output_path, 'w') as f:
    f.write(html_content)

print(f"HTML report generated: {output_path}")
print(f"Total disagreement cases: {len(disagreements)}")
