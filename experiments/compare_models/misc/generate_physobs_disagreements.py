"""Generate HTML report for physobs normalization disagreements."""
import json
import html
from pathlib import Path

# Paths to result files
base_dir = Path("experiments/compare_models/experiments/compare_models/prompt_experiments/physobs_10_all_models")
nano_file = base_dir / "openai_gpt-5-nano_20251009_143530.jsonl"
mini_file = base_dir / "openai_gpt-5-mini_20251009_143704.jsonl"
gpt5_file = base_dir / "openai_gpt-5_20251009_143944.jsonl"

# Load results
nano_results = [json.loads(line) for line in open(nano_file)]
mini_results = [json.loads(line) for line in open(mini_file)]
gpt5_results = [json.loads(line) for line in open(gpt5_file)]

# Import handler for comparison
import sys
sys.path.insert(0, '.')
from experiments.compare_models.handlers.physobs_normalization import PhysObsNormalizationHandler

handler = PhysObsNormalizationHandler()

# Find disagreements
disagreements = []
for i in range(10):
    nano_parsed = nano_results[i]['parsed_response']
    mini_parsed = mini_results[i]['parsed_response']
    gpt5_parsed = gpt5_results[i]['parsed_response']

    cmp1 = handler.compare_responses(nano_parsed, mini_parsed)
    cmp2 = handler.compare_responses(nano_parsed, gpt5_parsed)
    cmp3 = handler.compare_responses(mini_parsed, gpt5_parsed)

    if not (cmp1.agree and cmp2.agree and cmp3.agree):
        disagreements.append({
            'case_index': i,
            'nano': nano_results[i],
            'mini': mini_results[i],
            'gpt5': gpt5_results[i]
        })

print(f"Found {len(disagreements)} disagreement cases")

