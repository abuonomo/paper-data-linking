"""Unit tests for the pure batch-replay primitives (no Django/DB)."""

import pytest
from pydantic import BaseModel

from paper_data_linking.clients.batch_replay import (
    PendingBatch,
    canonical_request,
    canonical_response_format,
    to_openai_response_format,
    generation_params,
    request_hash,
    make_response_shim,
)


class _Schema(BaseModel):
    value: str


def test_deferredcall_is_ordinary_exception():
    """DeferredCall MUST be an ordinary Exception so the pipeline's per-branch
    error isolation absorbs it — that's what lets one collection pass discover
    every independent branch's frontier call (waves scale with depth, not count)."""
    from paper_data_linking.clients.batch_replay import DeferredCall
    assert issubclass(DeferredCall, Exception)
    assert PendingBatch is DeferredCall  # backwards-compatible alias
    caught = False
    try:
        raise DeferredCall("abc123")
    except Exception as e:  # noqa: BLE001 - simulating grounder branch isolation
        caught = True
        assert e.request_hash == "abc123"
    assert caught is True


def test_request_hash_is_stable_for_identical_inputs():
    msgs = [{"role": "user", "content": "hi"}]
    c1 = canonical_request("m", msgs, None, {"temperature": 1.0})
    c2 = canonical_request("m", [{"role": "user", "content": "hi"}], None, {"temperature": 1.0})
    assert request_hash(c1) == request_hash(c2)


@pytest.mark.parametrize("mutate", [
    lambda: canonical_request("m", [{"role": "user", "content": "bye"}], None, {"temperature": 1.0}),
    lambda: canonical_request("m2", [{"role": "user", "content": "hi"}], None, {"temperature": 1.0}),
    lambda: canonical_request("m", [{"role": "user", "content": "hi"}], None, {"temperature": 0.5}),
    lambda: canonical_request("m", [{"role": "user", "content": "hi"}], _Schema, {"temperature": 1.0}),
    lambda: canonical_request("m", [{"role": "user", "content": "hi"}], None, {"temperature": 1.0}, attempt=1),
])
def test_request_hash_changes_when_identity_changes(mutate):
    base = canonical_request("m", [{"role": "user", "content": "hi"}], None, {"temperature": 1.0})
    assert request_hash(base) != request_hash(mutate())


def test_generation_params_allowlist_drops_irrelevant_and_none():
    gp = generation_params({
        "temperature": 1.0,
        "reasoning_effort": "high",
        "max_tokens": None,          # dropped (None)
        "aws_region_name": "us-west-2",  # dropped (not output-affecting)
        "api_key": "secret",          # dropped
        "prompt_context": {"x": 1},  # dropped
    })
    assert gp == {"temperature": 1.0, "reasoning_effort": "high"}


def test_canonical_response_format_shapes():
    assert canonical_response_format(None) is None
    assert canonical_response_format({"type": "json_object"}) == {"type": "json_object"}
    cf = canonical_response_format(_Schema)
    assert cf["name"] == "_Schema"
    assert "properties" in cf["schema"]


def test_to_openai_response_format_envelope():
    assert to_openai_response_format(None) is None
    assert to_openai_response_format({"type": "json_object"}) == {"type": "json_object"}
    env = to_openai_response_format(_Schema)
    assert env["type"] == "json_schema"
    assert env["json_schema"]["name"] == "_Schema"
    assert env["json_schema"]["strict"] is True
    assert "properties" in env["json_schema"]["schema"]


def test_make_response_shim_matches_litellm_access_shape():
    shim = make_response_shim(
        '{"value": "x"}', prompt_tokens=3, completion_tokens=5, finish_reason="stop", model="m")
    assert shim.choices[0].message.content == '{"value": "x"}'
    assert shim.choices[0].finish_reason == "stop"
    assert shim.usage.prompt_tokens == 3
    assert shim.usage.completion_tokens == 5
    assert shim.usage.total_tokens == 8  # derived when not provided


def test_response_format_to_forced_tool_and_extract():
    from paper_data_linking.clients.batch_replay import (
        response_format_to_forced_tool, extract_tool_arguments, RESPONSE_FORMAT_TOOL_NAME)
    tools, tc = response_format_to_forced_tool(_Schema)
    assert tools[0]["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert "value" in tools[0]["function"]["parameters"]["properties"]
    assert tc["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert response_format_to_forced_tool(None) == (None, None)
    assert response_format_to_forced_tool({"type": "json_object"}) == (None, None)

    msg = {"content": None, "tool_calls": [
        {"function": {"name": RESPONSE_FORMAT_TOOL_NAME, "arguments": '{"value":"x"}'}}]}
    assert extract_tool_arguments(msg) == '{"value":"x"}'
    assert extract_tool_arguments({"content": "hi"}) is None


def test_batch_client_forced_tool_roundtrip():
    """schema -> forced tool in modelInput -> batch output tool_call -> content."""
    import json
    from paper_data_linking.clients.batch_client import BatchClient
    from paper_data_linking.clients.batch_replay import (
        response_format_to_forced_tool, RESPONSE_FORMAT_TOOL_NAME)
    tools, tc = response_format_to_forced_tool(_Schema)
    bc = BatchClient()
    jsonl = bc.prepare_generic_requests([{
        "record_id": "h1", "model": "bedrock/x",
        "messages": [{"role": "user", "content": "q"}],
        "params": {"temperature": 1.0}, "tools": tools, "tool_choice": tc,
    }], provider="bedrock")
    rec = json.loads(jsonl)
    assert rec["recordId"] == "h1"
    assert rec["modelInput"]["tools"][0]["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert rec["modelInput"]["tool_choice"]["function"]["name"] == RESPONSE_FORMAT_TOOL_NAME
    assert "response_format" not in rec["modelInput"]

    out = json.dumps({"recordId": "h1", "modelOutput": {
        "choices": [{"message": {"content": None, "tool_calls": [
            {"function": {"name": RESPONSE_FORMAT_TOOL_NAME, "arguments": '{"value":"x"}'}}]},
            "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}})
    parsed = bc._parse_bedrock_results([out])
    assert parsed[0]["custom_id"] == "h1"
    assert parsed[0]["content"] == '{"value":"x"}'


def test_pick_message_content_prefers_tool_args_and_strips_reasoning():
    """Regression for the live-probe finding: gpt-oss prepends <reasoning> to content
    on the batch path. Tool args (clean) win; otherwise reasoning is stripped."""
    from paper_data_linking.clients.batch_replay import (
        pick_message_content, strip_reasoning, RESPONSE_FORMAT_TOOL_NAME)
    # tool args win even when content carries reasoning
    msg = {"content": "<reasoning>figuring it out</reasoning>",
           "tool_calls": [{"function": {"name": RESPONSE_FORMAT_TOOL_NAME,
                                         "arguments": '{"v": 1}'}}]}
    assert pick_message_content(msg) == '{"v": 1}'
    # no tool -> strip the <reasoning>/<think> prefix from content
    assert pick_message_content({"content": '<reasoning>x</reasoning>\n{"v": 1}'}) == '{"v": 1}'
    assert strip_reasoning('<think>y</think>hi') == 'hi'
    assert strip_reasoning('plain') == 'plain'
