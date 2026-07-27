"""DB-backed tests for the wave-batch mode-gating of DjangoLiteLLMClient.completion."""

import pytest
from unittest.mock import patch

from paper_data_linking.pipeline_context import batch_execution
from paper_data_linking.clients.batch_replay import (
    PendingBatch, canonical_request, request_hash, make_response_shim,
)

pytestmark = pytest.mark.django_db

MODEL = "bedrock/converse/openai.gpt-oss-120b-1:0"
MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "ground this"}]


@pytest.fixture
def run():
    from vso_query_builder.models import BatchDownstreamRun
    return BatchDownstreamRun.objects.create(
        configuration_name="bedrock-120b-high-v5", total_papers=1)


def _hash(messages=MESSAGES, gen=None):
    return request_hash(canonical_request(MODEL, messages, None, gen or {"temperature": 1.0}))


def _client():
    from vso_query_builder.clients import DjangoLiteLLMClient
    return DjangoLiteLLMClient()


def test_collection_defers_uncached_call_and_writes_pending(run):
    from vso_query_builder.models import CachedLLMResponse, LLMCall
    client = _client()
    with batch_execution("collection", run.id):
        with pytest.raises(PendingBatch) as exc:
            client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    assert exc.value.request_hash == _hash()
    row = CachedLLMResponse.objects.get(run=run, request_hash=_hash())
    assert row.status == "pending"
    assert row.call_type == "mission_identification"
    assert row.request_payload["model"] == MODEL
    # No live call record is written during a collection pass.
    assert LLMCall.objects.count() == 0


def test_collection_dedups_identical_calls(run):
    from vso_query_builder.models import CachedLLMResponse
    client = _client()
    with batch_execution("collection", run.id):
        for _ in range(3):
            with pytest.raises(PendingBatch):
                client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    assert CachedLLMResponse.objects.filter(run=run, request_hash=_hash()).count() == 1


def test_collection_replays_resolved_without_pending_or_llmcall(run):
    from vso_query_builder.models import CachedLLMResponse, LLMCall
    CachedLLMResponse.objects.create(
        run=run, request_hash=_hash(), call_type="mission_identification",
        status="resolved", response_content='{"missions": ["SDO"]}',
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        finish_reason="stop",
    )
    client = _client()
    with batch_execution("collection", run.id):
        resp = client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    assert resp.choices[0].message.content == '{"missions": ["SDO"]}'
    assert resp.usage.total_tokens == 14
    assert LLMCall.objects.count() == 0  # collection never records


def test_commit_serves_cache_and_records_exactly_one_llmcall(run):
    from vso_query_builder.models import CachedLLMResponse, LLMCall
    CachedLLMResponse.objects.create(
        run=run, request_hash=_hash(), call_type="mission_identification",
        status="resolved", response_content='{"missions": ["SDO"]}',
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        finish_reason="stop",
    )
    client = _client()
    with batch_execution("commit", run.id):
        resp = client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    assert resp.choices[0].message.content == '{"missions": ["SDO"]}'
    calls = list(LLMCall.objects.all())
    assert len(calls) == 1
    call = calls[0]
    assert call.call_type == "mission_identification"
    assert call.output_content == '{"missions": ["SDO"]}'
    assert call.metadata.get("source") == "batch"
    assert call.metadata.get("request_hash") == _hash()
    assert call.prompt_tokens == 10


def test_commit_cache_miss_falls_back_to_live(run):
    from vso_query_builder.models import LLMCall
    client = _client()
    fake = make_response_shim('{"missions": []}', prompt_tokens=1, completion_tokens=1, model=MODEL)
    with patch.object(client, "_completion_live", return_value=fake) as live:
        with batch_execution("commit", run.id):
            resp = client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    live.assert_called_once()
    assert resp.choices[0].message.content == '{"missions": []}'


