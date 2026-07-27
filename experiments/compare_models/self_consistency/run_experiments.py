"""
Self-consistency experiment runner.

Runs N experiments for a given call type to measure LLM consistency at temperature=1.0.
Replaces the bash scripts with a cleaner Python implementation.

IMPORTANT: This module has NO default configurations. All call type configs
(prompt paths, handler classes) must be passed explicitly from the notebook.
This prevents silent bugs from stale defaults.
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Compute repo root from this file's location
# This file is at: experiments/compare_models/self_consistency/run_experiments.py
REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()

# Add repo root to path for imports
sys.path.insert(0, str(REPO_ROOT))

from experiments.compare_models.run_prompt_experiment import run_experiment


# Base directory for self-consistency results (absolute path)
RESULTS_BASE = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'results'

# Input directory (absolute path)
INPUT_BASE = REPO_ROOT / 'inputs' / 'test_set'


def run_self_consistency_experiments(
    call_type: str,
    test_set: str,
    call_type_config: dict,
    num_runs: int = 5,
    model: Optional[str] = None,
    max_cases: Optional[int] = None,
    sample_size: int = 100,
    random_seed: int = 42,
    force_rerun: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Run N self-consistency experiments for a call type.

    Args:
        call_type: The call type to test (e.g., 'physobs_normalization')
        test_set: Test set identifier (e.g., 'test_set_2025_11_26')
        call_type_config: Dict with 'prompt' and 'handler' keys for this call type
        num_runs: Number of runs to perform (default: 5)
        model: Model to use (REQUIRED - no default)
        max_cases: Maximum cases per run (default: None = use all)
        sample_size: Sample size for input file naming (default: 100)
        random_seed: Random seed for input file naming (default: 42)
        force_rerun: If True, re-run even if results exist (default: False)
        verbose: Print progress messages (default: True)

    Returns:
        Dictionary with run results and statistics

    Raises:
        ValueError: If required parameters are missing
    """
    # Validate required parameters
    if model is None:
        raise ValueError("model is required - no default model is set")

    if 'prompt' not in call_type_config:
        raise ValueError(f"call_type_config must have 'prompt' key for {call_type}")

    if 'handler' not in call_type_config:
        raise ValueError(f"call_type_config must have 'handler' key for {call_type}")

    # Make prompt path absolute (config stores relative paths from repo root)
    prompt_path = REPO_ROOT / call_type_config['prompt']
    handler_class = call_type_config['handler']

    # Construct input file path from conventions (absolute path)
    input_path = INPUT_BASE / f"{call_type}_{test_set}_sampled_{sample_size}_seed{random_seed}.jsonl"

    # Verify input file exists
    if not input_path.exists():
        raise FileNotFoundError(
            f"Input file not found: {input_path}\n"
            f"Run the sampling step in the notebook first, or check the path."
        )

    results = {
        'call_type': call_type,
        'test_set': test_set,
        'num_runs': num_runs,
        'model': model,
        'runs': [],
        'completed': 0,
        'skipped': 0,
        'failed': 0,
    }

    # Create model slug for directory naming
    model_slug = model.replace('/', '_').replace(':', '_').replace('.', '_')

    if verbose:
        print(f"{'='*60}")
        print(f"SELF-CONSISTENCY: {call_type}")
        print(f"{'='*60}")
        print(f"Test set: {test_set}")
        print(f"Model: {model}")
        print(f"Model slug: {model_slug}")
        print(f"Runs: {num_runs}")
        print(f"Input: {input_path}")
        print(f"Prompt: {prompt_path}")
        print(f"Handler: {handler_class}")
        print()

    # Run experiments
    # Results structure: results/{test_set}/{model_slug}/{call_type}/run{N}/
    for run in range(1, num_runs + 1):
        output_dir = RESULTS_BASE / test_set / model_slug / call_type / f"run{run}"

        # Check if already complete
        if output_dir.exists() and not force_rerun:
            jsonl_files = list(output_dir.glob('*.jsonl'))
            if jsonl_files:
                if verbose:
                    print(f"Run {run}/{num_runs}: Already complete, skipping")
                results['runs'].append({'run': run, 'status': 'skipped'})
                results['skipped'] += 1
                continue

        # Clear existing output if force_rerun
        if output_dir.exists() and force_rerun:
            if verbose:
                print(f"Run {run}/{num_runs}: Removing existing results")
            shutil.rmtree(output_dir)

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Run {run}/{num_runs}: Starting at {datetime.now().strftime('%H:%M:%S')}")

        try:
            run_experiment(
                call_type=call_type,
                input_file=str(input_path),
                system_prompt_path=str(prompt_path),
                models=[model],
                output_dir=str(output_dir),
                experiment_name=f"run{run}",
                max_cases=max_cases,
                handler_class=handler_class,
            )

            if verbose:
                print(f"Run {run}/{num_runs}: Completed")
            results['runs'].append({'run': run, 'status': 'success'})
            results['completed'] += 1

        except Exception as e:
            error_msg = str(e)[:200]
            if verbose:
                print(f"Run {run}/{num_runs}: FAILED - {error_msg}")
            results['runs'].append({'run': run, 'status': 'error', 'error': error_msg})
            results['failed'] += 1

    if verbose:
        print()
        print(f"{'='*60}")
        print(f"COMPLETE: {results['completed']} succeeded, {results['skipped']} skipped, {results['failed']} failed")
        print(f"Results: {RESULTS_BASE / test_set / model_slug / call_type}/")
        print(f"{'='*60}")

    return results


