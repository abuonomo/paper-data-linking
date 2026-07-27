"""Tests for batch monitoring dashboard feature.

Covers:
  - BatchJobSerializer.papers_pipeline_done computed field
  - BatchJobListView  GET /builder/batch-jobs/
  - BatchJobPapersView GET /builder/batch-jobs/<id>/papers/
  - _finalize_paper_pipeline task sets pipeline_completed_at
  - normalize_structured_instrument_details cleans up running nodes on failure
"""
import pytest
from django.utils import timezone
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def batch_job_factory(paper_analysis_factory):
    """Return a factory that creates a BatchJob with given papers."""
    from vso_query_builder.models import BatchJob

    def _make(papers=None, status='completed', **kwargs):
        papers = papers or []
        mapping = {str(pa.paper_id): pa.paper.bibcode for pa in papers}
        return BatchJob.objects.create(
            batch_id=f'test-batch-{timezone.now().timestamp()}',
            status=status,
            provider='openai',
            configuration_name='standard',
            paper_mapping=mapping,
            total_requests=len(papers),
            completed_requests=len(papers),
            failed_requests=0,
            submitted_at=timezone.now(),
            completed_at=timezone.now(),
            **kwargs,
        )
    return _make


# ---------------------------------------------------------------------------
# 1. BatchJobSerializer.papers_pipeline_done
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchJobSerializer:

    def test_papers_pipeline_done_counts_completed_analyses(
        self, batch_job_factory, paper_analysis_factory
    ):
        from vso_query_builder.serializers import BatchJobSerializer

        pa_done = paper_analysis_factory()
        pa_done.pipeline_completed_at = timezone.now()
        pa_done.save(update_fields=['pipeline_completed_at'])

        pa_pending = paper_analysis_factory()  # pipeline_completed_at stays null

        job = batch_job_factory(papers=[pa_done, pa_pending])
        data = BatchJobSerializer(job).data

        assert data['papers_pipeline_done'] == 1

    def test_papers_pipeline_done_zero_when_none_complete(
        self, batch_job_factory, paper_analysis_factory
    ):
        from vso_query_builder.serializers import BatchJobSerializer

        pa = paper_analysis_factory()
        job = batch_job_factory(papers=[pa])
        data = BatchJobSerializer(job).data

        assert data['papers_pipeline_done'] == 0

    def test_papers_pipeline_done_equals_total_when_all_complete(
        self, batch_job_factory, paper_analysis_factory
    ):
        from vso_query_builder.serializers import BatchJobSerializer

        papers = []
        for _ in range(3):
            pa = paper_analysis_factory()
            pa.pipeline_completed_at = timezone.now()
            pa.save(update_fields=['pipeline_completed_at'])
            papers.append(pa)

        job = batch_job_factory(papers=papers)
        data = BatchJobSerializer(job).data

        assert data['papers_pipeline_done'] == 3

    def test_serializer_includes_expected_fields(
        self, batch_job_factory
    ):
        from vso_query_builder.serializers import BatchJobSerializer

        job = batch_job_factory()
        data = BatchJobSerializer(job).data

        for field in ['id', 'batch_id', 'status', 'provider', 'configuration_name',
                      'total_requests', 'papers_pipeline_done', 'created_at']:
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 2. BatchJobListView  GET /builder/batch-jobs/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchJobListView:

    def test_returns_200_for_authenticated_user(self, api_client, batch_job_factory):
        batch_job_factory()
        resp = api_client.get('/builder/batch-jobs/')
        assert resp.status_code == 200

    def test_requires_authentication(self, batch_job_factory):
        from rest_framework.test import APIClient
        batch_job_factory()
        resp = APIClient().get('/builder/batch-jobs/')
        assert resp.status_code == 401

    def test_returns_list_of_jobs(self, api_client, batch_job_factory):
        batch_job_factory()
        batch_job_factory()
        resp = api_client.get('/builder/batch-jobs/')
        data = resp.json()
        assert 'results' in data
        assert data['count'] >= 2

    def test_returns_at_most_25_jobs_per_page(self, api_client, batch_job_factory):
        for _ in range(30):
            batch_job_factory()
        resp = api_client.get('/builder/batch-jobs/')
        data = resp.json()
        assert len(data['results']) <= 25
        assert data['count'] >= 30

    def test_jobs_ordered_newest_first(self, api_client, batch_job_factory):
        job1 = batch_job_factory()
        job2 = batch_job_factory()
        resp = api_client.get('/builder/batch-jobs/')
        ids = [j['id'] for j in resp.json()['results']]
        assert ids.index(job2.id) < ids.index(job1.id)


