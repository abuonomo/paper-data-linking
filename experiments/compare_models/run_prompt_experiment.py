#!/usr/bin/env python3
"""
Run prompt experimentation across different LLM call types.

Test different system prompts across multiple models to find optimal alignment.
Uses pluggable handler system for different call types (validation, normalization, etc.).
"""
import argparse
import json
from pathlib import Path
from datetime import datetime
import sys
from dotenv import load_dotenv, find_dotenv
from tqdm import tqdm

# Load environment variables from .env
load_dotenv(find_dotenv())

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.core.client import call_model
from experiments.compare_models.core.registry import CallTypeRegistry
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

# Import handlers to trigger registration
import experiments.compare_models.handlers


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


def run_experiment(
    call_type: str,
    input_file: str,
    system_prompt_path: str,
    models: list[str],
    output_dir: str,
    experiment_name: str,
    timeout_sec: int | None = None,
    max_retries: int = 1,
    temperature: float = 1.0,
    max_cases: int | None = None,
    handler_class: str | None = None
):
    """Run prompt experiment across multiple models using specified handler."""

    # Get handler - either by class name (if specified) or by call_type
    try:
        if handler_class:
            handler = CallTypeRegistry.get_by_class_name(handler_class)
            print(f"Using handler class: {handler_class}")
        else:
            handler = CallTypeRegistry.get(call_type)
        print(f"Handler: {handler.__class__.__name__}")
        print(f"Call type: {call_type}\n")
    except KeyError as e:
        print(f"Error: {e}")
        if handler_class:
            print(f"Handler class '{handler_class}' not found")
        else:
            print(f"Available call types: {', '.join(CallTypeRegistry.list_call_types())}")
        sys.exit(1)

    # Load system prompt
    print(f"Loading system prompt from: {system_prompt_path}")
    system_prompt = load_system_prompt(system_prompt_path)
    print(f"System prompt length: {len(system_prompt)} characters\n")

    # Load input cases
    print(f"Loading input cases from: {input_file}")
    cases = load_input_cases(input_file)

    # Apply max_cases limit if specified
    if max_cases and len(cases) > max_cases:
        print(f"Limiting to first {max_cases} cases (total available: {len(cases)})")
        cases = cases[:max_cases]

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

    # Get response format from handler if available
    response_format = handler.get_response_format()
    if response_format:
        print(f"Using structured output with schema: {response_format.__name__}\n")

    # Run each model
    for model in models:
        print(f"{'='*80}")
        print(f"Running model: {model}")
        print(f"{'='*80}\n")

        results = []

        for idx, case in enumerate(tqdm(cases, desc=f"  {model}", unit="case"), 1):
            # Handle two input formats:
            # 1. Old format: pre-rendered input_messages (from export_llm_calls)
            # 2. New format: raw_inputs + metadata (from export_normalization_test_data)

            user_msg = None

            # Try old format first (backwards compatibility)
            if 'input_messages' in case:
                for msg in case.get('input_messages', []):
                    if msg.get('role') == 'user':
                        user_msg = msg.get('content')
                        break

            # Try new format - render user message from raw inputs
            elif 'raw_inputs' in case:
                user_msg = handler.render_user_message(case)

            if not user_msg:
                tqdm.write(f"  Case {idx}: No user message found, skipping")
                continue

            # Build messages with new system prompt
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_msg}
            ]

            try:
                # Call model with optional response format
                call_kwargs = {
                    'model': model,
                    'messages': messages,
                    'temperature': temperature,
                    'timeout': timeout_sec,
                    'max_retries': max_retries
                }
                if response_format:
                    call_kwargs['response_format'] = response_format

                resp = call_model(**call_kwargs)

                # Parse response using handler
                try:
                    parsed = handler.parse_response(resp['content'])
                    parsed_str = handler.get_short_summary(parsed)
                except Exception as parse_error:
                    parsed = None
                    parsed_str = f"PARSE_ERROR: {parse_error}"

                # Store result
                result = {
                    'case_index': idx,
                    'original_id': case.get('id'),
                    'model_name': model,
                    'call_type': call_type,
                    'created_at': datetime.now().isoformat(),
                    'provider': resp['provider'],
                    'prompt_tokens': resp['tokens_used']['prompt_tokens'],
                    'completion_tokens': resp['tokens_used']['completion_tokens'],
                    'total_tokens': resp['tokens_used']['total_tokens'],
                    'estimated_cost_usd': resp['cost_estimate'],
                    'duration_ms': resp.get('response_time_ms'),
                    'input_messages': messages,
                    'output_content': resp['content'],
                    'parsed_response': parsed,
                    'system_prompt_path': str(system_prompt_path)
                }

                results.append(result)
                tqdm.write(f"    ✓ Case {idx}: {parsed_str} ({resp['tokens_used']['total_tokens']} tokens, ${resp['cost_estimate']:.6f})")

            except Exception as e:
                tqdm.write(f"    ✗ Case {idx} Error: {e}")
                results.append({
                    'case_index': idx,
                    'original_id': case.get('id'),
                    'model_name': model,
                    'call_type': call_type,
                    'error': str(e),
                    'system_prompt_path': str(system_prompt_path)
                })

        # Save results for this model
        model_name_safe = model.replace('/', '_').replace(':', '_')
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
        description='Run prompt experimentation on LLM calls with pluggable handlers',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run instrument validation experiment
  python run_prompt_experiment.py \\
    --call-type instrument_validation \\
    --input inputs/instrument_validation_sample_20.jsonl \\
    --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \\
    --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \\
    --experiment-name baseline

  # Run wavelength normalization experiment
  python run_prompt_experiment.py \\
    --call-type wavelength_normalization \\
    --input inputs/wavelength_test_cases.jsonl \\
    --system-prompt paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml \\
    --models openai/gpt-5-mini \\
    --experiment-name wavelength_test
        """
    )

    parser.add_argument('--call-type', required=True,
                       help='Type of LLM call (determines handler to use)')
    parser.add_argument('--input', required=True,
                       help='Input JSONL file with test cases')
    parser.add_argument('--system-prompt', required=True,
                       help='Path to system prompt XML file')
    parser.add_argument('--models', nargs='+', required=True,
                       help='Models to test (e.g., openai/gpt-5-nano openai/gpt-5-mini)')
    parser.add_argument('--experiment-name', required=True,
                       help='Name for this experiment (used for output directory)')
    parser.add_argument('--output-dir', default='experiments/compare_models/prompt_experiments',
                       help='Base output directory (default: experiments/compare_models/prompt_experiments)')
    parser.add_argument('--timeout-sec', type=int, default=None,
                       help='Timeout in seconds for each API call (default: None = no timeout)')
    parser.add_argument('--max-retries', type=int, default=1,
                       help='Maximum retries for failed calls (default: 1)')
    parser.add_argument('--temperature', type=float, default=1.0,
                       help='Temperature for LLM sampling (default: 1.0)')
    parser.add_argument('--max-cases', type=int, default=None,
                       help='Maximum number of cases to run (default: None = all cases)')
    parser.add_argument('--handler-class', default=None,
                       help='Override handler class name (e.g., PhysObsNormalizationFreeTextV2Handler)')

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
        call_type=args.call_type,
        input_file=args.input,
        system_prompt_path=args.system_prompt,
        models=args.models,
        output_dir=args.output_dir,
        experiment_name=args.experiment_name,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        temperature=args.temperature,
        max_cases=args.max_cases,
        handler_class=args.handler_class
    )


if __name__ == '__main__':
    main()
