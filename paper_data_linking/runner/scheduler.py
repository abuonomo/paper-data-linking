"""Runs a paper source to completion across one or more endpoints.

    feeder thread --> task queue --> worker process 0 (endpoint 0): N threads, a paper each
                                     worker process 1 (endpoint 1): ...

One worker process per endpoint keeps the hot path free of cross-process state: each
worker owns its endpoint's admission gate and its own output shards. Workers pull from
a shared queue, so a faster replica simply takes more papers. Nothing here depends on
how many endpoints there are; eight is the same code path as one.
"""

import fcntl
import hashlib
import json
import logging
import multiprocessing as mp
import os
import queue
import signal
import threading
import time
import traceback
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .admission import BudgetController, fetch_metrics, parse_gauges, resolve_capacity
from .sources import load_source
from .store import CALLS, FAILURES, RESULTS, STEP1, RunState, ShardWriter

logger = logging.getLogger(__name__)


@dataclass
class RunConfig:
    out_dir: str
    endpoints: List[str]
    source: str = "jsonl"
    papers: Optional[str] = None
    source_options: Dict[str, str] = field(default_factory=dict)
    config_name: str = "vllm-gemma4-batch"
    catalog: Optional[str] = None
    papers_in_flight: int = 128
    workers: Optional[int] = None
    kv_tokens: Optional[int] = None
    budget_fraction: float = 0.85
    fixed_budget: bool = False
    budget_interval: float = 10.0
    call_log: str = "meta"
    api_key: str = "EMPTY"
    model: Optional[str] = None
    request_timeout: float = 3600.0
    patience: float = 900.0
    max_paper_attempts: int = 3
    max_step1_attempts: int = 3
    limit: Optional[int] = None
    total: Optional[int] = None
    shard_index: int = 0
    shard_count: int = 1
    retry_failed: bool = False
    progress_interval: float = 30.0
    rate_window: float = 900.0
    grace: float = 120.0
    log_level: str = "WARNING"


def in_shard(bibcode: str, index: int, count: int) -> bool:
    if count <= 1:
        return True
    return int(hashlib.sha1(bibcode.encode("utf-8")).hexdigest(), 16) % count == index


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.WARNING),
                        format="%(asctime)s %(processName)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("LiteLLM", "litellm", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The linkers warn on every ordinary "no match" outcome, which is most of a corpus.
    if level.upper() not in ("DEBUG", "INFO"):
        logging.getLogger("paper_data_linking.linkers").setLevel(logging.ERROR)


class StopFlag:
    """The stop signal shared by the parent and its workers.

    Deliberately not a ``multiprocessing.Event``. Its ``set()`` waits for every process
    sleeping on it to acknowledge, and a worker's main thread is always sleeping on it,
    so once any worker has been killed (out of memory, or a signal sent to the whole
    process group) the parent blocks in ``set()`` for good: the run can never stop.
    This is one shared byte with no lock, which each worker polls into an ordinary
    ``threading.Event`` of its own, so no process can be left waiting on a dead one.
    """

    def __init__(self, ctx):
        self._shared = ctx.RawValue("b", 0)
        self._local = threading.Event()

    def __getstate__(self):
        return (self._shared,)

    def __setstate__(self, state):
        self._shared = state[0]
        self._local = threading.Event()

    def set(self) -> None:
        self._shared.value = 1
        self._local.set()

    def is_set(self) -> bool:
        return self._local.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._local.wait(timeout)

    def follow(self, poll: float = 0.2) -> None:
        """In a worker: set this process's event when the parent sets the shared byte."""
        def watch():
            while not self._shared.value:
                time.sleep(poll)
            self._local.set()
        threading.Thread(target=watch, name="stop-watch", daemon=True).start()


