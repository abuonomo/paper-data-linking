"""Wave-synchronous batch-downstream orchestrator (crash-safe / resumable).

Drives a corpus of papers through the downstream pipeline using Bedrock batch
inference instead of synchronous on-demand calls, WITHOUT changing any pipeline
logic. Each paper's prefix (structuring -> grounding -> normalization) is
re-executed in 'collection' mode: resolved LLM calls are served from the durable
CachedLLMResponse cache, and the first un-resolved call per branch is deferred into
the current Bedrock batch wave (PendingBatch). When a paper's prefix resolves with
no deferrals it is replayed once in 'commit' mode (warm cache) to write every side
effect — LLMCall, PipelineNode, DatasetUsage, quotes — exactly once.

Safety model (so a corpus run never loses work):
  * ALL state is durable in Postgres (BatchDownstreamRun / RunPaper /
    CachedLLMResponse / BatchJob); Bedrock results are durable in S3. Nothing
    lives in worker memory. Per-paper progress is a RunPaper state machine —
    chunk workers claim rows with bulk row-level UPDATEs and apply outcomes the
    same way, so there are no global locks, no O(run-size) list rewrites, and no
    round counters to storm or wedge; stale claims from dead chunks are reclaimed
    by the driver.
  * ``advance_run`` is a single IDEMPOTENT driver that derives the next action
    purely from DB state, so a crash anywhere resumes correctly on the next call.
  * A lease ensures only one worker drives a run at a time; a crashed worker's lease
    expires and the run becomes claimable again.
  * ``reconcile_runs`` (Celery beat) re-kicks any non-terminal run whose lease has
    gone stale — the crash-proof backstop.
  * Ingest is idempotent; a model-group below Bedrock's 100-record floor (and any
    straggler) is resolved synchronously instead.
"""

from __future__ import annotations

import logging
import os
import socket
from datetime import timedelta
from typing import Callable, List, Optional

from django.db import transaction
from django.utils import timezone

from paper_data_linking.pipeline_context import batch_execution
from paper_data_linking.clients.batch_replay import PendingBatch
from paper_data_linking.clients.batch_client import BatchClient
from paper_data_linking.clients.litellm_client import LiteLLMClient
from .models import BatchDownstreamRun, BatchJob, CachedLLMResponse, PaperAnalysis, RunPaper

logger = logging.getLogger(__name__)

# Base lease is SHORT and renewed via heartbeat from inside long driver steps
# (per job submitted/ingested, per N rows applied). The 40k synthetic rehearsal
# showed why: a worker killed mid-step orphans the lease, and at corpus scale
# steps are long enough that mid-step death is LIKELY — a 30-min lease turned a
# kill/resume drill into a 29-minute dead zone. Short lease + heartbeat bounds
# any crash's dead zone to ~LEASE_SECONDS.
LEASE_SECONDS = int(os.environ.get("PDL_LEASE_SECONDS", "300"))
# Re-check an in-flight batch wave every minute. Env-overridable so the
# fake-Bedrock stack can poll fast (real Bedrock jobs take ~1h; the fake takes
# seconds, and at 60s the countdown dominates E2E wall clock: 14 waves ≈ 12 min
# of mostly waiting).
POLL_COUNTDOWN = int(os.environ.get("PDL_POLL_COUNTDOWN", "60"))
WORK_COUNTDOWN = 5            # quick hop between local (collection/commit/submit) steps
MIN_BEDROCK_RECORDS = 100     # Bedrock batch floor; smaller groups resolve synchronously
MAX_RECORDS_PER_JOB = 50_000  # Bedrock record ceiling per job (quota: 100k)
# Bedrock enforces a 1GB ceiling on the batch INPUT FILE — with real prompts
# (~20-25KB once catalog content is embedded) that binds well before 50k
# records. Jobs are therefore cut by BYTES as well as records; 512MB keeps a
# comfortable margin and bounds the per-job JSONL buffer in worker memory.
MAX_JOB_BYTES = int(os.environ.get("PDL_MAX_JOB_BYTES", str(512 * 1024 * 1024)))
COLLECTION_CHUNK_SIZE = 50    # papers per collection task: small enough (~minutes)
                              # that control tasks (advance/reconcile/poll) never sit
                              # behind giant chunks on the shared gevent worker
MAX_CALL_ATTEMPTS = 6         # transient-retry cap per call before it becomes terminal
COMMIT_CHUNK_SIZE = 10        # papers per prefork commit task (must finish well
                              # inside the task time_limit; ~10 x a few s/paper)
# A RunPaper claim older than this belongs to a dead chunk — reclaim it. The
# collect/commit chunk tasks are hard-killed at time_limit=660s, so any claim
# past 660s (+delivery slack) is provably orphaned; 900s bounds a killed
# chunk's dead zone to ~15 min (was 45, which the syn40k2 kill drill turned
# into a 45-min frontier stall).
CLAIM_STALE_SECONDS = int(os.environ.get("PDL_CLAIM_STALE_SECONDS", "900"))


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


# --------------------------------------------------------------------------- #
# Default prefix / commit / sync-resolver (call the real pipeline directly,
# bypassing the check_and_* gate wrappers so commit re-runs from the warm cache).
# --------------------------------------------------------------------------- #

