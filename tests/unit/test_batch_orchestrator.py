"""Orchestration-level equivalence test for the wave-batch runner.

A synthetic prefix makes three *sequential, dependent* LLM calls (each input is the
prior call's output) to mimic the grounding tree-search. Driven through the real
chokepoint + CachedLLMResponse cache + a fake batch client, the wave loop must:
  * converge in exactly 3 waves (one sequential call resolved per wave),
  * produce the SAME final output as a synchronous baseline served the same
    (pinned) responses, and
  * write each LLMCall exactly once (commit pass), never duplicated across the
    repeated collection passes.

This proves the harness preserves behavior given identical responses — the
equivalence that is meaningful when the model itself is non-deterministic.
"""

import json
import pytest
from unittest.mock import patch

from paper_data_linking.pipeline_context import batch_execution
from paper_data_linking.clients.batch_replay import make_response_shim
from vso_query_builder import batch_downstream as bd

pytestmark = pytest.mark.django_db

MODEL = "bedrock/converse/openai.gpt-oss-120b-1:0"
CONFIG = "bedrock-120b-high-v5"

# Captured final outputs, keyed by paper_analysis_id.
RESULTS = {}


def _papers_in_state(run, state):
    """Sorted paper ids (str) in a RunPaper state — the post-refactor progress view."""
    from vso_query_builder.models import RunPaper
    return sorted(str(p) for p in RunPaper.objects
                  .filter(run=run, state=state).values_list('paper_id', flat=True))


def fake_llm(messages):
    """Deterministic 'model': wrap the last user message. Used by BOTH the sync
    baseline and the batch fake so any output difference is the harness's fault."""
    return f"R[{messages[-1]['content']}]"


def synthetic_chain(paper_analysis_id, configuration_name):
    """Three sequential dependent completion() calls through the real chokepoint."""
    from vso_query_builder.clients import DjangoLiteLLMClient
    from vso_query_builder.models import PaperAnalysis
    client = DjangoLiteLLMClient()
    base = PaperAnalysis.objects.get(id=paper_analysis_id).paper.bibcode
    c = base
    for step in ("step1", "step2", "step3"):
        resp = client.completion(step, MODEL, [{"role": "user", "content": c}], temperature=1.0)
        c = resp.choices[0].message.content
    RESULTS[str(paper_analysis_id)] = c


class FakeBatchClient:
    """Resolves each batched record with fake_llm(messages)."""

    def __init__(self):
        self.jobs = {}

    def prepare_generic_requests(self, records, provider="bedrock"):
        return "\n".join(
            json.dumps({"recordId": r["record_id"], "modelInput": {"messages": r["messages"]}})
            for r in records
        )

    def submit(self, jsonl, provider="bedrock", model_name=None, aws_region_name=None,
               aws_batch_role_arn=None):
        bid = f"job-{len(self.jobs)}"
        self.jobs[bid] = [json.loads(line) for line in jsonl.splitlines() if line.strip()]
        return {"batch_id": bid, "input_file_id": "s3://fake"}

    def check_status(self, batch_id, provider="bedrock", aws_region_name=None):
        n = len(self.jobs.get(batch_id, []))
        return {"status": "completed", "completed": n, "failed": 0, "total": n,
                "output_file_id": "s3://fake/out", "error_file_id": None}

    def retrieve_results(self, batch_id, provider="bedrock", aws_region_name=None):
        out = []
        for rec in self.jobs[batch_id]:
            content = fake_llm(rec["modelInput"]["messages"])
            out.append({
                "custom_id": rec["recordId"], "content": content,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "finish_reason": "stop",
            })
        return out


@pytest.fixture(autouse=True)
def _clear_results():
    RESULTS.clear()
    yield
    RESULTS.clear()


def _expected(bibcode):
    return f"R[R[R[{bibcode}]]]"


def test_sync_baseline_uses_pinned_responses(paper_analysis_factory):
    """Synchronous (off-mode) baseline served the pinned fake responses."""
    pa = paper_analysis_factory(configuration_name=CONFIG)
    fake = make_response_shim("", model=MODEL)

    def base_completion(self, call_type, model, messages, **kwargs):
        return make_response_shim(fake_llm(messages), model=model)

    with patch("paper_data_linking.clients.litellm_client.LiteLLMClient.completion", base_completion):
        synthetic_chain(str(pa.id), CONFIG)
    assert RESULTS[str(pa.id)] == _expected(pa.paper.bibcode)


