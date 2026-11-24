"""A stand-in for ``vllm serve`` that needs no GPU.

It speaks enough of the OpenAI chat API (plus /health and /metrics) for the runner to
exercise its whole path: scheduling, admission, retries, resume and the pipeline's own
parsers. It accepts and ignores vLLM's command-line flags, so it can replace the real
server through ``PDL_VLLM_CMD``:

    PDL_VLLM_CMD="python -m paper_data_linking.runner.fake_vllm serve" PDL_GPUS=0,1,2,3,4,5,6,7 pdl-batch all ...

Modes (FAKE_VLLM_MODE):
    synthetic  plausible answers built from the request, keyed on the x-pdl-call-type header
    replay     recorded answers from call logs (FAKE_VLLM_REPLAY, comma-separated files),
               matched on the hash of the request messages; an unknown request is a 404

Knobs: FAKE_VLLM_LATENCY (seconds per call), FAKE_VLLM_FAIL_PCT (percent of calls answered
503), FAKE_VLLM_STARTUP (seconds before /health turns 200), FAKE_VLLM_KV_TOKENS (capacity the
KV-usage gauge is measured against), FAKE_VLLM_KV_REPORTED (capacity the metrics claim).
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import message_hash

STEP1_FORM = """# Scientific Observation Instrumentation Form

## Summary of the Paper
- **Content Summary**: Synthetic summary produced by the fake server.

## Instrumentation Details
"""

STEP1_INSTRUMENT = """
### {name}
- **General Comments**:
  - Synthetic use of {name}.
- **Supporting Quote**: "We used data from {name}."

#### Data Collection Period 1: Synthetic period
- **Time Range**: 2000-05-18 09:45:15 UT – 2000-05-19 14:47:16 UT
  - **Supporting Quote**: "Observations were taken on 2000 May 18 and 19."
- **Wavelength(s)**:
  - 195 Å
  - **Supporting Quote**: "The 195 Å channel was used."
- **Physical Observable**: Intensity images
  - **Supporting Quote**: "Intensity images were analysed."
- **Additional Comments**:
  - None.
"""

VALIDATION_ANSWER = """VALIDATION ANALYSIS:
- Name/Type alignment: synthetic → pass
- Mission reference match: synthetic → pass
- Temporal compatibility: synthetic → pass
- Scientific capability match: synthetic → pass
- Domain consistency: synthetic → pass
- Domain alignment: synthetic → pass
- Explicit mention: synthetic → pass
- Scientific capability: synthetic → pass