def _synthetic_chain(paper_analysis_id: str, configuration_name: str) -> None:
    """TEST-HARNESS ONLY (PDL_SYNTHETIC_CHAIN=1, fake-Bedrock stack): a
    production-shaped call pattern — PDL_SYNTHETIC_BRANCHES independent branches
    of PDL_SYNTHETIC_DEPTH sequential dependent calls, each isolated like the
    grounder's per-branch retry loops — through the REAL chokepoint. Lets the
    full task path (RunPaper claims, waves, multi-job dispatch, commit fan-out)
    be rehearsed at corpus scale (tens of thousands of synthetic papers) with
    zero LLM cost. Never enabled in production (env unset => real pipeline)."""
    from .clients import DjangoLiteLLMClient
    branches = int(os.environ.get("PDL_SYNTHETIC_BRANCHES", "6"))
    depth = int(os.environ.get("PDL_SYNTHETIC_DEPTH", "2"))
    client = DjangoLiteLLMClient()
    model = "bedrock/converse/openai.gpt-oss-120b-1:0"
    for b in range(branches):
        try:
            content = f"{paper_analysis_id}/b{b}"
            for d in range(depth):
                resp = client.completion(
                    f"syn_b{b}_d{d}", model,
                    [{"role": "user", "content": content}], temperature=1.0)
                content = resp.choices[0].message.content
        except Exception:  # noqa: BLE001 — per-branch isolation, like the grounder
            continue


def _synthetic_mode() -> bool:
    return os.environ.get("PDL_SYNTHETIC_CHAIN") == "1"


def default_prefix_fn(paper_analysis_id: str, configuration_name: str) -> None:
    if _synthetic_mode():
        return _synthetic_chain(paper_analysis_id, configuration_name)
    from . import tasks
    tasks.analyze_paper_instruments_structure(paper_analysis_id, configuration_name)
    tasks.normalize_structured_instrument_details(paper_analysis_id, configuration_name)


def default_commit_fn(paper_analysis_id: str, configuration_name: str) -> None:
    """Replay the prefix from cache (writing LLMCall/PipelineNode once) then create
    the DatasetUsages — the science product.

    Deliberately STOPS before ``analyze_paper_dataset_usages``: that stage runs
    ``analyze_dataset_usage`` (bandit subprocess + exec/Fido, no timeout) which
    deterministically wedges the --pool=gevent worker at scale. DUs (instrument /
    observatory / window) are complete after ``create_dataset_usages``; snippet
    generation, if needed, is a separate prefork-pool job with a task_time_limit.
    """
    if _synthetic_mode():
        # Rehearsal commit = replay the synthetic chain from the warm cache
        # (exercises LLMCall writes + state transitions); no DU materialization.
        return _synthetic_chain(paper_analysis_id, configuration_name)
    from . import tasks
    pa = PaperAnalysis.objects.get(id=paper_analysis_id)
    tasks.analyze_paper_instruments_structure(paper_analysis_id, configuration_name)
    tasks.normalize_structured_instrument_details(paper_analysis_id, configuration_name)
    result = {
        "success": True,
        "paper_id": str(pa.paper_id),
        "paper_analysis_id": str(paper_analysis_id),
        "paper_bibcode": pa.paper.bibcode,
    }
    tasks.create_dataset_usages(result)


def default_sync_resolver(rows: List[CachedLLMResponse]) -> List[dict]:
    """Resolve a handful of calls with on-demand (non-batch) inference — used for
    sub-100-record groups and stragglers. Uses the side-effect-free base client."""
    client = LiteLLMClient()
    out = []
    for r in rows:
        p = r.request_payload or {}
        kwargs = dict(p.get("params") or {})
        # Structured-output calls carry a forced tool (not response_format) — pass it
        # through so the sync path enforces the same schema as the batch path.
        if p.get("tools"):
            kwargs["tools"] = p["tools"]
            if p.get("tool_choice"):
                kwargs["tool_choice"] = p["tool_choice"]
        try:
            resp = client.completion(r.call_type or "downstream", p["model"], p["messages"], **kwargs)
            usage = getattr(resp, "usage", None)
            content = _content_or_tool_args(resp)
            out.append({
                "custom_id": r.request_hash,
                "content": content,
                "usage": {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                },
                "finish_reason": resp.choices[0].finish_reason if resp.choices else "",
            })
        except Exception as e:  # noqa: BLE001
            # Classify: transient provider errors get retried (fresh call next
            # dispatch) instead of being cached as terminal — matching the sync
            # pipeline's retry semantics, which the batch replay otherwise loses.
            from paper_data_linking.clients.batch_replay import is_transient_error
            err = str(e)
            key = "transient_error" if is_transient_error(err) else "error"
            out.append({"custom_id": r.request_hash, key: err})
    return out


def _content_or_tool_args(resp) -> str:
    """A forced tool call's arguments if present (reasoning is separate there),
    else the reasoning-stripped message content. litellm returns response objects,
    so tool_calls are attributes, not dicts."""
    from paper_data_linking.clients.batch_replay import strip_reasoning
    if not getattr(resp, "choices", None):
        return ""
    msg = getattr(resp.choices[0], "message", None)
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        if fn is not None and getattr(fn, "arguments", None):
            return fn.arguments
    return strip_reasoning(getattr(msg, "content", None) if msg else None) or ""


def _paper_analysis_id(run: BatchDownstreamRun, paper_id: str) -> Optional[str]:
    pa = (PaperAnalysis.objects
          .filter(paper_id=paper_id, configuration_name=run.configuration_name)
          .order_by('-created_at').first())
    return str(pa.id) if pa else None


# --------------------------------------------------------------------------- #
# Lease (crash-safe single-writer)
# --------------------------------------------------------------------------- #

def claim_run(run_id, lease_seconds: int = LEASE_SECONDS, owner: Optional[str] = None) -> bool:
    """Atomically claim a non-terminal run whose lease is free/expired. Returns
    True iff this caller won the claim (a DB-level compare-and-swap)."""
    now = timezone.now()
    owner = owner or _worker_id()
    updated = (BatchDownstreamRun.objects
               .filter(id=run_id)
               .exclude(status__in=BatchDownstreamRun.TERMINAL_STATUSES)
               .filter(models_q_lease_free(now))
               .update(leased_until=now + timedelta(seconds=lease_seconds),
                       lease_owner=owner, last_progress_at=now))
    return updated == 1


def models_q_lease_free(now):
    from django.db.models import Q
    return Q(leased_until__isnull=True) | Q(leased_until__lt=now)


