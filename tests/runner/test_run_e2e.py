"""The whole runner against fake endpoints: real pipeline code and parsers, real worker
processes, no GPU."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

from paper_data_linking.runner.export import export, iter_usage_tuples, redact_normalized
from paper_data_linking.runner.scheduler import RunConfig, run
from paper_data_linking.runner.store import CALLS, FAILURES, RESULTS, read_shards

from .conftest import bibcode


def _config(tmp_path, endpoints, papers, catalog, **overrides):
    options = dict(out_dir=str(tmp_path / "out"), endpoints=endpoints, papers=papers, catalog=catalog,
                   papers_in_flight=6, progress_interval=1, patience=20, grace=10)
    options.update(overrides)
    return RunConfig(**options)


def _results(tmp_path):
    return list(read_shards(tmp_path / "out", RESULTS))


def test_two_endpoints_run_resume_and_export(tmp_path, fake_server, write_papers, catalog_path, snapshot, capsys):
    (url0, s0), (url1, s1) = fake_server(latency=0.01), fake_server(latency=0.01)
    papers = write_papers(24)
    cfg = _config(tmp_path, [url0, url1], papers, catalog_path, call_log="full")

    first = run(_config(tmp_path, [url0, url1], papers, catalog_path, call_log="full", limit=9))
    assert first["ok"] == 9 and first["unfinished"] == 0
    assert (first["total"], first["remaining"], first["percent"]) == (9, 0, 100.0)

    summary = run(cfg)
    assert (summary["ok"], summary["failed"], summary["unfinished"]) == (15, 0, 0)
    assert summary["skipped_already_settled"] == 9
    assert (summary["total"], summary["remaining"], summary["percent"]) == (24, 0, 100.0)  # 9 from the first run + 15
    results = _results(tmp_path)
    # Calls and tokens are reported by the workers as calls return, and add up to the papers' own counts.
    assert first["calls"] > 9 and summary["calls"] > 15
    assert first["calls"] + summary["calls"] == sum(r["stats"]["calls"] for r in results)
    assert first["completion_tokens"] + summary["completion_tokens"] == sum(r["stats"]["completion_tokens"] for r in results)
    assert Counter(r["bibcode"] for r in results) == Counter(bibcode(i) for i in range(24))  # each paper exactly once
    assert s0.state.requests > 0 and s1.state.requests > 0  # both endpoints took work

    by_code = {r["bibcode"]: r for r in results}
    two = by_code[bibcode(0)]["normalized_instrument_details"]["instruments"]
    assert {i["name"]["normalized"]["matched_instrument_code"] for i in two} == {"EIT", "AIA"}
    wind = by_code[bibcode(1)]["normalized_instrument_details"]["instruments"][0]["name"]["normalized"]
    assert (wind["data_system"], wind["matched_mission_code"], wind["matched_instrument_code"]) == ("cdaweb", "spase://Wind", "MFI")
    assert by_code[bibcode(2)]["normalized_instrument_details"]["instruments"] == []
    assert by_code[bibcode(3)]["stats"]["step1_attempts"] == 2  # the empty first answer was retried
    assert by_code[bibcode(0)]["versions"]["catalog"] == snapshot["content_hash"]

    # A third run has nothing to do.
    assert run(cfg)["submitted"] == 0

    # status counts from the index, and the index names every result.
    from paper_data_linking.runner.cli import main
    from paper_data_linking.runner.store import read_index

    assert {e["bibcode"] for e in read_index(tmp_path / "out", RESULTS)} == set(by_code)
    assert sorted(p.name for p in (tmp_path / "out" / "index").iterdir()) == ["failures", "results", "step1"]
    capsys.readouterr()
    assert main(["status", "--out", str(tmp_path / "out")]) == 0
    status = json.loads(capsys.readouterr().out)
    assert (status["results"], status["failures"]) == (24, 0) and status["last_run"]["total"] == 24

    # Exports.
    import io
    from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder

    out = io.StringIO()
    counts = export(str(tmp_path / "out"), "tuples", out)
    tuples = [json.loads(line) for line in out.getvalue().splitlines()]
    assert counts["papers"] == 24 and len(tuples) == 6 * 2 + 6 + 6  # per 4 papers: 2 + 1 + 0 + 1
    assert set(tuples[0]) == {"bibcode", "data_system", "mission_code", "instrument_code", "start", "end", "precision", "is_approximate"}
    out = io.StringIO()
    export(str(tmp_path / "out"), "du-tuples", out, finder=SnapshotInstrumentFinder(snapshot), config_label="x@1")
    row = json.loads(out.getvalue().splitlines()[0])
    assert row["cfg"] == "x@1" and row["window"] == '["2000-05-18 00:00:00+00","2000-05-19 23:59:59+00"]'
    out = io.StringIO()
    export(str(tmp_path / "out"), "redacted", out, allowlist={bibcode(0)})
    redacted = out.getvalue()
    assert redacted.count("\n") == 1 and "We used data from" not in redacted and "Synthetic" not in redacted
    assert len(list(iter_usage_tuples(json.loads(redacted)["normalized_instrument_details"]))) == 2

    # Replaying the recorded calls reproduces the run exactly.
    logs = ",".join(str(p) for p in sorted((tmp_path / "out" / CALLS).iterdir()))
    replay_url, replay_server = fake_server(mode="replay", replay=logs)
    replay_cfg = _config(tmp_path, [replay_url], papers, catalog_path, out_dir=str(tmp_path / "replay"), papers_in_flight=1)
    assert run(replay_cfg)["ok"] == 24 and replay_server.state.replay_misses == 0
    replayed = {r["bibcode"]: r for r in read_shards(tmp_path / "replay", RESULTS)}
    for code, result in by_code.items():
        assert replayed[code]["normalized_instrument_details"] == result["normalized_instrument_details"], code


def test_flaky_endpoint_still_finishes_every_paper(tmp_path, fake_server, write_papers, catalog_path):
    url, server = fake_server(fail_pct=15)
    summary = run(_config(tmp_path, [url], write_papers(12), catalog_path))
    assert (summary["ok"], summary["failed"], summary["unfinished"]) == (12, 0, 0)
    assert server.state.failures_injected > 0


def test_papers_on_a_dead_endpoint_move_to_a_live_one(tmp_path, fake_server, write_papers, catalog_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
    url, _ = fake_server()
    summary = run(_config(tmp_path, [dead, url], write_papers(12), catalog_path, patience=2))
    assert (summary["ok"], summary["failed"], summary["unfinished"]) == (12, 0, 0)
    assert summary["requeued"] > 0


def test_step1_that_never_recovers_is_recorded_as_a_failure(tmp_path, fake_server, catalog_path):
    papers = tmp_path / "papers.jsonl"
    papers.write_text(json.dumps({"bibcode": "2020Test..9999....A", "text": "FAKE_ALWAYS_EMPTY"}) + "\n"
                      + json.dumps({"bibcode": "2020Test..9998....A", "text": "  "}) + "\n")
    url, _ = fake_server()
    summary = run(_config(tmp_path, [url], str(papers), catalog_path))
    assert summary["failed"] == 2 and summary["failure_reasons"] == {"step1_broken": 1, "empty_text": 1}
    failures = {f["bibcode"]: f for f in read_shards(tmp_path / "out", FAILURES)}
    assert failures["2020Test..9999....A"]["detail"] == "empty after 3 attempts"
    assert run(_config(tmp_path, [url], str(papers), catalog_path))["submitted"] == 0  # failures are settled


def test_last_step1_attempt_runs_without_the_stop_sequence(tmp_path, fake_server, catalog_path):
    """A paper whose answer always opens with the stop sequence comes back empty every
    time; the final attempt drops the stop so the answer can be read."""
    papers = tmp_path / "papers.jsonl"
    papers.write_text(json.dumps({"bibcode": "2020Test..9997....A", "text": "FAKE_OPENS_WITH_SEPARATOR INSTRUMENTS: EIT on board SOHO"}) + "\n")
    url, _ = fake_server()
    summary = run(_config(tmp_path, [url], str(papers), catalog_path, call_log="full"))
    assert (summary["ok"], summary["failed"]) == (1, 0)
    assert _results(tmp_path)[0]["stats"]["step1_attempts"] == 3
    step1 = [c for c in read_shards(tmp_path / "out", CALLS) if c["call_type"] == "paper_analysis"]
    assert ["stop" in c["params"] for c in step1] == [True, True, False]


def test_runaway_reasoning_does_not_cost_the_paper_an_instrument(tmp_path, fake_server, catalog_path):
    papers = tmp_path / "papers.jsonl"
    papers.write_text(json.dumps({"bibcode": "2020Test..9996....A", "text": "Body. INSTRUMENTS: EIT on board SOHO FAKE_RUNAWAY_ONCE"}) + "\n")
    url, _ = fake_server()
    assert run(_config(tmp_path, [url], str(papers), catalog_path))["ok"] == 1
    result = _results(tmp_path)[0]
    assert result["stats"]["resamples"] >= 1
    assert result["normalized_instrument_details"]["instruments"][0]["name"]["normalized"]["matched_instrument_code"] == "EIT"


def test_budget_grows_when_the_server_under_reports_its_capacity(tmp_path, fake_server, write_papers, catalog_path):
    """The failure seen on a real L40S: the metrics gave two thirds of the true capacity,
    so the gate held calls back while the cache sat half empty."""
    url, _ = fake_server(latency=0.05, kv_tokens=10_000_000, kv_reported=20_000)
    cfg = _config(tmp_path, [url], write_papers(40), catalog_path, papers_in_flight=16, budget_interval=0.1)
    assert run(cfg)["ok"] == 40
    progress = json.loads((tmp_path / "out" / "progress.json").read_text())
    assert next(iter(progress["gates"].values()))["budget"] > 1.2 * 17_000

    fixed = _config(tmp_path, [url], write_papers(40), catalog_path, papers_in_flight=16, budget_interval=0.1,
                    fixed_budget=True, out_dir=str(tmp_path / "fixed"))
    assert run(fixed)["ok"] == 40
    progress = json.loads((tmp_path / "fixed" / "progress.json").read_text())
    assert next(iter(progress["gates"].values()))["budget"] == 17_000


def test_kill_9_mid_run_then_resume_processes_each_paper_once(tmp_path, fake_server, write_papers, catalog_path):
    url, _ = fake_server(latency=0.05)
    papers, out = write_papers(60), tmp_path / "out"
    cmd = [sys.executable, "-m", "paper_data_linking.runner.cli", "run", "--papers", papers, "--out", str(out),
           "--catalog", catalog_path, "--endpoints", url, "--papers-in-flight", "4", "--progress-interval", "1"]
    env = {**os.environ, "OPENAI_API_KEY": "test", "ADS_TOKEN": "test"}
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 120
    while len(list(read_shards(out, RESULTS))) < 5:
        assert time.monotonic() < deadline and proc.poll() is None, "run did not make progress"
        time.sleep(0.2)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    time.sleep(2.5)  # orphaned workers notice the dead parent within a second and exit
    done_before = len(list(read_shards(out, RESULTS)))
    assert 5 <= done_before < 60

    finished = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    assert finished.returncode == 0, finished.stdout[-2000:] + finished.stderr[-2000:]
    counts = Counter(r["bibcode"] for r in read_shards(out, RESULTS))
    assert set(counts) == {bibcode(i) for i in range(60)}
    assert max(counts.values()) == 1
    assert json.loads((out / "progress.json").read_text())["skipped_already_settled"] == done_before


def _wait_for_results(proc, out, n, timeout=120):
    deadline = time.monotonic() + timeout
    while len(list(read_shards(out, RESULTS))) < n:
        assert time.monotonic() < deadline and proc.poll() is None, "run did not make progress"
        time.sleep(0.2)


def _exit_code(proc, timeout=90):
    """The exit code, or a failure that names the hang instead of blocking the suite on it."""
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise AssertionError(f"the run was still going {timeout}s after it should have exited")


def _worker_pids(parent_pid):
    ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True, check=True).stdout
    rows = [line.split(None, 2) for line in ps.splitlines()]
    return [int(pid) for pid, ppid, command in (r for r in rows if len(r) == 3)
            if int(ppid) == parent_pid and "spawn_main" in command and "resource_tracker" not in command]


def test_run_still_ends_after_a_worker_is_killed(tmp_path, fake_server, write_papers, catalog_path):
    """What the kernel's out-of-memory killer does to a worker. The run replaces it and
    carries on, and must then be able to stop: with a multiprocessing.Event as the stop
    flag, the parent blocked for good waiting on the dead worker to acknowledge it."""
    url, _ = fake_server(latency=0.05)
    out, log = tmp_path / "out", tmp_path / "run.log"
    cmd = [sys.executable, "-m", "paper_data_linking.runner.cli", "run", "--papers", write_papers(60), "--out", str(out),
           "--catalog", catalog_path, "--endpoints", url, "--papers-in-flight", "4", "--progress-interval", "1"]
    env = {**os.environ, "OPENAI_API_KEY": "test", "ADS_TOKEN": "test"}
    proc = subprocess.Popen(cmd, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
    _wait_for_results(proc, out, 5)
    os.kill(_worker_pids(proc.pid)[0], signal.SIGKILL)

    assert _exit_code(proc) == 3, log.read_text()[-2000:]  # 3: the killed worker's papers are left for a rerun
    assert "exited with code -9" in log.read_text() and "restarting it" in log.read_text()
    summary = json.loads((out / "runs.jsonl").read_text().splitlines()[-1])["summary"]
    assert summary["ok"] + summary["unfinished"] == 60 and 0 < summary["unfinished"] <= 4

    finished = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    assert finished.returncode == 0, finished.stdout[-2000:] + finished.stderr[-2000:]
    assert Counter(r["bibcode"] for r in read_shards(out, RESULTS)) == Counter(bibcode(i) for i in range(60))


def test_stop_exits_with_full_size_papers_still_queued(tmp_path, fake_server, catalog_path):
    """Queued papers the workers will never read are larger than a pipe holds, so the
    parent's queue thread is blocked writing them when the run stops. Left alone, the
    interpreter waits for that thread at exit and the process never ends."""
    papers = tmp_path / "papers.jsonl"
    filler = "The solar wind was observed during the interval of interest. " * 1000  # ~60 KB, a real paper's size
    with open(papers, "w") as f:
        for i in range(300):
            f.write(json.dumps({"bibcode": bibcode(i), "text": f"{filler}Body. INSTRUMENTS: MFI on board Wind"}) + "\n")
    url, _ = fake_server(latency=0.05)
    out, log = tmp_path / "out", tmp_path / "run.log"
    cmd = [sys.executable, "-m", "paper_data_linking.runner.cli", "run", "--papers", str(papers), "--out", str(out),
           "--catalog", catalog_path, "--endpoints", url, "--papers-in-flight", "4", "--progress-interval", "1"]
    env = {**os.environ, "OPENAI_API_KEY": "test", "ADS_TOKEN": "test"}
    proc = subprocess.Popen(cmd, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
    _wait_for_results(proc, out, 5)
    proc.send_signal(signal.SIGTERM)  # to the runner alone, as `docker stop` sends it

    assert _exit_code(proc) == 3, log.read_text()[-2000:]
    summary = json.loads((out / "runs.jsonl").read_text().splitlines()[-1])["summary"]
    assert summary["interrupted"] and summary["unfinished"] > 0
    assert summary["ok"] == len(list(read_shards(out, RESULTS)))  # papers in flight were finished, not dropped


@pytest.mark.parametrize("signals", [1, 3])
def test_sigterm_to_the_whole_process_group_shuts_down_cleanly(tmp_path, write_papers, catalog_path, signals):
    """`timeout`, a job scheduler and systemd signal every process, not only the runner:
    the workers and the servers get it too. Three in quick succession is what `timeout`
    around `uv run` delivers."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        base_port = s.getsockname()[1]
    out, log = tmp_path / "out", tmp_path / "run.log"
    env = {**os.environ, "OPENAI_API_KEY": "test", "ADS_TOKEN": "test", "FAKE_VLLM_LATENCY": "0.05",
           "PDL_VLLM_CMD": f"{sys.executable} -m paper_data_linking.runner.fake_vllm serve"}
    cmd = [sys.executable, "-m", "paper_data_linking.runner.cli", "all", "--papers", write_papers(200), "--out", str(out),
           "--catalog", catalog_path, "--gpus", "0,1", "--base-port", str(base_port), "--papers-in-flight", "4",
           "--progress-interval", "1"]
    proc = subprocess.Popen(cmd, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
    _wait_for_results(proc, out, 5)
    for _ in range(signals):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):  # already gone (macOS reports a group of zombies as EPERM)
            break
        time.sleep(0.3)

    assert _exit_code(proc) == 3, log.read_text()[-3000:]
    text = log.read_text()
    assert "Traceback" not in text and "KeyboardInterrupt" not in text and "AssertionError" not in text, text[-3000:]
    assert "restarting in" not in text  # the supervisor did not bring back servers the signal stopped
    assert json.loads((out / "runs.jsonl").read_text().splitlines()[-1])["summary"]["interrupted"]
    for port in range(base_port, base_port + 2):  # servers are gone
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0