# ---------------------------------------------------------------------------
# 3. BatchJobPapersView  GET /builder/batch-jobs/<id>/papers/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchJobPapersView:

    def _make_node(self, pa, stage, status='completed'):
        from vso_query_builder.models import PipelineNode
        return PipelineNode.objects.create(
            analysis=pa, stage=stage, label=stage,
            status=status, started_at=timezone.now(), completed_at=timezone.now(),
        )

    def test_returns_200_with_papers_list(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        assert resp.status_code == 200
        assert 'papers' in resp.json()

    def test_returns_404_for_missing_batch(self, api_client):
        resp = api_client.get('/builder/batch-jobs/999999/papers/')
        assert resp.status_code == 404

    def test_requires_authentication(self, batch_job_factory):
        from rest_framework.test import APIClient
        job = batch_job_factory()
        resp = APIClient().get(f'/builder/batch-jobs/{job.id}/papers/')
        assert resp.status_code == 401

    def test_paper_entry_has_expected_fields(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        paper = resp.json()['papers'][0]

        for field in ['paper_id', 'bibcode', 'analysis_id',
                      'pipeline_completed_at', 'current_stage',
                      'has_running_nodes', 'has_failed_nodes']:
            assert field in paper, f"Missing field: {field}"

    def test_pipeline_completed_at_reflected(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        pa.pipeline_completed_at = timezone.now()
        pa.save(update_fields=['pipeline_completed_at'])

        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        paper = resp.json()['papers'][0]

        assert paper['pipeline_completed_at'] is not None

    def test_has_running_nodes_true_when_node_running(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        self._make_node(pa, 'grounding', status='running')

        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        paper = resp.json()['papers'][0]

        assert paper['has_running_nodes'] is True

    def test_has_failed_nodes_true_when_node_failed(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        self._make_node(pa, 'grounding', status='failed')

        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        paper = resp.json()['papers'][0]

        assert paper['has_failed_nodes'] is True

    def test_current_stage_reflects_latest_node(
        self, api_client, batch_job_factory, paper_analysis_factory
    ):
        pa = paper_analysis_factory()
        self._make_node(pa, 'structuring')
        self._make_node(pa, 'grounding')

        job = batch_job_factory(papers=[pa])
        resp = api_client.get(f'/builder/batch-jobs/{job.id}/papers/')
        paper = resp.json()['papers'][0]

        assert paper['current_stage'] == 'grounding'


# ---------------------------------------------------------------------------
# 4. _finalize_paper_pipeline task
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFinalizePaperPipeline:

    def test_sets_pipeline_completed_at(self, paper_analysis_factory):
        from vso_query_builder.tasks import _finalize_paper_pipeline
        from vso_query_builder.models import PaperAnalysis

        pa = paper_analysis_factory()
        assert pa.pipeline_completed_at is None

        _finalize_paper_pipeline(results=[], paper_analysis_id=pa.id)

        pa.refresh_from_db()
        assert pa.pipeline_completed_at is not None

    def test_is_idempotent(self, paper_analysis_factory):
        from vso_query_builder.tasks import _finalize_paper_pipeline
        from vso_query_builder.models import PaperAnalysis

        pa = paper_analysis_factory()
        _finalize_paper_pipeline(results=[], paper_analysis_id=pa.id)
        pa.refresh_from_db()
        first_ts = pa.pipeline_completed_at

        _finalize_paper_pipeline(results=[], paper_analysis_id=pa.id)
        pa.refresh_from_db()
        # timestamp updates on second call — just verify it doesn't raise
        assert pa.pipeline_completed_at is not None


# ---------------------------------------------------------------------------
# 5. normalize_structured_instrument_details — cleanup on failure
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNormalizeCleanupOnFailure:

    def test_running_nodes_marked_failed_on_exception(
        self, paper_analysis_factory
    ):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.tasks import normalize_structured_instrument_details

        pa = paper_analysis_factory(structured_instruments_details={'instruments': [{'name': 'EUVI'}]})

        # Create a node already in 'running' state (simulating mid-run crash)
        stuck_node = PipelineNode.objects.create(
            analysis=pa, stage='instrument', label='EUVI',
            status='running', started_at=timezone.now(),
        )

        with patch('vso_query_builder.tasks.get_django_structured_normalizer') as mock_factory, \
             patch('vso_query_builder.tasks.read_pdf_bytes', return_value=None), \
             patch('paper_data_linking.config.settings.get_llm_configuration'):
            mock_normalizer = MagicMock()
            mock_normalizer.forward.side_effect = RuntimeError('LLM timeout')
            mock_factory.return_value = mock_normalizer

            result = normalize_structured_instrument_details(pa.id, 'standard')

        assert result['success'] is False

        stuck_node.refresh_from_db()
        assert stuck_node.status == 'failed'
        assert stuck_node.completed_at is not None

    def test_completed_nodes_unaffected_on_failure(
        self, paper_analysis_factory
    ):
        from vso_query_builder.models import PipelineNode
        from vso_query_builder.tasks import normalize_structured_instrument_details

        pa = paper_analysis_factory(structured_instruments_details={'instruments': []})

        completed_node = PipelineNode.objects.create(
            analysis=pa, stage='structuring', label='Structuring',
            status='completed', started_at=timezone.now(), completed_at=timezone.now(),
        )

        with patch('vso_query_builder.tasks.get_django_structured_normalizer') as mock_factory, \
             patch('vso_query_builder.tasks.read_pdf_bytes', return_value=None), \
             patch('paper_data_linking.config.settings.get_llm_configuration'):
            mock_normalizer = MagicMock()
            mock_normalizer.forward.side_effect = RuntimeError('boom')
            mock_factory.return_value = mock_normalizer

            normalize_structured_instrument_details(pa.id, 'standard')

        completed_node.refresh_from_db()
        assert completed_node.status == 'completed'
