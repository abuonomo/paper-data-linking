import gzip
import json
import threading
import time

import pytest

from paper_data_linking.runner.admission import BudgetController, CallEstimator, TokenGate, parse_gauges, parse_kv_capacity
from paper_data_linking.runner import store
from paper_data_linking.runner.scheduler import _Progress, _progress_line, in_shard
from paper_data_linking.runner.sources import DirSource, JsonlSource, load_source
from paper_data_linking.runner.step1_checks import step1_problem
from paper_data_linking.runner.store import FAILURES, RESULTS, STEP1, RunState, ShardWriter, index_path, read_index, read_shards


def test_resume_survives_a_torn_last_line(tmp_path):
    w = ShardWriter(tmp_path / RESULTS, "s0w00")
    w.write({"bibcode": "A", "config": "c"})
    w.close()
    with open(w.path, "ab") as f:
        f.write(b'{"bibcode": "B", "config": "c", "instruments_det')  # killed mid-write
    w = ShardWriter(tmp_path / RESULTS, "s0w00")
    w.write({"bibcode": "C", "config": "c"})
    w.close()
    assert [r["bibcode"] for r in read_shards(tmp_path, RESULTS)] == ["A", "C"]
    state = RunState(tmp_path, "c")
    assert state.settled("A") and state.settled("C") and not state.settled("B")
    assert RunState(tmp_path, "other-config").done == set()


def test_step1_checkpoint_is_offered_only_for_unfinished_papers(tmp_path):
    ShardWriter(tmp_path / STEP1, "w").write({"bibcode": "A", "config": "c", "instruments_details": "form A"})
    ShardWriter(tmp_path / STEP1, "w2").write({"bibcode": "B", "config": "c", "instruments_details": "form B"})
    ShardWriter(tmp_path / RESULTS, "w").write({"bibcode": "A", "config": "c"})
    state = RunState(tmp_path, "c")
    assert state.step1_for("A") is None and state.step1_for("B") == "form B"


def test_failed_papers_are_skipped_unless_retried(tmp_path):
    ShardWriter(tmp_path / "failures", "w").write({"bibcode": "A", "config": "c", "reason": "step1_broken"})
    assert RunState(tmp_path, "c").settled("A")
    assert not RunState(tmp_path, "c", retry_failed=True).settled("A")


def test_indexed_shards_are_read_without_parsing_their_records(tmp_path, monkeypatch):
    results = ShardWriter(tmp_path / RESULTS, "w", index=True)
    results.write({"bibcode": "A", "config": "c", "normalized_instrument_details": {"big": "x" * 5000}})
    results.write({"bibcode": "B", "config": "other"})
    ShardWriter(tmp_path / FAILURES, "w", index=True).write({"bibcode": "C", "config": "c", "reason": "step1_broken"})
    step1 = ShardWriter(tmp_path / STEP1, "w", index=True)
    step1.write({"bibcode": "A", "config": "c", "instruments_details": "form A"})
    step1.write({"bibcode": "D", "config": "c", "instruments_details": "form D é"})

    scanned = []
    real_scan = store._scan
    monkeypatch.setattr(store, "_scan", lambda shard, start=0: scanned.append(shard) or real_scan(shard, start))
    state = RunState(tmp_path, "c")
    assert state.done == {"A"} and state.failed == {"C"}
    assert state.step1_for("D") == "form D é" and state.step1_for("A") is None
    assert [e["reason"] for e in read_index(tmp_path, FAILURES)] == ["step1_broken"]
    assert scanned == []  # everything came from the index


def test_index_catches_up_with_records_it_missed(tmp_path):
    """Killed between writing a result and its index line, or a directory from before
    the index existed: the next writer indexes what is missing, and until then readers
    take the uncovered part from the shard itself."""
    w = ShardWriter(tmp_path / RESULTS, "w", index=True)
    w.write({"bibcode": "A", "config": "c"})
    w.close()
    with open(w.path, "ab") as f:
        f.write(b'{"bibcode": "B", "config": "c"}\n{"bibcode": "C", "config": "c", "instr')  # B unindexed, C torn
    assert RunState(tmp_path, "c").done == {"A", "B"}

    w = ShardWriter(tmp_path / RESULTS, "w", index=True)
    w.write({"bibcode": "D", "config": "c"})
    w.close()
    indexed = [json.loads(line) for line in index_path(w.path).read_text().splitlines()]
    assert [e["bibcode"] for e in indexed if "bibcode" in e] == ["A", "B", "D"]
    raw = w.path.read_bytes()
    assert all(json.loads(raw[e["start"]:e["end"]])["bibcode"] == e["bibcode"] for e in indexed if "bibcode" in e)
    assert RunState(tmp_path, "c").done == {"A", "B", "D"}

    # No index at all, as a run directory written by an earlier version has.
    index_path(w.path).unlink()
    assert RunState(tmp_path, "c").done == {"A", "B", "D"}
    ShardWriter(tmp_path / RESULTS, "w", index=True).close()
    assert len(index_path(w.path).read_text().splitlines()) == 4  # three records and the covered-to marker