def _exit_if_orphaned(parent_pid: int) -> None:
    """A worker must not outlive a killed parent: it would keep appending to shard
    files that the next run also opens."""
    def watch():
        while os.getppid() == parent_pid:
            time.sleep(1)
        os._exit(1)
    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def worker_main(label: str, endpoint: str, cfg: RunConfig, task_q, event_q, stop) -> None:
    """Entry point of one worker process."""
    # The parent decides when to stop. A signal sent to the whole process group (a
    # terminal's Ctrl-C, `timeout`, a job scheduler) reaches the workers too, and one
    # that died of it could not finish its papers or report them.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    stop.follow()
    _configure_logging(cfg.log_level)
    _exit_if_orphaned(os.getppid())
    from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder

    from .client import Transport
    from .paper import ABORTED, PaperPipeline

    out = Path(cfg.out_dir)
    kv_tokens, kv_source = resolve_capacity(endpoint, cfg.kv_tokens)
    print(f"[pdl-batch] {label}: {endpoint} KV capacity {kv_tokens:,} tokens ({kv_source}); admission budget starts at "
          f"{int(kv_tokens * cfg.budget_fraction):,}" + ("" if cfg.fixed_budget else f" and follows KV use toward {cfg.budget_fraction:.0%}"),
          flush=True)
    transport = Transport(
        endpoint,
        budget_tokens=int(kv_tokens * cfg.budget_fraction),
        api_key=cfg.api_key,
        max_connections=cfg.papers_in_flight + 8,
        request_timeout=cfg.request_timeout,
        patience=cfg.patience,
        model_override=cfg.model,
    )
    failures = ShardWriter(out / FAILURES, label, index=True)
    pipeline = PaperPipeline(
        cfg.config_name,
        SnapshotInstrumentFinder(cfg.catalog),
        transport,
        results=ShardWriter(out / RESULTS, label, index=True),
        step1=ShardWriter(out / STEP1, label, index=True),
        failures=failures,
        calls=None if cfg.call_log == "off" else ShardWriter(out / CALLS, label, compress=cfg.call_log == "full"),
        call_log=cfg.call_log,
        max_step1_attempts=cfg.max_step1_attempts,
    )
    probe_lock = threading.Lock()

    def requeue(record) -> bool:
        while not stop.is_set():
            try:
                task_q.put(record, timeout=1)
                return True
            except queue.Full:
                continue
        return False

    def loop() -> None:
        while not stop.is_set():
            if not transport.healthy.is_set():
                # One thread probes; the rest wait rather than start papers on a dead endpoint.
                if probe_lock.acquire(blocking=False):
                    try:
                        if not transport.probe():
                            stop.wait(5)
                    finally:
                        probe_lock.release()
                else:
                    stop.wait(1)
                continue
            try:
                record = task_q.get(timeout=1)
            except queue.Empty:
                continue
            event_q.put(("start", label, record.bibcode))
            try:
                outcome = pipeline.run(record)
                status, reason = outcome.status, outcome.reason
            except Exception as e:
                failures.write({"bibcode": record.bibcode, "config": cfg.config_name, "reason": "runner_error",
                                "detail": traceback.format_exc()[-2000:]})
                status, reason = "failed", f"runner_error: {type(e).__name__}"
            if status == ABORTED:
                record.attempts += 1
                if record.attempts < cfg.max_paper_attempts and requeue(record):
                    event_q.put(("requeued", label, record.bibcode))
                    continue
                if record.attempts >= cfg.max_paper_attempts:
                    failures.write({"bibcode": record.bibcode, "config": cfg.config_name, "reason": "endpoint_down",
                                    "detail": reason or ""})
                    status = "failed"
                    reason = "endpoint_down"
                else:
                    # Stopping: leave the paper unfinished; the next run picks it up.
                    event_q.put(("dropped", label, record.bibcode))
                    continue
            event_q.put(("done", label, record.bibcode, status, reason))

    def report_usage() -> None:
        calls, prompt_tokens, completion_tokens = transport.usage.take()
        if calls:
            event_q.put(("usage", label, calls, prompt_tokens, completion_tokens))

    def steer() -> None:
        controller = BudgetController(transport.gate, target=cfg.budget_fraction)
        while not stop.wait(cfg.budget_interval):
            if not cfg.fixed_budget:
                text = fetch_metrics(endpoint, timeout=2.0)
                gauges = parse_gauges(text) if text else {}
                controller.update(gauges.get("kv"), gauges.get("waiting", 0))
            event_q.put(("gate", label, transport.gate.snapshot()))
            report_usage()

    threads = [threading.Thread(target=loop, name=f"{label}-t{i}", daemon=True) for i in range(cfg.papers_in_flight)]
    for t in threads:
        t.start()
    threading.Thread(target=steer, name=f"{label}-budget", daemon=True).start()
    stop.wait()
    transport.stopping.set()
    # A paper handed back to the queue that nobody will read must not hold up the exit.
    task_q.cancel_join_thread()
    deadline = time.monotonic() + cfg.grace
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    report_usage()
    pipeline.close()  # flushes the compressed call log
    transport.close()