def test_batch_run_converges_and_matches_and_writes_once(paper_factory):
    from vso_query_builder.models import PaperAnalysis, LLMCall, CachedLLMResponse

    # Two papers so we also exercise cross-paper dedup/independence.
    papers = [paper_factory(bibcode=f"2026paper..{i}") for i in range(2)]
    for p in papers:
        PaperAnalysis.objects.create(
            paper=p, configuration_name=CONFIG, status="completed",
            instruments_details="x", context=[], token_usage={})

    run = bd.create_run([str(p.id) for p in papers], CONFIG, aws_region_name="us-west-2")
    bd.drive_run_synchronously(
        run, FakeBatchClient(),
        prefix_fn=synthetic_chain, commit_fn=synthetic_chain,
        min_batch_size=1,  # force the batch path (2 records < real 100 floor)
    )
    run.refresh_from_db()

    assert run.status == "completed"
    # 3 sequential dependent calls => exactly 3 waves.
    assert run.current_wave == 3
    assert _papers_in_state(run, 'committed') == sorted(str(p.id) for p in papers)
    assert _papers_in_state(run, 'failed') == []

    for p in papers:
        pa = PaperAnalysis.objects.get(paper=p, configuration_name=CONFIG)
        # Output matches the deterministic pinned-response expectation.
        assert RESULTS[str(pa.id)] == _expected(p.bibcode)
        # Commit wrote each of the 3 calls exactly once (no duplication across the
        # repeated collection passes).
        calls = LLMCall.objects.filter(metadata__source="batch", output_content__contains=p.bibcode)
        assert calls.count() == 3
        for call in calls:
            assert call.metadata.get("source") == "batch"

    # Every cached row resolved; none left pending/batched.
    assert not CachedLLMResponse.objects.filter(run=run).exclude(status="resolved").exists()
    # 6 distinct logical calls (2 papers x 3 steps), each a unique cache row.
    assert CachedLLMResponse.objects.filter(run=run, status="resolved").count() == 6


# --------------------------------------------------------------------------- #
# Safety / resumability
# --------------------------------------------------------------------------- #

def test_lease_serializes_drivers():
    run = bd.create_run([], CONFIG)
    assert bd.claim_run(run.id, owner="w1") is True
    assert bd.claim_run(run.id, owner="w2") is False  # already leased by w1
    run.refresh_from_db()
    bd.release_run(run, free_immediately=True)
    assert bd.claim_run(run.id, owner="w2") is True   # claimable again after release


def test_reconciler_finds_only_stalled_nonterminal_runs():
    fresh = bd.create_run([], CONFIG)
    bd.claim_run(fresh.id)                 # leased ~30min into the future
    stale = bd.create_run([], CONFIG)      # never leased -> free
    done = bd.create_run([], CONFIG)
    done.status = "completed"; done.save(update_fields=["status"])

    ids = {str(r.id) for r in bd.find_stalled_runs()}
    assert str(stale.id) in ids
    assert str(fresh.id) not in ids        # actively leased -> skipped
    assert str(done.id) not in ids         # terminal -> skipped


def test_apply_results_is_idempotent():
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    row = CachedLLMResponse.objects.create(
        run=run, request_hash="h", call_type="x", status="pending", request_payload={})
    bd.apply_results(run, [row], [{"custom_id": "h", "content": "C",
                                   "usage": {"total_tokens": 2}, "finish_reason": "stop"}])
    row.refresh_from_db()
    assert row.status == "resolved" and row.response_content == "C"
    # Re-applying (e.g. a duplicated ingest) must not overwrite a resolved row.
    again = CachedLLMResponse.objects.get(id=row.id)
    bd.apply_results(run, [again], [{"custom_id": "h", "content": "DIFFERENT",
                                     "usage": {}, "finish_reason": ""}])
    row.refresh_from_db()
    assert row.response_content == "C"


def test_failed_record_marks_only_its_row():
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    ok = CachedLLMResponse.objects.create(run=run, request_hash="ok", status="batched", request_payload={})
    bad = CachedLLMResponse.objects.create(run=run, request_hash="bad", status="batched", request_payload={})
    bd.apply_results(run, [ok, bad], [
        {"custom_id": "ok", "content": "good", "usage": {}, "finish_reason": "stop"},
        {"custom_id": "bad", "error": "model error"},
    ])
    ok.refresh_from_db(); bad.refresh_from_db()
    assert ok.status == "resolved"
    assert bad.status == "failed" and "model error" in bad.error


def test_sync_fallback_resolves_sub_floor_group_without_batch():
    from vso_query_builder.models import CachedLLMResponse, BatchJob
    run = bd.create_run([], CONFIG)
    CachedLLMResponse.objects.create(
        run=run, request_hash="h1", call_type="x", status="pending",
        request_payload={"model": MODEL, "messages": [{"role": "user", "content": "q"}],
                         "params": {}, "response_format": None})

    def resolver(rows):
        return [{"custom_id": r.request_hash, "content": "SYNC", "usage": {}, "finish_reason": "stop"}
                for r in rows]

    disp = bd.dispatch_wave(run, FakeBatchClient(), min_batch_size=100, sync_resolver=resolver)
    assert disp["batched_jobs"] == 0 and disp["sync_resolved"] == 1
    assert BatchJob.objects.count() == 0  # no Bedrock job for a sub-floor group
    row = CachedLLMResponse.objects.get(run=run, request_hash="h1")
    assert row.status == "resolved" and row.response_content == "SYNC"


