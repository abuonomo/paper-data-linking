"""Starts and supervises one vLLM server per GPU.

Independent single-GPU replicas, not one tensor-parallel server: on PCIe-only L40S
boxes a TP=4 server measured ~140 papers/hr per GPU against ~500 for a single-GPU
replica, and a replica is the unit that can be tested on one GPU and repeated.

The default flags are the recipe measured on L40S for Gemma 4 26B-A4B (FP8 weights,
FP8 KV cache, MTP drafter). Every one can be overridden; see ``ServeConfig``.
"""

import json
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ServeConfig:
    model: str = "RedHatAI/gemma-4-26B-A4B-it-FP8-dynamic"
    served_model_name: str = "google/gemma-4-26B-A4B-it"
    drafter: Optional[str] = "google/gemma-4-26B-A4B-it-assistant"
    num_speculative_tokens: int = 4
    max_model_len: int = 160000
    gpu_memory_utilization: float = 0.92
    max_num_seqs: int = 128
    kv_cache_dtype: Optional[str] = "fp8"
    reasoning_parser: Optional[str] = "gemma4"
    host: str = "127.0.0.1"
    base_port: int = 8000
    api_key: Optional[str] = None
    gpus: Optional[List[int]] = None
    include_busy_gpus: bool = False
    extra_args: List[str] = field(default_factory=list)
    vllm_cmd: List[str] = field(default_factory=lambda: ["vllm", "serve"])
    log_dir: str = "logs"
    startup_timeout: float = 2400.0


def discover_gpus(explicit: Optional[List[int]] = None, include_busy: bool = False) -> List[int]:
    """GPU indices to use: the explicit list, else every GPU that is not already in
    use by something else (shared machines)."""
    if explicit:
        return list(explicit)
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"Could not list GPUs with nvidia-smi ({e}). Pass --gpus to name them.") from e
    gpus = []
    for line in out.strip().splitlines():
        index, total, used = (int(x.strip()) for x in line.split(","))
        if not include_busy and used > 0.1 * total:
            logger.warning("Skipping GPU %d: %d of %d MiB already in use (pass --include-busy-gpus to use it)", index, used, total)
            continue
        gpus.append(index)
    if not gpus:
        raise RuntimeError("No free GPUs found")
    return gpus


def build_command(cfg: ServeConfig, port: int) -> List[str]:
    cmd = list(cfg.vllm_cmd) + [
        cfg.model,
        "--served-model-name", cfg.served_model_name,
        "--host", cfg.host,
        "--port", str(port),
        "--max-model-len", str(cfg.max_model_len),
        "--gpu-memory-utilization", str(cfg.gpu_memory_utilization),
        "--max-num-seqs", str(cfg.max_num_seqs),
        # Gemma 4 is multimodal; text-only use skips the vision encoder's memory reservation.
        "--limit-mm-per-prompt", json.dumps({"image": 0, "video": 0}),
        "--enable-prefix-caching",
    ]
    if cfg.reasoning_parser:
        cmd += ["--reasoning-parser", cfg.reasoning_parser]
    if cfg.kv_cache_dtype:
        cmd += ["--kv-cache-dtype", cfg.kv_cache_dtype]
    if cfg.drafter:
        cmd += ["--speculative-config", json.dumps({"model": cfg.drafter, "num_speculative_tokens": cfg.num_speculative_tokens})]
    if cfg.api_key:
        cmd += ["--api-key", cfg.api_key]
    return cmd + list(cfg.extra_args)


def _die_with_parent() -> None:
    """Linux: have the kernel terminate a server whose launcher was killed, so it does
    not keep holding a GPU. (Elsewhere, and in a container, this is not needed.)"""
    try:
        import ctypes
        import signal
        PR_SET_PDEATHSIG = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass


def _healthy(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(endpoint + "/health", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


class ReplicaSet:
    """One server process per GPU, restarted if it exits."""

    def __init__(self, cfg: ServeConfig):
        self.cfg = cfg
        self.gpus = discover_gpus(cfg.gpus, cfg.include_busy_gpus)
        self.endpoints = [f"http://{cfg.host}:{cfg.base_port + i}" for i in range(len(self.gpus))]
        self._procs: Dict[int, subprocess.Popen] = {}
        self._restarts: Dict[int, int] = {}
        self._stopping = threading.Event()
        self._standing_down = threading.Event()
        self._supervisor: Optional[threading.Thread] = None
        Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)

    def _log_path(self, slot: int) -> Path:
        return Path(self.cfg.log_dir) / f"vllm-gpu{self.gpus[slot]}.log"

    def _launch(self, slot: int) -> None:
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = str(self.gpus[slot])
        # Weights come from a mounted cache; a server must never stall on a download.
        env.setdefault("HF_HUB_OFFLINE", "1")
        cmd = build_command(self.cfg, self.cfg.base_port + slot)
        log = open(self._log_path(slot), "ab")
        log.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} starting: {shlex.join(cmd)}\n".encode())
        log.flush()
        self._procs[slot] = subprocess.Popen(
            cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=_die_with_parent if sys.platform == "linux" else None,
        )

    def start(self) -> None:
        print(f"[pdl-batch] starting {len(self.gpus)} vLLM replica(s) on GPU(s) {self.gpus}; logs in {self.cfg.log_dir}/", flush=True)
        for slot in range(len(self.gpus)):
            self._launch(slot)
        self._supervisor = threading.Thread(target=self._supervise, name="vllm-supervisor", daemon=True)
        self._supervisor.start()

    def stand_down(self) -> None:
        """Stop restarting servers that exit: the run is shutting down, and the signal
        that asked it to may have reached the servers as well. Safe in a signal handler."""
        self._standing_down.set()

    def _supervise(self) -> None:
        while not self._stopping.wait(5):
            for slot, proc in list(self._procs.items()):
                if proc.poll() is None or self._standing_down.is_set():
                    continue
                n = self._restarts.get(slot, 0)
                backoff = min(10 * 2 ** n, 300)
                print(f"[pdl-batch] vLLM on GPU {self.gpus[slot]} exited with code {proc.returncode}; "
                      f"restarting in {backoff}s (see {self._log_path(slot)})", flush=True)
                if self._stopping.wait(backoff):
                    return
                if self._standing_down.is_set():
                    break
                self._restarts[slot] = n + 1
                self._launch(slot)

    def wait_healthy(self, timeout: Optional[float] = None) -> None:
        """Block until every replica answers its health check."""
        deadline = time.monotonic() + (timeout or self.cfg.startup_timeout)
        pending = set(range(len(self.gpus)))
        while pending:
            for slot in sorted(pending):
                if _healthy(self.endpoints[slot]):
                    pending.discard(slot)
                    print(f"[pdl-batch] vLLM on GPU {self.gpus[slot]} is up at {self.endpoints[slot]}", flush=True)
            if not pending:
                return
            if time.monotonic() > deadline:
                self.stop()
                raise RuntimeError(
                    "vLLM did not come up on GPU(s) "
                    f"{[self.gpus[s] for s in sorted(pending)]}; see {self.cfg.log_dir}/vllm-gpu*.log"
                )
            if self._stopping.wait(5):
                raise RuntimeError("Stopped while waiting for vLLM to start")

    def stop(self) -> None:
        self._stopping.set()
        for proc in self._procs.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in self._procs.values():
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
