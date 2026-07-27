#!/usr/bin/env python3
"""
Run prompt experimentation on disagreement cases.

Test different system prompts across multiple models to find optimal alignment.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime
import sys
from dotenv import load_dotenv, find_dotenv

# Load environment variables from .env
load_dotenv(find_dotenv())

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.core.client import call_model


def load_system_prompt(xml_path):
    """Load system prompt from XML file."""
    with open(xml_path) as f:
        return f.read().strip()


def load_input_cases(jsonl_path):
    """Load input cases from JSONL file."""
    cases = []
    with open(jsonl_path) as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def run_experiment(input_file, system_prompt_path, models, output_dir, experiment_name, timeout_sec=60, max_retries=1):
    """Run prompt experiment across multiple models."""

    # Load system prompt
    print(f"Loading system prompt from: {system_prompt_path}")
    system_prompt = load_system_prompt(system_prompt_path)
    print(f"System prompt length: {len(system_prompt)} characters\n")

    # Load input cases
    print(f"Loading input cases from: {input_file}")
    cases = load_input_cases(input_file)
    print(f"Loaded {len(cases)} cases\n")

    # Create output directory
    experiment_dir = Path(output_dir) / experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {experiment_dir}\n")

    # Save system prompt used for this experiment
    prompt_file = experiment_dir / "system_prompt.xml"
    with open(prompt_file, 'w') as f:
        f.write(system_prompt)
    print(f"Saved system prompt to: {prompt_file}\n")

    # Run each model
    for model in models:
        print(f"{'='*80}")
        print(f"Running model: {model}")
        print(f"{'='*80}\n")

        results = []

        for idx, case in enumerate(cases, 1):
            # Extract user message from input
            user_msg = None
            for msg in case.get('input_messages', []):
                if msg.get('role') == 'user':
                    user_msg = msg.get('content')
                    break

            if not user_msg:
                print(f"  Case {idx}: No user message found, skipping")
                continue

            print(f"  Case {idx}/{len(cases)}: Processing...")

            # Build messages with new system prompt
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_msg}
            ]

            try:
                # Call model (temperature=1.0 for gpt-5 models)
                resp = call_model(
                    model,
                    messages,
                    temperature=1.0,
                    timeout=timeout_sec,
                    max_retries=max_retries
                )

                # Store result
                result = {
                    'case_index': idx,
                    'original_id': case.get('id'),
                    'model_name': model,
                    'created_at': datetime.now().isoformat(),
                    'provider': resp['provider'],
                    'prompt_tokens': resp['tokens_used']['prompt_tokens'],
                    'completion_tokens': resp['tokens_used']['completion_tokens'],
                    'total_tokens': resp['tokens_used']['total_tokens'],
                    'estimated_cost_usd': resp['cost_estimate'],
                    'duration_ms': resp.get('response_time_ms'),
                    'input_messages': messages,
                    'output_content': resp['content'],
                    'system_prompt_path': str(system_prompt_path)
                }

                results.append(result)
                print(f"    ✓ Completed ({resp['tokens_used']['total_tokens']} tokens, ${resp['cost_estimate']:.6f})")

            except Exception as e:
                print(f"    ✗ Error: {e}")
                results.append({
                    'case_index': idx,
                    'original_id': case.get('id'),
                    'model_name': model,
                    'error': str(e),
                    'system_prompt_path': str(system_prompt_path)
                })

        # Save results for this model
        model_name_safe = model.replace('/', '_')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = experiment_dir / f"{model_name_safe}_{timestamp}.jsonl"

        with open(output_file, 'w') as f:
            for result in results:
                f.write(json.dumps(result) + '\n')

        print(f"\n  Saved {len(results)} results to: {output_file}")

        # Print summary statistics
        successes = sum(1 for r in results if 'error' not in r)
        total_cost = sum(r.get('estimated_cost_usd', 0) for r in results)
        total_tokens = sum(r.get('total_tokens', 0) for r in results)

        print(f"  Success rate: {successes}/{len(results)}")
        print(f"  Total cost: ${total_cost:.6f}")
        print(f"  Total tokens: {total_tokens:,}\n")

    print(f"{'='*80}")
    print(f"Experiment '{experiment_name}' complete!")
    print(f"Results saved to: {experiment_dir}")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(
        description='Run prompt experimentation on validation disagreement cases',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with current system prompt
  python run_prompt_experiment.py \\
    --input inputs/instrument_validation_disagreements_9.jsonl \\
    --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \\
    --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \\
    --experiment-name baseline

  # Run with strict variant
  python run_prompt_experiment.py \\
    --input inputs/instrument_validation_disagreements_9.jsonl \\
    --system-prompt paper_data_linking/linkers/general/prompts/validation/system_strict.xml \\
    --models openai/gpt-5-nano openai/gpt-5-mini \\
    --experiment-name strict
        """
    )

    parser.add_argument('--input', required=True,
                       help='Input JSONL file with disagreement cases')
    parser.add_argument('--system-prompt', required=True,
                       help='Path to system prompt XML file')
    parser.add_argument('--models', nargs='+', required=True,
                       help='Models to test (e.g., openai/gpt-5-nano openai/gpt-5-mini)')
    parser.add_argument('--experiment-name', required=True,
                       help='Name for this experiment (used for output directory)')
    parser.add_argument('--output-dir', default='experiments/compare_models/prompt_experiments',
                       help='Base output directory (default: experiments/compare_models/prompt_experiments)')
    parser.add_argument('--timeout-sec', type=int, default=60,
                       help='Timeout in seconds for each API call (default: 60)')
    parser.add_argument('--max-retries', type=int, default=1,
                       help='Maximum retries for failed calls (default: 1)')

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.input).exists():
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    if not Path(args.system_prompt).exists():
        print(f"Error: System prompt file not found: {args.system_prompt}")
        sys.exit(1)

    # Run experiment
    run_experiment(
        input_file=args.input,
        system_prompt_path=args.system_prompt,
        models=args.models,
        output_dir=args.output_dir,
        experiment_name=args.experiment_name,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries
    )


if __name__ == '__main__':
    main()
