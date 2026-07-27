#!/usr/bin/env python3
"""
Simple multi-model comparison tool
Reads LLM calls from JSONL file and runs them across different models
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime
from openai_client.openai_client import OpenAIClient
from openai_client.response_formats import NormalizedTimeRange

# Models to test
MODELS = ['gpt-5-nano', 'gpt-5-mini']

async def run_comparison(input_file: str, output_dir: str = "data"):
    """Run the same prompts across different models"""

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Initialize clients for each model
    clients = {}
    for model in MODELS:
        config = {'max_tokens': 1000, 'temperature': 1.0}
        clients[model] = OpenAIClient(model, config)

    # Read input file and process each line
    with open(input_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                messages = data.get('input_messages', [])

                if len(messages) >= 2:
                    system_msg = messages[0].get('content', '')
                    user_msg = messages[1].get('content', '')

                    print(f"Processing line {line_num}...")

                    # Run same prompt across all models
                    for model_name, client in clients.items():
                        try:
                            response = await client.generate_response(
                                system_message=system_msg,
                                user_message=user_msg,
                                response_fromat=NormalizedTimeRange
                            )

                            # Save result in same format as baseline
                            result = {
                                'model_name': model_name,
                                'created_at': datetime.now().isoformat(),
                                'call_type': 'time_normalization',
                                'provider': 'openai',
                                'prompt_tokens': response.get('tokens_used', {}).get('prompt_tokens', 0),
                                'completion_tokens': response.get('tokens_used', {}).get('completion_tokens', 0),
                                'total_tokens': response.get('tokens_used', {}).get('total_tokens', 0),
                                'estimated_cost_usd': response.get('cost_estimate', 0),
                                'duration_ms': response.get('response_time_ms', 0),
                                'input_messages': [
                                    {"role": "system", "content": system_msg},
                                    {"role": "user", "content": user_msg}
                                ],
                                'output_content': response['content']
                            }

                            # Write to model-specific file
                            output_file = output_path / f"{model_name}_{timestamp}.jsonl"
                            with open(output_file, 'a') as out_f:
                                out_f.write(json.dumps(result) + '\n')

                        except Exception as e:
                            print(f"Error with {model_name} on line {line_num}: {e}")

            except json.JSONDecodeError:
                print(f"Skipping invalid JSON on line {line_num}")
                continue

    print(f"Results saved to {output_dir}/")

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python main.py <input_jsonl_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    asyncio.run(run_comparison(input_file))