def renew_lease(run_id, owner: str, lease_seconds: int = LEASE_SECONDS) -> bool:
    """Heartbeat: extend the lease iff we still own it. Called from inside long
    driver steps so a live driver never expires mid-step, while a dead one's
    lease lapses within LEASE_SECONDS. Returns False if ownership was lost
    (another driver took over after our lease expired) — callers may ignore it;
    every step is idempotent."""
    now = timezone.now()
    return (BatchDownstreamRun.objects
            .filter(id=run_id, lease_owner=owner)
            .update(leased_until=now + timedelta(seconds=lease_seconds),
                    last_progress_at=now)) == 1


def release_run(run: BatchDownstreamRun, *, free_immediately: bool = True) -> None:
    """Release the lease. ``free_immediately`` makes the run claimable right away
    (used between local steps); otherwise the existing lease simply runs out."""
    run.last_progress_at = timezone.now()
    if free_immediately:
        run.leased_until = None
        run.lease_owner = None
    run.save(update_fields=['leased_until', 'lease_owner', 'last_progress_at', 'updated_at'])


# --------------------------------------------------------------------------- #
# Per-paper state machine (RunPaper) — indexed UPDATEs, no list rewrites,
# no round counters: "is a round outstanding?" is an EXISTS on a claimed state.
# --------------------------------------------------------------------------- #

def state_counts(run: BatchDownstreamRun) -> dict:
    """One GROUP BY over the run's papers — the driver's whole worldview."""
    from django.db.models import Count
    counts = dict(RunPaper.objects.filter(run=run)
                  .values_list('state').annotate(n=Count('id'))
                  .values_list('state', 'n'))
    return {s: counts.get(s, 0) for s, _ in RunPaper.STATES}


def reclaim_stale_claims(run: BatchDownstreamRun,
                         stale_seconds: int = CLAIM_STALE_SECONDS) -> int:
    """Return rows claimed by evidently-dead chunks to their pre-claim state.
    (A chunk stamps dispatched_at when it claims; a live chunk finishes well
    inside the window.) Called at the top of every driver step."""
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    n = (RunPaper.objects
         .filter(run=run, state='collecting', dispatched_at__lt=cutoff)
         .update(state='pending', dispatched_at=None))
    # attempts++ on commit reclaims: a chunk of several heavyweight papers can
    # NEVER finish inside the task time limit (cohort_10k's final 30 ratchet-
    # stalled for hours) — the dispatcher commits attempts>0 papers SOLO.
    from django.db.models import F
    n += (RunPaper.objects
          .filter(run=run, state='committing', dispatched_at__lt=cutoff)
          .update(state='llm_complete', dispatched_at=None, attempts=F('attempts') + 1))
    if n:
        logger.warning("batch-downstream run=%s reclaimed %d stale chunk claims", run.id, n)
    return n


def active_paper_ids(run: BatchDownstreamRun) -> List[str]:
    """Papers not yet LLM-complete or failed — the set a collection pass re-runs."""
    return [str(p) for p in (RunPaper.objects
                             .filter(run=run, state='pending')
                             .values_list('paper_id', flat=True))]


def collect_papers(run: BatchDownstreamRun, paper_ids: List[str], prefix_fn: Callable,
                   heartbeat: Optional[Callable] = None) -> dict:
    """Re-execute the prefix in collection mode for a SUBSET of papers.

    DeferredCall exceptions are absorbed inside the pipeline's per-branch error
    handling (that's the frontier-discovery design), so completion is judged by the
    out-of-band deferred-call counter: a paper is LLM-complete only when its pass
    finishes with ZERO deferrals. An escaped exception with deferrals>0 just means
    a deferral unwound past an unisolated boundary — the paper stays in progress.

    Pure w.r.t. run progress: it only writes pending CachedLLMResponse rows (race-free
    via unique (run, request_hash)) and RETURNS the per-paper outcomes. This makes it
    safe to fan out across the fleet — each chunk returns its results and a single
    writer (``merge_collection_progress``) folds them into the run.
    """
    from paper_data_linking.pipeline_context import deferred_calls
    complete, failed = [], []
    for i, paper_id in enumerate(paper_ids):
        if heartbeat and i and i % 10 == 0:
            heartbeat()
        pa_id = _paper_analysis_id(run, paper_id)
        if pa_id is None:
            failed.append(paper_id)
            continue
        cell = [0]
        token = deferred_calls.set(cell)
        try:
            with batch_execution('collection', run.id):
                prefix_fn(pa_id, run.configuration_name)
        except Exception as e:  # noqa: BLE001
            if cell[0] == 0:
                logger.warning("batch-downstream: paper %s failed in collection: %s", paper_id, e)
                failed.append(paper_id)
            # deferrals>0: an (absorbed-elsewhere) deferral escaped — in progress.
            continue
        finally:
            deferred_calls.reset(token)
        if cell[0] == 0:
            complete.append(paper_id)
        # else: deferred calls registered — more waves needed for this paper.
    return {"complete": complete, "failed": failed}


def finish_collection_chunk(run_or_id, chunk_paper_ids: List[str], outcome: dict) -> dict:
    """Apply one chunk's collect_papers() outcomes to the state machine.
    Row-level UPDATEs on the chunk's own papers — no global lock, no counters.
    The state filter makes re-application (duplicate task delivery) a no-op.

    complete -> llm_complete;  failed -> failed;  the rest -> pending (more waves).
    """
    run_id = getattr(run_or_id, 'id', run_or_id)
    complete = set(outcome.get("complete", []))
    failed = set(outcome.get("failed", []))
    remaining = [p for p in chunk_paper_ids if p not in complete and p not in failed]
    claimable = ('pending', 'collecting')   # 'pending' covers the inline (sync) driver
    base = RunPaper.objects.filter(run_id=run_id, state__in=claimable)
    n = base.filter(paper_id__in=list(complete)).update(
        state='llm_complete', dispatched_at=None)
    n += base.filter(paper_id__in=list(failed)).update(
        state='failed', dispatched_at=None, error='failed in collection')
    n += base.filter(paper_id__in=remaining).update(
        state='pending', dispatched_at=None)
    return {"updated": n, "complete": len(complete), "failed": len(failed)}