def run_all_self_consistency_experiments(
    call_types: list[str],
    test_set: str,
    call_type_configs: dict[str, dict],
    num_runs: int = 5,
    model: Optional[str] = None,
    **kwargs
) -> dict:
    """
    Run self-consistency experiments for multiple call types.

    Args:
        call_types: List of call types to test
        test_set: Test set identifier
        call_type_configs: Dict mapping call_type -> {'prompt': ..., 'handler': ...}
        num_runs: Number of runs per call type
        model: Model to use (REQUIRED)
        **kwargs: Additional arguments passed to run_self_consistency_experiments

    Returns:
        Dictionary with results for all call types
    """
    if model is None:
        raise ValueError("model is required - no default model is set")

    # Validate all call types have configs
    missing = set(call_types) - set(call_type_configs.keys())
    if missing:
        raise ValueError(f"Missing configs for call types: {missing}")

    all_results = {
        'test_set': test_set,
        'num_runs': num_runs,
        'model': model,
        'call_types': {},
        'summary': {
            'total_completed': 0,
            'total_skipped': 0,
            'total_failed': 0,
        }
    }

    for call_type in call_types:
        print(f"\n{'#'*60}")
        print(f"# {call_type.upper()}")
        print(f"{'#'*60}\n")

        try:
            results = run_self_consistency_experiments(
                call_type=call_type,
                test_set=test_set,
                call_type_config=call_type_configs[call_type],
                num_runs=num_runs,
                model=model,
                **kwargs
            )
            all_results['call_types'][call_type] = results
            all_results['summary']['total_completed'] += results['completed']
            all_results['summary']['total_skipped'] += results['skipped']
            all_results['summary']['total_failed'] += results['failed']
        except Exception as e:
            print(f"ERROR: {call_type} failed with: {e}")
            all_results['call_types'][call_type] = {'status': 'error', 'error': str(e)}

    print(f"\n{'='*60}")
    print("ALL EXPERIMENTS COMPLETE")
    print(f"{'='*60}")
    print(f"Completed: {all_results['summary']['total_completed']}")
    print(f"Skipped: {all_results['summary']['total_skipped']}")
    print(f"Failed: {all_results['summary']['total_failed']}")

    return all_results


if __name__ == '__main__':
    # CLI usage requires explicit config - print help and exit
    print("""
Self-Consistency Experiment Runner

This module is designed to be called from the Jupyter notebook, which defines
the call type configurations (prompt paths, handler classes).

Usage from notebook:
    from experiments.compare_models.self_consistency.run_experiments import (
        run_self_consistency_experiments,
        run_all_self_consistency_experiments,
    )

    # Define your config
    CALL_TYPE_CONFIG = {
        'physobs_normalization': {
            'prompt': 'paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml',
            'handler': 'PhysObsNormalizationFreeTextV2Handler',
        },
        ...
    }

    # Run experiments
    run_all_self_consistency_experiments(
        call_types=['physobs_normalization'],
        test_set='test_set_2025_11_26',
        call_type_configs=CALL_TYPE_CONFIG,
        model='bedrock/openai.gpt-oss-120b-1:0',
        num_runs=5,
    )
""")
