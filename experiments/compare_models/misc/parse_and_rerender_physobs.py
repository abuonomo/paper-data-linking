"""Parse old physobs prompts and re-render with new template."""
import json
import re
from pathlib import Path
from jinja2 import Template

# Load the new user template
user_template_path = Path("../../paper_data_linking/linkers/general/prompts/physobs_normalization/user.xml")
user_template_text = user_template_path.read_text()

# Parse template to get expected variables
template = Template(user_template_text)

def parse_old_user_prompt(user_content: str) -> dict:
    """Extract instrument_code, candidates, and raw_observable from old format."""

    # Extract instrument code
    instrument_match = re.search(r'for instrument (\w+):', user_content)
    if not instrument_match:
        raise ValueError(f"Could not find instrument in: {user_content[:100]}")
    instrument_code = instrument_match.group(1)

    # Extract candidates list (looking for Python list format)
    candidates_match = re.search(r"\[([^\]]+)\]", user_content)
    if not candidates_match:
        raise ValueError(f"Could not find candidates list in: {user_content[:100]}")

    # Parse the list items - they're quoted strings
    candidates_str = candidates_match.group(1)
    # Split by comma and clean up quotes/whitespace
    candidates_list = [item.strip().strip("'\"") for item in candidates_str.split(",")]

    # Format candidates as a bulleted list for new template
    candidates_formatted = "\n".join(f"- {c}" for c in candidates_list)

    # Extract raw observable (the quoted description)
    raw_match = re.search(r'Given the paper[‐-]quoted description:\s*["\']([^"\']+)["\']', user_content, re.DOTALL)
    if not raw_match:
        raise ValueError(f"Could not find raw observable in: {user_content[:200]}")
    raw_observable = raw_match.group(1)

    return {
        "instrument_code": instrument_code,
        "candidates": candidates_formatted,
        "raw_observable": raw_observable
    }

# Load old results
old_results_file = Path("experiments/compare_models/prompt_experiments/physobs_10_all_models/openai_gpt-5-nano_20251009_143530.jsonl")
old_results = [json.loads(line) for line in open(old_results_file)]

# Parse all cases and create new input file
new_cases = []
for result in old_results:
    case_index = result['case_index']
    old_user_prompt = result['input_messages'][1]['content']

    # Parse old format
    extracted = parse_old_user_prompt(old_user_prompt)

    # Render new user prompt
    new_user_prompt = template.render(**extracted)

    # Create new case with updated user prompt in expected format
    # The runner expects 'input_messages' with role/content structure
    new_case = {
        "case_index": case_index,
        "original_id": result['original_id'],
        "input_messages": [
            {"role": "user", "content": new_user_prompt}
        ]
    }

    new_cases.append(new_case)

# Write new input file
output_file = Path("../../inputs/physobs_normalization_rerendered_10.jsonl")
with open(output_file, 'w') as f:
    for case in new_cases:
        f.write(json.dumps(case) + '\n')

print(f"✓ Parsed {len(new_cases)} cases")
print(f"✓ Written to: {output_file}")
print(f"\nNew user prompt (first case):")
print(new_cases[0]['input_messages'][0]['content'])