# Generate HTML
html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>PhysObs Normalization Disagreements (3 Models)</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background: #f5f5f5;
        }
        .header {
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .case {
            background: white;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .case-header {
            font-size: 1.3em;
            font-weight: bold;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e0e0e0;
        }
        .section {
            margin: 15px 0;
        }
        .section-title {
            font-weight: bold;
            color: #555;
            margin-bottom: 8px;
            font-size: 0.95em;
            text-transform: uppercase;
        }
        .prompt-box {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            border-left: 4px solid #4a90e2;
            margin: 10px 0;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .responses {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin: 15px 0;
        }
        .response {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            border-left: 4px solid #4a90e2;
        }
        .response.nano {
            border-left-color: #e74c3c;
        }
        .response.mini {
            border-left-color: #3498db;
        }
        .response.gpt5 {
            border-left-color: #2ecc71;
        }
        .response-header {
            font-weight: bold;
            margin-bottom: 10px;
            font-size: 1.1em;
        }
        .response-content {
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            word-wrap: break-word;
            background: white;
            padding: 10px;
            border-radius: 3px;
            margin-top: 8px;
        }
        .parsed-response {
            margin-top: 10px;
            padding: 10px;
            background: #fffbf0;
            border-radius: 3px;
            border: 1px solid #ffd700;
        }
        .parsed-label {
            font-weight: bold;
            color: #f39c12;
            margin-bottom: 5px;
            font-size: 0.9em;
        }
        .copy-btn {
            background: #4a90e2;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 0.85em;
            margin-top: 5px;
        }
        .copy-btn:hover {
            background: #357abd;
        }
        .stats {
            background: #e8f4f8;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 15px;
        }
        .outlier {
            background: #fff3cd;
            border-left-color: #ff9800 !important;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>PhysObs Normalization Disagreements</h1>
        <div class="stats">
            <strong>Total disagreement cases:</strong> """ + str(len(disagreements)) + """<br>
            <strong>Models compared:</strong> nano, mini, gpt-5<br>
            <strong>Agreement rate:</strong> """ + str(round((10 - len(disagreements)) / 10 * 100)) + """%<br>
            <strong>Note:</strong> Models are choosing from instrument-specific candidate lists
        </div>
    </div>
"""

for disagreement in disagreements:
    case_idx = disagreement['case_index']
    nano = disagreement['nano']
    mini = disagreement['mini']
    gpt5 = disagreement['gpt5']

    # Get system and user messages (should be same across all models)
    system_msg = nano['input_messages'][0]['content']
    user_msg = nano['input_messages'][1]['content']

    # Determine outlier (if 2 agree and 1 disagrees)
    nano_val = nano['parsed_response']['physical_observable']
    mini_val = mini['parsed_response']['physical_observable']
    gpt5_val = gpt5['parsed_response']['physical_observable']

    outlier = None
    if nano_val == gpt5_val and nano_val != mini_val:
        outlier = 'mini'
    elif nano_val == mini_val and nano_val != gpt5_val:
        outlier = 'gpt5'
    elif mini_val == gpt5_val and mini_val != nano_val:
        outlier = 'nano'

    html_content += f"""
    <div class="case">
        <div class="case-header">Case {case_idx}</div>

        <div class="section">
            <div class="section-title">System Prompt</div>
            <div class="prompt-box" id="system-{case_idx}">{html.escape(system_msg)}</div>
            <button class="copy-btn" onclick="copyText('system-{case_idx}')">Copy System Prompt</button>
        </div>

        <div class="section">
            <div class="section-title">User Message</div>
            <div class="prompt-box" id="user-{case_idx}">{html.escape(user_msg)}</div>
            <button class="copy-btn" onclick="copyText('user-{case_idx}')">Copy User Message</button>
        </div>

        <div class="section">
            <div class="section-title">Model Responses {f'(Outlier: {outlier})' if outlier else ''}</div>
            <div class="responses">
                <div class="response nano {'outlier' if outlier == 'nano' else ''}">
                    <div class="response-header">nano {' ⚠️ OUTLIER' if outlier == 'nano' else ''}</div>
                    <div class="response-content" id="nano-raw-{case_idx}">{html.escape(nano['output_content'])}</div>
                    <div class="parsed-response">
                        <div class="parsed-label">Parsed:</div>
                        <div id="nano-parsed-{case_idx}">{html.escape(json.dumps(nano['parsed_response'], indent=2))}</div>
                    </div>
                    <button class="copy-btn" onclick="copyText('nano-raw-{case_idx}')">Copy Raw</button>
                    <button class="copy-btn" onclick="copyText('nano-parsed-{case_idx}')">Copy Parsed</button>
                </div>

                <div class="response mini {'outlier' if outlier == 'mini' else ''}">
                    <div class="response-header">mini {' ⚠️ OUTLIER' if outlier == 'mini' else ''}</div>
                    <div class="response-content" id="mini-raw-{case_idx}">{html.escape(mini['output_content'])}</div>
                    <div class="parsed-response">
                        <div class="parsed-label">Parsed:</div>
                        <div id="mini-parsed-{case_idx}">{html.escape(json.dumps(mini['parsed_response'], indent=2))}</div>
                    </div>
                    <button class="copy-btn" onclick="copyText('mini-raw-{case_idx}')">Copy Raw</button>
                    <button class="copy-btn" onclick="copyText('mini-parsed-{case_idx}')">Copy Parsed</button>
                </div>

                <div class="response gpt5 {'outlier' if outlier == 'gpt5' else ''}">
                    <div class="response-header">gpt-5 {' ⚠️ OUTLIER' if outlier == 'gpt5' else ''}</div>
                    <div class="response-content" id="gpt5-raw-{case_idx}">{html.escape(gpt5['output_content'])}</div>
                    <div class="parsed-response">
                        <div class="parsed-label">Parsed:</div>
                        <div id="gpt5-parsed-{case_idx}">{html.escape(json.dumps(gpt5['parsed_response'], indent=2))}</div>
                    </div>
                    <button class="copy-btn" onclick="copyText('gpt5-raw-{case_idx}')">Copy Raw</button>
                    <button class="copy-btn" onclick="copyText('gpt5-parsed-{case_idx}')">Copy Parsed</button>
                </div>
            </div>
        </div>
    </div>
"""

html_content += """
    <script>
        function copyText(elementId) {
            const element = document.getElementById(elementId);
            const text = element.textContent;
            navigator.clipboard.writeText(text).then(() => {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = 'Copied!';
                setTimeout(() => {
                    btn.textContent = originalText;
                }, 1500);
            });
        }
    </script>
</body>
</html>
"""

# Write HTML file
output_file = Path("experiments/compare_models/results/physobs_disagreements_3models.html")
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(html_content)

print(f"HTML report generated: {output_file}")
print(f"Total disagreement cases: {len(disagreements)}")
