"""``pdl-batch``: run the paper pipeline against vLLM with files in and files out.

    pdl-batch all     start one vLLM per GPU, process the papers, shut down
    pdl-batch serve   only start and supervise the vLLM replicas
    pdl-batch run     only process papers, against endpoints that already exist
    pdl-batch status  progress of a run directory
    pdl-batch export  write shareable output from a run directory
    pdl-batch doctor  preflight checks

Every option also reads a PDL_* environment variable, which is the convenient form
in a container. A second ``run`` or ``all`` on the same output directory resumes.
"""

import argparse
import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__


def _env(name: str, default=None):
    return os.environ.get(f"PDL_{name}", default)


def _csv(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--papers", default=_env("PAPERS"), help="Paper text: a .jsonl/.jsonl.gz file or a directory [PDL_PAPERS]")
    p.add_argument("--source", default=_env("SOURCE", "jsonl"),
                   help="jsonl | dir | package.module:factory for a custom source (default jsonl) [PDL_SOURCE]")
    p.add_argument("--source-option", action="append", default=[], metavar="KEY=VALUE",
                   help="Keyword argument passed to the source; repeatable")
    p.add_argument("--out", default=_env("OUT", "out"), help="Output directory; rerun with the same one to resume [PDL_OUT]")
    p.add_argument("--config", default=_env("CONFIG", "vllm-gemma4-batch"), help="LLM configuration name [PDL_CONFIG]")
    p.add_argument("--catalog", default=_env("CATALOG_SNAPSHOT"), help="Catalog snapshot file [PDL_CATALOG_SNAPSHOT]")
    p.add_argument("--papers-in-flight", type=int, default=int(_env("PAPERS_IN_FLIGHT", 128)),
                   help="Papers processed concurrently per endpoint (default 128)")
    p.add_argument("--workers", type=int, default=None, help="Worker processes (default: one per endpoint)")
    p.add_argument("--kv-tokens", type=int, default=int(_env("KV_TOKENS", 0)) or None,
                   help="KV-cache capacity per endpoint in tokens, the starting point for admission "
                        "(default: read from the server, else 965000)")
    p.add_argument("--budget-fraction", type=float, default=float(_env("BUDGET_FRACTION", 0.85)),
                   help="How full to keep each server's KV cache (default 0.85)")
    p.add_argument("--fixed-budget", action="store_true", default=_env("FIXED_BUDGET", "") not in ("", "0"),
                   help="Admit against budget-fraction x kv-tokens and never adjust it to the server's KV use [PDL_FIXED_BUDGET]")
    p.add_argument("--call-log", choices=("off", "meta", "full"), default=_env("CALL_LOG", "meta"),
                   help="Per-call log: off, meta (sizes and timings) or full (prompts and answers, gzip)")
    p.add_argument("--limit", type=int, default=None, help="Process at most this many papers")
    p.add_argument("--total", type=int, default=int(_env("TOTAL", 0)) or None,
                   help="Papers in this run's share of the source, for the percent done and time left. "
                        "Only needed when the source cannot be counted, or to skip counting it [PDL_TOTAL]")
    p.add_argument("--shard", default=_env("SHARD", "0/1"), metavar="I/N",
                   help="Process only shard I of N (by bibcode hash), for splitting one input across machines")
    p.add_argument("--retry-failed", action="store_true", help="Process papers again that a previous run recorded as failed")
    p.add_argument("--request-timeout", type=float, default=float(_env("REQUEST_TIMEOUT", 3600)))
    p.add_argument("--patience", type=float, default=float(_env("PATIENCE", 900)),
                   help="Seconds to keep retrying an endpoint that is not answering (default 900)")
    p.add_argument("--progress-interval", type=float, default=float(_env("PROGRESS_INTERVAL", 30)))
    p.add_argument("--log-level", default=_env("LOG_LEVEL", "WARNING"))


def _add_endpoint_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--endpoints", default=_env("ENDPOINTS"),
                   help="Comma-separated OpenAI-compatible base URLs, e.g. http://localhost:8000,http://localhost:8001 [PDL_ENDPOINTS]")
    p.add_argument("--api-key", default=_env("API_KEY", "EMPTY"), help="[PDL_API_KEY]")
    p.add_argument("--model", default=_env("SERVED_MODEL"), help="Model name to request (default: from the configuration)")