class _Progress:
    def __init__(self, rate_window: float = 900.0):
        self.ok = self.failed = self.requeued = self.lost = 0
        self.prompt_tokens = self.completion_tokens = self.calls = 0
        self.reasons: Dict[str, int] = {}
        # Per worker: the papers it is running and when each started.
        self.inflight: Dict[str, Dict[str, float]] = {}
        self.gates: Dict[str, Dict[str, int]] = {}
        self.started = time.monotonic()
        self.rate_window = rate_window
        self._finished: deque = deque()  # when each paper inside the rate window finished
        # Set once the source has been counted: papers settled by earlier runs, and
        # papers this run has to process. Without them there is no percent or time left.
        self.already = 0
        self.todo: Optional[int] = None

    @property
    def settled(self) -> int:
        return self.ok + self.failed + self.lost

    def apply(self, event) -> None:
        kind, label = event[0], event[1]
        if kind == "gate":
            self.gates[label] = event[2]
            return
        if kind == "usage":
            # Sent as calls return, so these move while papers are still in flight.
            _, _, calls, prompt_tokens, completion_tokens = event
            self.calls += calls
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            return
        bibcode = event[2]
        flight = self.inflight.setdefault(label, {})
        if kind == "start":
            flight[bibcode] = time.monotonic()
        elif kind == "requeued":
            flight.pop(bibcode, None)
            self.requeued += 1
        elif kind == "dropped":
            flight.pop(bibcode, None)
            self.lost += 1
        elif kind == "done":
            flight.pop(bibcode, None)
            _, _, _, status, reason = event
            self._finished.append(time.monotonic())
            if status == "ok":
                self.ok += 1
            else:
                self.failed += 1
                key = (reason or "unknown").split(":")[0]
                self.reasons[key] = self.reasons.get(key, 0) + 1

    def recent_rate(self) -> float:
        """Papers per hour over the last ``rate_window`` seconds. The average since the
        start reads low for as long as the first papers are still in flight, and says
        nothing about now on a run that has been going for days."""
        now = time.monotonic()
        while self._finished and self._finished[0] < now - self.rate_window:
            self._finished.popleft()
        # At least a minute, so the first paper to finish does not read as thousands an hour.
        span = max(60.0, min(self.rate_window, now - self.started))
        return len(self._finished) * 3600 / span

    def oldest(self) -> Optional[Dict[str, Any]]:
        """The paper that has been in flight longest: one that is stuck, or just large."""
        found = None
        for label, flight in self.inflight.items():
            for bibcode, began in flight.items():
                if found is None or began < found[1]:
                    found = (bibcode, began, label)
        if found is None:
            return None
        return {"bibcode": found[0], "seconds": int(time.monotonic() - found[1]), "worker": found[2]}

    def summary(self) -> Dict:
        elapsed = max(time.monotonic() - self.started, 1e-6)
        recent = self.recent_rate()
        summary = {
            "ok": self.ok, "failed": self.failed, "unfinished": self.lost, "requeued": self.requeued,
            "failure_reasons": dict(self.reasons), "calls": self.calls,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "elapsed_seconds": round(elapsed, 1), "papers_per_hour": round((self.ok + self.failed) * 3600 / elapsed, 1),
            "recent_papers_per_hour": round(recent, 1),
            "in_flight": sum(len(s) for s in self.inflight.values()),
            "oldest_in_flight": self.oldest(),
        }
        if self.todo is not None:
            total = self.already + self.todo
            finished = self.already + self.ok + self.failed
            # Papers a stopping run left unfinished are not coming back in this run.
            remaining = max(0, self.todo - self.settled)
            summary.update({
                "total": total, "remaining": remaining,
                "percent": round(100 * finished / total, 1) if total else 100.0,
                "eta_seconds": int(remaining * 3600 / recent) if recent > 0 else None,
            })
        return summary


