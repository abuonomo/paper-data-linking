"""Tests for the pipeline dependency tree feature.

Covers:
  - pipeline_context.py  — ContextVar logic and node_stage no-op behaviour
  - pipeline.py          — Django node factory (create / complete / fail / skip)
  - clients.py           — LLMCall → PipelineNode association
  - serializers.py       — PipelineNodeSerializer
  - views.py             — PipelineTreeView endpoint
  - tasks.py             — top-level nodes created in each Celery task
"""
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. pipeline_context — pure Python, no Django DB needed
# ---------------------------------------------------------------------------

class TestNodeStageNoop:
    """node_stage is a no-op when current_node_factory is not set."""

    def test_noop_when_no_factory(self):
        from paper_data_linking.pipeline_context import (
            current_node_factory, current_pipeline_node, node_stage
        )
        # Ensure clean state
        current_node_factory.set(None)
        current_pipeline_node.set(None)

        entered = []
        with node_stage('grounding', 'Test') as val:
            entered.append(val)

        assert entered == [None], "No-op context manager should yield None"

    def test_noop_does_not_change_current_node(self):
        from paper_data_linking.pipeline_context import (
            current_node_factory, current_pipeline_node, node_stage
        )
        sentinel = uuid.uuid4()
        current_node_factory.set(None)
        current_pipeline_node.set(sentinel)

        with node_stage('instrument', 'EUVI'):
            assert current_pipeline_node.get() == sentinel, \
                "No-op must not mutate current_pipeline_node"

        assert current_pipeline_node.get() == sentinel

    def test_noop_handles_skip_kwarg(self):
        from paper_data_linking.pipeline_context import current_node_factory, node_stage
        current_node_factory.set(None)
        # Should not raise even with skip=True / extra kwargs
        with node_stage('normalizer', 'time_range', skip=True, skip_reason='no data'):
            pass

    def test_factory_is_called_when_set(self):
        from paper_data_linking.pipeline_context import (
            current_node_factory, node_stage
        )
        calls = []

        @contextmanager
        def fake_factory(stage, label, **kwargs):
            calls.append({'stage': stage, 'label': label, **kwargs})
            yield 'fake-node'

        token = current_node_factory.set(fake_factory)
        try:
            with node_stage('grounding', 'Grounding') as node:
                assert node == 'fake-node'
        finally:
            current_node_factory.reset(token)

        assert calls == [{'stage': 'grounding', 'label': 'Grounding'}]

    def test_contextvars_are_task_isolated(self):
        """Each contextvars.copy_context() call gets an independent copy."""
        import contextvars
        from paper_data_linking.pipeline_context import current_pipeline_node

        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()

        results = {}

        def set_a():
            current_pipeline_node.set(uid_a)
            results['a'] = current_pipeline_node.get()

        def set_b():
            current_pipeline_node.set(uid_b)
            results['b'] = current_pipeline_node.get()

        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()

        ctx_a.run(set_a)
        ctx_b.run(set_b)

        assert results['a'] == uid_a
        assert results['b'] == uid_b