def test_resumes_from_mid_wave_after_simulated_crash(paper_factory):
    """Submit a wave, then drive to completion via fresh advance_run calls — proving
    the run resumes purely from durable DB state (no in-memory continuity)."""
    from vso_query_builder.models import PaperAnalysis, CachedLLMResponse, BatchJob
    p = paper_factory(bibcode="2026resume..1")
    PaperAnalysis.objects.create(paper=p, configuration_name=CONFIG, status="completed",
                                 instruments_details="x", context=[], token_usage={})
    run = bd.create_run([str(p.id)], CONFIG, aws_region_name="us-west-2")
    client = FakeBatchClient()  # one instance models durable S3 across "restarts"

    # First step: discovers wave 1 and submits it.
    res = bd.advance_run(run.id, client, prefix_fn=synthetic_chain,
                         commit_fn=synthetic_chain, min_batch_size=1)
    assert res["state"] == "submitted_wave"
    run.refresh_from_db()
    assert run.status == "batching"
    assert BatchJob.objects.filter(configuration_name=CONFIG).exists()
    assert CachedLLMResponse.objects.filter(run=run, status="batched").exists()
    assert run.leased_until is None  # lease released between steps

    # "Crash + reconciler": keep calling advance_run until terminal.
    for _ in range(32):
        res = bd.advance_run(run.id, client, prefix_fn=synthetic_chain,
                             commit_fn=synthetic_chain, min_batch_size=1)
        run.refresh_from_db()
        if run.status in ("completed", "failed"):
            break
    assert run.status == "completed"
    assert _papers_in_state(run, 'committed') == [str(p.id)]
    assert RESULTS[str(PaperAnalysis.objects.get(paper=p).id)] == _expected(p.bibcode)


# --------------------------------------------------------------------------- #
# Parallel (fleet) collection
# --------------------------------------------------------------------------- #

def _mk_papers(paper_factory, n):
    from vso_query_builder.models import PaperAnalysis
    papers = [paper_factory(bibcode=f"2026par..{i}") for i in range(n)]
    for p in papers:
        PaperAnalysis.objects.create(paper=p, configuration_name=CONFIG, status="completed",
                                     instruments_details="x", context=[], token_usage={})
    return papers


def test_chunked_collection_matches_serial(paper_factory):
    """Collecting in chunks + single-writer merge == one serial pass."""
    from vso_query_builder.models import CachedLLMResponse
    papers = _mk_papers(paper_factory, 4)
    ids = [str(p.id) for p in papers]

    serial = bd.create_run(ids, CONFIG)
    bd.run_collection_pass(serial, synthetic_chain)

    chunked = bd.create_run(ids, CONFIG)
    r1 = bd.collect_papers(chunked, ids[:2], synthetic_chain)
    r2 = bd.collect_papers(chunked, ids[2:], synthetic_chain)
    bd.finish_collection_chunk(chunked, ids[:2], r1)
    bd.finish_collection_chunk(chunked, ids[2:], r2)

    # Same pending frontier discovered either way (one step-1 call per paper).
    assert (CachedLLMResponse.objects.filter(run=serial, status="pending").count()
            == CachedLLMResponse.objects.filter(run=chunked, status="pending").count() == 4)
    assert (_papers_in_state(serial, 'llm_complete')
            == _papers_in_state(chunked, 'llm_complete'))


def test_parallel_celery_path_completes_and_matches(paper_factory, monkeypatch):
    """Full fleet path via Celery chord (eager): submit -> chunked collection ->
    waves -> commit, converging to the same pinned-response output."""
    from vso_query_builder import tasks
    from vso_query_builder.models import PaperAnalysis, BatchDownstreamRun
    papers = _mk_papers(paper_factory, 3)
    client = FakeBatchClient()
    monkeypatch.setattr(bd, "default_prefix_fn", synthetic_chain)
    monkeypatch.setattr(bd, "default_commit_fn", synthetic_chain)
    monkeypatch.setattr(bd, "BatchClient", lambda: client)
    monkeypatch.setattr(bd, "MIN_BEDROCK_RECORDS", 1)   # force batch path on tiny waves
    monkeypatch.setattr(bd, "COLLECTION_CHUNK_SIZE", 2)  # 3 papers -> 2 chunks

    res = tasks.submit_batch_downstream([str(p.id) for p in papers], CONFIG, "us-west-2")
    run = BatchDownstreamRun.objects.get(id=res["run_id"])

    assert run.status == "completed"
    assert _papers_in_state(run, 'committed') == sorted(str(p.id) for p in papers)
    for p in papers:
        pa = PaperAnalysis.objects.get(paper=p, configuration_name=CONFIG)
        assert RESULTS[str(pa.id)] == _expected(p.bibcode)


