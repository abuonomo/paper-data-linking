"""
Production batch API client supporting OpenAI (via litellm) and Bedrock (via boto3).

Handles batch JSONL preparation, submission, status polling, and result retrieval.
Works entirely in-memory (no filesystem I/O) and integrates with LLMCallConfig.

OpenAI: uses litellm.create_file / create_batch / retrieve_batch / file_content.
Bedrock: uses boto3 directly — S3 for input/output, bedrock for job lifecycle.
"""

import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
import litellm

from paper_data_linking.config.settings import LLMCallConfig
from paper_data_linking.clients.batch_replay import pick_message_content

logger = logging.getLogger(__name__)

# Map Bedrock job statuses → our internal statuses
_BEDROCK_STATUS_MAP = {
    "Submitted": "submitted",
    "Validating": "submitted",
    "InProgress": "processing",
    "Stopping": "processing",
    "Completed": "completed",
    "PartiallyCompleted": "completed",  # results are available
    "Failed": "failed",
    "Stopped": "failed",
    "Expired": "failed",
}


def _assume_role_credentials(role_arn: str, region: str) -> dict:
    """Assume an IAM role and return credential kwargs for boto3 client calls.

    Used on the EC2 instance where the instance role (account A) needs to call
    Bedrock APIs in a different account (account B) via pdl-bedrock-invoke-role.
    """
    sts = boto3.client("sts", region_name=region)
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="pdl-batch-client",
    )
    creds = response["Credentials"]
    return {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
    }


def _bedrock_client(region: str):
    """Create a Bedrock boto3 client, optionally via assume-role.

    If AWS_BEDROCK_INVOKE_ROLE_ARN is set, assumes that role first.
    This is required when the compute account (where the instance role lives)
    differs from the account that hosts the Bedrock models, so the caller must
    assume a cross-account invoke role.
    """
    invoke_role_arn = os.environ.get("AWS_BEDROCK_INVOKE_ROLE_ARN")
    if invoke_role_arn:
        creds = _assume_role_credentials(invoke_role_arn, region)
        logger.debug(f"Bedrock client using assumed role: {invoke_role_arn}")
        return boto3.session.Session().client("bedrock", region_name=region, **creds)
    # Fresh Session: the default session caches credentials for the process
    # lifetime; a new Session re-reads AWS_SHARED_CREDENTIALS_FILE each time,
    # so renewals take effect in long-lived workers without restarts.
    return boto3.session.Session().client("bedrock", region_name=region)


def _s3_client(region: str):
    """Create an S3 boto3 client, optionally via assume-role (same as _bedrock_client)."""
    invoke_role_arn = os.environ.get("AWS_BEDROCK_INVOKE_ROLE_ARN")
    if invoke_role_arn:
        creds = _assume_role_credentials(invoke_role_arn, region)
        return boto3.session.Session().client("s3", region_name=region, **creds)
    return boto3.session.Session().client("s3", region_name=region)  # fresh Session: re-reads creds file


