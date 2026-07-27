"""
Batch API runner for self-consistency experiments.

Provides async batch operations via litellm for running large-scale
self-consistency experiments with 50% cost savings and no laptop required.

Workflow:
1. prepare_batch_file() - Generate OpenAI batch JSONL from test cases
2. submit_batch() - Upload file and create batch job
3. check_batch_status() - Poll for completion
4. retrieve_batch_results() - Download and convert to standard output format
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Compute repo root from this file's location
# This file is at: experiments/compare_models/self_consistency/batch_runner.py
REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()

# Add repo root to path for imports
sys.path.insert(0, str(REPO_ROOT))

import logging

import litellm
from experiments.compare_models.core.registry import CallTypeRegistry

# Suppress verbose litellm INFO logs (cost calculation spam)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
litellm.suppress_debug_info = True

# Import all handlers to register them
import experiments.compare_models.handlers  # noqa: F401

# Base directories (absolute paths)
BATCH_DIR = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'batches'
RESULTS_BASE = REPO_ROOT / 'experiments' / 'compare_models' / 'self_consistency' / 'results'
INPUT_BASE = REPO_ROOT / 'inputs' / 'test_set'


def model_slug(model: str) -> str:
    """Convert model name to filesystem-safe slug."""
    return model.replace('/', '_').replace(':', '_').replace('.', '_')


def prepare_batch_file(
    call_type: str,
    test_set: str,
    call_type_config: dict,
    model: str,
    num_runs: int = 5,
    sample_size: int = 100,
    random_seed: int = 42,
    max_cases: Optional[int] = None,
    verbose: bool = True,
    reasoning_effort: Optional[str] = None,
    input_path_override: Optional[Path] = None,
    batch_suffix: Optional[str] = None,
) -> Path:
    """
    Generate OpenAI batch JSONL from test cases.

    Creates one request per (case, run) combination. For 100 cases with 5 runs,
    this creates 500 requests in a single batch file.

    Args:
        call_type: The call type to test (e.g., 'physobs_normalization')
        test_set: Test set identifier (e.g., 'test_set_2025_11_26')
        call_type_config: Dict with 'prompt' and 'handler' keys
        model: Model identifier (e.g., 'openai/gpt-5')
        num_runs: Number of runs per case (default: 5)
        sample_size: Sample size for input file naming (default: 100)
        random_seed: Random seed for input file naming (default: 42)
        max_cases: Maximum cases to include (default: None = use all)
        verbose: Print progress messages (default: True)
        reasoning_effort: Optional reasoning effort level (e.g., 'high')

    Returns:
        Path to the generated batch file
    """
    # Load system prompt
    prompt_path = REPO_ROOT / call_type_config['prompt']
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    system_prompt = prompt_path.read_text()

    # Load input file
    if input_path_override is not None:
        input_path = Path(input_path_override)
    else:
        input_path = INPUT_BASE / f"{call_type}_{test_set}_sampled_{sample_size}_seed{random_seed}.jsonl"
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Get handler for rendering user messages and response format
    handler_class = call_type_config['handler']
    handler = CallTypeRegistry.get_by_class_name(handler_class)

    # Get response_format if handler provides structured output schema
    response_format = None
    if hasattr(handler, 'get_response_format'):
        pydantic_model = handler.get_response_format()
        if pydantic_model is not None:
            # Convert Pydantic model to OpenAI json_schema format
            # Note: We don't use strict mode - it requires additionalProperties: false
            # at all schema levels, which Pydantic doesn't provide by default.
            # Without strict mode, the model still follows the schema reliably.
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": pydantic_model.__name__,
                    "schema": pydantic_model.model_json_schema(),
                }
            }
            if verbose:
                print(f"  Using response_format: {pydantic_model.__name__}")

    # Extract model name for batch body (strip provider prefix)
    # OpenAI batch API expects bare model name
    if '/' in model:
        batch_model = model.split('/', 1)[1]
    else:
        batch_model = model

    batch_requests = []
    case_count = 0

    with open(input_path) as f:
        for line in f:
            if max_cases and case_count >= max_cases:
                break

            case = json.loads(line)
            case_id = case.get('id', f'case_{case_count}')

            # Build messages - same logic as run_prompt_experiment.py
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
                if verbose:
                    print(f"  Case {case_id}: No user message found, skipping")
                continue

            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_msg}
            ]

            # Create request for each run
            for run in range(1, num_runs + 1):
                custom_id = f"{call_type}|{case_id}|run{run}"
                body = {
                    'model': batch_model,
                    'messages': messages,
                    'temperature': 1.0,
                }
                if reasoning_effort is not None:
                    body['reasoning_effort'] = reasoning_effort
                # Add response_format for structured output
                if response_format:
                    body['response_format'] = response_format

                batch_requests.append({
                    'custom_id': custom_id,
                    'method': 'POST',
                    'url': '/v1/chat/completions',
                    'body': body,
                })

            case_count += 1

    # Create output directory and file
    slug = model_slug(model)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    suffix = f"_{batch_suffix}" if batch_suffix else ""
    output_path = BATCH_DIR / test_set / f"{call_type}_{slug}{suffix}_{timestamp}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for req in batch_requests:
            f.write(json.dumps(req) + '\n')

    if verbose:
        print(f"Prepared batch file: {output_path}")
        print(f"  Cases: {case_count}")
        print(f"  Runs per case: {num_runs}")
        print(f"  Total requests: {len(batch_requests)}")

    return output_path


async def submit_batch(
    batch_file: Path,
    model: str,
    verbose: bool = True,
) -> dict:
    """
    Upload batch file and create batch job.

    Args:
        batch_file: Path to the batch JSONL file
        model: Model identifier (used to determine provider)
        verbose: Print progress messages

    Returns:
        Metadata dict with batch_id, input_file_id, etc.
    """
    # Determine provider from model string
    if model.startswith('openai/'):
        provider = 'openai'
    elif model.startswith('bedrock/'):
        provider = 'bedrock'
    else:
        provider = 'openai'  # Default to OpenAI

    if verbose:
        print(f"Submitting batch to {provider}...")

    # Upload file
    with open(batch_file, 'rb') as f:
        file_obj = await litellm.acreate_file(
            file=f,
            purpose='batch',
            custom_llm_provider=provider,
        )

    if verbose:
        print(f"  Uploaded file: {file_obj.id}")

    # Create batch
    batch = await litellm.acreate_batch(
        completion_window='24h',
        endpoint='/v1/chat/completions',
        input_file_id=file_obj.id,
        custom_llm_provider=provider,
    )

    if verbose:
        print(f"  Created batch: {batch.id}")

    # Save metadata
    metadata = {
        'batch_id': batch.id,
        'input_file_id': file_obj.id,
        'batch_file': str(batch_file),
        'model': model,
        'provider': provider,
        'created_at': datetime.now().isoformat(),
        'status': 'submitted',
    }

    metadata_path = batch_file.with_suffix('.meta.json')
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    if verbose:
        print(f"  Metadata saved: {metadata_path}")

    return metadata


async def check_batch_status(
    batch_id: str,
    provider: str,
) -> dict:
    """
    Check batch status and return progress info.

    Args:
        batch_id: The batch ID from submit_batch
        provider: The provider ('openai' or 'bedrock')

    Returns:
        Dict with status, completed, failed, total counts
    """
    batch = await litellm.aretrieve_batch(
        batch_id=batch_id,
        custom_llm_provider=provider,
    )

    # Extract request counts (structure varies by provider)
    request_counts = getattr(batch, 'request_counts', None) or {}
    if isinstance(request_counts, dict):
        completed = request_counts.get('completed', 0)
        failed = request_counts.get('failed', 0)
        total = request_counts.get('total', 0)
    else:
        # Handle object-style response
        completed = getattr(request_counts, 'completed', 0)
        failed = getattr(request_counts, 'failed', 0)
        total = getattr(request_counts, 'total', 0)

    return {
        'status': batch.status,
        'completed': completed,
        'failed': failed,
        'total': total,
        'output_file_id': getattr(batch, 'output_file_id', None),
        'error_file_id': getattr(batch, 'error_file_id', None),
    }


async def retrieve_batch_results(
    batch_id: str,
    provider: str,
    model: str,
    test_set: str,
    verbose: bool = True,
) -> dict:
    """
    Download batch results and convert to standard output format.

    Parses custom_id to route results to correct run directories,
    matching the structure used by synchronous experiments.

    Args:
        batch_id: The batch ID
        provider: The provider ('openai' or 'bedrock')
        model: Model identifier (for directory naming)
        test_set: Test set identifier
        verbose: Print progress messages

    Returns:
        Dict with paths to written result files
    """
    # Get batch status
    batch = await litellm.aretrieve_batch(
        batch_id=batch_id,
        custom_llm_provider=provider,
    )

    if batch.status != 'completed':
        raise ValueError(f"Batch not complete. Status: {batch.status}")

    output_file_id = getattr(batch, 'output_file_id', None)
    if not output_file_id:
        raise ValueError("Batch completed but no output_file_id found")

    if verbose:
        print(f"Retrieving results from {output_file_id}...")

    # Download results
    content = await litellm.afile_content(
        file_id=output_file_id,
        custom_llm_provider=provider,
    )

    # Parse and group results by (call_type, run)
    results_by_run = {}  # {(call_type, run): [results]}

    for line in content.text.strip().split('\n'):
        if not line:
            continue

        result = json.loads(line)
        custom_id = result.get('custom_id', '')

        try:
            call_type, case_id, run_str = custom_id.split('|')
            run = int(run_str.replace('run', ''))
        except ValueError:
            if verbose:
                print(f"  Warning: Could not parse custom_id: {custom_id}")
            continue

        # Extract response data
        response = result.get('response', {})
        body = response.get('body', {})
        choices = body.get('choices', [])
        usage = body.get('usage', {})

        if not choices:
            if verbose:
                print(f"  Warning: No choices in response for {custom_id}")
            continue

        output_content = choices[0].get('message', {}).get('content', '')

        output = {
            'original_id': case_id,
            'call_type': call_type,
            'model_name': model,
            'created_at': datetime.now().isoformat(),
            'provider': provider,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
            'output_content': output_content,
            'batch_id': batch_id,
            'custom_id': custom_id,
        }

        key = (call_type, run)
        if key not in results_by_run:
            results_by_run[key] = []
        results_by_run[key].append(output)

    # Write results to standard directory structure
    slug = model_slug(model)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    written_files = {}

    for (call_type, run), results in results_by_run.items():
        output_dir = RESULTS_BASE / test_set / slug / call_type / f"run{run}"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"{slug}_batch_{timestamp}.jsonl"
        with open(output_file, 'w') as f:
            for result in results:
                f.write(json.dumps(result) + '\n')

        written_files[(call_type, run)] = output_file

        if verbose:
            print(f"  {call_type}/run{run}: {len(results)} results -> {output_file}")

    return {
        'files': written_files,
        'total_results': sum(len(r) for r in results_by_run.values()),
    }


def list_pending_batches(test_set: Optional[str] = None) -> list[dict]:
    """
    List all batch metadata files to find pending batches.

    Args:
        test_set: Optional filter by test set

    Returns:
        List of metadata dicts for batches
    """
    batches = []
    search_dir = BATCH_DIR / test_set if test_set else BATCH_DIR

    if not search_dir.exists():
        return batches

    for meta_file in search_dir.glob('**/*.meta.json'):
        with open(meta_file) as f:
            meta = json.load(f)
            meta['metadata_file'] = str(meta_file)
            batches.append(meta)

    return batches


async def cancel_batch(batch_id: str, provider: str) -> dict:
    """
    Cancel a pending batch.

    Args:
        batch_id: The batch ID to cancel
        provider: The provider ('openai' or 'bedrock')

    Returns:
        Cancellation response
    """
    return await litellm.acancel_batch(
        batch_id=batch_id,
        custom_llm_provider=provider,
    )


# List prices ($/1M tokens), pre-batch-discount, by model family.
_MODEL_PRICING = {
    'gpt-oss': (0.15, 0.60),   # Bedrock openai.gpt-oss-120b
    'gpt-5': (2.50, 10.00),    # OpenAI gpt-5.x family
}
# Rough average OUTPUT tokens per request by reasoning effort (gpt-oss, from
# observed self-consistency / recreation runs). Used only for cost estimation.
_EFFORT_AVG_OUTPUT = {'low': 250, 'medium': 450, 'high': 1200}


def _pricing_for(model: str) -> tuple:
    """($/1M input, $/1M output) list prices for the model family."""
    if 'gpt-oss' in model:
        return _MODEL_PRICING['gpt-oss']
    if 'gpt-5' in model or model.startswith('openai/'):
        return _MODEL_PRICING['gpt-5']
    return _MODEL_PRICING['gpt-5']  # conservative default


def estimate_batch_cost(
    batch_file: Path,
    model: str,
    avg_output_tokens: int = 100,
    reasoning_effort: str = None,
) -> dict:
    """
    Estimate batch cost before submitting.

    Args:
        batch_file: Path to batch JSONL
        model: Model identifier (selects pricing: gpt-oss vs gpt-5)
        avg_output_tokens: Fallback average output tokens per request
        reasoning_effort: If given, overrides avg_output_tokens with an
            effort-appropriate estimate (low/medium/high).

    Returns:
        Dict with cost estimates
    """
    if reasoning_effort in _EFFORT_AVG_OUTPUT:
        avg_output_tokens = _EFFORT_AVG_OUTPUT[reasoning_effort]

    # Count requests and estimate tokens
    total_requests = 0
    total_input_tokens = 0

    with open(batch_file) as f:
        for line in f:
            req = json.loads(line)
            total_requests += 1

            # Rough token estimate (4 chars per token)
            messages = req.get('body', {}).get('messages', [])
            chars = sum(len(m.get('content', '')) for m in messages)
            total_input_tokens += chars // 4

    total_output_tokens = total_requests * avg_output_tokens

    # Model-aware list prices, with the 50% batch discount applied.
    list_in, list_out = _pricing_for(model)
    input_cost_per_1m = list_in * 0.5
    output_cost_per_1m = list_out * 0.5

    estimated_cost = (
        (total_input_tokens / 1_000_000) * input_cost_per_1m +
        (total_output_tokens / 1_000_000) * output_cost_per_1m
    )

    return {
        'total_requests': total_requests,
        'estimated_input_tokens': total_input_tokens,
        'estimated_output_tokens': total_output_tokens,
        'estimated_cost_usd': round(estimated_cost, 2),
        'note': (f'{model.split("/")[-1]} list ${list_in}/${list_out} per 1M, '
                 f'50% batch discount, ~{avg_output_tokens} out tok/req'
                 + (f', effort={reasoning_effort}' if reasoning_effort else '')),
    }


if __name__ == '__main__':
    print("""
Batch Runner for Self-Consistency Experiments

This module is designed to be called from the Jupyter notebook.

Usage from notebook:
    from experiments.compare_models.self_consistency.batch_runner import (
        prepare_batch_file,
        submit_batch,
        check_batch_status,
        retrieve_batch_results,
        list_pending_batches,
    )

    # 1. Prepare batch file
    batch_file = prepare_batch_file(
        call_type='physobs_normalization',
        test_set='test_set_2025_11_26',
        call_type_config=CALL_TYPE_CONFIG['physobs_normalization'],
        model='openai/gpt-5',
        num_runs=5,
    )

    # 2. Submit batch
    meta = await submit_batch(batch_file, 'openai/gpt-5')

    # 3. Check status (periodically)
    status = await check_batch_status(meta['batch_id'], meta['provider'])

    # 4. Retrieve results (when complete)
    results = await retrieve_batch_results(
        meta['batch_id'],
        meta['provider'],
        'openai/gpt-5',
        'test_set_2025_11_26',
    )
""")