def test_sync_resolver_forwards_forced_tool_and_extracts_args():
    """Sub-100 structured-output groups: sync fallback must pass the forced tool
    AND lift the tool-call arguments back into content (parity with the batch path)."""
    from types import SimpleNamespace
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    row = CachedLLMResponse.objects.create(
        run=run, request_hash="h", call_type="time_normalization", status="pending",
        request_payload={
            "model": MODEL, "messages": [{"role": "user", "content": "q"}],
            "params": {"temperature": 1.0},
            "tools": [{"type": "function", "function": {"name": "json_tool_call",
                                                        "parameters": {}, "strict": True}}],
            "tool_choice": {"type": "function", "function": {"name": "json_tool_call"}},
        })
    tc = SimpleNamespace(function=SimpleNamespace(arguments='{"value":"x"}', name="json_tool_call"))
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]),
                                 finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    captured = {}

    def fake_completion(self, call_type, model, messages, **kwargs):
        captured.update(kwargs)
        return resp

    with patch("paper_data_linking.clients.litellm_client.LiteLLMClient.completion", fake_completion):
        results = bd.default_sync_resolver([row])
    assert "tools" in captured
    assert captured["tool_choice"]["function"]["name"] == "json_tool_call"
    assert results[0]["content"] == '{"value":"x"}'


def test_dispatch_wave_uses_bare_bedrock_model_id():
    """Regression: Bedrock CreateModelInvocationJob needs the bare model id.
    `bedrock/converse/openai.gpt-oss-120b-1:0` must become `openai.gpt-oss-120b-1:0`,
    not `converse/openai...` (which triggers ValidationException on real Bedrock)."""
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    CachedLLMResponse.objects.create(
        run=run, request_hash="h", status="pending",
        request_payload={"model": "bedrock/converse/openai.gpt-oss-120b-1:0",
                         "messages": [{"role": "user", "content": "q"}], "params": {}})
    captured = {}

    class CapturingClient(FakeBatchClient):
        def submit(self, jsonl, provider="bedrock", model_name=None,
                   aws_region_name=None, aws_batch_role_arn=None):
            captured["model_name"] = model_name
            return super().submit(jsonl, provider, model_name, aws_region_name, aws_batch_role_arn)

    bd.dispatch_wave(run, CapturingClient(), min_batch_size=1)
    assert captured["model_name"] == "openai.gpt-oss-120b-1:0"


def test_renew_lease_requires_ownership():
    """Heartbeat extends the lease only for the current owner; a stranger's
    renewal is a no-op (it must not resurrect a lease it lost)."""
    run = bd.create_run([], CONFIG)
    assert bd.claim_run(run.id, owner="w1")
    run.refresh_from_db()
    before = run.leased_until
    assert bd.renew_lease(run.id, "w1") is True
    run.refresh_from_db()
    assert run.leased_until >= before
    assert bd.renew_lease(run.id, "w2") is False
    run.refresh_from_db()
    assert run.lease_owner == "w1"


def _fat_rows(run, n, content_bytes=400):
    from vso_query_builder.models import CachedLLMResponse
    for i in range(n):
        CachedLLMResponse.objects.create(
            run=run, request_hash=f"h{i}", status="pending",
            request_payload={"model": MODEL, "params": {},
                             "messages": [{"role": "user", "content": "x" * content_bytes}]})


class SizeCapturingClient(FakeBatchClient):
    def __init__(self):
        super().__init__()
        self.jsonl_sizes = []

    def submit(self, jsonl, provider="bedrock", model_name=None,
               aws_region_name=None, aws_batch_role_arn=None):
        self.jsonl_sizes.append(len(jsonl))
        return super().submit(jsonl, provider, model_name, aws_region_name, aws_batch_role_arn)


def test_dispatch_wave_splits_jobs_on_byte_budget(monkeypatch):
    """Bedrock's input-file limit (1GB live; shrunk here) must cut a job BEFORE
    the record cap when payloads are fat — with no row dropped or duplicated."""
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    _fat_rows(run, 6)                                    # each line ~500 bytes
    monkeypatch.setattr(bd, "MAX_JOB_BYTES", 1200)       # ~2 lines per job
    client = SizeCapturingClient()
    disp = bd.dispatch_wave(run, client, min_batch_size=1)
    assert disp["batched_jobs"] == 3
    assert all(s <= 1200 for s in client.jsonl_sizes)
    batched = CachedLLMResponse.objects.filter(run=run, status='batched')
    assert batched.count() == 6                          # nothing dropped
    assert sum(len(v) for v in client.jobs.values()) == 6
    assert batched.exclude(batch_job=None).count() == 6  # every row tied to its job


def test_dispatch_wave_splits_jobs_on_record_cap(monkeypatch):
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    _fat_rows(run, 5, content_bytes=5)
    monkeypatch.setattr(bd, "MAX_RECORDS_PER_JOB", 2)
    client = SizeCapturingClient()
    disp = bd.dispatch_wave(run, client, min_batch_size=1)
    assert disp["batched_jobs"] == 3                     # 2 + 2 + 1
    assert sorted(len(v) for v in client.jobs.values()) == [1, 2, 2]
    assert CachedLLMResponse.objects.filter(run=run, status='batched').count() == 5


