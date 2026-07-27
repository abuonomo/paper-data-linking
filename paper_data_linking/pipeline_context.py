from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional, Callable
from uuid import UUID

current_pipeline_node: ContextVar[Optional[UUID]] = ContextVar('current_pipeline_node', default=None)
current_node_factory: ContextVar[Optional[Callable]] = ContextVar('current_node_factory', default=None)

# Execution mode for the wave-synchronous batch-downstream runner.
#   'off'        — normal synchronous pipeline (default; unchanged behavior)
#   'collection' — re-execution pass: LLM calls are served from the durable cache
#                  or deferred into the current batch wave; no LLMCall / PipelineNode
#                  rows are written.
#   'commit'     — final pass with a warm cache: every LLM call resolves from cache
#                  and all side effects (LLMCall, PipelineNode, DatasetUsage, ...)
#                  are written exactly once, identically to a synchronous run.
# See api/vso_query_builder/batch_downstream.py for the orchestration that sets this.
pipeline_mode: ContextVar[str] = ContextVar('pipeline_mode', default='off')

# The BatchDownstreamRun whose durable cache the chokepoint should read/write while
# in 'collection'/'commit' mode. Stored as a str(uuid) to keep this module Django-free.
current_batch_run_id: ContextVar[Optional[str]] = ContextVar('current_batch_run_id', default=None)

# Per-execution deferred-call counter (a single-cell list so increments mutate in
# place). DeferredCall exceptions are ABSORBED by the pipeline's per-branch error
# handling, so "did this paper defer anything?" must be tracked out-of-band: the
# chokepoint increments this on every deferral; the collector reads it afterwards.
# A paper is LLM-complete only when a collection pass finishes with count == 0.
deferred_calls: ContextVar[Optional[list]] = ContextVar('deferred_calls', default=None)


def note_deferred_call() -> None:
    cell = deferred_calls.get()
    if cell is not None:
        cell[0] += 1


def get_pipeline_mode() -> str:
    return pipeline_mode.get()


@contextmanager
def batch_execution(mode: str, run_id):
    """Set the batch execution mode + run for the duration of a pipeline run.

    Used by the batch-downstream orchestrator to wrap a paper's (re-)execution.
    """
    if mode not in ('off', 'collection', 'commit'):
        raise ValueError(f"invalid pipeline_mode: {mode!r}")
    m_token = pipeline_mode.set(mode)
    r_token = current_batch_run_id.set(str(run_id) if run_id is not None else None)
    try:
        yield
    finally:
        current_batch_run_id.reset(r_token)
        pipeline_mode.reset(m_token)


@contextmanager
def _noop_cm(stage: str, label: str, **kwargs):
    yield None


def node_stage(stage: str, label: str, **kwargs):
    """Context manager for library code to declare a pipeline stage.
    No-op when no factory is set (non-Django contexts)."""
    factory = current_node_factory.get() or _noop_cm
    return factory(stage=stage, label=label, **kwargs)
