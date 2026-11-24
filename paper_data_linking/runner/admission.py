"""Admission control for one endpoint.

A vLLM replica is bound by KV-cache memory, not by request count: one L40S holds
roughly a million cached tokens, which is ~35 concurrent step-1 calls (19k-token
prompts) or a few hundred short downstream calls. Admitting by request count either
starves the GPU on short calls or overcommits it on long ones, so calls are admitted
against a token budget instead. vLLM's own queue remains the backstop.

The budget is in estimated tokens, and the estimate is not exact: prompt sizes are
guessed from character counts, and the capacity a server reports need not be what
it can hold. So the budget is not fixed. ``BudgetController`` moves it to keep the
server's own KV-usage gauge near the target.
"""

import logging
import re
import threading
import urllib.request
from collections import deque
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Measured on 1x L40S, FP8 KV cache, with the MTP drafter loaded: 965,910 tokens.
DEFAULT_KV_TOKENS = 965_000
DEFAULT_BUDGET_FRACTION = 0.85
# English scientific text runs ~3.5-4 characters per token; err toward more tokens.
CHARS_PER_TOKEN = 3.3
# Starting points measured with Gemma 4 on the 182-paper evaluation set; each is
# corrected from the server's token counts as calls return. Lists of catalog
# identifiers (SPASE paths) tokenize much denser than prose.
_CHARS_PER_TOKEN = {"paper_analysis": 4.0, "mission_identification": 2.6}

_EXPECTED_OUTPUT = {"paper_analysis": 8000}
_DEFAULT_EXPECTED_OUTPUT = 1500


class TokenGate:
    """Weighted FIFO semaphore. A call waits until its token cost fits in the budget;
    waiters are served in arrival order so a large step-1 call cannot be starved by a
    stream of small ones. A call larger than the whole budget runs alone."""

    def __init__(self, budget: int):
        self.budget = max(1, int(budget))
        self.in_use = 0
        self.running = 0
        self._cond = threading.Condition()
        self._waiters: deque = deque()

    def acquire(self, cost: int) -> int:
        cost = max(1, int(cost))
        ticket = object()
        with self._cond:
            self._waiters.append(ticket)
            while not (self._waiters[0] is ticket and (self.in_use + cost <= self.budget or self.running == 0)):
                self._cond.wait()
            self._waiters.popleft()
            self.in_use += cost
            self.running += 1
            # The next waiter may fit too.
            self._cond.notify_all()
        return cost

    def release(self, cost: int) -> None:
        with self._cond:
            self.in_use -= cost
            self.running -= 1
            self._cond.notify_all()

    def set_budget(self, budget: int) -> None:
        with self._cond:
            self.budget = max(1, int(budget))
            self._cond.notify_all()

    def snapshot(self) -> Dict[str, int]:
        with self._cond:
            return {"budget": self.budget, "in_use": self.in_use, "running": self.running, "waiting": len(self._waiters)}


def prompt_chars(messages) -> int:
    return sum(len(m.get("content") or "") for m in messages)


class CallEstimator:
    """Running means per call type, used to cost a call before it runs: completion
    tokens, and characters per prompt token."""

    def __init__(self):
        self._output: Dict[str, float] = dict(_EXPECTED_OUTPUT)
        self._chars_per_token: Dict[str, float] = dict(_CHARS_PER_TOKEN)
        self._lock = threading.Lock()

    def prompt_tokens(self, call_type: str, messages) -> int:
        with self._lock:
            ratio = self._chars_per_token.get(call_type, CHARS_PER_TOKEN)
        return int(prompt_chars(messages) / ratio) + 16

    def expected(self, call_type: str, max_tokens: Optional[int]) -> int:
        with self._lock:
            est = self._output.get(call_type, _DEFAULT_EXPECTED_OUTPUT)
        return int(min(est, max_tokens) if max_tokens else est)

    def observe(self, call_type: str, completion_tokens: int, chars: int = 0, prompt_tokens: int = 0) -> None:
        with self._lock:
            prev = self._output.get(call_type, _DEFAULT_EXPECTED_OUTPUT)
            self._output[call_type] = 0.95 * prev + 0.05 * completion_tokens
            if chars > 0 and prompt_tokens > 0:
                # Clamped so one odd usage report cannot skew the estimate far.
                ratio = min(max(chars / prompt_tokens, 1.0), 8.0)
                prev = self._chars_per_token.get(call_type, CHARS_PER_TOKEN)
                self._chars_per_token[call_type] = 0.9 * prev + 0.1 * ratio