def run_collection_pass(run: BatchDownstreamRun, prefix_fn: Callable,
                        heartbeat: Optional[Callable] = None) -> dict:
    """Serial collection over all active papers (used by the sync driver)."""
    papers = active_paper_ids(run)
    res = collect_papers(run, papers, prefix_fn, heartbeat=heartbeat)
    finish_collection_chunk(run, papers, res)
    return res


def pending_rows(run: BatchDownstreamRun):
    return CachedLLMResponse.objects.filter(run=run, status='pending')


def inflight_jobs(run: BatchDownstreamRun):
    job_ids = (CachedLLMResponse.objects
               .filter(run=run, status='batched', batch_job__isnull=False)
               .values_list('batch_job_id', flat=True).distinct())
    return BatchJob.objects.filter(id__in=list(job_ids)).exclude(
        status__in=['completed', 'failed', 'partially_failed'])


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _pending_models(run: BatchDownstreamRun) -> dict:
    """{model: pending_row_count} via a DB aggregate (no row loading)."""
    from django.db.models import Count
    from django.db.models.fields.json import KeyTextTransform
    return dict(pending_rows(run)
                .annotate(_model=KeyTextTransform('model', 'request_payload'))
                .values_list('_model').annotate(n=Count('id'))
                .values_list('_model', 'n'))


def _submit_job(run, batch_client, *, lines, row_ids, model, provider, region,
                role_arn) -> None:
    """Submit one batch job from pre-serialized JSONL lines and mark its rows."""
    jsonl = "\n".join(lines)
    batch_model = model.rsplit("/", 1)[-1] if (provider == "bedrock" and "/" in model) else model
    submit_result = batch_client.submit(
        jsonl, provider=provider, model_name=batch_model,
        aws_region_name=region, aws_batch_role_arn=role_arn)
    job = BatchJob.objects.create(
        batch_id=submit_result["batch_id"],
        input_file_id=submit_result.get("input_file_id"),
        status="submitted", provider=provider,
        configuration_name=run.configuration_name, aws_region_name=region,
        total_requests=len(row_ids), submitted_at=timezone.now())
    CachedLLMResponse.objects.filter(id__in=row_ids).update(
        status='batched', wave=run.current_wave, batch_job=job)
    logger.info("batch-downstream run=%s wave=%s job=%s records=%s bytes=%s model=%s",
                run.id, run.current_wave, job.batch_id, len(row_ids),
                sum(len(l) + 1 for l in lines), model)


def dispatch_wave(
    run: BatchDownstreamRun,
    batch_client: BatchClient,
    *,
    aws_region_name: Optional[str] = None,
    aws_batch_role_arn: Optional[str] = None,
    provider: str = "bedrock",
    min_batch_size: int = MIN_BEDROCK_RECORDS,
    sync_resolver: Callable = default_sync_resolver,
    heartbeat: Optional[Callable] = None,
) -> dict:
    """Submit this wave's pending calls. Per model group: batch if >= min_batch_size,
    else resolve synchronously. Jobs are cut at MAX_RECORDS_PER_JOB records OR
    MAX_JOB_BYTES of JSONL, whichever comes first (Bedrock's 1GB input-file limit
    binds before the record limit with real prompt sizes).

    STREAMS rows from the DB (iterator + per-row serialization) instead of
    loading the whole wave: a corpus wave is 10^5-10^6 rows x 10-30KB payloads —
    materializing it as ORM objects was a multi-GB spike. Peak memory is now one
    job's JSONL lines (bounded by MAX_JOB_BYTES). ``heartbeat`` (if given) is
    called after each job submit to renew the driver lease. Returns counts;
    ``batched_jobs`` > 0 means the caller should wait/poll before continuing."""
    model_counts = _pending_models(run)
    if not model_counts:
        return {"batched_jobs": 0, "sync_resolved": 0}
    region = aws_region_name or run.aws_region_name
    role_arn = aws_batch_role_arn or os.environ.get("AWS_BATCH_ROLE_ARN")

    batched_jobs, sync_resolved, sync_retried = 0, 0, 0
    for model, n_rows in model_counts.items():
        model_q = pending_rows(run).filter(request_payload__model=model)
        if model is None:
            logger.warning("batch-downstream run=%s: %d pending rows without a model "
                           "in request_payload — left pending", run.id, n_rows)
            continue
        if n_rows < min_batch_size:
            model_rows = list(model_q)   # small by definition
            results = sync_resolver(model_rows)
            ar = apply_results(run, model_rows, results)
            sync_resolved += ar["resolved"]
            sync_retried += ar.get("retried", 0)
            continue
        lines, row_ids, nbytes = [], [], 0
        for r in model_q.iterator(chunk_size=2000):
            p = r.request_payload or {}
            line = batch_client.prepare_generic_requests([{
                "record_id": r.request_hash, "model": model,
                "messages": p.get("messages"),
                "params": p.get("params") or {},
                "tools": p.get("tools"),
                "tool_choice": p.get("tool_choice"),
            }], provider=provider)
            if (row_ids and
                    (len(row_ids) >= MAX_RECORDS_PER_JOB
                     or nbytes + len(line) + 1 > MAX_JOB_BYTES)):
                _submit_job(run, batch_client, lines=lines, row_ids=row_ids,
                            model=model, provider=provider, region=region,
                            role_arn=role_arn)
                batched_jobs += 1
                if heartbeat:
                    heartbeat()
                lines, row_ids, nbytes = [], [], 0
            lines.append(line)
            row_ids.append(r.id)
            nbytes += len(line) + 1
        if row_ids:
            _submit_job(run, batch_client, lines=lines, row_ids=row_ids,
                        model=model, provider=provider, region=region,
                        role_arn=role_arn)
            batched_jobs += 1
            if heartbeat:
                heartbeat()

    run.current_wave += 1
    run.save(update_fields=['current_wave', 'updated_at'])
    return {"batched_jobs": batched_jobs, "sync_resolved": sync_resolved,
            "sync_retried": sync_retried}