# ---------------------------------------------------------------------------
# 2. pipeline.py — Django node factory (requires DB)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDjangoNodeStage:

    def test_creates_node_with_correct_fields(self, paper_analysis_factory):
        from django.utils import timezone
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)

        with factory('grounding', 'Grounding') as node:
            assert node is not None
            assert node.stage == 'grounding'
            assert node.label == 'Grounding'
            assert node.status == 'running'
            assert node.started_at is not None
            assert node.analysis == pa
            assert node.parent is None

    def test_node_marked_completed_on_success(self, paper_analysis_factory):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)

        with factory('structuring', 'Structuring') as node:
            node_id = node.id

        refreshed = PipelineNode.objects.get(id=node_id)
        assert refreshed.status == 'completed'
        assert refreshed.completed_at is not None

    def test_node_marked_failed_on_exception(self, paper_analysis_factory):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        node_id = None

        with pytest.raises(ValueError, match='oops'):
            with factory('grounding', 'Grounding') as node:
                node_id = node.id
                raise ValueError('oops')

        assert node_id is not None
        refreshed = PipelineNode.objects.get(id=node_id)
        assert refreshed.status == 'failed'
        assert 'oops' in refreshed.metadata.get('error', '')
        assert refreshed.completed_at is not None

    def test_current_pipeline_node_set_during_context(self, paper_analysis_factory):
        from paper_data_linking.pipeline_context import (
            current_node_factory, current_pipeline_node
        )
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        try:
            assert current_pipeline_node.get() is None
            with factory('paper_analysis', 'Paper Analysis') as node:
                assert current_pipeline_node.get() == node.id
            assert current_pipeline_node.get() is None
        finally:
            current_node_factory.reset(token)

    def test_nested_nodes_have_correct_parent(self, paper_analysis_factory):
        from paper_data_linking.pipeline_context import current_node_factory
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        try:
            with factory('instrument', 'EUVI') as outer:
                with factory('grounding', 'Grounding') as inner:
                    inner_id = inner.id
                outer_id = outer.id
        finally:
            current_node_factory.reset(token)

        inner_node = PipelineNode.objects.get(id=inner_id)
        assert inner_node.parent_id == outer_id

    def test_skip_creates_skipped_node_without_entering_context(self, paper_analysis_factory):
        from django.utils import timezone
        from paper_data_linking.pipeline_context import current_node_factory, current_pipeline_node
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        try:
            # Use a real DB row as the sentinel so the FK on parent_id is satisfied
            parent_node = PipelineNode.objects.create(
                analysis=pa, stage='normalization', label='Normalization',
                status='running', started_at=timezone.now()
            )
            sentinel = parent_node.id
            pid_token = current_pipeline_node.set(sentinel)
            try:
                with factory('normalizer', 'wavelength', skip=True, skip_reason='no data') as node:
                    assert node is None
                    # current_pipeline_node must NOT change during skip
                    assert current_pipeline_node.get() == sentinel
            finally:
                current_pipeline_node.reset(pid_token)
        finally:
            current_node_factory.reset(token)

        skipped = PipelineNode.objects.filter(stage='normalizer', label='wavelength').first()
        assert skipped is not None
        assert skipped.status == 'skipped'
        assert skipped.metadata['skip_reason'] == 'no data'
        assert skipped.completed_at is not None

    def test_current_pipeline_node_restored_after_exception(self, paper_analysis_factory):
        from paper_data_linking.pipeline_context import current_node_factory, current_pipeline_node
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        outer_id = None
        try:
            with factory('paper_analysis', 'Paper Analysis') as outer:
                outer_id = outer.id
                with pytest.raises(RuntimeError):
                    with factory('structuring', 'Structuring'):
                        raise RuntimeError('inner fail')
                # After inner failure, current node should be back to outer
                assert current_pipeline_node.get() == outer_id
        finally:
            current_node_factory.reset(token)

    def test_metadata_kwargs_stored_on_node(self, paper_analysis_factory):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)

        with factory('grounding_match', 'EUVI', data_system='vso', mission_code='STEREO') as node:
            node_id = node.id

        refreshed = PipelineNode.objects.get(id=node_id)
        assert refreshed.metadata['data_system'] == 'vso'
        assert refreshed.metadata['mission_code'] == 'STEREO'