class BudgetController:
    """Moves a gate's budget so the server's KV cache stays near ``target`` full.

    Measured on Gemma 4 with vLLM 0.32, the gate's token arithmetic was off in both
    directions within one run. The server's metrics gave two thirds of the capacity
    its log reported, so long step-1 calls ran 20 at a time at 45% KV use where
    about 34 fit. Later the same budget in short downstream calls filled the cache
    to 91-99%. The KV-usage gauge is the server's own account of its memory, so the
    budget follows that: up in small steps while the gate is holding calls back and
    the cache has room, down faster when the cache runs over the target.
    """

    def __init__(self, gate: TokenGate, target: float = DEFAULT_BUDGET_FRACTION, deadband: float = 0.05,
                 step_up: float = 1.03, step_down: float = 0.9, span: float = 4.0):
        self.gate = gate
        self.target = target
        self.deadband = deadband
        self.step_up = step_up
        self.step_down = step_down
        self.floor = max(1, int(gate.budget / span))
        self.ceiling = int(gate.budget * span)

    def update(self, kv_usage: Optional[float], server_waiting: float = 0) -> int:
        """Apply one reading of the server's gauges (``kv_usage`` in 0..1). Returns the budget."""
        snap = self.gate.snapshot()
        budget = snap["budget"]
        if kv_usage is None:
            return budget
        if kv_usage > self.target + self.deadband:
            factor = max(self.step_down, self.target / kv_usage)
        elif kv_usage < self.target - self.deadband and snap["waiting"] > 0 and not server_waiting:
            # Only while the gate is the limit: a quiet cache with nothing queued needs no more budget.
            factor = min(self.step_up, self.target / max(kv_usage, 0.01))
        else:
            return budget
        new = min(max(int(budget * factor), self.floor), self.ceiling)
        if new != budget:
            self.gate.set_budget(new)
        return new


def _metrics_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + "/metrics"


def fetch_metrics(endpoint: str, timeout: float = 5.0) -> Optional[str]:
    try:
        with urllib.request.urlopen(_metrics_url(endpoint), timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def parse_kv_capacity(metrics_text: str) -> Optional[int]:
    """KV-cache capacity in tokens from vLLM's ``cache_config_info`` metric
    (``num_gpu_blocks`` x ``block_size``), or None if the server does not expose it."""
    for line in metrics_text.splitlines():
        if "cache_config_info" not in line or line.startswith("#"):
            continue
        blocks = re.search(r'num_gpu_blocks="(\d+)"', line)
        size = re.search(r'block_size="(\d+)"', line)
        if blocks and size:
            return int(blocks.group(1)) * int(size.group(1))
    return None


def parse_gauges(metrics_text: str) -> Dict[str, float]:
    """The handful of vLLM gauges worth showing on a progress line."""
    wanted = {
        "num_requests_running": "running",
        "num_requests_waiting": "waiting",
        "kv_cache_usage_perc": "kv",
        "gpu_cache_usage_perc": "kv",  # name in older vLLM releases
    }
    out: Dict[str, float] = {}
    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue
        for metric, key in wanted.items():
            if f":{metric}" in line or line.startswith(metric):
                try:
                    out[key] = float(line.rsplit(" ", 1)[1])
                except (ValueError, IndexError):
                    pass
    return out


def resolve_capacity(endpoint: str, kv_tokens: Optional[int]) -> Tuple[int, str]:
    """KV capacity in tokens and where the figure came from: an explicit ``kv_tokens``
    wins, else what the server reports, else the L40S default."""
    if kv_tokens:
        return kv_tokens, "flag"
    text = fetch_metrics(endpoint)
    reported = parse_kv_capacity(text) if text else None
    if reported:
        return reported, "server metrics"
    return DEFAULT_KV_TOKENS, "default"


def resolve_budget(endpoint: str, kv_tokens: Optional[int], fraction: float = DEFAULT_BUDGET_FRACTION) -> int:
    """Starting token budget for an endpoint."""
    kv_tokens, source = resolve_capacity(endpoint, kv_tokens)
    budget = int(kv_tokens * fraction)
    logger.info("Endpoint %s: KV capacity %d tokens (%s), admission budget %d", endpoint, kv_tokens, source, budget)
    return budget
