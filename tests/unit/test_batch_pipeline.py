"""State-machine + safety tests for the end-to-end batch pipeline orchestrator."""

import pytest
from unittest.mock import patch, MagicMock

from vso_query_builder import batch_pipeline as bp

pytestmark = pytest.mark.django_db

CONFIG = "bedrock-120b-high-v5"


def test_pipeline_lease_and_reconciler():
    run = bp.create_pipeline([], CONFIG)
    assert bp.claim_pipeline(run.id, owner="w1") is True
    assert bp.claim_pipeline(run.id, owner="w2") is False  # already leased
    run.refresh_from_db()
    bp.release_pipeline(run)
    assert bp.claim_pipeline(run.id, owner="w2") is True    # claimable after release

    stale = bp.create_pipeline([], CONFIG)                  # never leased -> stalled
    fresh = bp.create_pipeline([], CONFIG)
    bp.claim_pipeline(fresh.id)                             # leased -> not stalled
    ids = {str(r.id) for r in bp.find_stalled_pipelines()}
    assert str(stale.id) in ids and str(fresh.id) not in ids


def test_pipeline_walks_all_stages(paper_factory, monkeypatch):
    """Drive extract -> step1 -> downstream -> analyze -> done, simulating each
    subsystem's completion via DB state (chords/sub-jobs mocked)."""
    from vso_query_builder import tasks
    from vso_query_builder import batch_downstream as bd
    from vso_query_builder.models import (
        Paper, PaperAnalysis, BatchJob, BatchDownstreamRun, BatchPipelineRun)
    from django.core.files.base import ContentFile

    p = paper_factory(bibcode="2026pipe.1", full_text="")
    p.pdf.save("p.pdf", ContentFile(b"%PDF-1.4"), save=True)
    run = bp.create_pipeline([str(p.id)], CONFIG, aws_region_name="us-west-2")

    # Never let real fan-out tasks fire.
    monkeypatch.setattr(tasks.extract_paper_text_task, "delay", lambda *a, **k: None)
    monkeypatch.setattr(tasks.advance_run_task, "delay", lambda *a, **k: None)

    # --- extract stage: dispatch, then completion derived from paper STATE
    # (chord-free: the gate is "no cohort paper still lacks text") ---
    res = bp.advance_pipeline(run.id)
    assert res["state"] == "extract:dispatched"
    run.refresh_from_db(); assert run.extract_dispatched and run.stage == "extract"
    assert bp.advance_pipeline(run.id)["state"] == "extract:waiting"  # text not written yet
    p.full_text = "some extracted text"; p.save()
    assert bp.advance_pipeline(run.id)["state"] == "extract:done"

    # --- step1 stage: submit (mocked) -> poll BatchJob ---
    bj = BatchJob.objects.create(batch_id="b1", status="submitted",
                                 configuration_name=CONFIG, provider="bedrock")
    fake_submit = MagicMock()
    fake_submit.apply.return_value.result = {"success": True, "batch_job_id": bj.id}
    monkeypatch.setattr(tasks, "submit_batch_paper_analysis", fake_submit)
    assert bp.advance_pipeline(run.id)["state"] == "step1:submitted"
    run.refresh_from_db(); assert run.step1_batch_job_id == bj.id
    # poll_batch_job flips status terminal BEFORE the async ingest runs; the
    # stage must WAIT until ingest stamps completed_at (cohort_1k race: advancing
    # early froze the downstream run at a partial paper set).
    bj.status = "completed"; bj.save()
    assert bp.advance_pipeline(run.id)["state"] == "step1:ingesting"
    from django.utils import timezone
    bj.completed_at = timezone.now(); bj.save()
    assert bp.advance_pipeline(run.id)["state"] == "step1:done"

    # --- downstream stage: create wave run (real), then mark it complete ---
    PaperAnalysis.objects.create(paper=p, configuration_name=CONFIG, status="completed",
                                 instruments_details="x", context=[], token_usage={})
    assert bp.advance_pipeline(run.id)["state"] == "downstream:started"
    run.refresh_from_db()
    dr = run.downstream_run
    assert dr is not None and dr.paper_ids == [str(p.id)]
    dr.status = "completed"; dr.save()
    assert bp.advance_pipeline(run.id)["state"] == "downstream:done"

    # --- analyze stage: no DUs -> completes immediately ---
    res = bp.advance_pipeline(run.id)
    assert res["state"] == "analyze:none"
    run.refresh_from_db()
    assert run.stage == "done" and run.status == "completed" and run.completed_at


def test_extract_stage_advances_past_dead_stragglers(paper_factory, monkeypatch):
    """cohort_10k regression: ~19/10,000 pathological PDFs were hard-killed and
    the old chord gate waited FOREVER at 9,981 done. The state-derived gate must
    advance once the remaining count has been flat for STAGE_STALL_SECONDS,
    logging the stragglers rather than freezing the run."""
    from django.utils import timezone
    from datetime import timedelta
    from django.core.files.base import ContentFile
    from vso_query_builder import tasks
    monkeypatch.setattr(tasks.extract_paper_text_task, "delay", lambda *a, **k: None)

    done = paper_factory(bibcode="2026stall..1", full_text="fine")
    stuck = paper_factory(bibcode="2026stall..2", full_text="")
    stuck.pdf.save("s.pdf", ContentFile(b"%PDF-1.4"), save=True)
    run = bp.create_pipeline([str(done.id), str(stuck.id)], CONFIG,
                             aws_region_name="us-west-2")
    assert bp.advance_pipeline(run.id)["state"] == "extract:dispatched"
    assert bp.advance_pipeline(run.id)["state"] == "extract:waiting"   # window opens
    # Backdate the stall tracker beyond the window: the gate must advance.
    run.refresh_from_db()
    count, _ = run.metadata['extract_stall']
    run.metadata['extract_stall'] = [count, (timezone.now() - timedelta(
        seconds=bp.STAGE_STALL_SECONDS + 5)).isoformat()]
    run.save(update_fields=['metadata'])
    assert bp.advance_pipeline(run.id)["state"] == "extract:done"
    run.refresh_from_db()
    assert run.stage == "step1" and run.extract_done