def _add_serve_args(p: argparse.ArgumentParser) -> None:
    from .serve import ServeConfig

    d = ServeConfig()
    p.add_argument("--gpus", default=_env("GPUS"), help="Comma-separated GPU indices (default: every free GPU) [PDL_GPUS]")
    p.add_argument("--include-busy-gpus", action="store_true", help="Also use GPUs that already have memory in use")
    p.add_argument("--fake-gpus", type=int, default=int(_env("FAKE_GPUS", 0)), metavar="N",
                   help="Dry run: start N built-in fake servers in place of vLLM; no GPU or model needed [PDL_FAKE_GPUS]")
    p.add_argument("--weights", default=_env("MODEL", d.model), help=f"Model to serve (default {d.model}) [PDL_MODEL]")
    p.add_argument("--served-model-name", default=_env("SERVED_MODEL", d.served_model_name))
    p.add_argument("--drafter", default=_env("DRAFTER", d.drafter),
                   help="MTP drafter model for speculative decoding; empty string disables it [PDL_DRAFTER]")
    p.add_argument("--max-model-len", type=int, default=int(_env("MAX_MODEL_LEN", d.max_model_len)))
    p.add_argument("--gpu-memory-utilization", type=float, default=float(_env("GPU_MEMORY_UTILIZATION", d.gpu_memory_utilization)))
    p.add_argument("--max-num-seqs", type=int, default=int(_env("MAX_NUM_SEQS", d.max_num_seqs)))
    p.add_argument("--host", default=_env("HOST", d.host))
    p.add_argument("--base-port", type=int, default=int(_env("BASE_PORT", d.base_port)))
    p.add_argument("--vllm-cmd", default=_env("VLLM_CMD", "vllm serve"), help="Command that starts a server [PDL_VLLM_CMD]")
    p.add_argument("--vllm-extra-args", default=_env("VLLM_EXTRA_ARGS", ""), help="Extra arguments appended to every server [PDL_VLLM_EXTRA_ARGS]")
    p.add_argument("--startup-timeout", type=float, default=float(_env("STARTUP_TIMEOUT", d.startup_timeout)))


def _serve_config(args, log_dir: str):
    from .serve import ServeConfig

    if args.fake_gpus:
        args.vllm_cmd = shlex.join([sys.executable, "-m", "paper_data_linking.runner.fake_vllm", "serve"])
        args.gpus = ",".join(str(i) for i in range(args.fake_gpus))
    return ServeConfig(
        model=args.weights,
        served_model_name=args.served_model_name,
        drafter=args.drafter or None,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_num_seqs=args.max_num_seqs,
        host=args.host,
        base_port=args.base_port,
        api_key=None if getattr(args, "api_key", "EMPTY") == "EMPTY" else args.api_key,
        gpus=[int(g) for g in _csv(args.gpus)] or None,
        include_busy_gpus=args.include_busy_gpus,
        extra_args=shlex.split(args.vllm_extra_args),
        vllm_cmd=shlex.split(args.vllm_cmd),
        log_dir=log_dir,
        startup_timeout=args.startup_timeout,
    )


def _run_config(args, endpoints: List[str]):
    from .scheduler import RunConfig

    try:
        shard_index, shard_count = (int(x) for x in args.shard.split("/"))
        assert 0 <= shard_index < shard_count
    except Exception:
        raise SystemExit(f"--shard must look like I/N with 0 <= I < N, got '{args.shard}'")
    options = {}
    for item in args.source_option:
        key, _, value = item.partition("=")
        options[key] = value
    return RunConfig(
        out_dir=args.out, endpoints=endpoints, source=args.source, papers=args.papers, source_options=options,
        config_name=args.config, catalog=args.catalog, papers_in_flight=args.papers_in_flight, workers=args.workers,
        kv_tokens=args.kv_tokens, budget_fraction=args.budget_fraction, fixed_budget=args.fixed_budget,
        call_log=args.call_log, api_key=args.api_key,
        model=getattr(args, "model", None), request_timeout=args.request_timeout, patience=args.patience,
        limit=args.limit, total=args.total, shard_index=shard_index, shard_count=shard_count, retry_failed=args.retry_failed,
        progress_interval=args.progress_interval, log_level=args.log_level,
    )


