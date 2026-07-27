"""Django ORM tests for batch Celery tasks.

Tests submit_batch_paper_analysis, poll_batch_job, and ingest_batch_results
with a real test database but mocked external calls (litellm/BatchClient).

Requires Docker postgres running for the batch-api worktree.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
from django.utils import timezone

from paper_data_linking.config.settings import (
    LLMCallConfig, LLMPipelineConfig, NormalizationConfig, InstrumentGroundingConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline_config(model="openai/gpt-5"):
    """Build a minimal LLMPipelineConfig for testing."""
    pa = LLMCallConfig(model=model, temperature=0.2, max_tokens=16000)
    sp = LLMCallConfig(model=model, temperature=0.2, max_tokens=16000)
    emb = LLMCallConfig(model="openai/text-embedding-3-small", temperature=1.0, max_tokens=1)
    norm = LLMCallConfig(model=model, temperature=0.2)
    return LLMPipelineConfig(
        paper_analysis=pa,
        structured_parsing=sp,
        embeddings=emb,
        normalization=NormalizationConfig(
            time_range=norm, wavelength=norm,
            physical_observable=norm, detector=norm, cadence=norm,
        ),
        instrument_grounding=InstrumentGroundingConfig(),
        structure_validation=LLMCallConfig(model=model, temperature=0.2),
    )


def _openai_batch_results():
    """Sample retrieve_results output (2 successes, 1 error)."""
    return [
        {
            "custom_id": "paper_analysis|PAPER_ID_1",
            "content": "# Instrument: AIA\n## Period 1\n- Time range: 2020-01-01 to 2020-12-31",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            "finish_reason": "stop",
        },
        {
            "custom_id": "paper_analysis|PAPER_ID_2",
            "content": "# Instrument: LASCO\n## Period 1\n- Time range: 2019-06-01 to 2019-06-30",
            "usage": {"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
            "finish_reason": "stop",
        },
        {
            "custom_id": "paper_analysis|PAPER_ID_3",
            "error": "Content filter triggered",
        },
    ]


# ---------------------------------------------------------------------------
# submit_batch_paper_analysis
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSubmitBatchPaperAnalysis:

    @patch("paper_data_linking.clients.batch_client.BatchClient.submit")
    @patch("paper_data_linking.clients.batch_client.BatchClient.prepare_requests")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_creates_batch_job_record(
        self, mock_poll, mock_prompt, mock_get_config,
        mock_prepare, mock_submit, paper_factory,
    ):
        """Submitting papers creates a BatchJob record in the DB."""
        from vso_query_builder.models import BatchJob
        from vso_query_builder.tasks import submit_batch_paper_analysis

        paper = paper_factory(full_text="Solar wind observations from AIA...")
        mock_prompt.return_value = "You are a helpful assistant."
        mock_get_config.return_value = _make_pipeline_config()
        mock_prepare.return_value = '{"custom_id":"test"}'
        mock_submit.return_value = {"batch_id": "batch-abc", "input_file_id": "file-123"}

        result = submit_batch_paper_analysis.apply(
            args=[[str(paper.id)], "standard"]
        ).result

        assert result["success"] is True
        assert result["total_papers"] == 1

        batch_job = BatchJob.objects.get(batch_id="batch-abc")
        assert batch_job.status == "submitted"
        assert batch_job.provider == "openai"
        assert batch_job.total_requests == 1
        assert str(paper.id) in batch_job.paper_mapping

    @patch("paper_data_linking.clients.batch_client.BatchClient.submit")
    @patch("paper_data_linking.clients.batch_client.BatchClient.prepare_requests")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_skips_papers_with_existing_analysis(
        self, mock_poll, mock_prompt, mock_get_config,
        mock_prepare, mock_submit, paper_factory,
    ):
        """Papers that already have a completed analysis for this config are skipped."""
        from vso_query_builder.models import PaperAnalysis
        from vso_query_builder.tasks import submit_batch_paper_analysis

        paper = paper_factory(full_text="Solar wind data...")
        PaperAnalysis.objects.create(
            paper=paper,
            configuration_name="standard",
            context=[],
            instruments_details="# Already analyzed",
            status="completed",
        )

        mock_prompt.return_value = "system prompt"
        mock_get_config.return_value = _make_pipeline_config()

        result = submit_batch_paper_analysis.apply(
            args=[[str(paper.id)], "standard"]
        ).result

        assert result["success"] is True
        assert str(paper.id) in result["skipped"]
        mock_submit.assert_not_called()

    @patch("paper_data_linking.clients.batch_client.BatchClient.submit")
    @patch("paper_data_linking.clients.batch_client.BatchClient.prepare_requests")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_schedules_poll_after_submission(
        self, mock_poll, mock_prompt, mock_get_config,
        mock_prepare, mock_submit, paper_factory,
    ):
        """After successful submission, poll_batch_job is scheduled."""
        from vso_query_builder.tasks import submit_batch_paper_analysis

        paper = paper_factory(full_text="Some paper text")
        mock_prompt.return_value = "system prompt"
        mock_get_config.return_value = _make_pipeline_config()
        mock_prepare.return_value = '{"custom_id":"test"}'
        mock_submit.return_value = {"batch_id": "batch-xyz", "input_file_id": "file-456"}

        submit_batch_paper_analysis.apply(
            args=[[str(paper.id)], "standard"]
        )

        mock_poll.apply_async.assert_called_once()
        call_args = mock_poll.apply_async.call_args
        assert call_args.kwargs.get("countdown") or call_args[1].get("countdown")

    @patch("paper_data_linking.clients.batch_client.BatchClient.submit")
    @patch("paper_data_linking.clients.batch_client.BatchClient.prepare_requests")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_detects_bedrock_provider(
        self, mock_poll, mock_prompt, mock_get_config,
        mock_prepare, mock_submit, paper_factory,
    ):
        """Bedrock models set provider='bedrock' and submit with correct params."""
        from vso_query_builder.tasks import submit_batch_paper_analysis

        # Bedrock requires >=100 papers; create exactly 100
        papers = [paper_factory(full_text="Some paper text") for _ in range(100)]
        paper_ids = [str(p.id) for p in papers]
        mock_prompt.return_value = "system prompt"
        mock_get_config.return_value = _make_pipeline_config(
            model="bedrock/converse/openai.gpt-oss-120b-1:0"
        )
        mock_prepare.return_value = '{"recordId":"test"}'
        mock_submit.return_value = {"batch_id": "batch-br-1", "input_file_id": "file-br-1"}
        mock_poll.apply_async = MagicMock()

        result = submit_batch_paper_analysis.apply(
            args=[paper_ids, "bedrock-test"]
        ).result

        assert result["success"] is True
        submit_call = mock_submit.call_args
        assert submit_call.kwargs["provider"] == "bedrock"
        assert submit_call.kwargs["model_name"] == "openai.gpt-oss-120b-1:0"

    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_skips_papers_without_text_or_pdf(
        self, mock_poll, mock_prompt, mock_get_config, paper_factory,
    ):
        """Papers with no full_text and no PDF are skipped."""
        from vso_query_builder.tasks import submit_batch_paper_analysis

        paper = paper_factory(full_text=None)  # no text, no pdf
        mock_prompt.return_value = "system prompt"
        mock_get_config.return_value = _make_pipeline_config()

        result = submit_batch_paper_analysis.apply(
            args=[[str(paper.id)], "standard"]
        ).result

        assert result["success"] is True
        assert str(paper.id) in result["skipped"]

    @patch("paper_data_linking.clients.batch_client.BatchClient.submit")
    @patch("paper_data_linking.clients.batch_client.BatchClient.prepare_requests")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    @patch("vso_query_builder.tasks._load_paper_analysis_system_prompt")
    @patch("vso_query_builder.tasks.poll_batch_job")
    @patch("vso_query_builder.tasks.read_pdf_bytes")
    @patch("vso_query_builder.tasks.PDFTextExtractor")
    def test_corrupted_pdf_skipped_not_fatal(
        self, mock_extractor_cls, mock_read_pdf, mock_poll, mock_prompt,
        mock_get_config, mock_prepare, mock_submit, paper_factory,
    ):
        """A corrupted PDF should skip that paper, not kill the entire batch loop."""
        from vso_query_builder.tasks import submit_batch_paper_analysis

        bad_paper = paper_factory(full_text=None, bibcode="2023ApJS..265...34Y")
        good_paper = paper_factory(full_text=None, bibcode="2024ApJ...good001")

        # Give both papers a pdf field so they enter the extraction path
        from django.core.files.base import ContentFile
        bad_paper.pdf.save("bad.pdf", ContentFile(b"not a real pdf"))
        good_paper.pdf.save("good.pdf", ContentFile(b"%PDF-1.4 fake"))

        # First call (bad paper) raises, second call (good paper) succeeds
        mock_read_pdf.side_effect = [b"corrupt bytes", b"%PDF-1.4 fake"]
        mock_extractor = MagicMock()
        mock_extractor.extract_text.side_effect = [
            Exception("Could not extract text from PDF"),
            ("Solar wind observations from AIA...", False),
        ]
        mock_extractor_cls.return_value = mock_extractor

        mock_prompt.return_value = "system prompt"
        mock_get_config.return_value = _make_pipeline_config()
        mock_prepare.return_value = '{"custom_id":"test"}'
        mock_submit.return_value = {"batch_id": "batch-pdf-err", "input_file_id": "file-pdf"}

        result = submit_batch_paper_analysis.apply(
            args=[[str(bad_paper.id), str(good_paper.id)], "standard"]
        ).result

        assert result["success"] is True
        assert str(bad_paper.id) in result["skipped"]
        assert result["total_papers"] == 1  # only the good paper made it through


# ---------------------------------------------------------------------------
# poll_batch_job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPollBatchJob:

    @patch("paper_data_linking.clients.batch_client.BatchClient.check_status")
    @patch("vso_query_builder.tasks.ingest_batch_results")
    def test_completed_triggers_ingestion(
        self, mock_ingest, mock_check_status, batch_job_factory,
    ):
        """When batch reports completed, update BatchJob and trigger ingestion."""
        from vso_query_builder.tasks import poll_batch_job
        from vso_query_builder.models import BatchJob

        batch_job = batch_job_factory(batch_id="batch-poll-1")
        mock_check_status.return_value = {
            "status": "completed",
            "completed": 5,
            "failed": 0,
            "total": 5,
            "output_file_id": "file-out-1",
            "error_file_id": None,
        }

        result = poll_batch_job.apply(args=[batch_job.id]).result

        batch_job.refresh_from_db()
        assert batch_job.status == "completed"
        assert batch_job.output_file_id == "file-out-1"
        assert batch_job.completed_requests == 5
        mock_ingest.delay.assert_called_once_with(batch_job.id)

    @patch("paper_data_linking.clients.batch_client.BatchClient.check_status")
    def test_in_progress_reschedules(
        self, mock_check_status, batch_job_factory,
    ):
        """In-progress status re-schedules polling."""
        from vso_query_builder.tasks import poll_batch_job
        from vso_query_builder.models import BatchJob

        batch_job = batch_job_factory(batch_id="batch-poll-2")
        mock_check_status.return_value = {
            "status": "in_progress",
            "completed": 2,
            "failed": 0,
            "total": 5,
            "output_file_id": None,
            "error_file_id": None,
        }

        # Mock apply_async on the task to prevent recursive self-scheduling
        with patch.object(poll_batch_job, "apply_async") as mock_reschedule:
            result = poll_batch_job.apply(args=[batch_job.id, 0]).result

        batch_job.refresh_from_db()
        assert batch_job.status == "processing"
        mock_reschedule.assert_called_once()

    @patch("paper_data_linking.clients.batch_client.BatchClient.check_status")
    def test_failed_sets_status(self, mock_check_status, batch_job_factory):
        """Failed batch sets BatchJob status to 'failed'."""
        from vso_query_builder.tasks import poll_batch_job
        from vso_query_builder.models import BatchJob

        batch_job = batch_job_factory(batch_id="batch-poll-3")
        mock_check_status.return_value = {
            "status": "failed",
            "completed": 0,
            "failed": 5,
            "total": 5,
            "output_file_id": None,
            "error_file_id": None,
        }

        result = poll_batch_job.apply(args=[batch_job.id]).result

        batch_job.refresh_from_db()
        assert batch_job.status == "failed"
        assert result["success"] is False

    @patch("paper_data_linking.clients.batch_client.BatchClient.check_status")
    def test_timeout_after_max_retries(
        self, mock_check_status, batch_job_factory,
    ):
        """After max retries, marks batch as failed with timeout."""
        from vso_query_builder.tasks import poll_batch_job, BATCH_POLL_MAX_RETRIES
        from vso_query_builder.models import BatchJob

        batch_job = batch_job_factory(batch_id="batch-poll-4")
        mock_check_status.return_value = {
            "status": "in_progress",
            "completed": 3,
            "failed": 0,
            "total": 5,
            "output_file_id": None,
            "error_file_id": None,
        }

        # Mock apply_async to prevent recursive self-scheduling
        with patch.object(poll_batch_job, "apply_async"):
            result = poll_batch_job.apply(args=[batch_job.id, BATCH_POLL_MAX_RETRIES]).result

        batch_job.refresh_from_db()
        assert batch_job.status == "failed"
        assert result["status"] == "timeout"

    def test_already_terminal_is_noop(self, batch_job_factory):
        """If BatchJob is already completed, return early without polling."""
        from vso_query_builder.tasks import poll_batch_job

        batch_job = batch_job_factory(batch_id="batch-poll-5", status="completed")

        result = poll_batch_job.apply(args=[batch_job.id]).result

        assert result["success"] is True
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# ingest_batch_results
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIngestBatchResults:

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_creates_paper_analysis_and_llm_call(
        self, mock_get_config, mock_retrieve, mock_chain, paper_factory, batch_job_factory,
    ):
        """Successful results create PaperAnalysis and LLMCall records."""
        from vso_query_builder.models import PaperAnalysis, BatchJob
        from vso_query_builder.tasks import ingest_batch_results

        paper = paper_factory(bibcode="2024ApJ...ingest001")
        paper_id = str(paper.id)

        batch_job = batch_job_factory(
            batch_id="batch-ingest-1",
            status="completed",
            paper_mapping={paper_id: f"paper_analysis|{paper_id}"},
            total_requests=1,
        )

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{paper_id}",
                "content": "# Instrument: AIA",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
                "finish_reason": "stop",
            },
        ]
        # Prevent downstream chain from executing
        mock_chain.return_value.apply_async = MagicMock()

        result = ingest_batch_results.apply(args=[batch_job.id]).result

        assert result["success"] is True
        assert result["succeeded"] == 1
        assert result["failed"] == 0

        # Verify PaperAnalysis created
        analysis = PaperAnalysis.objects.get(paper=paper, configuration_name="standard")
        assert analysis.status == "completed"
        assert "AIA" in analysis.instruments_details

        # Verify BatchJob updated
        batch_job.refresh_from_db()
        assert batch_job.status == "completed"
        assert batch_job.completed_requests == 1

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_handles_error_results(
        self, mock_get_config, mock_retrieve, mock_chain, paper_factory, batch_job_factory,
    ):
        """Error results increment failed count without creating records."""
        from vso_query_builder.models import PaperAnalysis
        from vso_query_builder.tasks import ingest_batch_results

        paper = paper_factory(bibcode="2024ApJ...ingest002")
        paper_id = str(paper.id)

        batch_job = batch_job_factory(
            batch_id="batch-ingest-2",
            status="completed",
            paper_mapping={paper_id: f"paper_analysis|{paper_id}"},
            total_requests=1,
        )

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{paper_id}",
                "error": "Content filter triggered",
            },
        ]

        result = ingest_batch_results.apply(args=[batch_job.id]).result

        assert result["succeeded"] == 0
        assert result["failed"] == 1
        assert not PaperAnalysis.objects.filter(paper=paper).exists()

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_kicks_off_downstream_chain(
        self, mock_get_config, mock_retrieve, mock_chain, paper_factory, batch_job_factory,
    ):
        """Successful results trigger the downstream processing chain."""
        from vso_query_builder.tasks import ingest_batch_results

        paper = paper_factory(bibcode="2024ApJ...ingest003")
        paper_id = str(paper.id)

        batch_job = batch_job_factory(
            batch_id="batch-ingest-3",
            status="completed",
            paper_mapping={paper_id: f"paper_analysis|{paper_id}"},
            total_requests=1,
        )

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{paper_id}",
                "content": "# Instrument: LASCO",
                "usage": {"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
                "finish_reason": "stop",
            },
        ]
        mock_chain.return_value.apply_async = MagicMock()

        ingest_batch_results.apply(args=[batch_job.id])

        # chain() should have been called to build the downstream pipeline
        mock_chain.assert_called_once()
        mock_chain.return_value.apply_async.assert_called_once()

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_strips_reasoning_block_from_instruments_details(
        self, mock_get_config, mock_retrieve, mock_chain, paper_factory, batch_job_factory,
    ):
        """<reasoning> block is stripped from instruments_details but preserved in LLMCall."""
        from vso_query_builder.models import PaperAnalysis, LLMCall
        from vso_query_builder.tasks import ingest_batch_results

        paper = paper_factory(bibcode="2024ApJ...reasoning001")
        paper_id = str(paper.id)

        batch_job = batch_job_factory(
            batch_id="batch-reasoning-1",
            status="completed",
            paper_mapping={paper_id: f"paper_analysis|{paper_id}"},
            total_requests=1,
        )

        reasoning_text = "I need to think about which instruments were used..."
        clean_content = "# Instrument: AIA\n## Period 1\n- Time range: 2020-01-01 to 2020-12-31"
        raw_content = f"<reasoning>{reasoning_text}</reasoning>\n{clean_content}"

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{paper_id}",
                "content": raw_content,
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
                "finish_reason": "stop",
            },
        ]
        mock_chain.return_value.apply_async = MagicMock()

        result = ingest_batch_results.apply(args=[batch_job.id]).result

        assert result["success"] is True

        # instruments_details should have reasoning stripped
        analysis = PaperAnalysis.objects.get(paper=paper, configuration_name="standard")
        assert "<reasoning>" not in analysis.instruments_details
        assert "AIA" in analysis.instruments_details

        # LLMCall should preserve full raw output and reasoning in metadata
        llm_call = analysis.llm_calls.get(call_type="paper_analysis")
        assert "<reasoning>" in llm_call.output_content
        assert llm_call.metadata.get("reasoning") == reasoning_text

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_no_reasoning_block_passthrough(
        self, mock_get_config, mock_retrieve, mock_chain, paper_factory, batch_job_factory,
    ):
        """Content without a <reasoning> block is stored unchanged."""
        from vso_query_builder.models import PaperAnalysis
        from vso_query_builder.tasks import ingest_batch_results

        paper = paper_factory(bibcode="2024ApJ...reasoning002")
        paper_id = str(paper.id)

        batch_job = batch_job_factory(
            batch_id="batch-reasoning-2",
            status="completed",
            paper_mapping={paper_id: f"paper_analysis|{paper_id}"},
            total_requests=1,
        )

        clean_content = "# Instrument: LASCO\n## Period 1\n- Time range: 2019-01-01 to 2019-12-31"

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{paper_id}",
                "content": clean_content,
                "usage": {"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
                "finish_reason": "stop",
            },
        ]
        mock_chain.return_value.apply_async = MagicMock()

        ingest_batch_results.apply(args=[batch_job.id])

        analysis = PaperAnalysis.objects.get(paper=paper, configuration_name="standard")
        assert analysis.instruments_details == clean_content

        llm_call = analysis.llm_calls.get(call_type="paper_analysis")
        assert "reasoning" not in llm_call.metadata

    @patch("vso_query_builder.tasks.chain")
    @patch("paper_data_linking.clients.batch_client.BatchClient.retrieve_results")
    @patch("paper_data_linking.config.settings.get_llm_configuration")
    def test_partially_failed_status(
        self, mock_get_config, mock_retrieve, mock_chain,
        paper_factory, batch_job_factory,
    ):
        """Mix of success and error results sets status to partially_failed."""
        from vso_query_builder.tasks import ingest_batch_results

        paper1 = paper_factory(bibcode="2024ApJ...ingest004a")
        paper2 = paper_factory(bibcode="2024ApJ...ingest004b")
        p1_id, p2_id = str(paper1.id), str(paper2.id)

        batch_job = batch_job_factory(
            batch_id="batch-ingest-4",
            status="completed",
            paper_mapping={
                p1_id: f"paper_analysis|{p1_id}",
                p2_id: f"paper_analysis|{p2_id}",
            },
            total_requests=2,
        )

        mock_get_config.return_value = _make_pipeline_config()
        mock_retrieve.return_value = [
            {
                "custom_id": f"paper_analysis|{p1_id}",
                "content": "# Success",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                "finish_reason": "stop",
            },
            {
                "custom_id": f"paper_analysis|{p2_id}",
                "error": "Rate limit exceeded",
            },
        ]
        mock_chain.return_value.apply_async = MagicMock()

        result = ingest_batch_results.apply(args=[batch_job.id]).result

        assert result["succeeded"] == 1
        assert result["failed"] == 1

        batch_job.refresh_from_db()
        assert batch_job.status == "partially_failed"