class BatchClient:
    """Batch API client supporting OpenAI (litellm) and Bedrock (boto3)."""

    def prepare_requests(
        self,
        papers_with_text: list[dict],
        llm_config: LLMCallConfig,
        system_prompt: str,
        provider: str = "openai",
    ) -> str:
        """Build JSONL string for batch submission.

        Args:
            papers_with_text: List of {"paper_id": str, "text": str}
            llm_config: Config with model, temperature, etc.
            system_prompt: The paper_analysis system prompt
            provider: "openai" or "bedrock" — controls JSONL format

        Returns:
            JSONL string ready for upload
        """
        if provider == "bedrock":
            return self._prepare_bedrock_requests(papers_with_text, llm_config, system_prompt)
        return self._prepare_openai_requests(papers_with_text, llm_config, system_prompt)

    def _prepare_openai_requests(
        self,
        papers_with_text: list[dict],
        llm_config: LLMCallConfig,
        system_prompt: str,
    ) -> str:
        # OpenAI batch API expects bare model name (no provider prefix)
        batch_model = llm_config.model
        if "/" in batch_model:
            batch_model = batch_model.split("/", 1)[1]

        lines = []
        for paper in papers_with_text:
            paper_id = str(paper["paper_id"])
            body = {
                "model": batch_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": paper["text"]},
                ],
                "temperature": llm_config.temperature,
            }
            if llm_config.max_tokens is not None:
                body["max_tokens"] = llm_config.max_tokens
            if llm_config.reasoning_effort is not None:
                body["reasoning_effort"] = llm_config.reasoning_effort

            lines.append(json.dumps({
                "custom_id": f"paper_analysis|{paper_id}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }))

        return "\n".join(lines)

    def _prepare_bedrock_requests(
        self,
        papers_with_text: list[dict],
        llm_config: LLMCallConfig,
        system_prompt: str,
    ) -> str:
        # Bedrock batch format: {"recordId": "...", "modelInput": {...}}
        # Model is specified at job level, not per-record.
        lines = []
        for paper in papers_with_text:
            paper_id = str(paper["paper_id"])
            model_input = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": paper["text"]},
                ],
                "temperature": llm_config.temperature,
            }
            if llm_config.max_tokens is not None:
                model_input["max_tokens"] = llm_config.max_tokens
            if llm_config.reasoning_effort is not None:
                model_input["reasoning_effort"] = llm_config.reasoning_effort

            lines.append(json.dumps({
                "recordId": f"paper_analysis|{paper_id}",
                "modelInput": model_input,
            }))

        return "\n".join(lines)

    def prepare_generic_requests(
        self,
        records: list[dict],
        provider: str = "bedrock",
    ) -> str:
        """Build batch JSONL for arbitrary downstream LLM calls (wave runner).

        Each record is::

            {"record_id": str,            # used as recordId / custom_id (the request hash)
             "model": str,                # litellm model string (job-level for Bedrock)
             "messages": [...],
             "params": {...},             # generation params (temperature, max_tokens, ...)
             "response_format": dict|None}  # OpenAI json_schema envelope or {"type": ...}

        For Bedrock, all records in one call must share a model (it's set at the job
        level); the caller groups by model before invoking this.
        """
        if provider == "bedrock":
            lines = []
            for r in records:
                model_input = {"messages": r["messages"], **(r.get("params") or {})}
                # Structured output is enforced via a FORCED tool (litellm's approach),
                # NOT response_format — Bedrock batch honors the former, ignores the latter.
                if r.get("tools"):
                    model_input["tools"] = r["tools"]
                    if r.get("tool_choice"):
                        model_input["tool_choice"] = r["tool_choice"]
                lines.append(json.dumps({
                    "recordId": r["record_id"],
                    "modelInput": model_input,
                }))
            return "\n".join(lines)

        # OpenAI (symmetry; Bedrock is the supported corpus path)
        lines = []
        for r in records:
            model = r["model"]
            batch_model = model.split("/", 1)[1] if "/" in model else model
            body = {"model": batch_model, "messages": r["messages"], **(r.get("params") or {})}
            if r.get("tools"):
                body["tools"] = r["tools"]
                if r.get("tool_choice"):
                    body["tool_choice"] = r["tool_choice"]
            lines.append(json.dumps({
                "custom_id": r["record_id"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }))
        return "\n".join(lines)

    def submit(
        self,
        jsonl_content: str,
        provider: str = "openai",
        model_name: Optional[str] = None,
        aws_region_name: Optional[str] = None,
        aws_batch_role_arn: Optional[str] = None,
    ) -> dict:
        """Upload JSONL and create batch job.

        Args:
            jsonl_content: JSONL string from prepare_requests()
            provider: "openai" or "bedrock"
            model_name: Required for Bedrock — bare model ID (e.g. "openai.gpt-oss-120b-1:0")
            aws_region_name: AWS region for Bedrock (e.g. "us-west-2")
            aws_batch_role_arn: IAM role ARN Bedrock assumes for S3 access

        Returns:
            {"batch_id": str, "input_file_id": str}
        """
        if provider == "bedrock":
            return self._submit_bedrock(
                jsonl_content,
                model_name=model_name,
                aws_region_name=aws_region_name or "us-east-1",
                aws_batch_role_arn=aws_batch_role_arn,
            )
        return self._submit_openai(jsonl_content)

    def _submit_openai(self, jsonl_content: str) -> dict:
        file_bytes = jsonl_content.encode("utf-8")
        file_obj = litellm.create_file(
            file=io.BytesIO(file_bytes),
            purpose="batch",
            custom_llm_provider="openai",
        )
        logger.info(f"Uploaded batch file: {file_obj.id}")

        batch = litellm.create_batch(
            completion_window="24h",
            endpoint="/v1/chat/completions",
            input_file_id=file_obj.id,
            custom_llm_provider="openai",
        )
        logger.info(f"Created OpenAI batch: {batch.id}")
        return {"batch_id": batch.id, "input_file_id": file_obj.id}

    def _submit_bedrock(
        self,
        jsonl_content: str,
        model_name: str,
        aws_region_name: str,
        aws_batch_role_arn: Optional[str],
    ) -> dict:
        if not aws_batch_role_arn:
            raise ValueError("aws_batch_role_arn is required for Bedrock batch submission")

        n_records = sum(1 for line in jsonl_content.splitlines() if line.strip())
        # Real Bedrock enforces a 100-record floor; the fake-Bedrock test stack
        # lowers it via env so every group exercises the batch path offline.
        min_records = int(os.environ.get("PDL_BEDROCK_MIN_RECORDS", "100"))
        if n_records < min_records:
            raise ValueError(
                f"Bedrock Batch requires at least {min_records} records; got {n_records}. "
                "Use the regular (non-batch) API for smaller sets."
            )

        bucket = os.environ.get("AWS_BATCH_BUCKET", "pdl-bedrock-batch")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        job_id = uuid.uuid4().hex[:8]
        job_name = f"pdl-batch-{timestamp}-{job_id}"
        input_key = f"batch-input/{job_name}.jsonl"
        output_prefix = f"s3://{bucket}/batch-output/{job_name}/"

        # Upload input JSONL to S3
        s3 = _s3_client(aws_region_name)
        s3.put_object(Bucket=bucket, Key=input_key, Body=jsonl_content.encode("utf-8"))
        input_s3_uri = f"s3://{bucket}/{input_key}"
        logger.info(f"Uploaded Bedrock batch input: {input_s3_uri}")

        # Create Bedrock batch inference job
        bedrock = _bedrock_client(aws_region_name)
        response = bedrock.create_model_invocation_job(
            jobName=job_name,
            modelId=model_name,
            roleArn=aws_batch_role_arn,
            inputDataConfig={
                "s3InputDataConfig": {
                    "s3Uri": input_s3_uri,
                    "s3InputFormat": "JSONL",
                }
            },
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": output_prefix,
                }
            },
        )

        job_arn = response["jobArn"]
        logger.info(f"Created Bedrock batch job: {job_arn}")
        return {"batch_id": job_arn, "input_file_id": input_s3_uri}

    def check_status(
        self,
        batch_id: str,
        provider: str = "openai",
        aws_region_name: Optional[str] = None,
    ) -> dict:
        """Check batch status.

        Returns:
            {"status": str, "completed": int, "failed": int, "total": int,
             "output_file_id": str | None, "error_file_id": str | None}
        """
        if provider == "bedrock":
            return self._check_status_bedrock(batch_id, aws_region_name or "us-east-1")
        return self._check_status_openai(batch_id)

    def _check_status_openai(self, batch_id: str) -> dict:
        batch = litellm.retrieve_batch(batch_id=batch_id, custom_llm_provider="openai")
        request_counts = getattr(batch, "request_counts", None) or {}
        if isinstance(request_counts, dict):
            completed = request_counts.get("completed", 0)
            failed = request_counts.get("failed", 0)
            total = request_counts.get("total", 0)
        else:
            completed = getattr(request_counts, "completed", 0)
            failed = getattr(request_counts, "failed", 0)
            total = getattr(request_counts, "total", 0)

        return {
            "status": batch.status,
            "completed": completed,
            "failed": failed,
            "total": total,
            "output_file_id": getattr(batch, "output_file_id", None),
            "error_file_id": getattr(batch, "error_file_id", None),
        }

    def _check_status_bedrock(self, job_arn: str, aws_region_name: str) -> dict:
        bedrock = _bedrock_client(aws_region_name)
        response = bedrock.get_model_invocation_job(jobIdentifier=job_arn)

        bedrock_status = response.get("status", "")
        status = _BEDROCK_STATUS_MAP.get(bedrock_status, "processing")

        stats = response.get("statistics") or {}
        completed = stats.get("numberOfRecordsSucceeded", 0)
        failed = stats.get("numberOfRecordsFailed", 0)

        output_uri = (
            response.get("outputDataConfig", {})
            .get("s3OutputDataConfig", {})
            .get("s3Uri")
        )

        return {
            "status": status,
            "completed": completed,
            "failed": failed,
            "total": completed + failed,
            "output_file_id": output_uri,
            "error_file_id": None,
        }

    def retrieve_results(
        self,
        batch_id: str,
        provider: str = "openai",
        aws_region_name: Optional[str] = None,
    ) -> list[dict]:
        """Download and parse batch results.

        Args:
            batch_id: OpenAI batch ID or Bedrock job ARN
            provider: "openai" or "bedrock"
            aws_region_name: AWS region (Bedrock only)

        Returns:
            List of {"custom_id", "content", "usage", "finish_reason"}
            or {"custom_id", "error"} for failures.
        """
        if provider == "bedrock":
            return self._retrieve_results_bedrock(batch_id, aws_region_name or "us-east-1")
        return self._retrieve_results_openai(batch_id)

    def _retrieve_results_openai(self, batch_id: str) -> list[dict]:
        batch = litellm.retrieve_batch(batch_id=batch_id, custom_llm_provider="openai")
        if batch.status != "completed":
            raise ValueError(f"Batch not complete. Status: {batch.status}")

        output_file_id = getattr(batch, "output_file_id", None)
        if not output_file_id:
            raise ValueError("Batch completed but no output_file_id found")

        content = litellm.file_content(file_id=output_file_id, custom_llm_provider="openai")
        return self._parse_openai_results(content.text)

    def _retrieve_results_bedrock(self, job_arn: str, aws_region_name: str) -> list[dict]:
        bedrock = _bedrock_client(aws_region_name)
        job = bedrock.get_model_invocation_job(jobIdentifier=job_arn)

        if job["status"] not in ("Completed", "PartiallyCompleted"):
            raise ValueError(f"Batch not complete. Status: {job['status']}")

        output_uri = job["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"]
        match = re.match(r"s3://([^/]+)/(.+)", output_uri)
        if not match:
            raise ValueError(f"Cannot parse output S3 URI: {output_uri}")
        bucket, prefix = match.group(1), match.group(2)

        s3 = _s3_client(aws_region_name)
        paginator = s3.get_paginator("list_objects_v2")
        all_lines = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".jsonl") or key.endswith(".out"):
                    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
                    all_lines.extend(body.strip().split("\n"))

        return self._parse_bedrock_results(all_lines)

    def _parse_openai_results(self, text: str) -> list[dict]:
        results = []
        for line in text.strip().split("\n"):
            if not line:
                continue
            result = json.loads(line)
            custom_id = result.get("custom_id", "")
            response = result.get("response", {})
            body = response.get("body", {})
            choices = body.get("choices", [])
            usage = body.get("usage", {})
            error_info = (result.get("error") or {}).get("message")

            if not choices:
                results.append({
                    "custom_id": custom_id,
                    "error": str(error_info) if error_info else "No choices in response",
                })
                continue

            message = choices[0].get("message", {})
            content = pick_message_content(message)
            results.append({
                "custom_id": custom_id,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "finish_reason": choices[0].get("finish_reason", ""),
            })
        return results

    def _parse_bedrock_results(self, lines: list[str]) -> list[dict]:
        results = []
        for line in lines:
            if not line:
                continue
            result = json.loads(line)
            custom_id = result.get("recordId", "")
            model_output = result.get("modelOutput", {})
            choices = model_output.get("choices", [])
            usage = model_output.get("usage", {})
            error_info = result.get("error", model_output.get("error"))

            if not choices:
                results.append({
                    "custom_id": custom_id,
                    "error": str(error_info) if error_info else "No choices in response",
                })
                continue

            message = choices[0].get("message", {})
            content = pick_message_content(message)
            results.append({
                "custom_id": custom_id,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                    "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "finish_reason": choices[0].get("finish_reason", ""),
            })
        return results

    @staticmethod
    def estimate_cost(
        papers_with_text: list[dict],
        model: str,
        avg_output_tokens: int = 3000,
    ) -> dict:
        """Estimate batch cost before submitting.

        Args:
            papers_with_text: List of {"paper_id": str, "text": str}
            model: Model identifier (e.g., "openai/gpt-5")
            avg_output_tokens: Estimated average output tokens per request

        Returns:
            {"total_requests": int, "estimated_input_tokens": int,
             "estimated_output_tokens": int, "estimated_cost_usd": float}
        """
        total_input_tokens = 0
        for paper in papers_with_text:
            # Rough estimate: ~4 chars per token
            total_input_tokens += len(paper["text"]) // 4

        total_output_tokens = len(papers_with_text) * avg_output_tokens

        # Batch API provides 50% discount
        input_cost_per_1m = 1.25   # rough gpt-5 estimate with batch discount
        output_cost_per_1m = 5.00  # rough gpt-5 estimate with batch discount

        estimated_cost = (
            (total_input_tokens / 1_000_000) * input_cost_per_1m
            + (total_output_tokens / 1_000_000) * output_cost_per_1m
        )

        return {
            "total_requests": len(papers_with_text),
            "estimated_input_tokens": total_input_tokens,
            "estimated_output_tokens": total_output_tokens,
            "estimated_cost_usd": round(estimated_cost, 2),
            "note": "Estimates with 50% batch discount applied",
        }
