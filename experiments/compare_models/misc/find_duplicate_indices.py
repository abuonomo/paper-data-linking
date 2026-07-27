"""
Find mission_identification cases with duplicate indices in the response.
"""
import json
from pathlib import Path
from collections import Counter

def main():
    test_file = Path("inputs/test_set/mission_identification.jsonl")

    duplicate_cases = []

    with open(test_file) as f:
        for line_num, line in enumerate(f, 1):
            data = json.loads(line)
            parsed = data.get('parsed_response', {})
            indices = parsed.get('mission_indices', [])

            if indices:
                # Check for duplicates
                if len(indices) != len(set(indices)):
                    context = data.get('render_context', {}).get('mission_context', '')
                    first_line = context.split('\n')[0] if context else ''

                    duplicate_cases.append({
                        'line_num': line_num,
                        'id': data.get('id'),
                        'indices': indices,
                        'duplicates': [idx for idx, count in Counter(indices).items() if count > 1],
                        'context_preview': first_line[:100]
                    })

    print(f"Found {len(duplicate_cases)} cases with duplicate indices\n")
    print("="*80)

    for case in duplicate_cases:
        print(f"\nLine {case['line_num']}:")
        print(f"  ID: {case['id']}")
        print(f"  Indices: {case['indices']}")
        print(f"  Duplicates: {case['duplicates']}")
        print(f"  Context: {case['context_preview']}")

        # Check if GOES mentioned
        if 'goes' in case['context_preview'].lower():
            print(f"  ⚠️  GOES mentioned!")

if __name__ == "__main__":
    main()
