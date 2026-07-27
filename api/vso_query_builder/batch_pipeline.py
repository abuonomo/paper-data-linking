"""End-to-end corpus pipeline orchestrator: extract -> step1 -> downstream -> analyze.

One crash-safe idempotent driver (`advance_pipeline`) walks a BatchPipelineRun through
the four stages, each delegated to the right subsystem:
  * extract   — prefork chord of extract_paper_text_task (OCR off for corpus)
  * step1     — Bedrock batch paper_analysis (trigger_downstream=False)
  * downstream— the wave runner (BatchDownstreamRun)
  * analyze   — prefork chord of analyze_dataset_usage (execution off for corpus)

Lease + the beat reconciler make it resumable exactly like BatchDownstreamRun. This
is the 90k entrypoint. All stage transitions derive from durable DB state, so a crash
at any point resumes correctly.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import List, Optional

from django.db.models import Q
from django.utils import timezone

from .models import (
    BatchPipelineRun, BatchJob, Paper, PaperAnalysis, DatasetUsage, DatasetUsageAnalysis,
)
from .batch_downstream import (
    LEASE_SECONDS, POLL_COUNTDOWN, WORK_COUNTDOWN, models_q_lease_free, _worker_id,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Lease (same compare-and-swap pattern as the wave runner)
# --------------------------------------------------------------------------- #

def claim_pipeline(run_id, lease_seconds: int = LEASE_SECONDS, owner: Optional[str] = None) -> bool:
    now = timezone.now()
    updated = (BatchPipelineRun.objects
               .filter(id=run_id)
               .exclude(status__in=BatchPipelineRun.TERMINAL_STATUSES)
               .filter(models_q_lease_free(now))
               .update(leased_until=now + timedelta(seconds=lease_seconds),
                       lease_owner=owner or _worker_id(), last_progress_at=now))
    return updated == 1


def release_pipeline(run: BatchPipelineRun) -> None:
    run.leased_until = None
    run.lease_owner = None
    run.last_progress_at = timezone.now()
    run.save(update_fields=['leased_until', 'lease_owner', 'last_progress_at', 'updated_at'])


def find_stalled_pipelines():
    return (BatchPipelineRun.objects
            .exclude(status__in=BatchPipelineRun.TERMINAL_STATUSES)
            .filter(models_q_lease_free(timezone.now())))


# --------------------------------------------------------------------------- #
# Paper-set helpers
# --------------------------------------------------------------------------- #

def _papers_with_pdf(paper_ids) -> List[str]:
    ids = (Paper.objects.filter(id__in=paper_ids)
           .exclude(Q(pdf='') | Q(pdf__isnull=True)).values_list('id', flat=True))
    return [str(i) for i in ids]


def _papers_with_text(paper_ids) -> List[str]:
    ids = (Paper.objects.filter(id__in=paper_ids)
           .exclude(Q(full_text='') | Q(full_text__isnull=True)).values_list('id', flat=True))
    return [str(i) for i in ids]


def _papers_with_analysis(run: BatchPipelineRun) -> List[str]:
    ids = (PaperAnalysis.objects
           .filter(paper_id__in=run.paper_ids, configuration_name=run.configuration_name)
           .values_list('paper_id', flat=True).distinct())
    return [str(i) for i in ids]


def _du_ids_needing_analysis(run: BatchPipelineRun) -> List[str]:
    dus = DatasetUsage.objects.filter(
        paper_analysis__configuration_name=run.configuration_name,
        paper_analysis__paper_id__in=run.paper_ids)
    done = DatasetUsageAnalysis.objects.values_list('dataset_usage_id', flat=True)
    return [str(i) for i in dus.exclude(id__in=done).values_list('id', flat=True)]


def _set_stage(run: BatchPipelineRun, stage: str):
    run.stage = stage
    run.save(update_fields=['stage', 'updated_at'])


def _fail(run: BatchPipelineRun, reason: str):
    run.status = 'failed'
    run.error_details = {'reason': reason, 'stage': run.stage}
    run.save(update_fields=['status', 'error_details', 'updated_at'])
    logger.error("batch-pipeline %s FAILED at %s: %s", run.id, run.stage, reason)


def _complete(run: BatchPipelineRun):
    run.stage = 'done'
    run.status = 'completed'
    run.completed_at = timezone.now()
    run.save(update_fields=['stage', 'status', 'completed_at', 'updated_at'])
    logger.info("batch-pipeline %s COMPLETED", run.id)


# --------------------------------------------------------------------------- #
# Stage handlers — return {"state", "reschedule"} ; None reschedule = terminal/handed off
# --------------------------------------------------------------------------- #

# Fan-out stage completion is STATE-DERIVED with a bounded stall window — NOT a
# celery chord. Chords proved fragile in this deployment three separate times
# (collection, commit, and the pipeline's extract gate at 10k scale): a chord
# stalls FOREVER if any header task is hard-killed uncounted, which at corpus
# scale is a certainty (observed live: ~19/10,000 pathological PDFs exceeded
# the extraction time limit and the run froze at 9,981 done). A stage is done
# when its remaining-work count reaches zero, or when the count has not moved
# for STAGE_STALL_SECONDS (dead stragglers; logged and skipped).
STAGE_STALL_SECONDS = int(os.environ.get("PDL_STAGE_STALL_SECONDS", "900"))


def _stalled_complete(run: BatchPipelineRun, key: str, remaining: int) -> bool:
    """True iff `remaining` has been flat for STAGE_STALL_SECONDS. Progress is
    tracked in run.metadata[key] = [count, iso_timestamp]; any decrease resets
    the window."""
    from datetime import datetime
    now = timezone.now()
    prev = run.metadata.get(key)
    if prev and prev[0] == remaining:
        return (now - datetime.fromisoformat(prev[1])).total_seconds() >= STAGE_STALL_SECONDS
    run.metadata[key] = [remaining, now.isoformat()]
    run.save(update_fields=['metadata', 'updated_at'])
    return False


def _papers_pdf_no_text(paper_ids) -> int:
    return (Paper.objects.filter(id__in=paper_ids)
            .exclude(Q(pdf='') | Q(pdf__isnull=True))
            .filter(Q(full_text='') | Q(full_text__isnull=True)).count())


def _stage_extract(run: BatchPipelineRun) -> dict:
    from . import tasks
    if not run.extract_dispatched:
        papers = _papers_with_pdf(run.paper_ids)
        if not papers:
            _set_stage(run, 'step1'); return {"state": "extract:none", "reschedule": WORK_COUNTDOWN}
        for pid in papers:
            tasks.extract_paper_text_task.delay(pid, run.allow_ocr)
        run.extract_dispatched = True
        run.save(update_fields=['extract_dispatched', 'updated_at'])
        return {"state": "extract:dispatched", "reschedule": POLL_COUNTDOWN}
    remaining = _papers_pdf_no_text(run.paper_ids)
    if run.extract_done or remaining == 0 or _stalled_complete(run, 'extract_stall', remaining):
        if remaining:
            logger.warning("batch-pipeline %s: extract advancing with %d unextracted "
                           "stragglers (stalled %ss)", run.id, remaining, STAGE_STALL_SECONDS)
        run.extract_done = True
        run.save(update_fields=['extract_done', 'updated_at'])
        _set_stage(run, 'step1'); return {"state": "extract:done", "reschedule": WORK_COUNTDOWN}
    return {"state": "extract:waiting", "reschedule": POLL_COUNTDOWN}


def _stage_step1(run: BatchPipelineRun) -> dict:
    from . import tasks
    from .models import BatchJob
    if run.step1_batch_job_id is None:
        papers = _papers_with_text(run.paper_ids)
        if not papers:
            _fail(run, "no papers with text after extraction"); return {"state": "failed", "reschedule": None}
        # The inline submit serializes + uploads the whole cohort's prompts
        # (minutes at 10k+, well past the 300s lease). Extend the lease first so
        # the reconciler cannot start a second driver mid-submit and double-pay
        # step-1; release_pipeline resets it when this step returns.
        BatchPipelineRun.objects.filter(id=run.id).update(
            leased_until=timezone.now() + timedelta(seconds=3600))
        res = tasks.submit_batch_paper_analysis.apply(
            args=[papers, run.configuration_name], kwargs={'trigger_downstream': False}).result
        bj_id = (res or {}).get('batch_job_id')
        if not bj_id:
            _fail(run, f"step1 submit returned no batch_job_id: {res}"); return {"state": "failed", "reschedule": None}
        # Size-aware chunking can split step-1 into several jobs; track them all
        # (metadata, no schema change). The FK keeps pointing at the first for
        # display/back-compat.
        run.step1_batch_job_id = bj_id
        run.metadata['step1_batch_job_ids'] = res.get('batch_job_ids', [bj_id])
        run.save(update_fields=['step1_batch_job', 'metadata', 'updated_at'])
        return {"state": "step1:submitted", "reschedule": POLL_COUNTDOWN}
    job_ids = run.metadata.get('step1_batch_job_ids') or [run.step1_batch_job_id]
    jobs = list(BatchJob.objects.filter(id__in=job_ids))
    if not jobs:
        _fail(run, "step1 batch job vanished"); return {"state": "failed", "reschedule": None}
    if any(j.status not in ('completed', 'partially_failed', 'failed') for j in jobs):
        return {"state": "step1:waiting", "reschedule": POLL_COUNTDOWN}
    live = [j for j in jobs if j.status in ('completed', 'partially_failed')]
    if not live:
        _fail(run, "step1 batch failed"); return {"state": "failed", "reschedule": None}
    # RACE GUARD (found live, cohort_1k): poll_batch_job flips status to
    # 'completed' BEFORE firing the async ingest; PaperAnalyses are still being
    # written for minutes afterward. Advancing on status alone froze the
    # downstream run at the 600/989 papers ingested so far. completed_at is
    # stamped ONLY by ingest_batch_results at its very end — require it on
    # EVERY surviving job before advancing.
    if any(j.completed_at is None for j in live):
        return {"state": "step1:ingesting", "reschedule": POLL_COUNTDOWN}
    # A wholly-failed chunk just means its papers get no PaperAnalysis; the
    # downstream stage selects papers WITH analyses, so a partial cohort
    # proceeds rather than failing everyone.
    _set_stage(run, 'downstream'); return {"state": "step1:done", "reschedule": WORK_COUNTDOWN}


def _stage_downstream(run: BatchPipelineRun) -> dict:
    from . import batch_downstream as bd
    from . import tasks
    if run.downstream_run_id is None:
        papers = _papers_with_analysis(run)
        if not papers:
            _fail(run, "no PaperAnalysis after step1"); return {"state": "failed", "reschedule": None}
        dr = bd.create_run(papers, run.configuration_name, run.aws_region_name,
                           corpus_mode=run.corpus_mode)
        run.downstream_run = dr
        run.save(update_fields=['downstream_run', 'updated_at'])
        tasks.advance_run_task.delay(str(dr.id))
        return {"state": "downstream:started", "reschedule": POLL_COUNTDOWN}
    dr = run.downstream_run
    if dr is None:
        _fail(run, "downstream run vanished"); return {"state": "failed", "reschedule": None}
    if dr.status == 'completed':
        _set_stage(run, 'analyze'); return {"state": "downstream:done", "reschedule": WORK_COUNTDOWN}
    if dr.status == 'failed':
        _fail(run, "downstream run failed"); return {"state": "failed", "reschedule": None}
    # keep the wave runner moving (belt-and-suspenders alongside its own reschedule)
    tasks.advance_run_task.delay(str(dr.id))
    return {"state": "downstream:waiting", "reschedule": POLL_COUNTDOWN}


def _stage_analyze(run: BatchPipelineRun) -> dict:
    from . import tasks
    if not run.analyze_dispatched:
        du_ids = _du_ids_needing_analysis(run)
        if not du_ids:
            _complete(run); return {"state": "analyze:none", "reschedule": None}
        for d in du_ids:
            tasks.analyze_dataset_usage.delay(d, run.run_execution)
        run.analyze_dispatched = True
        run.save(update_fields=['analyze_dispatched', 'updated_at'])
        return {"state": "analyze:dispatched", "reschedule": POLL_COUNTDOWN}
    remaining = len(_du_ids_needing_analysis(run))
    if run.analyze_done or remaining == 0 or _stalled_complete(run, 'analyze_stall', remaining):
        if remaining:
            logger.warning("batch-pipeline %s: analyze advancing with %d unanalyzed "
                           "stragglers (stalled %ss)", run.id, remaining, STAGE_STALL_SECONDS)
        run.analyze_done = True
        run.save(update_fields=['analyze_done', 'updated_at'])
        _complete(run); return {"state": "completed", "reschedule": None}
    return {"state": "analyze:waiting", "reschedule": POLL_COUNTDOWN}


_STAGES = {
    'extract': _stage_extract, 'step1': _stage_step1,
    'downstream': _stage_downstream, 'analyze': _stage_analyze,
}


def advance_pipeline(run_id, owner: Optional[str] = None) -> dict:
    """Drive the pipeline one idempotent step, chosen from durable DB state."""
    if not claim_pipeline(run_id, owner=owner):
        return {"state": "busy_or_terminal", "reschedule": None}
    try:
        run = BatchPipelineRun.objects.get(id=run_id)
        handler = _STAGES.get(run.stage)
        if handler is None:
            return {"state": "done", "reschedule": None}
        res = handler(run)
        if res.get("reschedule"):
            release_pipeline(run)
        return res
    except Exception:
        try:
            release_pipeline(BatchPipelineRun.objects.get(id=run_id))
        except Exception:  # noqa: BLE001
            pass
        raise


def create_pipeline(paper_ids, configuration_name, aws_region_name=None,
                    allow_ocr=False, run_execution=False,
                    corpus_mode=False) -> BatchPipelineRun:
    return BatchPipelineRun.objects.create(
        configuration_name=configuration_name, aws_region_name=aws_region_name,
        paper_ids=[str(p) for p in paper_ids], allow_ocr=allow_ocr,
        run_execution=run_execution, corpus_mode=corpus_mode,
        stage='extract', status='running')