def apply_results(run: BatchDownstreamRun, rows, results: List[dict],
                  heartbeat: Optional[Callable] = None) -> dict:
    """Idempotently write batch/sync results onto CachedLLMResponse rows.

    Three outcomes:
      * content        -> 'resolved'
      * transient error / missing -> keep RETRYABLE ('pending', attempts++) until the
        cap, then terminal 'failed'. A retried row re-dispatches next wave for a fresh
        attempt (the whole point — the sync pipeline recovers from transient Bedrock
        errors this way; the naive batch cache did not).
      * permanent error -> terminal 'failed'
    Re-applying to already-resolved rows is a no-op. ``heartbeat`` (if given) is
    called every ~1000 rows to renew the driver lease — a corpus wave ingests
    10^5-10^6 rows, which outruns a short lease.
    """
    by_hash = {r.get("custom_id"): r for r in results}
    resolved, failed, retried = 0, 0, 0
    for i, row in enumerate(rows):
        if heartbeat and i and i % 1000 == 0:
            heartbeat()
        if row.status == 'resolved':
            continue
        res = by_hash.get(row.request_hash)
        # Missing from output OR an explicit transient marker -> retryable.
        transient = res is None or "transient_error" in res
        permanent = res is not None and "error" in res
        if transient and not permanent:
            row.attempts += 1
            if row.attempts >= MAX_CALL_ATTEMPTS:
                row.status = 'failed'
                row.error = "transient after %d attempts: %s" % (
                    row.attempts, (res or {}).get("transient_error", "missing from output"))
                row.resolved_at = timezone.now()
                row.save(update_fields=['status', 'error', 'attempts', 'resolved_at'])
                failed += 1
            else:
                row.status = 'pending'   # retry: re-dispatched next wave, fresh attempt
                row.error = None
                row.batch_job = None
                row.save(update_fields=['status', 'error', 'batch_job', 'attempts'])
                retried += 1
            continue
        if permanent:
            row.status = 'failed'
            row.error = res["error"]
            row.resolved_at = timezone.now()
            row.save(update_fields=['status', 'error', 'resolved_at'])
            failed += 1
            continue
        row.status = 'resolved'
        row.response_content = res.get("content", "")
        row.usage = res.get("usage", {}) or {}
        row.finish_reason = res.get("finish_reason", "")
        row.resolved_at = timezone.now()
        # Payload lifecycle: a resolved row's request payload (full prompt,
        # 10-30KB) serves nothing — replay reads response_content by hash, and
        # the batch input JSONL is archived in S3. Dropping it here keeps the
        # cache table O(responses), not O(prompts). Failed rows keep theirs
        # (they are the debugging targets); retryable rows need theirs to
        # re-dispatch.
        row.request_payload = {}
        row.save(update_fields=['status', 'response_content', 'usage', 'finish_reason',
                                'resolved_at', 'request_payload'])
        resolved += 1
    return {"resolved": resolved, "failed": failed, "retried": retried}


def progress_inflight_jobs(run: BatchDownstreamRun, batch_client: BatchClient,
                           poll: Optional[Callable] = None,
                           heartbeat: Optional[Callable] = None) -> dict:
    """Poll in-flight jobs; ingest any that completed. Returns whether any remain.
    ``heartbeat`` renews the driver lease once per job (each ingest is an S3
    download + 10^4-10^5 row writes) and is forwarded into apply_results."""
    jobs = list(inflight_jobs(run))
    if not jobs:
        return {"still_processing": 0, "ingested": 0}
    if poll is None:
        def poll(job):
            return batch_client.retrieve_results(
                job.batch_id, provider=job.provider, aws_region_name=job.aws_region_name)

    still, ingested = 0, 0
    for job in jobs:
        if heartbeat:
            heartbeat()
        status = batch_client.check_status(
            job.batch_id, provider=job.provider, aws_region_name=job.aws_region_name)
        if status["status"] in ("completed",):
            rows = CachedLLMResponse.objects.filter(run=run, batch_job=job)
            res = apply_results(run, list(rows), poll(job), heartbeat=heartbeat)
            job.status = 'completed'; job.completed_at = timezone.now()
            job.completed_requests = res["resolved"]; job.failed_requests = res["failed"]
            job.save(update_fields=['status', 'completed_at', 'completed_requests', 'failed_requests'])
            ingested += 1
        elif status["status"] in ("failed", "cancelled", "expired"):
            # A whole-job failure is usually transient (infra / quota / region) — retry
            # its records (up to the per-call cap) rather than killing those papers.
            rows = list(CachedLLMResponse.objects.filter(run=run, batch_job=job, status='batched'))
            apply_results(run, rows, [
                {"custom_id": r.request_hash, "transient_error": f"batch job {status['status']}"}
                for r in rows], heartbeat=heartbeat)
            job.status = 'failed'; job.completed_at = timezone.now()
            job.save(update_fields=['status', 'completed_at'])
            ingested += 1
        else:
            still += 1
    return {"still_processing": still, "ingested": ingested}


