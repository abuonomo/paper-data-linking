# paper_data_linking/clients/batch_replay.py
"""
Pure (Django-free) primitives for the wave-synchronous batch-downstream runner.

The runner re-executes the existing per-paper pipeline multiple times. On each
"collection" pass, the LLM chokepoint either serves a previously-resolved response
from a durable cache or defers the call into the current Bedrock batch wave by
raising :class:`PendingBatch`. These helpers are shared by the chokepoint
(api/vso_query_builder/clients.py) and the orchestrator
(api/vso_query_builder/batch_downstream.py).

Nothing here touches Django so the hashing / serialization / response-shim logic
can be unit-tested without a database.
"""

from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

# gpt-oss is a reasoning model; on the Bedrock batch / InvokeModel path it PREPENDS
# its reasoning wrapped in <reasoning>…</reasoning> (or <think>…</think>) to the text
# content — unlike the live Converse path, which separates it. Strip it so the JSON /
# text a caller parses matches the live behavior. (Tool-call ARGS are clean — the
# reasoning lands in content, not the arguments — so structured calls are unaffected.)
_REASONING_RE = re.compile(r'<(reasoning|think)>.*?</(reasoning|think)>\s*', re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    return _REASONING_RE.sub('', text).strip()


# Substrings that mark a RETRYABLE (transient) provider error — the call should get
# a fresh attempt, not be cached as terminally failed. Bedrock throws these at scale
# (ServiceUnavailable, throttling) and locally on SSO expiry. Permanent errors
# (validation, unparseable output) are NOT here and become terminal 'failed'.
_TRANSIENT_MARKERS = (
    "serviceunavailable", "service unavailable", "throttl", "toomanyrequests",
    "too many requests", "429", "rate exceeded", "rate limit",
    "unexpected error", "try your request again", "try again",
    "expired", "security token", "internalserver", "internal server",
    "internalfailure", "connection", "timed out", "timeout", "503", "500", "502",
    "modelnotready", "model not ready",
)


def is_transient_error(err: Optional[str]) -> bool:
    """True if an error string looks transient/retryable (vs a permanent failure)."""
    e = (err or "").lower()
    return any(m in e for m in _TRANSIENT_MARKERS)


class DeferredCall(Exception):
    """Raised by the chokepoint (collection mode) when a logical LLM call has not
    yet been resolved.

    Deliberately an ORDINARY ``Exception`` so the pipeline's existing per-branch
    error isolation absorbs it: the grounder's retry loop gives up on that
    instrument x data-system branch and the loops continue to SIBLING branches,
    each registering its own pending call. One collection pass therefore discovers
    the whole frontier (all independent branches' next calls) instead of aborting
    at the first one — waves scale with dependency DEPTH, not per-paper call count.

    Paper completion is signalled by the deferred-call COUNTER (see
    pipeline_context.deferred_calls), not by this exception escaping.
    """

    def __init__(self, request_hash: str):
        super().__init__(f"deferred batch LLM call {request_hash}")
        self.request_hash = request_hash


# Backwards-compatible alias (previous BaseException-based design).
PendingBatch = DeferredCall


# Only these kwargs affect the model's output and therefore the cache identity.
# Everything else (aws_region_name, api_base, timeouts, prompt_context, retries,
# metadata, ...) is intentionally excluded so it cannot perturb the hash.
_GENERATION_PARAM_KEYS = (
    "temperature",
    "max_tokens",
    "max_completion_tokens",
    "reasoning_effort",
    "top_p",
    "top_k",
    "stop",
    "seed",
    "n",
    "frequency_penalty",
    "presence_penalty",
    "logit_bias",
)


def canonical_response_format(response_format: Any) -> Optional[Any]:
    """Return a stable, JSON-serializable representation of ``response_format``.

    Handles the three shapes used in the pipeline:
      * a pydantic ``BaseModel`` subclass (class) -> ``{name, schema}``
      * a plain dict (e.g. ``{"type": "json_object"}`` or an OpenAI json_schema
        envelope) -> the dict itself
      * ``None`` -> ``None``
    """
    if response_format is None:
        return None
    if isinstance(response_format, dict):
        return response_format
    # pydantic model class (has model_json_schema); use name + schema
    schema_fn = getattr(response_format, "model_json_schema", None)
    if callable(schema_fn):
        return {"name": getattr(response_format, "__name__", "schema"),
                "schema": schema_fn()}
    # pydantic v1 fallback
    schema_fn_v1 = getattr(response_format, "schema", None)
    if callable(schema_fn_v1):
        return {"name": getattr(response_format, "__name__", "schema"),
                "schema": schema_fn_v1()}
    # Unknown — fall back to a string form so the hash stays stable.
    return {"repr": repr(response_format)}


# litellm's constant for the synthetic tool it forces to enforce a response schema.
RESPONSE_FORMAT_TOOL_NAME = "json_tool_call"


def response_format_to_forced_tool(response_format: Any):
    """Translate a response_format into a FORCED function/tool call — exactly how
    litellm enforces structured output on Bedrock (it never sends response_format;
    it forces a tool whose parameters are the schema and lifts the tool-call args
    back into message content). Bedrock's batch API honors forced tools but ignores
    response_format, so this is what makes structured output work in a batch.

    Returns ``(tools, tool_choice)`` or ``(None, None)`` when no schema is available.
    """
    if response_format is None:
        return None, None
    schema = None
    if isinstance(response_format, dict):
        if response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema")
        elif response_format.get("type") == "json_object":
            return None, None  # no schema to enforce
        else:
            schema = response_format  # assume a raw JSON schema
    else:
        fn = getattr(response_format, "model_json_schema", None) or getattr(
            response_format, "schema", None)
        schema = fn() if callable(fn) else None
    if schema is None:
        return None, None
    tools = [{
        "type": "function",
        "function": {
            "name": RESPONSE_FORMAT_TOOL_NAME,
            "description": "Return the response strictly as JSON matching the schema.",
            "parameters": schema,
            # AWS "Strict Tool Use" structured-output method — officially supported
            # for gpt-oss-120b including batch inference. Guarantees schema conformance.
            "strict": True,
        },
    }]
    tool_choice = {"type": "function", "function": {"name": RESPONSE_FORMAT_TOOL_NAME}}
    return tools, tool_choice


def extract_tool_arguments(message: Dict[str, Any]) -> Optional[str]:
    """If a chat message carries a forced json_tool_call, return its raw argument
    string (the structured JSON the caller will parse). Mirrors litellm lifting
    tool-call args into content for response_format calls."""
    tool_calls = (message or {}).get("tool_calls") or []
    for tc in tool_calls:
        fn = (tc or {}).get("function") or {}
        if fn.get("name") == RESPONSE_FORMAT_TOOL_NAME and fn.get("arguments") is not None:
            return fn["arguments"]
    if tool_calls:  # any forced tool — take the first
        fn = (tool_calls[0] or {}).get("function") or {}
        return fn.get("arguments")
    return None


def pick_message_content(message: Dict[str, Any]) -> str:
    """The answer text from a chat message dict: a forced json_tool_call's arguments
    if present (reasoning is separate there), else the content with any leading
    <reasoning>/<think> block stripped. This is what makes batch output match the
    live path regardless of reasoning-model quirks."""
    args = extract_tool_arguments(message)
    if args is not None:
        return args
    return strip_reasoning((message or {}).get("content")) or ""


def to_openai_response_format(response_format: Any) -> Optional[Dict[str, Any]]:
    """Convert ``response_format`` to the OpenAI-style dict accepted in a batch
    record's ``modelInput`` (gpt-oss on Bedrock takes OpenAI-compatible input).

    Returns ``None`` when no structured output was requested.
    """
    if response_format is None:
        return None
    if isinstance(response_format, dict):
        return response_format
    schema_fn = getattr(response_format, "model_json_schema", None) or getattr(
        response_format, "schema", None
    )
    if callable(schema_fn):
        name = getattr(response_format, "__name__", "schema")
        return {
            "type": "json_schema",
            "json_schema": {"name": name, "schema": schema_fn(), "strict": True},
        }
    return None


def generation_params(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the output-affecting generation params from a call's kwargs."""
    return {k: kwargs[k] for k in _GENERATION_PARAM_KEYS if k in kwargs and kwargs[k] is not None}


def canonical_request(
    model: str,
    messages: List[Dict[str, Any]],
    response_format: Any = None,
    gen_params: Optional[Dict[str, Any]] = None,
    attempt: int = 0,
) -> Dict[str, Any]:
    """Build the canonical request dict that defines a logical call's identity."""
    return {
        "model": model,
        "messages": messages,
        "response_format": canonical_response_format(response_format),
        "params": gen_params or {},
        # ``attempt`` lets a caller's parse-failure retry (identical messages)
        # map to a DISTINCT cache entry instead of replaying the bad response.
        "attempt": attempt,
    }


def request_hash(canonical: Dict[str, Any]) -> str:
    """Deterministic SHA-256 over a canonical request dict.

    Stable across re-execution passes (sorted keys, compact separators) so the
    same logical call lands on the same cache key every pass.
    """
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def make_response_shim(
    content: Optional[str],
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    finish_reason: str = "stop",
    model: str = "",
) -> Any:
    """Reconstruct a minimal litellm-like response object from cached content.

    Mirrors the shape callers read: ``response.choices[0].message.content``,
    ``response.choices[0].finish_reason`` and ``response.usage.*``.
    """
    message = SimpleNamespace(content=content, role="assistant", tool_calls=None, function_call=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason, index=0)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens or (prompt_tokens + completion_tokens),
    )
    return SimpleNamespace(choices=[choice], usage=usage, model=model, id="cached")