def test_step1_chunks_jobs_by_byte_budget(paper_factory, monkeypatch):
    """Step-1 prompts embed full paper text, so Bedrock's 1GB input-file limit
    binds ~15k papers — the submit path must cut multiple jobs by bytes, and
    never strand a sub-100-record remainder (Bedrock's floor)."""
    from vso_query_builder import tasks, batch_downstream as bd
    from vso_query_builder.models import BatchJob
    from paper_data_linking.clients import batch_client as bc

    papers = [paper_factory(full_text="solar wind " * 200) for _ in range(220)]
    submitted = []

    def fake_submit(self, jsonl, provider="bedrock", model_name=None,
                    aws_region_name=None, aws_batch_role_arn=None):
        submitted.append(len(jsonl))
        return {"batch_id": f"job-{len(submitted)}", "input_file_id": "s3://x"}
    monkeypatch.setattr(bc.BatchClient, "submit", fake_submit)
    # eager celery would run the poll (and hit real boto3) inline
    monkeypatch.setattr(tasks.poll_batch_job, "apply_async", lambda *a, **k: None)

    # Byte cap ~= 100 real records: with 220 bedrock papers the first cut is
    # legal (100 in-chunk, 120 remaining); a second cut would strand 20 (<100),
    # so the tail must FOLD into the final job.
    from vso_query_builder.tasks import _load_paper_analysis_system_prompt
    line_len = len(bc.BatchClient().prepare_requests(
        [{"paper_id": str(papers[0].id), "text": "solar wind " * 200}],
        __import__("paper_data_linking.config.settings", fromlist=["s"]).get_llm_configuration(CONFIG).paper_analysis,
        _load_paper_analysis_system_prompt(), provider="bedrock")) + 1
    monkeypatch.setattr(bd, "MAX_JOB_BYTES", line_len * 100)

    res = tasks.submit_batch_paper_analysis.apply(
        args=[[str(p.id) for p in papers], CONFIG],
        kwargs={"trigger_downstream": False}).result
    assert res["success"] is True
    jobs = list(BatchJob.objects.filter(id__in=res["batch_job_ids"]))
    sizes = sorted(j.total_requests for j in jobs)
    assert sum(sizes) == 220
    assert len(jobs) == 2                 # 100 + 120: tail folded, both >= floor
    assert min(sizes) >= 100              # Bedrock's per-job record floor holds
    assert res["batch_job_id"] == res["batch_job_ids"][0]


def test_step1_stage_waits_for_all_chunk_jobs(paper_factory, monkeypatch):
    """The pipeline must gate on EVERY step-1 chunk job (terminal + ingested),
    and tolerate a wholly-failed chunk as a partial cohort."""
    from django.utils import timezone
    from vso_query_builder.models import BatchJob
    p = paper_factory(bibcode="2026multi.1", full_text="text")
    run = bp.create_pipeline([str(p.id)], CONFIG, aws_region_name="us-west-2")
    run.stage = 'step1'
    bj1 = BatchJob.objects.create(batch_id="m1", status="processing",
                                  configuration_name=CONFIG, provider="bedrock")
    bj2 = BatchJob.objects.create(batch_id="m2", status="completed",
                                  configuration_name=CONFIG, provider="bedrock",
                                  completed_at=timezone.now())
    run.step1_batch_job = bj1
    run.metadata['step1_batch_job_ids'] = [bj1.id, bj2.id]
    run.save()

    assert bp.advance_pipeline(run.id)["state"] == "step1:waiting"   # bj1 running
    bj1.status = "partially_failed"; bj1.save()
    assert bp.advance_pipeline(run.id)["state"] == "step1:ingesting"  # bj1 not ingested
    bj1.completed_at = timezone.now(); bj1.save()
    assert bp.advance_pipeline(run.id)["state"] == "step1:done"
    # all chunks failed -> stage fails
    run2 = bp.create_pipeline([str(p.id)], CONFIG, aws_region_name="us-west-2")
    run2.stage = 'step1'
    bj3 = BatchJob.objects.create(batch_id="m3", status="failed",
                                  configuration_name=CONFIG, provider="bedrock")
    run2.step1_batch_job = bj3
    run2.metadata['step1_batch_job_ids'] = [bj3.id]
    run2.save()
    assert bp.advance_pipeline(run2.id)["state"] == "failed"


def test_create_run_derives_region_from_config():
    """cohort_1k regression: a downstream run created without an explicit region
    must inherit the LLM configuration's region (us-west-2 for the bedrock
    configs) — NOT fall back to the ambient boto3 default, which sent every
    downstream job to us-east-1 where the model doesn't exist."""
    from vso_query_builder import batch_downstream as bd
    run = bd.create_run([], CONFIG)
    assert run.aws_region_name == "us-west-2"
    # explicit region still wins
    run2 = bd.create_run([], CONFIG, aws_region_name="eu-central-1")
    assert run2.aws_region_name == "eu-central-1"
