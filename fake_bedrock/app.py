"""Fake Bedrock batch-inference endpoint for fast, free, offline E2E testing.

Implements exactly the two Bedrock APIs the batch runner uses —
CreateModelInvocationJob / GetModelInvocationJob (rest-json) — against a real
S3-compatible store (MinIO), so the REAL BatchClient code path (boto3 clients,
S3 upload, polling, output listing/parsing) runs unmodified: point
AWS_ENDPOINT_URL_BEDROCK / AWS_ENDPOINT_URL_S3 at this stack and go.

Response modes (FAKE_MODE):
  replay — answer each record by its recordId (= request_hash) from a captured
           run's (hash -> response) pairs (FAKE_REPLAY_FILE, JSONL of
           {"h":..., "c":..., "u":{...}, "f":...}). Full-fidelity deterministic
           re-runs of real corpora without Bedrock. Unknown hashes follow
           FAKE_UNKNOWN (error | echo).
  echo   — wrap the last user message: R[<content>]. For synthetic-harness and
           scale/mechanics testing.

Failure injection (deterministic per record/job, so runs are reproducible):
  FAKE_LATENCY_S       job completion delay (default 5)
  FAKE_THROTTLE_PCT    % records returned as throttling errors (transient class)
  FAKE_STRAGGLER_PCT   % records silently missing from output (transient class)
  FAKE_JOB_FAIL_PCT    % whole jobs that end status=Failed
"""
import hashlib
import json
import logging
import os
import re
import threading
import time
from urllib.parse import unquote

import boto3
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s fake-bedrock %(message)s")
log = logging.getLogger("fake-bedrock")

MODE = os.environ.get("FAKE_MODE", "echo")
REPLAY_FILE = os.environ.get("FAKE_REPLAY_FILE", "/data/replay.jsonl")
UNKNOWN = os.environ.get("FAKE_UNKNOWN", "error")
LATENCY_S = float(os.environ.get("FAKE_LATENCY_S", "5"))
THROTTLE_PCT = int(os.environ.get("FAKE_THROTTLE_PCT", "0"))
STRAGGLER_PCT = int(os.environ.get("FAKE_STRAGGLER_PCT", "0"))
JOB_FAIL_PCT = int(os.environ.get("FAKE_JOB_FAIL_PCT", "0"))
BUCKET = os.environ.get("AWS_BATCH_BUCKET", "pdl-fake-batch")

app = FastAPI()
JOBS = {}          # jobArn -> dict
JOBS_LOCK = threading.Lock()
REPLAY = {}


def _s3():
    return boto3.client("s3")   # endpoint/creds via env (same mechanism as the app under test)


@app.on_event("startup")
def _startup():
    if MODE == "replay":
        n = 0
        with open(REPLAY_FILE) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    REPLAY[r["h"]] = r
                    n += 1
        log.info("replay mode: loaded %d captured responses", n)
    # Ensure the batch bucket exists (idempotent; MinIO may still be booting).
    for attempt in range(30):
        try:
            _s3().head_bucket(Bucket=BUCKET)
            break
        except Exception:
            try:
                _s3().create_bucket(Bucket=BUCKET)
                log.info("created bucket %s", BUCKET)
                break
            except Exception:
                time.sleep(1)
    log.info("mode=%s latency=%.1fs throttle=%d%% straggler=%d%% jobfail=%d%%",
             MODE, LATENCY_S, THROTTLE_PCT, STRAGGLER_PCT, JOB_FAIL_PCT)


def _pct(key: str) -> int:
    """Deterministic 0-99 from a string — reproducible failure injection."""
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) % 100