def _duration(seconds: float) -> str:
    days, minutes = divmod(int(seconds // 60), 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def _progress_line(s: Dict, gauges: str) -> str:
    line = f"[pdl-batch] done {s['ok']} failed {s['failed']} in-flight {s['in_flight']} | "
    if "total" in s:
        line += f"{s['percent']:.1f}% of {s['total']} | "
    line += f"{s['recent_papers_per_hour']:.0f} papers/hr"
    if s.get("remaining") and s.get("eta_seconds") is not None:
        line += f", about {_duration(s['eta_seconds'])} left"
    line += f" | calls {s['calls']} tok in/out {s['prompt_tokens'] / 1e6:.1f}M/{s['completion_tokens'] / 1e6:.1f}M"
    oldest = s.get("oldest_in_flight")
    if oldest:
        line += f" | oldest {oldest['bibcode']} {_duration(oldest['seconds'])}"
    return line + (f" | {gauges}" if gauges else "")


def _endpoint_gauges(endpoints: List[str], gates: List[Optional[Dict[str, int]]]) -> str:
    """Per endpoint: the server's running and waiting requests and KV use, then the
    runner's own gate (calls held back, and the budget in thousands of tokens)."""
    parts = []
    for i, ep in enumerate(endpoints):
        text = fetch_metrics(ep, timeout=2.0)
        if text is None:
            parts.append(f"ep{i} DOWN")
            continue
        g = parse_gauges(text)
        if g:
            part = f"ep{i} run {int(g.get('running', 0))} wait {int(g.get('waiting', 0))} kv {g.get('kv', 0) * 100:.0f}%"
            if gates[i]:
                part += f" held {gates[i]['waiting']} budget {gates[i]['budget'] / 1000:.0f}k"
            parts.append(part)
    return " | ".join(parts)


def run(cfg: RunConfig, on_stop=None) -> Dict:
    """Process every unsettled paper of the source. Returns the run summary.
    ``on_stop`` is called, from the signal handler, when a signal asks the run to stop."""
    if not cfg.endpoints:
        raise ValueError("At least one endpoint is required")
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Two runs appending to the same shard files would interleave lines.
    lock_file = open(out / f".lock-shard{cfg.shard_index}", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise RuntimeError(f"Another run is already writing shard {cfg.shard_index} of {out}")

    source = load_source(cfg.source, cfg.papers, cfg.source_options)
    state = RunState(out, cfg.config_name, retry_failed=cfg.retry_failed)
    n_workers = cfg.workers or len(cfg.endpoints)
    print(f"[pdl-batch] config {cfg.config_name} | {len(cfg.endpoints)} endpoint(s), {n_workers} worker(s) x "
          f"{cfg.papers_in_flight} papers | already done {len(state.done)}, failed {len(state.failed)}", flush=True)

    ctx = mp.get_context("spawn")
    task_q = ctx.Queue(maxsize=max(16, 2 * n_workers * cfg.papers_in_flight))
    event_q = ctx.Queue()
    stop = StopFlag(ctx)

    def spawn(i: int):
        label = f"s{cfg.shard_index}w{i:02d}"
        p = ctx.Process(target=worker_main, name=label,
                        args=(label, cfg.endpoints[i % len(cfg.endpoints)], cfg, task_q, event_q, stop))
        p.start()
        return label, p

    workers = dict(spawn(i) for i in range(n_workers))
    worker_index = {label: i for i, label in enumerate(workers)}

    submitted = [0]
    skipped = [0]
    feeder_done = threading.Event()

    def feed() -> None:
        seen: Set[str] = set()
        try:
            for record in source.iter_papers():
                if stop.is_set():
                    return
                if record.bibcode in seen or not in_shard(record.bibcode, cfg.shard_index, cfg.shard_count):
                    continue
                seen.add(record.bibcode)
                if state.settled(record.bibcode):
                    skipped[0] += 1
                    continue
                if cfg.limit is not None and submitted[0] >= cfg.limit:
                    break
                record.step1 = state.step1_for(record.bibcode)
                while not stop.is_set():
                    try:
                        task_q.put(record, timeout=1)
                        submitted[0] += 1
                        break
                    except queue.Full:
                        continue
        except Exception:
            logger.exception("Paper source failed; finishing the papers already queued")
        finally:
            feeder_done.set()

    threading.Thread(target=feed, name="feeder", daemon=True).start()

    progress = _Progress(cfg.rate_window)

    def count() -> None:
        """Work out how many papers this run has to process, for the percent done and
        the time left. Runs beside the feeder so a large source does not delay the start."""
        already = todo = 0
        if cfg.total is not None:
            already = sum(1 for b in state.done | state.failed if in_shard(b, cfg.shard_index, cfg.shard_count))
            todo = max(0, cfg.total - already)
        else:
            iter_ids = getattr(source, "iter_ids", None)
            if iter_ids is None:
                return
            seen: Set[str] = set()
            try:
                for bibcode in iter_ids():
                    if stop.is_set():
                        return
                    if bibcode in seen or not in_shard(bibcode, cfg.shard_index, cfg.shard_count):
                        continue
                    seen.add(bibcode)
                    if state.settled(bibcode):
                        already += 1
                    else:
                        todo += 1
            except Exception:
                logger.exception("Could not count the paper source; progress will show no total")
                return
        if cfg.limit is not None:
            todo = min(todo, cfg.limit)
        progress.already = already
        progress.todo = todo

    threading.Thread(target=count, name="counter", daemon=True).start()

    interrupted = [False]
    # Set once shutdown cannot be made any faster. From then on signals are ignored: an
    # interrupt landing in the cleanup would skip the rest of it.
    hold = [False]

    def on_signal(signum, _frame):
        if hold[0]:
            return
        if interrupted[0]:
            hold[0] = True  # before raising, so that this is raised once only
            raise KeyboardInterrupt
        interrupted[0] = True
        print(f"[pdl-batch] signal {signum}: no new papers; waiting up to {int(cfg.grace)}s for papers in flight "
              "(send again to stop now)", flush=True)
        stop.set()
        if on_stop is not None:
            on_stop()

    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {s: signal.signal(s, on_signal) for s in (signal.SIGINT, signal.SIGTERM)}

    last_print = time.monotonic()
    stop_deadline = None
    forced = False
    try:
        while True:
            try:
                progress.apply(event_q.get(timeout=1))
                while True:
                    progress.apply(event_q.get_nowait())
            except queue.Empty:
                pass

            for label, proc in list(workers.items()):
                if proc.is_alive() or stop.is_set():
                    continue
                # A worker died (crash or OOM kill). Its in-flight papers are unfinished for
                # this run; a rerun completes them. Replace the worker so the run continues.
                lost = progress.inflight.pop(label, {})
                progress.lost += len(lost)
                print(f"[pdl-batch] worker {label} exited with code {proc.exitcode}; "
                      f"{len(lost)} papers left unfinished; restarting it", flush=True)
                workers[label] = spawn(worker_index[label])[1]

            now = time.monotonic()
            if now - last_print >= cfg.progress_interval:
                last_print = now
                s = progress.summary()
                # With the default of one worker per endpoint, worker i is endpoint i's gate.
                by_index = {worker_index[label]: gate for label, gate in progress.gates.items()}
                gauges = _endpoint_gauges(cfg.endpoints, [by_index.get(i) for i in range(len(cfg.endpoints))])
                print(_progress_line(s, gauges), flush=True)
                _write_json(out / "progress.json", {**s, "gates": progress.gates, "submitted": submitted[0], "updated_at": _now()})

            if stop.is_set():
                # Workers give their papers `grace` seconds and then exit by themselves.
                # The deadline is for one that cannot (stuck on something a killed worker held).
                if stop_deadline is None:
                    stop_deadline = now + cfg.grace + 10
                if not any(p.is_alive() for p in workers.values()) or now > stop_deadline:
                    break
            elif feeder_done.is_set() and progress.settled >= submitted[0]:
                stop.set()
        hold[0] = True
    except KeyboardInterrupt:
        forced = True  # a second signal: stop now
    finally:
        hold[0] = True
        stop.set()
        stuck = [p for p in workers.values() if p.is_alive()]
        if stuck and not forced:
            print(f"[pdl-batch] {len(stuck)} worker(s) did not exit in time; stopping them", flush=True)
        for p in stuck:
            p.kill()  # workers ignore SIGTERM
        for p in workers.values():
            p.join(10)
        try:
            while True:
                progress.apply(event_q.get_nowait())
        except queue.Empty:
            pass
        # Papers still queued for workers that are gone would otherwise be flushed, to
        # nobody, when this process exits, and the exit would never finish.
        task_q.cancel_join_thread()
        for s, handler in previous.items():
            signal.signal(s, handler)

    summary = progress.summary()
    summary["unfinished"] = max(summary["unfinished"], submitted[0] - summary["ok"] - summary["failed"])
    summary.update({"submitted": submitted[0], "skipped_already_settled": skipped[0], "interrupted": interrupted[0],
                    "config": cfg.config_name, "finished_at": _now()})
    _write_json(out / "progress.json", {**summary, "gates": progress.gates, "updated_at": _now()})
    with open(out / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"summary": summary, "run_config": {k: v for k, v in asdict(cfg).items() if k != "api_key"}}) + "\n")
    print(f"[pdl-batch] finished: {summary['ok']} ok, {summary['failed']} failed, {summary['unfinished']} unfinished "
          f"in {summary['elapsed_seconds']:.0f}s ({summary['papers_per_hour']:.0f} papers/hr)", flush=True)
    lock_file.close()
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: Dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)
