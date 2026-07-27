"""Integration tests for the batch runner with real Bedrock Batch API calls.

These tests submit actual batch jobs to the AWS Bedrock Batch API and verify
the submission succeeds. They do NOT wait for completion (can take minutes/hours).

Requires:
    - AWS credentials with Bedrock Batch access (AWS_ACCESS_KEY_ID etc in env)
    - AWS_BATCH_ROLE_ARN set to the pdl-bedrock-batch-role ARN
    - bedrock-test LLM configuration (openai.gpt-oss-120b-1:0, us-west-2)

Run with:
    pytest tests/integration/test_batch_runner_integration.py -m integration -v -s
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from paper_data_linking.clients.batch_client import BatchClient
from paper_data_linking.config.settings import get_llm_configuration


SAMPLE_PAPER_TEXT = (
    "We present observations of solar flares using the Atmospheric Imaging Assembly (AIA) "
    "instrument aboard the Solar Dynamics Observatory (SDO). AIA provided EUV images at "
    "171 Angstroms with a cadence of 12 seconds from 2012-01-01 to 2012-03-31. "
    "Additional data from the Large Angle and Spectrometric Coronagraph (LASCO) C2 and C3 "
    "aboard SOHO were used for coronal mass ejection tracking between 2012-01-15 and "
    "2012-02-28. The Solar Energetic Particle instrument on STEREO-A provided particle "
    "flux data throughout the observation period."
)


@pytest.mark.integration
class TestBatchClientBedrockIntegration:
    """Tests BatchClient.submit() and check_status() against real Bedrock Batch API."""

    def test_submit_and_check_status(self):
        """Submit a single-paper batch to Bedrock Batch and verify initial state."""
        if not os.environ.get("AWS_BATCH_ROLE_ARN"):
            pytest.skip("AWS_BATCH_ROLE_ARN not set")

        config = get_llm_configuration("bedrock-test")
        paper_analysis_config = config.paper_analysis
        client = BatchClient()

        # Bedrock Batch requires a minimum of 100 records per job.
        papers = [
            {"paper_id": f"integration-test-{i:03d}", "text": SAMPLE_PAPER_TEXT}
            for i in range(100)
        ]
        jsonl = client.prepare_requests(
            papers,
            paper_analysis_config,
            "You are a heliophysics expert. Identify all instruments, observatories, "
            "and datasets mentioned, including the time ranges of data used.",
            provider="bedrock",
        )

        model_name = paper_analysis_config.model.rsplit("/", 1)[-1]

        result = client.submit(
            jsonl,
            provider="bedrock",
            model_name=model_name,
            aws_region_name=paper_analysis_config.aws_region_name,
            aws_batch_role_arn=os.environ["AWS_BATCH_ROLE_ARN"],
        )

        print(f"\nBatch submitted — id: {result['batch_id']}, file: {result['input_file_id']}")

        assert result["batch_id"], "Expected non-empty batch_id"
        assert result["input_file_id"], "Expected non-empty input_file_id"

        status = client.check_status(
            result["batch_id"],
            provider="bedrock",
            aws_region_name=paper_analysis_config.aws_region_name,
        )

        print(f"Initial status: {status['status']} ({status['completed']}/{status['total']} complete)")

        assert status["status"] in (
            "validating", "in_progress", "submitted", "processing", "completed"
        ), f"Unexpected initial status: {status['status']}"
        # Bedrock does not populate statistics until processing starts;
        # total may be 0 when status is "submitted" or "validating".
        assert status["total"] >= 0


@pytest.mark.integration
@pytest.mark.django_db
class TestSubmitBatchPaperAnalysisBedrockIntegration:
    """Tests the full Celery task path with real Bedrock Batch submission and DB state."""

    @patch("vso_query_builder.tasks.poll_batch_job")
    def test_task_creates_bedrock_batch_job(self, mock_poll, paper_factory):
        """submit_batch_paper_analysis submits to Bedrock and creates a BatchJob record."""
        from vso_query_builder.tasks import submit_batch_paper_analysis
        from vso_query_builder.models import BatchJob

        if not os.environ.get("AWS_BATCH_ROLE_ARN"):
            pytest.skip("AWS_BATCH_ROLE_ARN not set")

        mock_poll.apply_async = MagicMock()
        paper = paper_factory(full_text=SAMPLE_PAPER_TEXT)

        result = submit_batch_paper_analysis.apply(
            args=[[str(paper.id)], "bedrock-test"]
        ).result

        print(f"\nTask result: {result}")

        assert result["success"] is True, f"Expected success, got: {result.get('error')}"
        assert result["total_papers"] == 1

        batch_job = BatchJob.objects.get(batch_id=result["batch_id"])
        assert batch_job.provider == "bedrock"
        assert batch_job.status == "submitted"
        assert batch_job.total_requests == 1
        assert batch_job.configuration_name == "bedrock-test"

        print(f"BatchJob created — id: {batch_job.batch_id}, status: {batch_job.status}")