def commit_single_paper(run: BatchDownstreamRun, paper_id: str,
                        commit_fn: Callable = None) -> dict:
    """Commit ONE paper (replay from warm cache; writes LLMCall/nodes/DUs once).
    Designed to run as an isolated prefork task: the gevent worker's shared-process
    connection churn (@close_db_connection from concurrent tasks) breaks a long
    in-process commit loop with InterfaceError('connection already closed').

    Idempotency across lost bookkeeping (e.g. a chunk killed before its chord
    merged): if this run already wrote PipelineNodes for the paper, the replay
    already happened — skip it (avoiding duplicate LLMCall/node rows) and just
    re-run the idempotent DU materialization to backfill anything interrupted.
    """
    from .models import PipelineNode
    commit_fn = commit_fn or default_commit_fn
    pa_id = _paper_analysis_id(run, paper_id)
    try:
        already = PipelineNode.objects.filter(
            analysis_id=pa_id, started_at__gte=run.created_at).exists()
        if already:
            from . import tasks
            pa = PaperAnalysis.objects.get(id=pa_id)
            # Run the skip-replay path INSIDE the commit context too: the
            # corpus-mode gates (deferred quote embeddings, etc.) key off
            # pipeline_mode + current_batch_run_id, and re-entered commits
            # (crash recovery, stale-claim reclaim) take exactly this path —
            # observed live in the prod sentinel's kill/resume drill, where
            # guard-path quotes were eagerly sync-embedded outside the context.
            with batch_execution('commit', run.id):
                tasks.create_dataset_usages({
                    "success": True, "paper_id": str(pa.paper_id),
                    "paper_analysis_id": str(pa_id), "paper_bibcode": pa.paper.bibcode,
                })
            return {"paper_id": paper_id, "committed": True, "skipped_replay": True}
        with batch_execution('commit', run.id):
            commit_fn(pa_id, run.configuration_name)
    except Exception as e:  # noqa: BLE001
        logger.warning("batch-downstream: paper %s failed in commit: %s", paper_id, e)
        return {"paper_id": paper_id, "committed": False}
    return {"paper_id": paper_id, "committed": True}


def finish_commit_chunk(run_or_id, results: List[dict]) -> dict:
    """Apply per-paper commit outcomes to the state machine. Row-level UPDATEs
    filtered by claimed state — duplicate task delivery is a no-op. Chord-free:
    the prefork(header) -> gevent(callback) chord callback silently never fires
    in this deployment (observed live)."""
    run_id = getattr(run_or_id, 'id', run_or_id)
    committed = [r["paper_id"] for r in results if r and r.get("committed")]
    failed = [r["paper_id"] for r in results if r and not r.get("committed")]
    claimable = ('llm_complete', 'committing')   # 'llm_complete' covers the inline driver
    base = RunPaper.objects.filter(run_id=run_id, state__in=claimable)
    n = base.filter(paper_id__in=committed).update(state='committed', dispatched_at=None)
    n += base.filter(paper_id__in=failed).update(
        state='failed', dispatched_at=None, error='failed in commit')
    return {"updated": n, "committed": len(committed), "failed": len(failed)}


# Max papers claimed/queued for commit at once. Commit dispatch must be a
# BOUNDED top-up, not an unbounded fan-out: at 10k papers the old
# claim-everything dispatch queued ~1,000 chunks (hours of queue latency), so
# claims aged past CLAIM_STALE_SECONDS while still QUEUED, were reclaimed and
# re-dispatched as duplicates, and the duplicates compounded until real commit
# throughput collapsed (observed live, cohort_10k: 27/min -> 2.7/min under 12k
# queued messages). A small in-flight budget keeps claim age ~= execution age,
# which is the invariant the stale-claim reclaim depends on.
COMMIT_MAX_IN_FLIGHT = int(os.environ.get("PDL_COMMIT_MAX_IN_FLIGHT", "120"))


def dispatch_parallel_commit(run_id, chunk_size: int = COMMIT_CHUNK_SIZE) -> int:
    """Top up the commit fleet: claim at most (COMMIT_MAX_IN_FLIGHT - already
    committing) llm_complete rows (-> committing, row-level UPDATE) and dispatch
    them as chunk tasks. Finishing chunks re-enter the driver, which calls this
    again — so the fleet stays fed without ever queueing deep. A duplicate
    dispatcher tops up at most to the same cap, then claims nothing."""
    from . import tasks
    now = timezone.now()
    in_flight = RunPaper.objects.filter(run_id=run_id, state='committing').count()
    budget = COMMIT_MAX_IN_FLIGHT - in_flight
    if budget <= 0:
        return 0
    target_ids = list(RunPaper.objects
                      .filter(run_id=run_id, state='llm_complete')
                      .values_list('id', flat=True)[:budget])
    if not target_ids:
        tasks.advance_run_task.delay(str(run_id))
        return 0
    # Row-level claim of just this round's targets, then read back THIS claim's
    # rows by its unique stamp. A racing dispatcher claims a disjoint set.
    RunPaper.objects.filter(id__in=target_ids, state='llm_complete').update(
        state='committing', dispatched_at=now)
    claimed = [str(p) for p in RunPaper.objects
               .filter(id__in=target_ids, state='committing', dispatched_at=now)
               .values_list('paper_id', flat=True)]
    if not claimed:
        tasks.advance_run_task.delay(str(run_id))
        return 0
    # Papers already reclaimed once (attempts>0) commit SOLO: a chunk of
    # several multi-minute heavyweights can never beat the task time limit —
    # retried as singles, each fits (cohort_10k final-30 ratchet stall).
    retried = set(RunPaper.objects.filter(
        run_id=run_id, paper_id__in=claimed, attempts__gt=0)
        .values_list('paper_id', flat=True))
    retried = {str(p) for p in retried}
    fresh = [p for p in claimed if p not in retried]
    chunks = [list(c) for c in _chunks(fresh, chunk_size)] + [[p] for p in retried]
    for c in chunks:
        tasks.commit_chunk_task.delay(str(run_id), c)
    return len(chunks)