# ---------------------------------------------------------------------------
# 3. DjangoLiteLLMClient — LLMCall → PipelineNode association
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestClientPipelineNodeAssociation:

    def _make_fake_response(self, tokens=100, cost=0.001):
        """Build a minimal LiteLLM-style response."""
        usage = SimpleNamespace(
            prompt_tokens=tokens, completion_tokens=10, total_tokens=tokens + 10
        )
        choice = SimpleNamespace(
            message=SimpleNamespace(content='ok'),
            finish_reason='stop',
        )
        return SimpleNamespace(usage=usage, choices=[choice])

    @patch('vso_query_builder.clients.LiteLLMClient.completion')
    @patch('vso_query_builder.clients.DjangoLiteLLMClient._calculate_cost', return_value=0.001)
    def test_llm_call_associated_with_active_node(
        self, mock_cost, mock_completion, paper_analysis_factory
    ):
        from paper_data_linking.pipeline_context import current_node_factory, current_pipeline_node
        from vso_query_builder.clients import DjangoLiteLLMClient
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        mock_completion.return_value = self._make_fake_response()

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        try:
            with factory('grounding_substep', 'similarity_filter') as node:
                client = DjangoLiteLLMClient()
                client.completion(
                    call_type='mission_identification',
                    model='openai/gpt-4o',
                    messages=[{'role': 'user', 'content': 'test'}],
                )
                node_id = node.id
        finally:
            current_node_factory.reset(token)

        refreshed = PipelineNode.objects.get(id=node_id)
        assert refreshed.llm_calls.count() == 1

    @patch('vso_query_builder.clients.LiteLLMClient.completion')
    @patch('vso_query_builder.clients.DjangoLiteLLMClient._calculate_cost', return_value=0.0)
    def test_no_node_association_when_no_active_node(self, mock_cost, mock_completion):
        from paper_data_linking.pipeline_context import current_node_factory, current_pipeline_node
        from vso_query_builder.clients import DjangoLiteLLMClient
        from vso_query_builder.models import LLMCall

        mock_completion.return_value = self._make_fake_response()
        current_node_factory.set(None)
        current_pipeline_node.set(None)

        before = LLMCall.objects.count()
        client = DjangoLiteLLMClient()
        client.completion(
            call_type='paper_analysis',
            model='openai/gpt-4o',
            messages=[{'role': 'user', 'content': 'hi'}],
        )
        # LLMCall created but no node associated — just check it doesn't crash
        assert LLMCall.objects.count() == before + 1

    @patch('vso_query_builder.clients.LiteLLMClient.completion')
    @patch('vso_query_builder.clients.DjangoLiteLLMClient._calculate_cost', return_value=0.001)
    def test_association_callback_and_node_both_fire(
        self, mock_cost, mock_completion, paper_analysis_factory
    ):
        from paper_data_linking.pipeline_context import current_node_factory
        from vso_query_builder.clients import DjangoLiteLLMClient
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.pipeline import make_node_factory

        mock_completion.return_value = self._make_fake_response()

        pa = paper_analysis_factory()
        factory = make_node_factory(pa)
        token = current_node_factory.set(factory)
        callback_calls = []

        try:
            with factory('grounding_substep', 'validation') as node:
                client = DjangoLiteLLMClient(
                    association_callback=lambda call: callback_calls.append(call)
                )
                client.completion(
                    call_type='instrument_validation',
                    model='openai/gpt-4o',
                    messages=[{'role': 'user', 'content': 'validate'}],
                )
                node_id = node.id
        finally:
            current_node_factory.reset(token)

        assert len(callback_calls) == 1
        refreshed = PipelineNode.objects.get(id=node_id)
        assert refreshed.llm_calls.count() == 1
        assert refreshed.llm_calls.first() == callback_calls[0]