def test_commit_reclaim_increments_attempts_and_retries_solo(paper_factory, monkeypatch):
    """cohort_10k final-30 regression: a chunk of several heavyweight papers can
    never beat the task time limit, so reclaimed papers must retry as SOLO
    chunks (attempts>0 -> chunk size 1)."""
    from datetime import timedelta
    from django.utils import timezone
    from vso_query_builder.models import RunPaper
    from vso_query_builder import tasks
    dispatched = []
    monkeypatch.setattr(tasks.commit_chunk_task, "delay",
                        lambda rid, papers: dispatched.append(papers))
    monkeypatch.setattr(tasks.advance_run_task, "delay", lambda *a, **k: None)

    papers = [paper_factory() for _ in range(12)]
    run = bd.create_run([str(p.id) for p in papers], CONFIG)
    # 3 papers stuck in a stale committing claim (dead heavy chunk)
    stuck = [str(p.id) for p in papers[:3]]
    old = timezone.now() - timedelta(seconds=bd.CLAIM_STALE_SECONDS + 5)
    RunPaper.objects.filter(run=run, paper_id__in=stuck).update(
        state='committing', dispatched_at=old)
    RunPaper.objects.filter(run=run).exclude(paper_id__in=stuck).update(state='llm_complete')

    assert bd.reclaim_stale_claims(run) == 3
    assert RunPaper.objects.filter(run=run, attempts=1).count() == 3

    bd.dispatch_parallel_commit(run.id)
    solos = [c for c in dispatched if len(c) == 1]
    assert sorted(p for c in solos for p in c) == sorted(stuck)  # retried papers go solo
    assert sum(len(c) for c in dispatched) == 12                 # everyone dispatched


def test_corpus_completion_kicks_trailing_sweeps(monkeypatch):
    """Issue #175: a corpus-mode run kicks the embedding + coordinate sweeps at
    completion (promptness); a research run does not (nothing was deferred)."""
    from vso_query_builder import tasks
    kicked = []
    monkeypatch.setattr(tasks.embed_missing_quotes, "delay",
                        lambda *a, **k: kicked.append("embed"))
    monkeypatch.setattr(tasks.submit_batch_enrich_coordinates, "delay",
                        lambda *a, **k: kicked.append(("coords", k.get("configuration_name"))))

    corpus = bd.create_run([], CONFIG, corpus_mode=True)
    res = bd.advance_run(corpus.id, FakeBatchClient())
    assert res["state"] == "completed"
    assert kicked == ["embed", ("coords", CONFIG)]

    kicked.clear()
    research = bd.create_run([], CONFIG)
    res = bd.advance_run(research.id, FakeBatchClient())
    assert res["state"] == "completed"
    assert kicked == []


def test_embed_missing_quotes_self_chains_until_drained(paper_analysis_factory, monkeypatch):
    """Issue #175: a capped sweep with backlog re-delays itself — one kick drains
    everything (eager mode runs the chain inline, so the table ends fully embedded
    even though the first sweep was capped at 1)."""
    from types import SimpleNamespace
    from vso_query_builder import tasks
    from vso_query_builder.models import SupportQuote
    pa = paper_analysis_factory()
    for i in range(2):
        SupportQuote.objects.create(paper_analysis=pa, quote=f"quote {i}",
                                    page_number=0, y_coord=0.0, coordinate_regions=[])
    SupportQuote.objects.update(embedding=None)

    class FakeClient:
        def __init__(self, **kw):
            self.embeddings = self
        def create(self, input, model):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.5] * 1536)
                                         for _ in input])
    monkeypatch.setattr("openai.OpenAI", FakeClient)

    res = tasks.embed_missing_quotes(max_quotes=1, chunk_size=1)
    assert res == {"embedded": 1, "remaining": 1}   # this sweep hit its cap...
    assert SupportQuote.objects.filter(embedding__isnull=True).count() == 0  # ...chain drained the rest


def test_commit_dispatch_is_bounded_topup(paper_factory, monkeypatch):
    """cohort_10k regression: unbounded commit fan-out queued ~1,000 chunks,
    queue latency exceeded CLAIM_STALE_SECONDS, and reclaim-spawned duplicate
    chunks compounded until throughput collapsed. Dispatch must claim at most
    COMMIT_MAX_IN_FLIGHT papers and top up as chunks finish."""
    from vso_query_builder.models import RunPaper
    from vso_query_builder import tasks
    dispatched = []
    monkeypatch.setattr(tasks.commit_chunk_task, "delay",
                        lambda rid, papers: dispatched.append(papers))
    monkeypatch.setattr(tasks.advance_run_task, "delay", lambda *a, **k: None)
    monkeypatch.setattr(bd, "COMMIT_MAX_IN_FLIGHT", 30)

    papers = [paper_factory() for _ in range(50)]
    run = bd.create_run([str(p.id) for p in papers], CONFIG)
    RunPaper.objects.filter(run=run).update(state='llm_complete')

    n = bd.dispatch_parallel_commit(run.id)
    assert sum(len(c) for c in dispatched) == 30          # capped, not 50
    assert RunPaper.objects.filter(run=run, state='committing').count() == 30
    assert n == 3                                          # 30 papers / chunk_size 10

    # A second (duplicate) dispatcher while the fleet is full claims NOTHING.
    dispatched.clear()
    assert bd.dispatch_parallel_commit(run.id) == 0
    assert dispatched == []

    # As papers finish, the next call tops up only the freed budget.
    done = RunPaper.objects.filter(run=run, state='committing')[:10]
    RunPaper.objects.filter(id__in=[r.id for r in done]).update(state='committed')
    bd.dispatch_parallel_commit(run.id)
    assert sum(len(c) for c in dispatched) == 10
    assert RunPaper.objects.filter(run=run, state='committing').count() == 30