def test_index_that_does_not_match_its_shard_is_ignored(tmp_path):
    w = ShardWriter(tmp_path / RESULTS, "w", index=True)
    for code in "ABC":
        w.write({"bibcode": code, "config": "c"})
    w.close()
    w.path.write_text(json.dumps({"bibcode": "Z", "config": "c"}) + "\n")  # shard replaced by a shorter one
    assert RunState(tmp_path, "c").done == {"Z"}
    ShardWriter(tmp_path / RESULTS, "w", index=True).close()
    assert [json.loads(line).get("bibcode") for line in index_path(w.path).read_text().splitlines()] == ["Z", None]


def test_progress_counts_calls_as_they_return_and_reports_total_rate_and_oldest():
    p = _Progress(rate_window=900)
    assert "total" not in p.summary() and p.summary()["oldest_in_flight"] is None
    for code in ("A", "B", "C"):
        p.apply(("start", "w0", code))
    p.inflight["w0"]["B"] -= 1500  # B has been running for 25 minutes
    p.apply(("usage", "w0", 7, 9000, 1200))
    s = p.summary()
    assert (s["ok"], s["calls"], s["prompt_tokens"], s["completion_tokens"]) == (0, 7, 9000, 1200)  # nothing finished yet
    assert s["oldest_in_flight"]["bibcode"] == "B" and 1500 <= s["oldest_in_flight"]["seconds"] < 1510

    p.started -= 3600  # an hour in
    p.already, p.todo = 100, 300
    p.apply(("done", "w0", "A", "ok", None))
    p.apply(("done", "w0", "C", "failed", "step1_broken: empty"))
    p._finished.extendleft([time.monotonic() - 2000] * 50)  # finished before the 15-minute window: not in the rate
    s = p.summary()
    assert (s["total"], s["remaining"], s["percent"]) == (400, 298, 25.5)
    assert s["recent_papers_per_hour"] == 8.0 and s["eta_seconds"] == 298 * 450
    assert s["failure_reasons"] == {"step1_broken": 1}
    line = _progress_line(s, "ep0 run 3 wait 0 kv 80%")
    assert line == ("[pdl-batch] done 1 failed 1 in-flight 1 | 25.5% of 400 | 8 papers/hr, about 1d13h left | "
                    "calls 7 tok in/out 0.0M/0.0M | oldest B 25m | ep0 run 3 wait 0 kv 80%")


def test_sources_list_ids_matching_the_papers_they_yield(tmp_path):
    (tmp_path / "a.jsonl").write_text(json.dumps({"bibcode": "A", "text": "ta"}) + "\nnot json\n"
                                      + json.dumps({"bibcode": "B"}) + "\n" + json.dumps({"bibcode": "C", "text": "tc"}) + "\n")
    source = JsonlSource(str(tmp_path))
    assert list(source.iter_ids()) == [r.bibcode for r in source.iter_papers()] == ["A", "C"]
    (tmp_path / "2020ApJ...900....1A.txt").write_text("hello")
    assert list(DirSource(str(tmp_path)).iter_ids()) == ["2020ApJ...900....1A"]


def test_truncated_gzip_call_log_yields_what_was_flushed(tmp_path):
    w = ShardWriter(tmp_path / "calls", "w", compress=True)
    for i in range(450):
        w.write({"i": i})
    # no close(): the process was killed. Two sync flushes (every 200 records) are on disk.
    assert len(list(read_shards(tmp_path, "calls"))) >= 400


def test_jsonl_source_reads_gz_and_skips_bad_lines(tmp_path):
    with gzip.open(tmp_path / "a.jsonl.gz", "wt") as f:
        f.write(json.dumps({"bibcode": "A", "text": "ta", "year": 2020}) + "\n")
        f.write("not json\n")
        f.write(json.dumps({"bibcode": "B"}) + "\n")  # no text field
    (tmp_path / "b.jsonl").write_text(json.dumps({"bibcode": "C", "text": "tc"}) + "\n")
    records = list(JsonlSource(str(tmp_path)).iter_papers())
    assert [(r.bibcode, r.text) for r in records] == [("A", "ta"), ("C", "tc")]
    assert records[0].meta == {"year": 2020}


