"""LLM client for the runner: the same ``completion()`` seam the linkers already use,
talking straight to one OpenAI-compatible endpoint.

Two kinds of failure are kept apart on purpose. The linkers catch ``Exception``
around most calls and carry on (a failed validation means "reject", a failed
grounding means "no match"), which is the right reading of a bad model answer but
the wrong reading of a dead server: an outage would quietly become thousands of
papers with no instruments. So transport failures are retried here and, if the
endpoint stays down, surface as ``EndpointDown``, a ``BaseException`` that passes
through those handlers and aborts the paper. A paper only reaches results/ if every
one of its calls was answered by the model.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import openai

from paper_data_linking.clients.batch_replay import make_response_shim, strip_reasoning, to_openai_response_format

from .admission import CallEstimator, TokenGate, prompt_chars

logger = logging.getLogger(__name__)

_TRANSPORT_ERRORS = (openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError)
# Provider prefixes used in LLM_CONFIGURATIONS model strings; the server wants the bare name.
_PROVIDER_PREFIXES = ("hosted_vllm/", "openai/")


class EndpointDown(BaseException):
    """The endpoint did not answer within the patience window. Deliberately not an
    ``Exception``: see the module docstring."""


class ModelRequestError(Exception):
    """The server rejected the request itself (4xx), e.g. prompt over the context limit."""


def message_hash(messages: List[Dict[str, Any]]) -> str:
    """Identity of a call's input, used to pair recorded calls with replays."""
    blob = json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def served_model_name(model: str) -> str:
    for prefix in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