def test_all_mode_starts_a_replica_per_gpu_and_shuts_them_down(tmp_path, write_papers, catalog_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        base_port = s.getsockname()[1]
    out = tmp_path / "out"
    env = {**os.environ, "OPENAI_API_KEY": "test", "ADS_TOKEN": "test",
           "PDL_VLLM_CMD": f"{sys.executable} -m paper_data_linking.runner.fake_vllm serve", "FAKE_VLLM_STARTUP": "1"}
    cmd = [sys.executable, "-m", "paper_data_linking.runner.cli", "all", "--papers", write_papers(16), "--out", str(out),
           "--catalog", catalog_path, "--gpus", "0,1,2", "--base-port", str(base_port), "--papers-in-flight", "4",
           "--progress-interval", "1"]
    finished = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    assert finished.returncode == 0, finished.stdout[-3000:] + finished.stderr[-3000:]
    assert len(list(read_shards(out, RESULTS))) == 16
    logs = sorted(p.name for p in (out / "logs").iterdir())
    assert logs == ["vllm-gpu0.log", "vllm-gpu1.log", "vllm-gpu2.log"]
    first = (out / "logs" / "vllm-gpu1.log").read_text()
    assert "--speculative-config" in first and "--kv-cache-dtype fp8" in first and "GPU 1" in first
    for port in range(base_port, base_port + 3):  # replicas are gone
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0