FINAL DECISION: valid"""


class State:
    def __init__(self, mode=None, latency=None, fail_pct=None, kv_tokens=None, startup=None, replay=None, kv_reported=None):
        env = os.environ.get
        self.mode = mode or env("FAKE_VLLM_MODE", "synthetic")
        self.latency = float(env("FAKE_VLLM_LATENCY", "0") if latency is None else latency)
        self.fail_pct = float(env("FAKE_VLLM_FAIL_PCT", "0") if fail_pct is None else fail_pct)
        self.kv_tokens = int(env("FAKE_VLLM_KV_TOKENS", "965904") if kv_tokens is None else kv_tokens)
        # What the metrics claim the capacity is; real servers have been seen to under-report it.
        self.kv_reported = int(env("FAKE_VLLM_KV_REPORTED", "0") if kv_reported is None else kv_reported) or self.kv_tokens
        self.held_tokens = 0
        self.ready_at = time.monotonic() + float(env("FAKE_VLLM_STARTUP", "0") if startup is None else startup)
        replay = env("FAKE_VLLM_REPLAY", "") if replay is None else replay
        self.lock = threading.Lock()
        self.running = 0
        self.peak_running = 0
        self.requests = 0
        self.failures_injected = 0
        self.replay_misses = 0
        self.seen = defaultdict(int)  # message hash -> times requested
        self.replay = defaultdict(deque)
        if self.mode == "replay":
            for path in filter(None, replay.split(",")):
                opener = gzip.open if path.endswith(".gz") else open
                try:
                    with opener(path, "rt", encoding="utf-8") as f:
                        for line in f:
                            try:
                                row = json.loads(line)
                            except ValueError:
                                continue
                            if row.get("mh") and "content" in row:
                                self.replay[row["mh"]].append(row)
                except EOFError:
                    pass


def _section(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1) if m else ""


RUNAWAY = object()  # reasoning ran to the token cap: no content, finish_reason "length"


def synthetic_answer(call_type: str, messages, attempt: int, stop=None):
    user = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
    if call_type == "paper_analysis":
        if "FAKE_NO_INSTRUMENTS" in user:
            return "No instruments were used in this paper."
        if "FAKE_EMPTY_ONCE" in user and attempt == 0:
            return ""  # what a fired "---" stop sequence looks like
        if "FAKE_ALWAYS_EMPTY" in user:
            return ""
        if "FAKE_OPENS_WITH_SEPARATOR" in user and stop:
            return ""  # a paper whose answer always starts with the stop sequence
        m = re.search(r"INSTRUMENTS:\s*(.+)", user)
        names = [n.strip() for n in m.group(1).split(";") if n.strip()] if m else ["EIT on board SOHO"]
        return STEP1_FORM + "".join(STEP1_INSTRUMENT.format(name=n) for n in names)
    if call_type == "mission_identification":
        if "FAKE_RUNAWAY_ONCE" in user and attempt == 0:
            return RUNAWAY
        description = _section(user, "instrument_description").lower()
        picks = []
        for num, code, name in re.findall(r"^\s*(\d+)\.\s+(\S+)\s+\((.+?)\)", _section(user, "available_missions"), re.M):
            if re.search(rf"\b{re.escape(name.lower())}\b", description) or re.search(rf"\b{re.escape(code.lower())}\b", description):
                picks.append(f"{code}({num})")
        return ", ".join(picks[:3]) or "UNKNOWN"
    if call_type == "instrument_selection":
        entries = re.findall(r"^\s*(\d+)\.\s.*\[([^/\]]+)/[^\]]+\]\s*$", user, re.M)
        rest = re.sub(r"^\s*\d+\.\s.*\[[^\]]+\]\s*$", "", user, flags=re.M).lower()
        picks = [num for num, code in entries if re.search(rf"\b{re.escape(code.lower())}\b", rest)]
        return ", ".join(picks) or ("1" if entries else "0")
    if call_type == "mission_selection":
        return "1"
    if call_type in ("mission_validation", "instrument_validation"):
        return VALIDATION_ANSWER
    if call_type == "structure_validation_time_range":
        return json.dumps({"patches": [], "unfixable_paths": []})
    if call_type == "time_normalization":
        dates = re.findall(r"(\d{4})-(\d{2})-(\d{2})", user)
        start = "-".join(dates[0]) if dates else "2010-01-01"
        end = "-".join(dates[-1]) if dates else "2010-01-02"
        return json.dumps({"start_datetime": f"{start}T00:00:00Z", "end_datetime": f"{end}T23:59:59Z",
                           "precision": "day", "is_approximate": False, "original_text": "synthetic"})
    if call_type == "wavelength_normalization":
        return "195 angstrom"
    if call_type == "cadence_normalization":
        return "NONE"
    if call_type in ("physobs_normalization", "detector_normalization"):
        return "UNCERTAIN"
    return "ready"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def state(self) -> State:
        return self.server.state

    def log_message(self, *args):  # quiet
        pass

    def _send(self, status: int, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        st = self.state
        if self.path == "/health":
            return self._send(200 if time.monotonic() >= st.ready_at else 503, {})
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": "fake", "object": "model"}]})
        if self.path == "/metrics":
            text = (
                f'vllm:cache_config_info{{block_size="16",num_gpu_blocks="{st.kv_reported // 16}"}} 1.0\n'
                f"vllm:num_requests_running {float(st.running)}\n"
                "vllm:num_requests_waiting 0.0\n"
                f"vllm:kv_cache_usage_perc {min(1.0, st.held_tokens / st.kv_tokens)}\n"
            )
            return self._send(200, text.encode(), "text/plain")
        if self.path == "/fake/stats":
            return self._send(200, {"requests": st.requests, "peak_running": st.peak_running,
                                    "failures_injected": st.failures_injected, "replay_misses": st.replay_misses})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        st = self.state
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": "not found"})
        if time.monotonic() < st.ready_at:
            return self._send(503, {"error": {"message": "model not ready"}})
        messages = body.get("messages") or []
        call_type = self.headers.get("x-pdl-call-type", "")
        mh = message_hash(messages)
        held = sum(len(m.get("content") or "") for m in messages) // 4
        with st.lock:
            st.requests += 1
            st.running += 1
            st.held_tokens += held
            st.peak_running = max(st.peak_running, st.running)
            attempt = st.seen[mh]
            st.seen[mh] += 1
            n = st.requests
        try:
            if st.latency:
                time.sleep(st.latency)
            # Deterministic failure injection: a fixed share of request numbers fail.
            if st.fail_pct and int(hashlib.md5(str(n).encode()).hexdigest(), 16) % 10000 < st.fail_pct * 100:
                with st.lock:
                    st.failures_injected += 1
                return self._send(503, {"error": {"message": "injected failure"}})
            finish_reason, usage, reasoning = "stop", None, None
            if st.mode == "replay":
                with st.lock:
                    rows = st.replay.get(mh)
                    row = rows.popleft() if rows and len(rows) > 1 else (rows[0] if rows else None)
                    if row is None:
                        st.replay_misses += 1
                if row is None:
                    return self._send(404, {"error": {"message": f"replay miss for {call_type} {mh[:12]}"}})
                content, finish_reason, reasoning = row["content"], row.get("finish_reason") or "stop", row.get("reasoning")
                usage = {"prompt_tokens": row.get("prompt_tokens", 0), "completion_tokens": row.get("completion_tokens", 0)}
            else:
                content = synthetic_answer(call_type, messages, attempt, body.get("stop"))
                if content is RUNAWAY:
                    content, finish_reason = None, "length"
            if usage is None:
                usage = {"prompt_tokens": sum(len(m.get("content") or "") for m in messages) // 4,
                         "completion_tokens": max(1, len(content or "") // 4)}
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            message = {"role": "assistant", "content": content}
            if reasoning:
                message["reasoning_content"] = reasoning
            self._send(200, {
                "id": f"fake-{n}", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "fake"),
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": usage,
            })
        finally:
            with st.lock:
                st.running -= 1
                st.held_tokens -= held


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 2048


def serve(host: str, port: int, **state_options) -> _Server:
    """A server ready for ``serve_forever()``; ``port`` 0 picks a free one."""
    server = _Server((host, port), Handler)
    server.state = State(**state_options)
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GPU-free stand-in for `vllm serve`")
    parser.add_argument("command", nargs="?", default="serve")
    parser.add_argument("model", nargs="?", default="fake")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args, _ignored = parser.parse_known_args(argv)
    server = serve(args.host, args.port)
    print(f"fake vLLM ({server.state.mode}) on {args.host}:{args.port}, GPU {os.environ.get('CUDA_VISIBLE_DEVICES', '-')}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