class UsageTally:
    """Calls and tokens through one endpoint since the last ``take()``. The worker
    reports these as it goes, so progress does not wait for whole papers to finish."""

    def __init__(self):
        self._lock = threading.Lock()
        self._calls = self._prompt_tokens = self._completion_tokens = 0

    def add(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        with self._lock:
            self._calls += 1
            self._prompt_tokens += prompt_tokens
            self._completion_tokens += completion_tokens

    def take(self) -> Tuple[int, int, int]:
        with self._lock:
            taken = (self._calls, self._prompt_tokens, self._completion_tokens)
            self._calls = self._prompt_tokens = self._completion_tokens = 0
        return taken


class Transport:
    """One endpoint's connection pool, admission gate and health flag, shared by all
    of a worker's threads."""

    def __init__(
        self,
        endpoint: str,
        budget_tokens: int,
        api_key: str = "EMPTY",
        max_connections: int = 256,
        request_timeout: float = 3600.0,
        patience: float = 900.0,
        model_override: Optional[str] = None,
        max_resamples: int = 2,
    ):
        self.endpoint = endpoint.rstrip("/")
        base_url = self.endpoint if self.endpoint.endswith("/v1") else self.endpoint + "/v1"
        self._http = httpx.Client(
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
            timeout=httpx.Timeout(request_timeout, connect=10.0),
        )
        self.openai = openai.OpenAI(base_url=base_url, api_key=api_key, http_client=self._http, max_retries=0)
        self.gate = TokenGate(budget_tokens)
        self.estimator = CallEstimator()
        self.usage = UsageTally()
        self.patience = patience
        self.max_resamples = max_resamples
        self.model_override = model_override
        self.stopping = threading.Event()
        # Cleared while the endpoint is failing, so the worker stops starting new papers.
        self.healthy = threading.Event()
        self.healthy.set()

    def probe(self) -> bool:
        """True if the server answers its health check; also restores the healthy flag."""
        root = self.endpoint[:-3] if self.endpoint.endswith("/v1") else self.endpoint
        try:
            ok = self._http.get(root + "/health", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            ok = False
        if ok:
            self.healthy.set()
        return ok

    def close(self) -> None:
        self._http.close()


class CallRecorder:
    """Per-paper tally of LLM calls, plus the optional call log."""

    def __init__(self, bibcode: str, log_writer=None, log_level: str = "meta"):
        self.bibcode = bibcode
        self._writer = log_writer if log_level != "off" else None
        self._full = log_level == "full"
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.errors = 0
        self.resamples = 0
        self.transport_retries = 0
        self.llm_seconds = 0.0
        self.by_type: Dict[str, Dict[str, int]] = {}
        self.last: Dict[str, Dict[str, Any]] = {}

    def record(self, call_type, messages, params, endpoint, duration, *, response=None, reasoning=None, error=None,
               retries=0, gate_wait=0.0, resample=False):
        usage = getattr(response, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        finish = response.choices[0].finish_reason if response is not None else None
        content = response.choices[0].message.content if response is not None else None
        with self._lock:
            seq = self.calls
            self.calls += 1
            self.prompt_tokens += pt
            self.completion_tokens += ct
            self.transport_retries += retries
            self.resamples += int(resample)
            self.llm_seconds += duration
            t = self.by_type.setdefault(call_type, {"n": 0, "prompt_tokens": 0, "completion_tokens": 0, "errors": 0})
            t["n"] += 1
            t["prompt_tokens"] += pt
            t["completion_tokens"] += ct
            if error is not None:
                self.errors += 1
                t["errors"] += 1
            self.last[call_type] = {"finish_reason": finish, "completion_tokens": ct, "error": error}
        if self._writer is None:
            return
        row = {
            "bibcode": self.bibcode, "seq": seq, "call_type": call_type, "mh": message_hash(messages),
            # "ts" is when the answer arrived; the call was admitted "ms" earlier, after "gate_ms" in the queue.
            "endpoint": endpoint, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "ms": int(duration * 1000), "gate_ms": int(gate_wait * 1000), "prompt_tokens": pt, "completion_tokens": ct,
            "finish_reason": finish, "retries": retries,
        }
        if error is not None:
            row["error"] = error
        if self._full:
            if call_type == "paper_analysis":
                # The user message is the paper text, which the run already has as input.
                messages = [
                    m if m.get("role") != "user" else {"role": "user", "ref": "paper_text", "chars": len(m.get("content") or "")}
                    for m in messages
                ]
            row.update({"messages": messages, "params": params, "content": content, "reasoning": reasoning})
        self._writer.write(row)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls, "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "call_errors": self.errors, "resamples": self.resamples, "transport_retries": self.transport_retries,
                "llm_seconds": round(self.llm_seconds, 1), "by_call_type": {k: dict(v) for k, v in self.by_type.items()},
            }


def _cut_off_before_answering(response) -> bool:
    choice = response.choices[0]
    return choice.finish_reason == "length" and not (choice.message.content or "").strip()


class VLLMClient:
    """Drop-in for ``LiteLLMClient`` in the linkers. One instance per paper."""

    def __init__(self, transport: Transport, recorder: CallRecorder):
        self.transport = transport
        self.recorder = recorder

    def completion(self, call_type: str, model: str, messages: List[Dict[str, str]], **kwargs) -> Any:
        tr = self.transport
        max_tokens = kwargs.get("max_tokens")
        body: Dict[str, Any] = {
            "model": tr.model_override or served_model_name(model),
            "messages": messages,
        }
        if kwargs.get("temperature") is not None:
            body["temperature"] = kwargs["temperature"]
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if kwargs.get("stop"):
            body["stop"] = kwargs["stop"]
        response_format = to_openai_response_format(kwargs.get("response_format"))
        if response_format is not None:
            body["response_format"] = response_format
        extra_body = kwargs.get("extra_body")
        headers = {
            "x-pdl-call-type": call_type,
            "x-pdl-paper": self.recorder.bibcode.encode("ascii", "replace").decode("ascii"),
        }
        params = {k: v for k, v in body.items() if k not in ("messages", "model")}
        if extra_body:
            params["extra_body"] = extra_body

        for attempt in range(1 + tr.max_resamples):
            response = self._attempt(call_type, messages, body, extra_body, headers, params, max_tokens, resample=attempt > 0)
            if not _cut_off_before_answering(response):
                break
            # The token cap went on reasoning and no answer came out. The linkers read
            # that as a failed call (a rejected validation, an unmatched instrument); a
            # fresh sample almost always answers, so ask again before they see it.
            logger.warning("%s for %s hit max_tokens with no answer (attempt %d)", call_type, self.recorder.bibcode, attempt + 1)
        return response

    def _attempt(self, call_type, messages, body, extra_body, headers, params, max_tokens, resample):
        tr = self.transport
        chars = prompt_chars(messages)
        queued = time.monotonic()
        held = tr.gate.acquire(tr.estimator.prompt_tokens(call_type, messages) + tr.estimator.expected(call_type, max_tokens))
        start = time.monotonic()
        retries = 0
        try:
            raw, retries = self._create_with_patience(body, extra_body, headers)
        except ModelRequestError as e:
            self.recorder.record(call_type, messages, params, tr.endpoint, time.monotonic() - start, error=str(e)[:500],
                                 gate_wait=start - queued, resample=resample)
            tr.usage.add()
            raise
        finally:
            tr.gate.release(held)

        message = raw.choices[0].message
        content = message.content
        if isinstance(content, str):
            # NUL bytes have turned up in model output and Postgres rejects them on import.
            content = strip_reasoning(content.replace("\x00", ""))
        usage = raw.usage
        response = make_response_shim(
            content,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            finish_reason=raw.choices[0].finish_reason,
            model=raw.model,
        )
        tr.estimator.observe(call_type, response.usage.completion_tokens, chars, response.usage.prompt_tokens)
        extras = getattr(message, "model_extra", None) or {}
        reasoning = extras.get("reasoning_content") or extras.get("reasoning")
        self.recorder.record(
            call_type, messages, params, tr.endpoint, time.monotonic() - start,
            response=response, reasoning=reasoning, retries=retries, gate_wait=start - queued, resample=resample,
        )
        tr.usage.add(response.usage.prompt_tokens, response.usage.completion_tokens)
        return response

    def _create_with_patience(self, body, extra_body, headers):
        tr = self.transport
        deadline = time.monotonic() + tr.patience
        delay, retries = 0.5, 0
        while True:
            try:
                raw = tr.openai.chat.completions.create(**body, extra_body=extra_body, extra_headers=headers)
                if retries:
                    tr.healthy.set()
                return raw, retries
            except _TRANSPORT_ERRORS as e:
                tr.healthy.clear()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or tr.stopping.is_set():
                    raise EndpointDown(f"{tr.endpoint}: {type(e).__name__}: {e}") from e
                retries += 1
                if retries == 1:
                    logger.warning("Endpoint %s not answering (%s); retrying for up to %ds", tr.endpoint, type(e).__name__, int(tr.patience))
                if tr.stopping.wait(min(delay, remaining)):
                    raise EndpointDown(f"{tr.endpoint}: stopped while waiting for the endpoint") from e
                delay = min(delay * 2, 30.0)
            except openai.APIStatusError as e:
                raise ModelRequestError(f"HTTP {e.status_code}: {e}") from e