def _sigterm_as_interrupt() -> None:
    """Let `docker stop` unwind through the same cleanup as Ctrl-C, so the vLLM
    processes this command started are not left holding the GPUs."""
    def handler(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, handler)


def _stop_replicas(replicas) -> None:
    """Stop the servers and see it through. A signal arriving in the middle would
    otherwise end the stop before it kills a server that ignored the request to exit."""
    for _ in range(3):
        try:
            previous = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}
            break
        except KeyboardInterrupt:
            continue
    else:
        previous = {}
    try:
        replicas.stop()
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def _exit_code(summary) -> int:
    # 0: everything settled. 3: stopped or lost papers; rerun the same command to finish.
    return 3 if summary["unfinished"] or summary["interrupted"] else 0


def cmd_run(args) -> int:
    from .scheduler import run

    endpoints = _csv(args.endpoints)
    if not endpoints:
        raise SystemExit("--endpoints (or PDL_ENDPOINTS) is required for `run`; use `all` to start vLLM too")
    return _exit_code(run(_run_config(args, endpoints)))


def cmd_serve(args) -> int:
    from .serve import ReplicaSet

    _sigterm_as_interrupt()
    replicas = ReplicaSet(_serve_config(args, args.log_dir))
    replicas.start()
    try:
        replicas.wait_healthy()
        print("[pdl-batch] endpoints: " + ",".join(replicas.endpoints), flush=True)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        _stop_replicas(replicas)
    return 0


def cmd_all(args) -> int:
    from .scheduler import run
    from .serve import ReplicaSet

    _sigterm_as_interrupt()
    replicas = ReplicaSet(_serve_config(args, str(Path(args.out) / "logs")))
    replicas.start()
    try:
        replicas.wait_healthy()
        if not args.model:
            args.model = args.served_model_name
        return _exit_code(run(_run_config(args, replicas.endpoints), on_stop=replicas.stand_down))
    except KeyboardInterrupt:
        return 3
    finally:
        _stop_replicas(replicas)


def cmd_status(args) -> int:
    from .store import FAILURES, RESULTS, read_index

    out = Path(args.out)
    # Counted the way a resumed run counts them: per configuration, each paper once, and
    # a failure that a later run turned into a result is a result.
    done = {}
    for entry in read_index(out, RESULTS):
        done.setdefault(entry.get("config"), set()).add(entry["bibcode"])
    failed = {}
    for entry in read_index(out, FAILURES):
        if entry["bibcode"] not in done.get(entry.get("config"), ()):
            failed.setdefault(entry.get("config"), {})[entry["bibcode"]] = entry.get("reason") or "unknown"

    def tally(configs):
        reasons = {}
        for config in configs:
            for reason in failed.get(config, {}).values():
                reasons[reason] = reasons.get(reason, 0) + 1
        return {"results": sum(len(done.get(c, ())) for c in configs), "failures": sum(reasons.values()),
                "failure_reasons": reasons}

    configs = sorted(set(done) | set(failed), key=str)
    report = tally(configs)
    if len(configs) > 1:
        report["by_config"] = {str(config): tally([config]) for config in configs}
    progress = out / "progress.json"
    if progress.exists():
        report["last_run"] = json.loads(progress.read_text(encoding="utf-8"))
    print(json.dumps(report, indent=1))
    return 0


def cmd_export(args) -> int:
    from .export import export, load_allowlist, load_paper_ids

    finder = None
    if args.level == "du-tuples":
        from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder

        finder = SnapshotInstrumentFinder(args.catalog)
    stream = open(args.to, "w", encoding="utf-8") if args.to else sys.stdout
    try:
        counts = export(args.out, args.level, stream, config_name=args.config, allowlist=load_allowlist(args.allowlist),
                        finder=finder, paper_ids=load_paper_ids(args.paper_ids), config_label=args.label)
    finally:
        if args.to:
            stream.close()
    print(json.dumps(counts), file=sys.stderr)
    return 0


