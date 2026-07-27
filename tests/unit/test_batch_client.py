"""Tests for the BatchClient (batch API client via litellm)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from paper_data_linking.clients.batch_client import BatchClient
from paper_data_linking.config.settings import LLMCallConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return BatchClient()


@pytest.fixture
def llm_config_openai():
    return LLMCallConfig(model="openai/gpt-5", temperature=0.2, max_tokens=16000)


@pytest.fixture
def llm_config_bedrock():
    return LLMCallConfig(
        model="bedrock/converse/openai.gpt-oss-120b-1:0",
        temperature=0.2,
        max_tokens=16000,
        aws_region_name="us-west-2",
    )


@pytest.fixture
def llm_config_with_reasoning():
    return LLMCallConfig(
        model="openai/o3", temperature=1.0, reasoning_effort="medium",
    )


@pytest.fixture
def sample_papers():
    return [
        {"paper_id": "abc-123", "text": "Solar wind measurements from AIA..."},
        {"paper_id": "def-456", "text": "LASCO coronagraph observations..."},
    ]


@pytest.fixture
def openai_batch_output_jsonl():
    """Sample OpenAI batch output JSONL (two results, one error)."""
    lines = [
        json.dumps({
            "custom_id": "paper_analysis|abc-123",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{
                        "message": {"content": "# Analysis of abc-123"},
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                },
            },
        }),
        json.dumps({
            "custom_id": "paper_analysis|def-456",
            "response": {"status_code": 200, "body": {"choices": []}},
            "error": {"message": "Content filter triggered"},
        }),
    ]
    return "\n".join(lines)


@pytest.fixture
def bedrock_batch_output_jsonl():
    """Sample Bedrock batch output JSONL."""
    lines = [
        json.dumps({
            "recordId": "paper_analysis|abc-123",
            "modelOutput": {
                "choices": [{
                    "message": {"content": "# Bedrock analysis of abc-123"},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "input_tokens": 900,
                    "output_tokens": 400,
                },
            },
        }),
        json.dumps({
            "recordId": "paper_analysis|def-456",
            "modelOutput": {},
            "error": "Model timeout",
        }),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# prepare_requests
# ---------------------------------------------------------------------------

class TestPrepareRequests:
    def test_generates_valid_jsonl(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "You are a helpful assistant.")
        lines = result.strip().split("\n")
        assert len(lines) == 2

        for line in lines:
            obj = json.loads(line)
            assert obj["method"] == "POST"
            assert obj["url"] == "/v1/chat/completions"
            assert "body" in obj
            assert "custom_id" in obj

    def test_strips_provider_prefix(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert first["body"]["model"] == "gpt-5"

    def test_strips_bedrock_prefix(self, client, sample_papers, llm_config_bedrock):
        result = client.prepare_requests(sample_papers, llm_config_bedrock, "system prompt")
        first = json.loads(result.split("\n")[0])
        # split('/', 1)[1] on "bedrock/converse/openai.gpt-oss-120b-1:0"
        assert first["body"]["model"] == "converse/openai.gpt-oss-120b-1:0"

    def test_custom_id_format(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert first["custom_id"] == "paper_analysis|abc-123"

    def test_includes_temperature(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert first["body"]["temperature"] == 0.2

    def test_includes_max_tokens_when_set(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert first["body"]["max_tokens"] == 16000

    def test_omits_max_tokens_when_none(self, client, sample_papers):
        config = LLMCallConfig(model="openai/gpt-5", temperature=0.5)
        result = client.prepare_requests(sample_papers, config, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert "max_tokens" not in first["body"]

    def test_includes_reasoning_effort_when_set(self, client, sample_papers, llm_config_with_reasoning):
        result = client.prepare_requests(sample_papers, llm_config_with_reasoning, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert first["body"]["reasoning_effort"] == "medium"

    def test_omits_reasoning_effort_when_none(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "system prompt")
        first = json.loads(result.split("\n")[0])
        assert "reasoning_effort" not in first["body"]

    def test_messages_structure(self, client, sample_papers, llm_config_openai):
        result = client.prepare_requests(sample_papers, llm_config_openai, "Analyze this paper.")
        first = json.loads(result.split("\n")[0])
        messages = first["body"]["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "Analyze this paper."}
        assert messages[1] == {"role": "user", "content": sample_papers[0]["text"]}

    def test_empty_papers_list(self, client, llm_config_openai):
        result = client.prepare_requests([], llm_config_openai, "system prompt")
        assert result == ""


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

class TestSubmit:
    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_openai_submit(self, mock_litellm, client):
        mock_litellm.create_file.return_value = SimpleNamespace(id="file-abc123")
        mock_litellm.create_batch.return_value = SimpleNamespace(id="batch_xyz")

        result = client.submit('{"custom_id":"test","method":"POST","url":"/v1/chat/completions","body":{}}')

        assert result == {"batch_id": "batch_xyz", "input_file_id": "file-abc123"}
        mock_litellm.create_file.assert_called_once()
        call_kwargs = mock_litellm.create_file.call_args
        assert call_kwargs.kwargs["purpose"] == "batch"
        assert call_kwargs.kwargs["custom_llm_provider"] == "openai"
        assert "extra_body" not in call_kwargs.kwargs

    @patch("paper_data_linking.clients.batch_client._s3_client")
    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_bedrock_submit_uses_boto3(self, mock_bedrock_factory, mock_s3_factory, client):
        mock_s3 = MagicMock()
        mock_s3_factory.return_value = mock_s3

        mock_bedrock = MagicMock()
        mock_bedrock.create_model_invocation_job.return_value = {
            "jobArn": "arn:aws:bedrock:us-west-2:123:model-invocation-job/test-job"
        }
        mock_bedrock_factory.return_value = mock_bedrock

        # Bedrock requires ≥100 records
        jsonl_100 = "\n".join(
            f'{{"recordId": "r{i}", "modelInput": {{}}}}'
            for i in range(100)
        )
        result = client.submit(
            jsonl_100,
            provider="bedrock",
            model_name="openai.gpt-oss-120b-1:0",
            aws_region_name="us-west-2",
            aws_batch_role_arn="arn:aws:iam::123456789:role/pdl-bedrock-batch-role",
        )

        assert result["batch_id"] == "arn:aws:bedrock:us-west-2:123:model-invocation-job/test-job"
        assert "s3://" in result["input_file_id"]

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_bedrock.create_model_invocation_job.call_args.kwargs
        assert call_kwargs["modelId"] == "openai.gpt-oss-120b-1:0"
        assert call_kwargs["roleArn"] == "arn:aws:iam::123456789:role/pdl-bedrock-batch-role"

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_returns_batch_and_file_ids(self, mock_litellm, client):
        mock_litellm.create_file.return_value = SimpleNamespace(id="file-001")
        mock_litellm.create_batch.return_value = SimpleNamespace(id="batch-002")

        result = client.submit("jsonl content")
        assert "batch_id" in result
        assert "input_file_id" in result

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_create_batch_called_with_file_id(self, mock_litellm, client):
        mock_litellm.create_file.return_value = SimpleNamespace(id="file-xyz")
        mock_litellm.create_batch.return_value = SimpleNamespace(id="batch-001")

        client.submit("jsonl")
        mock_litellm.create_batch.assert_called_once_with(
            completion_window="24h",
            endpoint="/v1/chat/completions",
            input_file_id="file-xyz",
            custom_llm_provider="openai",
        )


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------

class TestCheckStatus:
    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_parses_dict_request_counts(self, mock_litellm, client):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="in_progress",
            request_counts={"completed": 5, "failed": 1, "total": 10},
            output_file_id=None,
            error_file_id=None,
        )

        result = client.check_status("batch-123")
        assert result == {
            "status": "in_progress",
            "completed": 5,
            "failed": 1,
            "total": 10,
            "output_file_id": None,
            "error_file_id": None,
        }

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_parses_object_request_counts(self, mock_litellm, client):
        """request_counts can be an object with attributes instead of a dict."""
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="completed",
            request_counts=SimpleNamespace(completed=10, failed=0, total=10),
            output_file_id="file-out-123",
            error_file_id=None,
        )

        result = client.check_status("batch-456")
        assert result["status"] == "completed"
        assert result["completed"] == 10
        assert result["failed"] == 0
        assert result["output_file_id"] == "file-out-123"

    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_bedrock_check_status_uses_boto3(self, mock_bedrock_factory, client):
        mock_bedrock = MagicMock()
        mock_bedrock.get_model_invocation_job.return_value = {
            "status": "InProgress",
            "statistics": {"numberOfRecordsSucceeded": 3, "numberOfRecordsFailed": 1},
            "outputDataConfig": {"s3OutputDataConfig": {"s3Uri": "s3://bucket/out/"}},
        }
        mock_bedrock_factory.return_value = mock_bedrock

        result = client.check_status("arn:aws:bedrock:us-west-2:123:job/test", provider="bedrock", aws_region_name="us-west-2")

        assert result["status"] == "processing"
        assert result["completed"] == 3
        assert result["failed"] == 1
        mock_bedrock.get_model_invocation_job.assert_called_once_with(
            jobIdentifier="arn:aws:bedrock:us-west-2:123:job/test"
        )

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_handles_none_request_counts(self, mock_litellm, client):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="validating",
            request_counts=None,
            output_file_id=None,
            error_file_id=None,
        )

        result = client.check_status("batch-000")
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# retrieve_results — OpenAI format
# ---------------------------------------------------------------------------

class TestRetrieveResultsOpenAI:
    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_parses_successful_result(self, mock_litellm, client, openai_batch_output_jsonl):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="completed", output_file_id="file-out-1",
        )
        mock_litellm.file_content.return_value = SimpleNamespace(text=openai_batch_output_jsonl)

        results = client.retrieve_results("batch-1")

        assert len(results) == 2
        assert results[0]["custom_id"] == "paper_analysis|abc-123"
        assert results[0]["content"] == "# Analysis of abc-123"
        assert results[0]["finish_reason"] == "stop"
        assert results[0]["usage"]["prompt_tokens"] == 1000
        assert results[0]["usage"]["completion_tokens"] == 500
        assert results[0]["usage"]["total_tokens"] == 1500

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_parses_error_result(self, mock_litellm, client, openai_batch_output_jsonl):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="completed", output_file_id="file-out-1",
        )
        mock_litellm.file_content.return_value = SimpleNamespace(text=openai_batch_output_jsonl)

        results = client.retrieve_results("batch-1")

        assert results[1]["custom_id"] == "paper_analysis|def-456"
        assert "error" in results[1]
        assert "Content filter" in results[1]["error"]

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_raises_if_not_completed(self, mock_litellm, client):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="in_progress", output_file_id=None,
        )

        with pytest.raises(ValueError, match="Batch not complete"):
            client.retrieve_results("batch-1")

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_raises_if_no_output_file_id(self, mock_litellm, client):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="completed", output_file_id=None,
        )

        with pytest.raises(ValueError, match="no output_file_id"):
            client.retrieve_results("batch-1")


# ---------------------------------------------------------------------------
# retrieve_results — Bedrock format
# ---------------------------------------------------------------------------

class TestRetrieveResultsBedrock:
    def _make_boto3_mocks(self, bedrock_factory, s3_factory, output_jsonl):
        """Set up mock bedrock + s3 clients returning the given output JSONL."""
        mock_bedrock = MagicMock()
        mock_bedrock.get_model_invocation_job.return_value = {
            "status": "Completed",
            "outputDataConfig": {"s3OutputDataConfig": {"s3Uri": "s3://pdl-bedrock-batch/batch-output/job1/"}},
        }
        bedrock_factory.return_value = mock_bedrock

        mock_s3 = MagicMock()
        mock_s3.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "batch-output/job1/output.jsonl"}]}
        ]
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: output_jsonl.encode())}
        s3_factory.return_value = mock_s3

    @patch("paper_data_linking.clients.batch_client._s3_client")
    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_parses_bedrock_successful_result(self, mock_bedrock_factory, mock_s3_factory, client, bedrock_batch_output_jsonl):
        self._make_boto3_mocks(mock_bedrock_factory, mock_s3_factory, bedrock_batch_output_jsonl)

        results = client.retrieve_results("arn:aws:bedrock:us-west-2:123:job/job1", provider="bedrock", aws_region_name="us-west-2")

        assert len(results) == 2
        assert results[0]["custom_id"] == "paper_analysis|abc-123"
        assert results[0]["content"] == "# Bedrock analysis of abc-123"
        assert results[0]["finish_reason"] == "stop"

    @patch("paper_data_linking.clients.batch_client._s3_client")
    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_normalizes_bedrock_usage_keys(self, mock_bedrock_factory, mock_s3_factory, client, bedrock_batch_output_jsonl):
        self._make_boto3_mocks(mock_bedrock_factory, mock_s3_factory, bedrock_batch_output_jsonl)

        results = client.retrieve_results("arn:aws:bedrock:us-west-2:123:job/job1", provider="bedrock", aws_region_name="us-west-2")

        usage = results[0]["usage"]
        assert usage["prompt_tokens"] == 900
        assert usage["completion_tokens"] == 400
        assert usage["total_tokens"] == 0  # not provided in Bedrock output

    @patch("paper_data_linking.clients.batch_client._s3_client")
    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_parses_bedrock_error_result(self, mock_bedrock_factory, mock_s3_factory, client, bedrock_batch_output_jsonl):
        self._make_boto3_mocks(mock_bedrock_factory, mock_s3_factory, bedrock_batch_output_jsonl)

        results = client.retrieve_results("arn:aws:bedrock:us-west-2:123:job/job1", provider="bedrock", aws_region_name="us-west-2")

        assert results[1]["custom_id"] == "paper_analysis|def-456"
        assert "error" in results[1]
        assert "Model timeout" in results[1]["error"]

    @patch("paper_data_linking.clients.batch_client._s3_client")
    @patch("paper_data_linking.clients.batch_client._bedrock_client")
    def test_passes_aws_region_name(self, mock_bedrock_factory, mock_s3_factory, client):
        single_line = '{"recordId":"test","modelOutput":{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{}}}'
        self._make_boto3_mocks(mock_bedrock_factory, mock_s3_factory, single_line)

        client.retrieve_results("arn:aws:bedrock:us-west-2:123:job/job1", provider="bedrock", aws_region_name="us-west-2")

        mock_bedrock_factory.assert_called_with("us-west-2")
        mock_s3_factory.assert_called_with("us-west-2")

    @patch("paper_data_linking.clients.batch_client.litellm")
    def test_omits_aws_region_for_openai(self, mock_litellm, client, openai_batch_output_jsonl):
        mock_litellm.retrieve_batch.return_value = SimpleNamespace(
            status="completed", output_file_id="file-out-1",
        )
        mock_litellm.file_content.return_value = SimpleNamespace(text=openai_batch_output_jsonl)

        client.retrieve_results("batch-1", provider="openai", aws_region_name="us-west-2")

        call_kwargs = mock_litellm.file_content.call_args.kwargs
        assert "aws_region_name" not in call_kwargs


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

class TestEstimateCost:
    def test_basic_estimate(self):
        papers = [
            {"paper_id": "1", "text": "a" * 4000},  # ~1000 tokens
            {"paper_id": "2", "text": "b" * 8000},  # ~2000 tokens
        ]
        result = BatchClient.estimate_cost(papers, "openai/gpt-5")

        assert result["total_requests"] == 2
        assert result["estimated_input_tokens"] == 3000
        assert result["estimated_output_tokens"] == 6000  # 2 * 3000 default

    def test_custom_output_tokens(self):
        papers = [{"paper_id": "1", "text": "a" * 400}]
        result = BatchClient.estimate_cost(papers, "openai/gpt-5", avg_output_tokens=1000)

        assert result["estimated_output_tokens"] == 1000

    def test_empty_papers(self):
        result = BatchClient.estimate_cost([], "openai/gpt-5")
        assert result["total_requests"] == 0
        assert result["estimated_cost_usd"] == 0.0

    def test_returns_expected_keys(self):
        papers = [{"paper_id": "1", "text": "hello"}]
        result = BatchClient.estimate_cost(papers, "openai/gpt-5")
        assert set(result.keys()) == {
            "total_requests", "estimated_input_tokens",
            "estimated_output_tokens", "estimated_cost_usd", "note",
        }