def test_dir_source_and_custom_source(tmp_path):
    (tmp_path / "2020ApJ...900....1A.txt").write_text("hello")
    assert [(r.bibcode, r.text) for r in DirSource(str(tmp_path)).iter_papers()] == [("2020ApJ...900....1A", "hello")]
    custom = load_source("paper_data_linking.runner.sources:DirSource", str(tmp_path))
    assert len(list(custom.iter_papers())) == 1
    with pytest.raises(ValueError, match="Unknown source"):
        load_source("nope", str(tmp_path))


def test_shards_partition_the_input():
    codes = [f"2020Test..{i:04d}....A" for i in range(200)]
    parts = [{c for c in codes if in_shard(c, i, 3)} for i in range(3)]
    assert set().union(*parts) == set(codes) and sum(len(p) for p in parts) == len(codes)
    assert all(len(p) > 30 for p in parts)


@pytest.mark.parametrize("content,finish,expected", [
    ("# Scientific Observation Instrumentation Form\n...", "stop", None),
    ("No instruments were used.", "stop", None),
    ("", "stop", "empty"),                                   # the "---" stop sequence fired
    (None, "stop", "empty"),
    ("# Scientific Observation Instrumentation Form\n...", "length", "finish_reason=length"),
    ("Scientific Observation Instrumentation Form\n" + "---\n" * 25, "stop", "looping"),
    ("Here is my analysis of the paper.", "stop", "no_form_header"),
])
def test_step1_problem(content, finish, expected):
    assert step1_problem(content, finish) == expected


def test_token_gate_admits_by_cost_and_never_deadlocks_on_oversized_calls():
    gate = TokenGate(100)
    a = gate.acquire(60)
    b = gate.acquire(40)
    assert gate.snapshot()["in_use"] == 100
    gate.release(a)
    gate.release(b)
    big = gate.acquire(5000)  # larger than the whole budget: runs alone
    assert gate.snapshot()["running"] == 1
    gate.release(big)
    assert gate.snapshot() == {"budget": 100, "in_use": 0, "running": 0, "waiting": 0}


def test_vllm_metrics_parsing():
    text = ('# HELP vllm:cache_config_info x\n'
            'vllm:cache_config_info{block_size="16",cache_dtype="fp8",num_gpu_blocks="60369"} 1.0\n'
            'vllm:num_requests_running{model_name="m"} 37.0\n'
            'vllm:num_requests_waiting{model_name="m"} 2.0\n'
            'vllm:kv_cache_usage_perc{model_name="m"} 0.91\n')
    assert parse_kv_capacity(text) == 60369 * 16
    assert parse_gauges(text) == {"running": 37.0, "waiting": 2.0, "kv": 0.91}
    assert parse_kv_capacity("nothing here") is None


def test_budget_follows_the_servers_kv_use():
    gate = TokenGate(600)
    controller = BudgetController(gate, target=0.85)
    # Room in the cache but nothing held back: more budget would change nothing.
    assert controller.update(0.45) == 600
    held = [threading.Thread(target=gate.acquire, args=(400,), daemon=True) for _ in range(3)]
    for t in held:
        t.start()
    deadline = time.monotonic() + 5
    while gate.snapshot()["waiting"] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert gate.snapshot()["running"] == 1
    # The gate is the limit and the cache has room: grow in small steps, which lets waiters in.
    assert controller.update(0.45) == 618
    for _ in range(12):
        controller.update(0.45)
    for t in held[:2]:
        t.join(5)
    assert gate.snapshot()["running"] >= 2 and gate.snapshot()["budget"] > 800
    # Inside the band, or with the server itself queueing, the budget holds.
    budget = gate.snapshot()["budget"]
    assert controller.update(0.86) == budget and controller.update(0.45, server_waiting=3) == budget
    # Over the target it comes down, at most 10% a step and never below a quarter of the start.
    assert controller.update(0.99) == int(budget * 0.9)
    for _ in range(40):
        controller.update(1.0)
    assert gate.snapshot()["budget"] == 150
    # No gauge (not a vLLM server): leave it alone.
    assert controller.update(None) == 150


def test_prompt_size_estimate_learns_from_the_servers_counts():
    estimator = CallEstimator()
    messages = [{"role": "user", "content": "x" * 26000}]
    assert estimator.prompt_tokens("mission_identification", messages) == 10016  # catalog lists start denser than prose
    assert estimator.prompt_tokens("some_new_call", messages) == int(26000 / 3.3) + 16
    for _ in range(60):
        estimator.observe("some_new_call", 100, chars=26000, prompt_tokens=13000)
    assert abs(estimator.prompt_tokens("some_new_call", messages) - 13016) < 100
    estimator.observe("some_new_call", 100)  # a call with no usage report changes nothing
    assert abs(estimator.prompt_tokens("some_new_call", messages) - 13016) < 100
