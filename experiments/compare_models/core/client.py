from __future__ import annotations

import time
from typing import Any, Dict, List

import litellm


def call_model(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 1.0,
    timeout: float | None = None,
    max_retries: int | None = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Thin wrapper around litellm.completion to get content, token usage, and timing.
    Provider is inferred from model string (e.g., 'openai/gpt-4o' → 'openai').
    """
    start = time.time()
    completion_kwargs = dict(kwargs)
    if timeout is not None:
        completion_kwargs["timeout"] = timeout
    if max_retries is not None:
        completion_kwargs["max_retries"] = max_retries
    resp = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        **completion_kwargs,
    )
    dur_ms = int((time.time() - start) * 1000)

    provider = model.split('/')[0] if '/' in model else 'unknown'

    # Try real cost from litellm; fallback to 0.0
    try:
        cost = getattr(resp, '_hidden_params', {}).get('response_cost', None)
        if cost is None:
            cost = litellm.completion_cost(resp)
        cost = float(cost or 0.0)
    except Exception:
        cost = 0.0

    content = None
    if getattr(resp, 'choices', None):
        content = resp.choices[0].message.content

    usage = resp.usage if hasattr(resp, 'usage') else None
    return {
        'provider': provider,
        'content': content or '',
        'tokens_used': {
            'prompt_tokens': (usage.prompt_tokens if usage else 0),
            'completion_tokens': (usage.completion_tokens if usage else 0),
            'total_tokens': (usage.total_tokens if usage else 0),
        },
        'response_time_ms': dur_ms,
        'cost_estimate': cost,
        'finish_reason': (resp.choices[0].finish_reason if getattr(resp, 'choices', None) else None),
    }