# ---------------------------------------------------------------------------
# 4. PipelineNodeSerializer
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPipelineNodeSerializer:

    def _make_node(self, pa, stage='grounding', label='Grounding',
                   status='completed', parent=None, metadata=None):
        from django.utils import timezone
        from vso_query_builder.models import PipelineNode
        return PipelineNode.objects.create(
            analysis=pa, stage=stage, label=label, status=status,
            parent=parent, started_at=timezone.now(), completed_at=timezone.now(),
            metadata=metadata or {},
        )

    def test_serializes_basic_fields(self, paper_analysis_factory):
        from vso_query_builder.serializers import PipelineNodeSerializer

        pa = paper_analysis_factory()
        node = self._make_node(pa)
        data = PipelineNodeSerializer(node).data

        assert data['stage'] == 'grounding'
        assert data['label'] == 'Grounding'
        assert data['status'] == 'completed'
        assert 'started_at' in data
        assert 'completed_at' in data
        assert data['metadata'] == {}

    def test_llm_calls_nested(self, paper_analysis_factory):
        from vso_query_builder.models import LLMCall
        from vso_query_builder.serializers import PipelineNodeSerializer
        from django.utils import timezone

        pa = paper_analysis_factory()
        node = self._make_node(pa)
        call = LLMCall.objects.create(
            call_type='mission_identification',
            model_name='openai/gpt-4o',
            provider='openai',
            total_tokens=50,
            estimated_cost_usd=0.001,
        )
        node.llm_calls.add(call)

        data = PipelineNodeSerializer(node).data
        assert len(data['llm_calls']) == 1
        assert data['llm_calls'][0]['call_type'] == 'mission_identification'

    def test_children_nested_recursively(self, paper_analysis_factory):
        from vso_query_builder.serializers import PipelineNodeSerializer

        pa = paper_analysis_factory()
        parent = self._make_node(pa, stage='instrument', label='EUVI')
        child = self._make_node(pa, stage='grounding', label='Grounding', parent=parent)
        grandchild = self._make_node(pa, stage='grounding_substep', label='similarity_filter', parent=child)

        data = PipelineNodeSerializer(parent).data
        assert len(data['children']) == 1
        assert data['children'][0]['label'] == 'Grounding'
        assert len(data['children'][0]['children']) == 1
        assert data['children'][0]['children'][0]['label'] == 'similarity_filter'

    def test_root_has_no_children_when_leaf(self, paper_analysis_factory):
        from vso_query_builder.serializers import PipelineNodeSerializer

        pa = paper_analysis_factory()
        node = self._make_node(pa)
        data = PipelineNodeSerializer(node).data
        assert data['children'] == []

    def test_skipped_node_has_skip_reason_in_metadata(self, paper_analysis_factory):
        from vso_query_builder.serializers import PipelineNodeSerializer

        pa = paper_analysis_factory()
        node = self._make_node(
            pa, stage='normalizer', label='wavelength', status='skipped',
            metadata={'skip_reason': 'no wavelength data'}
        )
        data = PipelineNodeSerializer(node).data
        assert data['status'] == 'skipped'
        assert data['metadata']['skip_reason'] == 'no wavelength data'