def commit_papers(run: BatchDownstreamRun, commit_fn: Callable,
                  heartbeat: Optional[Callable] = None) -> dict:
    """Inline commit over all LLM-complete papers (sync driver / tests)."""
    results = []
    for paper_id in [str(p) for p in RunPaper.objects.filter(run=run, state='llm_complete')
                     .values_list('paper_id', flat=True)]:
        if heartbeat:
            heartbeat()
        # NOTE: commit_single_paper is deliberately NOT wrapped in
        # transaction.atomic() — the commit tasks carry @close_db_connection, and
        # closing the connection inside an atomic block raises
        # InterfaceError('connection already closed'). Crash-safety comes from
        # idempotency instead: every commit-path write uses
        # get_or_create/update_or_create natural keys.
        results.append(commit_single_paper(run, paper_id, commit_fn))
    out = finish_commit_chunk(run, results)
    return {"committed": out["committed"], "failed": out["failed"]}


# --------------------------------------------------------------------------- #
# The idempotent driver — one step, derived purely from DB state.
# --------------------------------------------------------------------------- #

def advance_run(
    run_id,
    batch_client: Optional[BatchClient] = None,
    *,
    prefix_fn: Optional[Callable] = None,
    commit_fn: Optional[Callable] = None,
    sync_resolver: Optional[Callable] = None,
    min_batch_size: Optional[int] = None,
    provider: str = "bedrock",
    poll: Optional[Callable] = None,
    owner: Optional[str] = None,
    collect: bool = True,
) -> dict:
    """Drive a run forward by one step. Idempotent and resumable: the action is
    chosen from current DB state, so calling it repeatedly (normal countdown chain
    or the reconciler) converges the run to completion. Returns
    {"state": ..., "reschedule": countdown|None}.
    """
    # Resolve the owner BEFORE claiming so the heartbeat closure renews the same
    # identity the claim stamped (claim_run defaults internally otherwise).
    owner = owner or _worker_id()
    if not claim_run(run_id, owner=owner):
        return {"state": "busy_or_terminal", "reschedule": None}
    heartbeat = lambda: renew_lease(run_id, owner)  # noqa: E731

    if min_batch_size is None:
        # PDL_MIN_BATCH_SIZE: the fake-Bedrock test stack sets this to 1 so even
        # sub-100 groups go through the (fake) batch path instead of the live
        # sync fallback — no live LLM calls in offline E2E runs.
        min_batch_size = int(os.environ.get("PDL_MIN_BATCH_SIZE", MIN_BEDROCK_RECORDS))
    prefix_fn = prefix_fn or default_prefix_fn
    commit_fn = commit_fn or default_commit_fn
    sync_resolver = sync_resolver or default_sync_resolver
    batch_client = batch_client or BatchClient()
    try:
        run = BatchDownstreamRun.objects.get(id=run_id)

        # 0) Return any rows stranded by dead chunks to a workable state.
        reclaim_stale_claims(run)

        # 1) Make progress on any in-flight batch wave first.
        prog = progress_inflight_jobs(run, batch_client, poll=poll, heartbeat=heartbeat)
        if prog["still_processing"]:
            release_run(run, free_immediately=True)
            return {"state": "waiting_batch", "reschedule": POLL_COUNTDOWN}

        # 2) Dispatch any pending calls a collection pass already discovered.
        def _dispatch():
            disp = dispatch_wave(run, batch_client, provider=provider,
                                 min_batch_size=min_batch_size, sync_resolver=sync_resolver,
                                 heartbeat=heartbeat)
            if disp["batched_jobs"]:
                run.status = 'batching'
                run.save(update_fields=['status', 'updated_at'])
                release_run(run, free_immediately=True)
                return {"state": "submitted_wave", "reschedule": POLL_COUNTDOWN}
            if disp["sync_resolved"]:
                release_run(run, free_immediately=True)
                return {"state": "sync_resolved", "reschedule": WORK_COUNTDOWN}
            if disp.get("sync_retried"):
                # Only transient retries this pass (no progress) — back off so the
                # provider can recover instead of hammering it every few seconds.
                release_run(run, free_immediately=True)
                return {"state": "retrying_transient", "reschedule": POLL_COUNTDOWN}
            return None

        if pending_rows(run).exists():
            out = _dispatch()
            if out:
                return out

        # 3) Discover the next frontier. The sync driver collects inline; the async
        #    (fleet-parallel) driver gets this signal and fans collection out.
        #    PENDING papers are dispatched even while other papers are still
        #    'collecting' — claims are race-safe row-level UPDATEs, and gating on
        #    stragglers let a killed chunk freeze the whole frontier until stale
        #    reclaim (observed in the syn40k2 kill drill: 2400 orphaned claims
        #    blocked 37600 ready papers).
        counts = state_counts(run)
        if counts['pending']:
            if not collect:
                release_run(run, free_immediately=True)
                return {"state": "need_collection", "reschedule": None}
            run_collection_pass(run, prefix_fn, heartbeat=heartbeat)
            if pending_rows(run).exists():
                out = _dispatch()
                if out:
                    return out
            # Collection finished some papers without new calls — re-loop to commit.
            release_run(run, free_immediately=True)
            return {"state": "collected", "reschedule": WORK_COUNTDOWN}
        if counts['collecting']:
            # No pending papers, but dispatched chunks are still running; they
            # re-enter the driver as they finish. The countdown is only a
            # liveness backstop (stale claims are reclaimed at step 0).
            release_run(run, free_immediately=True)
            return {"state": "collection_in_progress", "reschedule": POLL_COUNTDOWN}

        # 4) Nothing pending -> everyone is LLM-complete (or failed). Commit.
        if counts['committing']:
            release_run(run, free_immediately=True)
            return {"state": "commit_in_progress", "reschedule": POLL_COUNTDOWN}
        if counts['llm_complete']:
            run.status = 'committing'
            run.save(update_fields=['status', 'updated_at'])
            if not collect:
                # Async path: fan commit out to the prefork cpu workers — a long
                # in-process loop on the gevent worker gets its DB connection
                # yanked by concurrent tasks' @close_db_connection.
                release_run(run, free_immediately=True)
                return {"state": "need_commit", "reschedule": None}
            commit_papers(run, commit_fn, heartbeat=heartbeat)
        if run.corpus_mode:
            prune_run_payloads(run)
        run.status = 'completed'
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'completed_at', 'updated_at'])
        release_run(run, free_immediately=True)
        if run.corpus_mode:
            # Corpus commits defer quote embeddings + coordinates; kick the
            # trailing sweeps NOW for promptness (issue #175) — the beat tick
            # stays as the self-healing backstop. Both are idempotent, and
            # embed_missing_quotes self-chains until the backlog is drained.
            from . import tasks
            tasks.embed_missing_quotes.delay()
            tasks.submit_batch_enrich_coordinates.delay(
                configuration_name=run.configuration_name)
        return {"state": "completed", "reschedule": None}
    except Exception:
        # Never hold a lease through an unexpected error — let the reconciler retry.
        try:
            release_run(BatchDownstreamRun.objects.get(id=run_id), free_immediately=True)
        except Exception:  # noqa: BLE001
            pass
        raise