def test_pending_papers_dispatch_despite_collecting_stragglers(paper_factory):
    """A killed chunk's orphaned 'collecting' claims must not block the frontier:
    with ready pending papers the driver asks for collection instead of waiting
    (syn40k2 drill: 2400 orphaned claims froze 37600 ready papers for 45 min)."""
    from django.utils import timezone
    from vso_query_builder.models import RunPaper
    p1 = paper_factory(bibcode="2026stuck...1")
    p2 = paper_factory(bibcode="2026ready...2")
    run = bd.create_run([str(p1.id), str(p2.id)], CONFIG)
    RunPaper.objects.filter(run=run, paper_id=p1.id).update(
        state='collecting', dispatched_at=timezone.now())  # fresh claim, not stale
    res = bd.advance_run(run.id, FakeBatchClient(), collect=False)
    assert res["state"] == "need_collection"


def test_dispatch_and_ingest_call_heartbeat(monkeypatch):
    """The driver's lease heartbeat must fire once per submitted job and once per
    polled job — the loops that outran the (now short) lease at 40k scale."""
    run = bd.create_run([], CONFIG)
    _fat_rows(run, 4, content_bytes=5)
    monkeypatch.setattr(bd, "MAX_RECORDS_PER_JOB", 2)
    beats = []
    client = FakeBatchClient()
    disp = bd.dispatch_wave(run, client, min_batch_size=1,
                            heartbeat=lambda: beats.append("d"))
    assert disp["batched_jobs"] == 2 and beats == ["d", "d"]
    prog = bd.progress_inflight_jobs(run, client, heartbeat=lambda: beats.append("p"))
    assert prog["ingested"] == 2 and beats == ["d", "d", "p", "p"]


# --------------------------------------------------------------------------- #
# Transient-error retry (the confirmed root cause of the E2E tail stall)
# --------------------------------------------------------------------------- #

def test_is_transient_error_classification():
    from paper_data_linking.clients.batch_replay import is_transient_error
    assert is_transient_error("BedrockException: ServiceUnavailableError, try your request again")
    assert is_transient_error("ThrottlingException: Too many requests (429)")
    assert is_transient_error("The security token included in the request is expired")
    assert not is_transient_error("ValidationException: The provided model identifier is invalid")
    assert not is_transient_error("could not parse json")


def test_apply_results_retries_transient_then_fails_at_cap():
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    row = CachedLLMResponse.objects.create(run=run, request_hash="h", status="batched", request_payload={})
    tr = [{"custom_id": "h", "transient_error": "ServiceUnavailableError"}]
    for i in range(1, bd.MAX_CALL_ATTEMPTS):        # attempts 1..5 stay retryable
        r = bd.apply_results(run, [CachedLLMResponse.objects.get(id=row.id)], tr)
        row.refresh_from_db()
        assert row.status == "pending" and row.attempts == i and r["retried"] == 1
    # the cap-hitting attempt becomes terminal
    r = bd.apply_results(run, [CachedLLMResponse.objects.get(id=row.id)], tr)
    row.refresh_from_db()
    assert row.status == "failed" and r["failed"] == 1


def test_apply_results_permanent_error_fails_immediately():
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    row = CachedLLMResponse.objects.create(run=run, request_hash="h", status="batched", request_payload={})
    r = bd.apply_results(run, [row], [{"custom_id": "h", "error": "ValidationException: bad schema"}])
    row.refresh_from_db()
    assert row.status == "failed" and row.attempts == 0 and r["failed"] == 1


def test_sync_resolver_marks_transient_vs_permanent():
    from unittest.mock import patch
    from vso_query_builder.models import CachedLLMResponse
    run = bd.create_run([], CONFIG)
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "q"}], "params": {}}
    r1 = CachedLLMResponse.objects.create(run=run, request_hash="t", status="pending", request_payload=payload)
    with patch("paper_data_linking.clients.litellm_client.LiteLLMClient.completion",
               side_effect=Exception("BedrockException ServiceUnavailableError try again")):
        out = bd.default_sync_resolver([r1])
    assert "transient_error" in out[0] and "error" not in out[0]
    with patch("paper_data_linking.clients.litellm_client.LiteLLMClient.completion",
               side_effect=Exception("ValidationException invalid model identifier")):
        out = bd.default_sync_resolver([r1])
    assert "error" in out[0] and "transient_error" not in out[0]