def _respond(record: dict) -> dict | None:
    """Build one output line's modelOutput (or an error line / None=straggler)."""
    rid = record.get("recordId", "")
    if _pct("straggle:" + rid) < STRAGGLER_PCT:
        return None
    if _pct("throttle:" + rid) < THROTTLE_PCT:
        return {"recordId": rid,
                "error": "ThrottlingException: Too many requests (fake injection)"}

    messages = (record.get("modelInput") or {}).get("messages") or []
    if MODE == "replay":
        hit = REPLAY.get(rid)
        if hit is None and UNKNOWN == "error":
            return {"recordId": rid,
                    "error": f"fake-bedrock: no captured response for {rid[:16]}…"}
        if hit is not None:
            usage = hit.get("u") or {}
            return {"recordId": rid, "modelOutput": {
                "choices": [{"message": {"content": hit["c"]},
                             "finish_reason": hit.get("f") or "stop"}],
                "usage": usage}}
    # echo (and replay-unknown fallback)
    last = next((m.get("content", "") for m in reversed(messages)
                 if m.get("role") == "user"), "")
    return {"recordId": rid, "modelOutput": {
        "choices": [{"message": {"content": f"R[{last}]"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}}


def _process(job: dict) -> None:
    """Read input JSONL from S3, produce the output JSONL under the output prefix."""
    m = re.match(r"s3://([^/]+)/(.+)", job["input_uri"])
    body = _s3().get_object(Bucket=m.group(1), Key=m.group(2))["Body"].read().decode()
    out_lines, ok, fail = [], 0, 0
    for line in body.splitlines():
        if not line.strip():
            continue
        res = _respond(json.loads(line))
        if res is None:
            continue                       # straggler: absent from output
        if "error" in res:
            fail += 1
        else:
            ok += 1
        out_lines.append(json.dumps(res))
    m = re.match(r"s3://([^/]+)/(.+?)/?$", job["output_uri"])
    out_key = f"{m.group(2)}/{job['name']}.jsonl.out"
    _s3().put_object(Bucket=m.group(1), Key=out_key,
                     Body=("\n".join(out_lines) + "\n").encode())
    job.update(processed=True, ok=ok, fail=fail)
    log.info("job %s processed: ok=%d fail=%d stragglers=%d",
             job["name"], ok, fail, job["total"] - ok - fail)


@app.post("/model-invocation-job")
async def create_job(request: Request):
    body = await request.json()
    name = body["jobName"]
    arn = f"arn:aws:bedrock:us-fake-1:000000000000:model-invocation-job/{name}"
    input_uri = body["inputDataConfig"]["s3InputDataConfig"]["s3Uri"]
    m = re.match(r"s3://([^/]+)/(.+)", input_uri)
    n_records = len([l for l in _s3().get_object(Bucket=m.group(1), Key=m.group(2))
                     ["Body"].read().decode().splitlines() if l.strip()])
    with JOBS_LOCK:
        JOBS[arn] = {
            "name": name, "arn": arn, "model": body["modelId"],
            "input_uri": input_uri,
            "output_uri": body["outputDataConfig"]["s3OutputDataConfig"]["s3Uri"],
            "created": time.time(), "total": n_records, "processed": False,
            "doomed": _pct("jobfail:" + name) < JOB_FAIL_PCT,
            "ok": 0, "fail": 0,
        }
    log.info("job %s created: %d records model=%s", name, n_records, body["modelId"])
    return JSONResponse({"jobArn": arn}, status_code=200)


@app.get("/model-invocation-job/{job_id:path}")
def get_job(job_id: str):
    arn = unquote(job_id)
    job = JOBS.get(arn)
    if job is None:
        return JSONResponse({"message": f"job not found: {arn}"}, status_code=404)
    elapsed = time.time() - job["created"]
    if elapsed < LATENCY_S:
        status = "InProgress"
    elif job["doomed"]:
        status = "Failed"
    else:
        with JOBS_LOCK:
            if not job["processed"]:
                _process(job)
        status = "Completed"
    return JSONResponse({
        "jobArn": arn, "jobName": job["name"], "status": status,
        "statistics": {"numberOfRecordsSucceeded": job["ok"],
                       "numberOfRecordsFailed": job["fail"]},
        "inputDataConfig": {"s3InputDataConfig": {"s3Uri": job["input_uri"],
                                                  "s3InputFormat": "JSONL"}},
        "outputDataConfig": {"s3OutputDataConfig": {"s3Uri": job["output_uri"]}},
    })


@app.get("/health")
def health():
    return {"mode": MODE, "jobs": len(JOBS), "replay_pairs": len(REPLAY)}
