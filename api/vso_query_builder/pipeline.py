from contextlib import contextmanager
from django.utils import timezone
from paper_data_linking.pipeline_context import (
    current_pipeline_node, current_node_factory, pipeline_mode,
)
from .models import PaperAnalysis, PipelineNode


@contextmanager
def _django_node_stage(analysis, stage, label, skip=False, skip_reason='', **metadata):
    if pipeline_mode.get() == 'collection':
        # Throwaway collection passes persist nothing; the single commit pass
        # rebuilds the full PipelineNode tree exactly once from the warm cache.
        yield None
        return
    parent_id = current_pipeline_node.get()
    if skip:
        PipelineNode.objects.create(
            analysis=analysis, stage=stage, label=label, parent_id=parent_id,
            status='skipped', started_at=timezone.now(), completed_at=timezone.now(),
            metadata={'skip_reason': skip_reason, **metadata}
        )
        yield None
        return
    node = PipelineNode.objects.create(
        analysis=analysis, stage=stage, label=label, parent_id=parent_id,
        status='running', started_at=timezone.now(), metadata=metadata
    )
    token = current_pipeline_node.set(node.id)
    try:
        yield node
        node.status = 'completed'
        node.completed_at = timezone.now()
        node.save(update_fields=['status', 'completed_at'])
    except Exception as e:
        node.status = 'failed'
        node.completed_at = timezone.now()
        node.metadata['error'] = str(e)
        node.save(update_fields=['status', 'completed_at', 'metadata'])
        raise
    finally:
        current_pipeline_node.reset(token)


def make_node_factory(analysis: PaperAnalysis):
    """Returns a context manager factory bound to a specific PaperAnalysis."""
    @contextmanager
    def factory(stage, label, **kwargs):
        with _django_node_stage(analysis, stage, label, **kwargs) as node:
            yield node
    return factory