# --------------------------------------------------------------------------- #
# Frontier discovery: independent branches parallelize within one wave
# --------------------------------------------------------------------------- #

def branchy_chain(paper_analysis_id, configuration_name):
    """Two INDEPENDENT branches (like instruments/data-systems), each a 3-step
    sequential chain, each with grounder-style per-branch isolation. The old
    stack-unwinding defer needed 6 waves; frontier discovery needs 3."""
    from vso_query_builder.clients import DjangoLiteLLMClient
    from vso_query_builder.models import PaperAnalysis
    client = DjangoLiteLLMClient()
    base = PaperAnalysis.objects.get(id=paper_analysis_id).paper.bibcode
    outs = {}
    for branch in ("A", "B"):
        try:  # per-branch isolation, mirroring the grounder loops
            c = f"{base}/{branch}"
            for step in range(3):
                resp = client.completion(f"br{branch}s{step}", MODEL,
                                         [{"role": "user", "content": c}], temperature=1.0)
                c = resp.choices[0].message.content
            outs[branch] = c
        except Exception:  # noqa: BLE001
            outs[branch] = None
    RESULTS[str(paper_analysis_id)] = outs


def test_independent_branches_converge_in_depth_not_count(paper_factory):
    from vso_query_builder.models import PaperAnalysis
    p = paper_factory(bibcode="2026branchy.1")
    PaperAnalysis.objects.create(paper=p, configuration_name=CONFIG, status="completed",
                                 instruments_details="x", context=[], token_usage={})
    run = bd.create_run([str(p.id)], CONFIG)
    bd.drive_run_synchronously(run, FakeBatchClient(),
                               prefix_fn=branchy_chain, commit_fn=branchy_chain,
                               min_batch_size=1)
    run.refresh_from_db()
    assert run.status == "completed"
    # 2 branches x depth 3 = 6 calls, but only 3 WAVES (frontier discovery).
    assert run.current_wave == 3
    pa = PaperAnalysis.objects.get(paper=p, configuration_name=CONFIG)
    exp = {b: f"R[R[R[{p.bibcode}/{b}]]]" for b in ("A", "B")}
    assert RESULTS[str(pa.id)] == exp  # both branches fully resolved, correct outputs


# --------------------------------------------------------------------------- #
# RunPaper state machine: claim idempotency + stale-claim recovery
# --------------------------------------------------------------------------- #

def test_duplicate_dispatch_claims_nothing(paper_factory, monkeypatch):
    """A second (racing/redundant) dispatcher must find zero claimable rows and
    dispatch zero chunks — the structural replacement for the old round counters,
    which once let a re-entry re-dispatch a full round (3,367-dup storm)."""
    from vso_query_builder import tasks
    from vso_query_builder.models import RunPaper
    papers = _mk_papers(paper_factory, 4)
    run = bd.create_run([str(p.id) for p in papers], CONFIG)

    dispatched = []
    monkeypatch.setattr(tasks.collect_chunk_task, "delay",
                        lambda *a, **k: dispatched.append(a))
    # The zero-claim path re-enters the driver; keep it out of this unit's scope.
    monkeypatch.setattr(tasks.advance_run_task, "delay", lambda *a, **k: None)

    n1 = bd.dispatch_parallel_collection(run.id, chunk_size=2)
    assert n1 == 2
    assert RunPaper.objects.filter(run=run, state='collecting').count() == 4

    # Duplicate dispatch: nothing pending -> nothing claimed, nothing dispatched.
    n2 = bd.dispatch_parallel_collection(run.id, chunk_size=2)
    assert n2 == 0
    assert len(dispatched) == 2  # only the first round's chunks


def test_guard_path_commit_runs_inside_commit_context(paper_factory, monkeypatch):
    """The skip-replay guard path (re-entered commits: crash recovery / stale
    reclaim) must run create_dataset_usages INSIDE batch_execution('commit'),
    or the corpus-mode gates don't fire — observed live in the prod sentinel's
    kill/resume drill (guard-path quotes were eagerly sync-embedded)."""
    from django.utils import timezone as dj_tz
    from paper_data_linking.pipeline_context import get_pipeline_mode, current_batch_run_id
    from vso_query_builder import tasks
    from vso_query_builder.models import PaperAnalysis, PipelineNode

    papers = _mk_papers(paper_factory, 1)
    run = bd.create_run([str(papers[0].id)], CONFIG, corpus_mode=True)
    pa = PaperAnalysis.objects.get(paper=papers[0], configuration_name=CONFIG)
    # A node stamped after run creation triggers the skip-replay guard.
    PipelineNode.objects.create(
        analysis=pa, stage='structuring', label='x', status='completed',
        started_at=dj_tz.now(), completed_at=dj_tz.now(), metadata={})

    seen = {}
    def capture(result):
        seen['mode'] = get_pipeline_mode()
        seen['run_id'] = str(current_batch_run_id.get())
        return result
    monkeypatch.setattr(tasks, "create_dataset_usages", capture)

    res = bd.commit_single_paper(run, str(papers[0].id))
    assert res["committed"] is True and res.get("skipped_replay") is True
    assert seen["mode"] == "commit"
    assert seen["run_id"] == str(run.id)


