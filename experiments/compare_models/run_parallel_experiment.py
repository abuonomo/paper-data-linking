#!/usr/bin/env python3
"""
Run model comparison experiments in parallel across multiple models.

Usage:
    # Run from YAML config file
    python experiments/compare_models/run_parallel_experiment.py \
        --config experiment_configs/my_experiment.yaml

    # Run specific models on specific call types (CLI args)
    python experiments/compare_models/run_parallel_experiment.py \
        --models openai/gpt-5-mini bedrock/openai.gpt-oss-120b-1:0 \
        --call-types detector_normalization wavelength_normalization \
        --max-cases 100 \
        --max-workers 4

    # Run all call types with 2 models (CLI args)
    python experiments/compare_models/run_parallel_experiment.py \
        --models openai/gpt-5-nano bedrock/openai.gpt-oss-120b-1:0 \
        --max-workers 8
"""

import argparse
from pathlib import Path
from datetime import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess  # Still needed for test_model_access
import os
from dotenv import find_dotenv, load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.compare_models.core.experiment_config import load_experiment_config
from experiments.compare_models.run_prompt_experiment import run_experiment

# Call type configurations
CALL_TYPES = {
    'mission_identification': {
        'prompt': 'paper_data_linking/linkers/general/prompts/mission_identification/system.xml',
        'input': 'inputs/test_set/mission_identification.jsonl'
    },
    'time_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/time_normalization/system.xml',
        'input': 'inputs/test_set/time_normalization.jsonl'
    },
    'mission_selection': {
        'prompt': 'paper_data_linking/linkers/general/prompts/mission_selection/system.xml',
        'input': 'inputs/test_set/mission_selection.jsonl'
    },
    'instrument_selection': {
        'prompt': 'paper_data_linking/linkers/general/prompts/instrument_selection/system.xml',
        'input': 'inputs/test_set/instrument_selection.jsonl'
    },
    'instrument_validation': {
        'prompt': 'paper_data_linking/linkers/general/prompts/validation/system.xml',
        'input': 'inputs/test_set/instrument_validation.jsonl'
    },
    'wavelength_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml',
        'input': 'inputs/test_set/wavelength_normalization.jsonl'
    },
    'physobs_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml',
        'input': 'inputs/test_set/physobs_normalization.jsonl'
    },
    'cadence_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/cadence_normalization/system.xml',
        'input': 'inputs/test_set/cadence_normalization.jsonl'
    },
    'detector_normalization': {
        'prompt': 'paper_data_linking/linkers/general/prompts/detector_normalization/system.xml',
        'input': 'inputs/test_set/detector_normalization.jsonl'
    },
    'structure_analysis': {
        'prompt': 'paper_data_linking/linkers/general/prompts/structured_parsing/system.xml',
        'input': 'inputs/test_set/structure_analysis.jsonl'
    }
}


def run_single_model_task(model, call_type, experiment_name, max_cases=None, timeout=600,
                          call_type_config=None, output_dir=None):
    """
    Run experiment for a single model on a single call type.

    Args:
        model: Model identifier
        call_type: Call type name
        experiment_name: Experiment name
        max_cases: Maximum number of test cases
        timeout: Timeout in seconds (not currently enforced for direct calls)
        call_type_config: Optional CallTypeConfig object (from YAML)
        output_dir: Optional output directory path
    """
    # Get config from either YAML or legacy CALL_TYPES dict
    if call_type_config:
        prompt_path = str(call_type_config.prompt)
        input_path = str(call_type_config.input)
        handler_class = call_type_config.handler_class
    else:
        config = CALL_TYPES[call_type]
        prompt_path = config['prompt']
        input_path = config['input']
        handler_class = None

    print(f"[{model}] [{call_type}] Starting...")

    try:
        run_experiment(
            call_type=call_type,
            input_file=input_path,
            system_prompt_path=prompt_path,
            models=[model],  # Single model as list
            output_dir=output_dir or 'experiments/compare_models/results',
            experiment_name=experiment_name,
            max_cases=max_cases,
            handler_class=handler_class,
        )

        print(f"[{model}] [{call_type}] ✓ Completed")

        return {
            'model': model,
            'call_type': call_type,
            'status': 'success'
        }

    except Exception as e:
        error_msg = str(e)[:200]
        print(f"[{model}] [{call_type}] ✗ Error: {error_msg}")
        return {
            'model': model,
            'call_type': call_type,
            'status': 'error',
            'error': error_msg
        }