def test_off_mode_delegates_to_live(run):
    """Default mode (no run context) must take the unchanged live path."""
    client = _client()
    fake = make_response_shim('ok', prompt_tokens=1, completion_tokens=1, model=MODEL)
    with patch.object(client, "_completion_live", return_value=fake) as live:
        resp = client.completion("mission_identification", MODEL, MESSAGES, temperature=1.0)
    live.assert_called_once()
    assert resp.choices[0].message.content == 'ok'


def test_deferredcall_absorbed_by_branch_isolation_and_counted(run):
    """The frontier-discovery design: a grounder-style branch (retry loop that
    gives up and returns None) ABSORBS DeferredCall, sibling branches keep going
    and register their own pending calls, and the out-of-band counter reports
    the paper as still-in-progress. One pass -> the whole frontier."""
    from vso_query_builder.models import CachedLLMResponse
    from paper_data_linking.pipeline_context import deferred_calls
    client = _client()

    def branch(messages):
        # mirrors instrument_grounder: retry twice, give up -> branch yields None
        for attempt in range(2):
            try:
                return client.completion("mission_identification", MODEL, messages, temperature=1.0)
            except Exception:  # noqa: BLE001 - real per-branch isolation
                continue
        return None

    msgs_b = [{"role": "user", "content": "another instrument"}]
    cell = [0]
    token = deferred_calls.set(cell)
    try:
        with batch_execution("collection", run.id):
            r1 = branch(MESSAGES)   # branch 1 defers, absorbed
            r2 = branch(msgs_b)     # branch 2 STILL RUNS, defers too
    finally:
        deferred_calls.reset(token)
    assert r1 is None and r2 is None
    # BOTH branches' frontier calls registered in ONE pass, no duplicates from retries.
    assert CachedLLMResponse.objects.filter(run=run, status="pending").count() == 2
    # Counter saw all deferral events (2 branches x 2 retry attempts each).
    assert cell[0] == 4


def test_collection_response_format_defers_with_forced_tool(run):
    """A response_format call is batched like everything else, carrying its schema
    as a FORCED json_tool_call in the payload (the enforcement Bedrock batch honors).
    No live call, no separate lane."""
    from vso_query_builder.models import CachedLLMResponse, LLMCall
    from paper_data_linking.clients.batch_replay import RESPONSE_FORMAT_TOOL_NAME
    from pydantic import BaseModel

    class Schema(BaseModel):
        value: str

    client = _client()
    with batch_execution("collection", run.id):
        with pytest.raises(PendingBatch):
            client.completion("time_normalization", MODEL, MESSAGES,
                              temperature=1.0, response_format=Schema)
    row = CachedLLMResponse.objects.get(run=run)
    assert row.status == "pending"
    tools = row.request_payload["tools"]
    assert tools[0]["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert "value" in tools[0]["function"]["parameters"]["properties"]
    assert row.request_payload["tool_choice"]["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert LLMCall.objects.count() == 0  # no live call


def test_grounder_call_carries_reasoning_effort_into_batch_payload(run):
    """Regression for the reasoning_effort pipeline bug: a linker call routed
    through config.to_kwargs() must land effort in the batch request payload
    (generation_params allowlists it), so the Bedrock batch runs at the config's
    effort instead of the provider default."""
    from vso_query_builder.models import CachedLLMResponse
    from paper_data_linking.config.settings import get_llm_configuration
    cfg = get_llm_configuration("bedrock-120b-high-v5").instrument_grounding.similarity_filter
    assert cfg.reasoning_effort is not None  # config actually sets an effort
    client = _client()
    with batch_execution("collection", run.id):
        with pytest.raises(Exception):
            client.completion("mission_identification", cfg.model, MESSAGES,
                              **cfg.to_kwargs(prompt_context={"t": 1}))
    row = CachedLLMResponse.objects.get(run=run)
    assert row.request_payload["params"]["reasoning_effort"] == cfg.reasoning_effort