def test_stale_claims_are_reclaimed(paper_factory, monkeypatch):
    """Rows claimed by a chunk that died are returned to a workable state by the
    driver (dispatched_at older than the staleness window)."""
    from datetime import timedelta
    from django.utils import timezone
    from vso_query_builder import tasks
    from vso_query_builder.models import RunPaper
    papers = _mk_papers(paper_factory, 2)
    run = bd.create_run([str(p.id) for p in papers], CONFIG)

    monkeypatch.setattr(tasks.collect_chunk_task, "delay", lambda *a, **k: None)
    bd.dispatch_parallel_collection(run.id)
    assert RunPaper.objects.filter(run=run, state='collecting').count() == 2

    # Fresh claims are NOT reclaimed...
    assert bd.reclaim_stale_claims(run) == 0
    # ...but claims older than the window are.
    RunPaper.objects.filter(run=run).update(
        dispatched_at=timezone.now() - timedelta(seconds=bd.CLAIM_STALE_SECONDS + 60))
    assert bd.reclaim_stale_claims(run) == 2
    assert RunPaper.objects.filter(run=run, state='pending').count() == 2


# --------------------------------------------------------------------------- #
# Payload lifecycle (corpus mode)
# --------------------------------------------------------------------------- #

def test_resolved_rows_drop_request_payload(paper_factory):
    """apply_results strips the (10-30KB prompt) payload on resolve — replay only
    needs response_content; batch inputs live in S3. Failed rows keep theirs."""
    from vso_query_builder.models import CachedLLMResponse
    papers = _mk_papers(paper_factory, 1)
    run = bd.create_run([str(papers[0].id)], CONFIG)
    ok = CachedLLMResponse.objects.create(
        run=run, request_hash="h-ok", call_type="t", status="pending",
        request_payload={"model": MODEL, "messages": [{"role": "user", "content": "x"}]})
    bad = CachedLLMResponse.objects.create(
        run=run, request_hash="h-bad", call_type="t", status="pending",
        request_payload={"model": MODEL, "messages": [{"role": "user", "content": "y"}]})
    bd.apply_results(run, [ok, bad], [
        {"custom_id": "h-ok", "content": "fine", "usage": {"completion_tokens": 1}},
        {"custom_id": "h-bad", "error": "permanent parse failure"},
    ])
    ok.refresh_from_db(); bad.refresh_from_db()
    assert ok.status == "resolved" and ok.request_payload == {}
    assert ok.response_content == "fine"
    assert bad.status == "failed" and bad.request_payload  # kept for debugging


def test_corpus_mode_prunes_cache_but_keeps_full_llmcall_provenance(paper_factory):
    """End-to-end corpus_mode run: resolved cache rows lose response_content at
    completion (pure transport), but LLMCalls keep FULL provenance — input,
    output, usage — so the prune is lossless and everything stays auditable."""
    from vso_query_builder.models import PaperAnalysis, LLMCall, CachedLLMResponse
    papers = _mk_papers(paper_factory, 2)
    run = bd.create_run([str(p.id) for p in papers], CONFIG, corpus_mode=True)
    bd.drive_run_synchronously(
        run, FakeBatchClient(),
        prefix_fn=synthetic_chain, commit_fn=synthetic_chain, min_batch_size=1)
    run.refresh_from_db()
    assert run.status == "completed"
    assert _papers_in_state(run, 'committed') == sorted(str(p.id) for p in papers)

    calls = LLMCall.objects.filter(metadata__source="batch")
    assert calls.count() == 6
    for c in calls:
        assert c.input_messages                  # full provenance, even in corpus mode
        assert c.output_content
        assert c.total_tokens > 0

    rows = CachedLLMResponse.objects.filter(run=run, status="resolved")
    assert rows.count() == 6
    for r in rows:
        assert r.response_content is None        # pruned at completion (lossless: see LLMCall)
        assert r.usage.get("completion_tokens")  # analytics kept


def test_default_mode_keeps_full_provenance(paper_factory):
    """Without corpus_mode (research/eval runs), nothing is pruned and LLMCalls
    keep their input messages — case studies depend on this."""
    from vso_query_builder.models import LLMCall, CachedLLMResponse
    papers = _mk_papers(paper_factory, 1)
    run = bd.create_run([str(papers[0].id)], CONFIG)
    bd.drive_run_synchronously(
        run, FakeBatchClient(),
        prefix_fn=synthetic_chain, commit_fn=synthetic_chain, min_batch_size=1)
    run.refresh_from_db()
    assert run.status == "completed"
    for c in LLMCall.objects.filter(metadata__source="batch"):
        assert c.input_messages                  # full provenance
    for r in CachedLLMResponse.objects.filter(run=run, status="resolved"):
        assert r.response_content                # content kept