def cmd_doctor(args) -> int:
    """Check the pieces a run needs before spending GPU time on it."""
    from paper_data_linking.config.settings import get_llm_configuration
    from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder

    from .admission import fetch_metrics, parse_kv_capacity
    from .client import CallRecorder, EndpointDown, Transport, VLLMClient, served_model_name

    ok = True

    def check(label: str, fn) -> None:
        nonlocal ok
        try:
            print(f"  ok    {label}: {fn()}")
        except Exception as e:
            ok = False
            print(f"  FAIL  {label}: {type(e).__name__}: {e}")

    print(f"pdl-batch {__version__}")
    config = None

    def load_config():
        nonlocal config
        config = get_llm_configuration(args.config)
        return f"{args.config} -> {config.paper_analysis.model}"

    check("configuration", load_config)

    def load_catalog():
        finder = SnapshotInstrumentFinder(args.catalog)
        return (f"{len(finder.catalog)} instruments, {len(finder.get_unique_missions())} missions, "
                f"data systems {finder.get_available_data_systems()}, exported {finder.exported_at}, hash {finder.version[:12]}")

    check("catalog snapshot", load_catalog)
    if args.papers:
        from .sources import load_source

        def first_paper():
            record = next(iter(load_source(args.source, args.papers).iter_papers()))
            return f"first paper {record.bibcode}, {len(record.text):,} characters"

        check("paper source", first_paper)
    for endpoint in _csv(args.endpoints):
        def smoke(endpoint=endpoint):
            text = fetch_metrics(endpoint)
            kv = parse_kv_capacity(text) if text else None
            transport = Transport(endpoint, budget_tokens=10_000, api_key=args.api_key, patience=5, request_timeout=120,
                                  model_override=args.model)
            try:
                model = config.normalization.cadence.model if config else "unknown"
                response = VLLMClient(transport, CallRecorder("doctor", None, "off")).completion(
                    "doctor", model, [{"role": "user", "content": "Reply with the single word: ready"}],
                    temperature=0.0, max_tokens=512,
                    extra_body=config.normalization.cadence.extra_body if config else None,
                )
            except EndpointDown as e:  # a BaseException by design; report it like any failure
                raise RuntimeError(str(e)) from None
            finally:
                transport.close()
            answer = (response.choices[0].message.content or "").strip()[:40]
            return (f"model {args.model or served_model_name(model)} answered {answer!r}; "
                    f"KV capacity {kv if kv else 'not reported'}")

        check(f"endpoint {endpoint}", smoke)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdl-batch", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"pdl-batch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="Process papers against existing endpoints")
    _add_run_args(p)
    _add_endpoint_args(p)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("serve", help="Start and supervise one vLLM replica per GPU")
    _add_serve_args(p)
    p.add_argument("--api-key", default=_env("API_KEY", "EMPTY"))
    p.add_argument("--log-dir", default=_env("LOG_DIR", "logs"))
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("all", help="Start vLLM on every GPU, process the papers, shut down")
    _add_run_args(p)
    _add_serve_args(p)
    p.add_argument("--api-key", default=_env("API_KEY", "EMPTY"))
    p.add_argument("--model", default=None, help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_all)

    p = sub.add_parser("status", help="Progress of a run directory")
    p.add_argument("--out", default=_env("OUT", "out"))
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("export", help="Write shareable output from a run directory")
    p.add_argument("--out", default=_env("OUT", "out"))
    p.add_argument("--level", choices=("tuples", "redacted", "full", "du-tuples"), default="tuples")
    p.add_argument("--to", help="Output file (default: stdout)")
    p.add_argument("--config", default=None, help="Only results of this configuration")
    p.add_argument("--allowlist", help="File of bibcodes, one per line; only these papers are exported")
    p.add_argument("--catalog", default=_env("CATALOG_SNAPSHOT"), help="Catalog snapshot (du-tuples)")
    p.add_argument("--paper-ids", help="JSON map between bibcodes and paper ids (du-tuples)")
    p.add_argument("--label", help="Configuration label to write in du-tuples rows")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("doctor", help="Preflight checks: configuration, catalog, paper source, endpoints")
    p.add_argument("--config", default=_env("CONFIG", "vllm-gemma4-batch"))
    p.add_argument("--catalog", default=_env("CATALOG_SNAPSHOT"))
    p.add_argument("--papers", default=_env("PAPERS"))
    p.add_argument("--source", default=_env("SOURCE", "jsonl"))
    _add_endpoint_args(p)
    p.set_defaults(fn=cmd_doctor)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