# ---------------------------------------------------------------------------
# 5. PipelineTreeView endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPipelineTreeView:

    def _make_node(self, pa, stage, label, parent=None, status='completed'):
        from django.utils import timezone
        from vso_query_builder.models import PipelineNode
        return PipelineNode.objects.create(
            analysis=pa, stage=stage, label=label, status=status,
            parent=parent, started_at=timezone.now(), completed_at=timezone.now(),
        )

    def test_returns_empty_nodes_for_analysis_with_no_nodes(
        self, api_client, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.status_code == 200
        data = resp.json()
        assert data['nodes'] == []
        assert data['pipeline_completed_at'] is None

    def test_returns_404_for_missing_analysis(self, api_client):
        resp = api_client.get('/builder/analyses/999999/pipeline-tree/')
        assert resp.status_code == 404

    def test_returns_root_nodes_only_at_top_level(self, api_client, paper_analysis_factory):
        pa = paper_analysis_factory()
        root = self._make_node(pa, 'paper_analysis', 'Paper Analysis')
        child = self._make_node(pa, 'structuring', 'Structuring', parent=root)

        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.status_code == 200
        nodes = resp.json()['nodes']
        assert len(nodes) == 1, "Only root node should appear at top level"
        assert nodes[0]['stage'] == 'paper_analysis'

    def test_children_nested_in_response(self, api_client, paper_analysis_factory):
        pa = paper_analysis_factory()
        root = self._make_node(pa, 'paper_analysis', 'Paper Analysis')
        child = self._make_node(pa, 'structuring', 'Structuring', parent=root)
        grandchild = self._make_node(pa, 'instrument', 'EUVI', parent=child)

        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        nodes = resp.json()['nodes']
        assert nodes[0]['stage'] == 'paper_analysis'
        assert nodes[0]['children'][0]['stage'] == 'structuring'
        assert nodes[0]['children'][0]['children'][0]['stage'] == 'instrument'

    def test_requires_authentication(self, paper_analysis_factory):
        from rest_framework.test import APIClient
        pa = paper_analysis_factory()
        unauth = APIClient()
        resp = unauth.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.status_code == 401

    def test_failed_node_reflected_in_response(self, api_client, paper_analysis_factory):
        pa = paper_analysis_factory()
        self._make_node(pa, 'grounding', 'Grounding', status='failed')

        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        nodes = resp.json()['nodes']
        assert nodes[0]['status'] == 'failed'

    def test_multiple_roots_returned(self, api_client, paper_analysis_factory):
        """Two separate pipeline runs for the same analysis both appear."""
        pa = paper_analysis_factory()
        self._make_node(pa, 'paper_analysis', 'Paper Analysis')
        self._make_node(pa, 'paper_analysis', 'Paper Analysis (re-run)')

        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.status_code == 200
        assert len(resp.json()['nodes']) == 2

    def test_pipeline_completed_at_returned_when_set(self, api_client, paper_analysis_factory):
        from django.utils import timezone
        pa = paper_analysis_factory()
        pa.pipeline_completed_at = timezone.now()
        pa.save(update_fields=['pipeline_completed_at'])

        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.status_code == 200
        assert resp.json()['pipeline_completed_at'] is not None

    def test_pipeline_completed_at_null_when_not_set(self, api_client, paper_analysis_factory):
        pa = paper_analysis_factory()
        resp = api_client.get(f'/builder/analyses/{pa.id}/pipeline-tree/')
        assert resp.json()['pipeline_completed_at'] is None


# ---------------------------------------------------------------------------
# 6. tasks.py — nodes created during pipeline tasks
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTaskPipelineNodes:
    """Integration-style: run real task code with mocked LLM calls."""

    def _make_pipeline_config(self):
        from paper_data_linking.config.settings import (
            LLMCallConfig, LLMPipelineConfig, NormalizationConfig, InstrumentGroundingConfig,
        )
        call = LLMCallConfig(model='openai/gpt-4o', temperature=0.2, max_tokens=1000)
        emb = LLMCallConfig(model='openai/text-embedding-3-small', temperature=1.0, max_tokens=1)
        return LLMPipelineConfig(
            paper_analysis=call, structured_parsing=call, embeddings=emb,
            normalization=NormalizationConfig(
                time_range=call, wavelength=call,
                physical_observable=call, detector=call, cadence=call,
            ),
            instrument_grounding=InstrumentGroundingConfig(),
            structure_validation=call,
        )

    def _fake_analysis_data(self):
        return SimpleNamespace(
            context=[],
            instruments_details='# EUVI\n...',
            annotated_pdf=None,
            metadata={'token_usage': {}},
        )

    @patch('paper_data_linking.config.settings.get_llm_configuration')
    @patch('vso_query_builder.tasks.DirectPaperAnalyzer')
    @patch('vso_query_builder.tasks.read_pdf_bytes', return_value=b'pdf')
    def test_analyze_paper_task_creates_paper_analysis_node(
        self, mock_pdf, MockAnalyzer, mock_config, paper_factory
    ):
        from vso_query_builder.models import Paper, PaperAnalysis, PipelineNode
        from vso_query_builder.tasks import analyze_paper_task

        mock_config.return_value = self._make_pipeline_config()
        mock_instance = MagicMock()
        mock_instance.forward.return_value = self._fake_analysis_data()
        MockAnalyzer.return_value = mock_instance

        paper = paper_factory(full_text='Solar wind data from AIA and LASCO.')

        analyze_paper_task(str(paper.id), 'standard')

        pa = PaperAnalysis.objects.filter(paper=paper).first()
        assert pa is not None

        nodes = PipelineNode.objects.filter(analysis=pa)
        assert nodes.count() >= 1

        root = nodes.filter(stage='paper_analysis').first()
        assert root is not None
        assert root.status == 'completed'
        assert root.parent is None

    @patch('paper_data_linking.config.settings.get_llm_configuration')
    @patch('vso_query_builder.tasks.DeterministicStructureAnalyzer')
    def test_structure_task_creates_structuring_node(
        self, MockAnalyzer, mock_config, paper_analysis_factory
    ):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.tasks import analyze_paper_instruments_structure

        mock_config.return_value = self._make_pipeline_config()
        mock_instance = MagicMock()
        mock_instance.forward.return_value = SimpleNamespace(
            success=True,
            structured_data={'instruments': []},
            metadata={'instruments_count': 0, 'total_data_periods': 0, 'token_usage': {}},
            error_message=None,
        )
        MockAnalyzer.return_value = mock_instance

        pa = paper_analysis_factory()

        analyze_paper_instruments_structure(pa.id, 'standard')

        nodes = PipelineNode.objects.filter(analysis=pa)
        structuring = nodes.filter(stage='structuring').first()
        assert structuring is not None
        assert structuring.status == 'completed'

    @patch('paper_data_linking.config.settings.get_llm_configuration')
    @patch('vso_query_builder.tasks.DeterministicStructureAnalyzer')
    def test_structure_task_links_structuring_to_paper_analysis_node(
        self, MockAnalyzer, mock_config, paper_analysis_factory
    ):
        """structuring node's parent should be the paper_analysis node."""
        from django.utils import timezone
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.tasks import analyze_paper_instruments_structure

        mock_config.return_value = self._make_pipeline_config()
        mock_instance = MagicMock()
        mock_instance.forward.return_value = SimpleNamespace(
            success=True,
            structured_data={'instruments': []},
            metadata={'instruments_count': 0, 'total_data_periods': 0, 'token_usage': {}},
            error_message=None,
        )
        MockAnalyzer.return_value = mock_instance

        pa = paper_analysis_factory()
        # Simulate a paper_analysis node already existing from the previous task
        pa_node = PipelineNode.objects.create(
            analysis=pa, stage='paper_analysis', label='Paper Analysis',
            status='completed', started_at=timezone.now(), completed_at=timezone.now(),
        )

        analyze_paper_instruments_structure(pa.id, 'standard')

        structuring = PipelineNode.objects.filter(analysis=pa, stage='structuring').first()
        assert structuring is not None
        assert structuring.parent_id == pa_node.id

    @patch('paper_data_linking.config.settings.get_llm_configuration')
    @patch('vso_query_builder.tasks.get_django_structured_normalizer')
    @patch('vso_query_builder.tasks.read_pdf_bytes', return_value=None)
    def test_normalize_task_creates_instrument_nodes_as_children_of_structuring(
        self, mock_pdf, mock_factory, mock_config, paper_analysis_factory
    ):
        """instrument nodes' parent should be the structuring node."""
        from django.utils import timezone
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.tasks import normalize_structured_instrument_details
        from paper_data_linking.pipeline_context import current_node_factory, node_stage

        mock_config.return_value = self._make_pipeline_config()

        # Normalizer.forward() creates instrument nodes via node_stage.
        # We simulate that by having the mock call node_stage directly.
        def fake_forward(structured, pdf_path=None):
            with node_stage('instrument', 'EUVI'):
                pass
            return {'instruments': []}

        mock_normalizer = MagicMock()
        mock_normalizer.forward.side_effect = fake_forward
        mock_factory.return_value = mock_normalizer

        pa = paper_analysis_factory(structured_instruments_details={'instruments': []})
        structuring_node = PipelineNode.objects.create(
            analysis=pa, stage='structuring', label='Structuring',
            status='completed', started_at=timezone.now(), completed_at=timezone.now(),
        )

        normalize_structured_instrument_details(pa.id, 'standard')

        instrument_node = PipelineNode.objects.filter(analysis=pa, stage='instrument').first()
        assert instrument_node is not None
        assert instrument_node.parent_id == structuring_node.id


# ---------------------------------------------------------------------------
# 7. node_stage in library code — truly no-op (no Django setup at all)
# ---------------------------------------------------------------------------

class TestLibraryCodeNoop:
    """Verify that library classes using node_stage work without Django."""

    def test_structured_normalizer_imports_without_django(self):
        """The library module loads even when Django is not configured."""
        import importlib
        # If this import succeeds without Django DB errors, we're good
        from paper_data_linking.linkers.general.structured_normalizer import StructuredNormalizer
        assert StructuredNormalizer is not None

    def test_instrument_grounder_imports_without_django(self):
        from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
        assert InstrumentGrounder is not None

    def test_pipeline_context_imports_are_stdlib_only(self):
        """pipeline_context.py must only use stdlib — no Django imports."""
        import ast, pathlib
        src = pathlib.Path(
            'paper_data_linking/pipeline_context.py'
        ).read_text()
        tree = ast.parse(src)
        top_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for imp in top_imports:
            if isinstance(imp, ast.ImportFrom):
                assert not imp.module.startswith('django'), \
                    f"pipeline_context.py must not import Django: {imp.module}"