def drive_run_synchronously(
    run: BatchDownstreamRun,
    batch_client: BatchClient,
    prefix_fn: Callable = default_prefix_fn,
    commit_fn: Callable = default_commit_fn,
    sync_resolver: Callable = default_sync_resolver,
    min_batch_size: int = MIN_BEDROCK_RECORDS,
    provider: str = "bedrock",
    poll: Optional[Callable] = None,
    max_steps: int = 256,
) -> BatchDownstreamRun:
    """Run the whole loop inline (eager Celery / tests) by repeatedly calling the
    same idempotent ``advance_run`` driver until the run is terminal."""
    for _ in range(max_steps):
        res = advance_run(
            run.id, batch_client, prefix_fn=prefix_fn, commit_fn=commit_fn,
            sync_resolver=sync_resolver, min_batch_size=min_batch_size,
            provider=provider, poll=poll)
        run.refresh_from_db()
        if res["state"] == "completed" or run.status in BatchDownstreamRun.TERMINAL_STATUSES:
            return run
        if res["state"] == "busy_or_terminal":
            return run
    run.status = 'failed'
    run.error_details = {"reason": f"exceeded max_steps={max_steps}"}
    run.save(update_fields=['status', 'error_details', 'updated_at'])
    return run


def dispatch_parallel_collection(run_id, chunk_size: int = COLLECTION_CHUNK_SIZE) -> int:
    """Fan a collection pass out across the Celery fleet: claim pending rows
    (-> collecting, bulk row-level UPDATE) then dispatch one task per chunk.
    A duplicate dispatcher claims nothing (rows already 'collecting') and
    dispatches nothing. Each chunk applies its own outcomes and re-enters the
    driver — chord-free, counter-free.

    Each chunk runs independently and only writes race-free pending
    CachedLLMResponse rows, so the fleet parallelizes the (registry-lookup +
    cached-read + Python) re-execution.
    """
    from . import tasks
    now = timezone.now()
    RunPaper.objects.filter(run_id=run_id, state='pending').update(
        state='collecting', dispatched_at=now)
    claimed = [str(p) for p in RunPaper.objects
               .filter(run_id=run_id, state='collecting', dispatched_at=now)
               .values_list('paper_id', flat=True)]
    if not claimed:
        tasks.advance_run_task.delay(str(run_id))
        return 0
    chunks = [list(c) for c in _chunks(claimed, chunk_size)]
    for c in chunks:
        tasks.collect_chunk_task.delay(str(run_id), c)
    return len(chunks)


def prune_run_payloads(run: BatchDownstreamRun) -> int:
    """Corpus-mode storage lifecycle, called once at run completion: nothing will
    ever replay a completed run, so resolved rows' response_content (and any
    leftover payloads) are dead weight — usage/cost/call_type stay for analytics.
    Failed rows are left intact for debugging. Idempotent."""
    n = (CachedLLMResponse.objects
         .filter(run=run, status='resolved')
         .exclude(response_content=None)
         .update(response_content=None, request_payload={}))
    if n:
        logger.info("batch-downstream run=%s pruned payloads from %d resolved rows", run.id, n)
    return n


def find_stalled_runs(stale_after_seconds: int = LEASE_SECONDS):
    """Non-terminal runs whose lease has expired (or was never set) — the
    reconciler re-drives these (crash recovery / liveness backstop)."""
    now = timezone.now()
    return (BatchDownstreamRun.objects
            .exclude(status__in=BatchDownstreamRun.TERMINAL_STATUSES)
            .filter(models_q_lease_free(now)))


@transaction.atomic
def create_run(paper_ids: List[str], configuration_name: str,
               aws_region_name: Optional[str] = None,
               corpus_mode: bool = False) -> BatchDownstreamRun:
    paper_ids = [str(p) for p in paper_ids]
    if aws_region_name is None:
        # Default the region from the LLM configuration, the same source the
        # step-1 batch uses — NOT boto3's ambient default. Found live (cohort_1k):
        # a pipeline created without an explicit region sent step-1 to us-west-2
        # (config) but every downstream job to us-east-1 (the host's ambient region),
        # where the model doesn't exist — 100% of downstream jobs failed.
        try:
            from paper_data_linking.config.settings import get_llm_configuration
            aws_region_name = get_llm_configuration(
                configuration_name).paper_analysis.aws_region_name
        except Exception:  # noqa: BLE001 — unknown config: keep legacy behavior
            pass
        logger.info("batch-downstream create_run: config=%s region=%s (derived)",
                    configuration_name, aws_region_name)
    run = BatchDownstreamRun.objects.create(
        configuration_name=configuration_name, aws_region_name=aws_region_name,
        paper_ids=paper_ids, total_papers=len(paper_ids), status='preparing',
        corpus_mode=corpus_mode)
    RunPaper.objects.bulk_create(
        [RunPaper(run=run, paper_id=p, state='pending') for p in paper_ids],
        batch_size=5000)
    return run