def check_credentials(models):
    """Check if necessary credentials are available for the specified models."""
    issues = []

    has_openai = any(m.startswith('openai/') for m in models)
    has_bedrock = any(m.startswith('bedrock/') for m in models)

    if has_openai:
        if not os.environ.get('OPENAI_API_KEY'):
            issues.append("OpenAI models requested but OPENAI_API_KEY not set")

    if has_bedrock:
        # Bedrock typically uses AWS credentials
        if not os.environ.get('AWS_ACCESS_KEY_ID') and not os.environ.get('AWS_PROFILE'):
            issues.append("Bedrock models requested but AWS credentials not configured (need AWS_ACCESS_KEY_ID or AWS_PROFILE)")

        # Check for region
        if not os.environ.get('AWS_DEFAULT_REGION') and not os.environ.get('AWS_REGION'):
            issues.append("Bedrock models requested but AWS region not set (need AWS_DEFAULT_REGION or AWS_REGION)")

    return issues


def test_model_access(model):
    """Test if a model is accessible by making a simple call."""
    print(f"Testing access to {model}...")

    try:
        # Make a minimal test call
        result = subprocess.run(
            [
                'python', '-c',
                f'''
import sys
sys.path.insert(0, ".")
from experiments.compare_models.core.client import call_model

try:
    resp = call_model(
        model="{model}",
        messages=[{{"role": "user", "content": "test"}}],
        temperature=0.0,
        max_retries=0
    )
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {{e}}")
    sys.exit(1)
'''
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if "SUCCESS" in result.stdout:
            print(f"  ✓ {model} is accessible")
            return True
        else:
            error = result.stdout.strip() or result.stderr.strip()
            print(f"  ✗ {model} not accessible: {error}")
            return False

    except Exception as e:
        print(f"  ✗ {model} test failed: {e}")
        return False


def main():
    # Load environment variables from .env file
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(
        description='Run parallel model comparison experiments',
        epilog='Either provide --config for YAML-based config, or use CLI arguments'
    )

    # YAML config option (new)
    parser.add_argument(
        '--config',
        type=Path,
        help='Path to experiment YAML config file'
    )

    # CLI arguments (backward compatibility)
    parser.add_argument(
        '--models',
        nargs='+',
        help='Models to compare (e.g., openai/gpt-5-mini bedrock/openai.gpt-oss-120b-1:0)'
    )

    parser.add_argument(
        '--call-types',
        nargs='+',
        choices=list(CALL_TYPES.keys()),
        help='Call types to test (default: all when using CLI)'
    )

    parser.add_argument(
        '--max-cases',
        type=int,
        help='Maximum cases per call type (default: 100 for CLI, from config for YAML)'
    )

    parser.add_argument(
        '--max-workers',
        type=int,
        help='Maximum parallel workers (default: 4)'
    )

    parser.add_argument(
        '--experiment-name',
        help='Experiment name (default: comparison_<timestamp> for CLI, from config for YAML)'
    )

    parser.add_argument(
        '--timeout',
        type=int,
        help='Timeout per task in seconds (default: 600)'
    )

    parser.add_argument(
        '--skip-credential-check',
        action='store_true',
        help='Skip credential and model access checks'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        help='Output directory for results (overrides config file setting)'
    )

    args = parser.parse_args()

    # Determine config source and load parameters
    if args.config:
        # Load from YAML
        try:
            exp_config = load_experiment_config(args.config)
        except Exception as e:
            print(f"Error loading config file: {e}")
            sys.exit(1)

        # Use config values
        models = exp_config.models
        call_types = exp_config.call_types
        call_type_configs = exp_config.call_type_configs
        max_cases = exp_config.max_cases
        max_workers = exp_config.max_workers
        experiment_name = exp_config.experiment_name
        timeout = exp_config.timeout_seconds
        # CLI --output-dir overrides config file
        output_dir = args.output_dir or str(exp_config.output_dir)

        print(f"Loaded experiment config from: {args.config}")
        if exp_config.description:
            print(f"Description: {exp_config.description}")
        print()
    else:
        # Use CLI arguments (legacy mode)
        if not args.models:
            parser.error("--models is required when not using --config")

        models = args.models
        call_types = args.call_types or list(CALL_TYPES.keys())
        call_type_configs = None  # Use legacy CALL_TYPES dict
        max_cases = args.max_cases or 100
        max_workers = args.max_workers or 4
        experiment_name = args.experiment_name or f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        timeout = args.timeout or 600
        output_dir = args.output_dir or 'experiments/compare_models/results'

    # Check credentials first
    if not args.skip_credential_check:
        print("Checking credentials...")
        cred_issues = check_credentials(models)
        if cred_issues:
            print("\n⚠️  Credential Issues:")
            for issue in cred_issues:
                print(f"  - {issue}")
            print("\nSet the required environment variables or use --skip-credential-check to proceed anyway.")
            sys.exit(1)
        print("✓ Credentials look good\n")

        # Test model access
        print("Testing model access (this may take a minute)...")
        access_results = {}
        for model in models:
            access_results[model] = test_model_access(model)

        failed_models = [m for m, success in access_results.items() if not success]
        if failed_models:
            print(f"\n⚠️  The following models are not accessible:")
            for model in failed_models:
                print(f"  - {model}")
            print("\nFix the access issues or use --skip-credential-check to proceed anyway.")
            sys.exit(1)

        print("\n✓ All models accessible\n")

    # Print configuration
    print("="*80)
    print("PARALLEL MODEL COMPARISON EXPERIMENT")
    print("="*80)
    print(f"Experiment name: {experiment_name}")
    print(f"Models: {', '.join(models)}")
    print(f"Call types: {', '.join(call_types)}")
    print(f"Max cases per call type: {max_cases}")
    print(f"Max parallel workers: {max_workers}")
    print(f"Timeout per task: {timeout}s")
    print("="*80)
    print()

    # Build task list
    tasks = []
    for call_type in call_types:
        for model in models:
            # Get call type config if using YAML
            ct_config = call_type_configs.get(call_type) if call_type_configs else None
            tasks.append((model, call_type, experiment_name, max_cases, timeout, ct_config, output_dir))

    print(f"Total tasks: {len(tasks)}")
    print()

    # Execute tasks in parallel
    print(f"Running {len(tasks)} tasks with max {max_workers} workers...")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_model_task, *task): task
            for task in tasks
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Summary
    print("\n" + "="*80)
    print("EXPERIMENT COMPLETE")
    print("="*80)

    successes = sum(1 for r in results if r['status'] == 'success')
    failures = sum(1 for r in results if r['status'] == 'error')
    timeouts = sum(1 for r in results if r['status'] == 'timeout')

    print(f"Total: {len(results)} | Success: {successes} | Failed: {failures} | Timeout: {timeouts}")
    print(f"\nResults: {output_dir}/{experiment_name}/")

    if failures > 0 or timeouts > 0:
        print("\nFailed/timeout tasks:")
        for r in results:
            if r['status'] != 'success':
                print(f"  [{r['model']}] [{r['call_type']}] - {r['status']}")


if __name__ == '__main__':
    main()
