import json
import socket

import pytest

from paper_data_linking.config.settings import get_llm_configuration
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedTimeRange
from paper_data_linking.linkers.general.snapshot_finder import SnapshotInstrumentFinder
from paper_data_linking.runner.client import CallRecorder, EndpointDown, ModelRequestError, Transport, VLLMClient, message_hash

MESSAGES = [{"role": "user", "content": "hello"}]


class _Rows(list):
    write = list.append


def _client(url, log=None, **transport_options):
    options = {"budget_tokens": 100_000, "patience": 5, "request_timeout": 10}
    options.update(transport_options)
    recorder = CallRecorder("2020Test..0000....A", log, "full")
    return VLLMClient(Transport(url, **options), recorder), recorder


def _dead_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def test_completion_returns_the_shape_linkers_read(fake_server):
    url, server = fake_server()
    client, recorder = _client(url)
    response = client.completion(
        "time_normalization", "hosted_vllm/google/gemma-4-26B-A4B-it", MESSAGES,
        temperature=1.0, max_tokens=100, response_format=NormalizedTimeRange,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}}, prompt_context={"ignored": True},
    )
    parsed = NormalizedTimeRange.model_validate_json(response.choices[0].message.content)
    assert parsed.precision == "day" and response.choices[0].finish_reason == "stop"
    assert recorder.stats()["calls"] == 1 and recorder.last["time_normalization"]["finish_reason"] == "stop"
    assert client.transport.gate.snapshot()["in_use"] == 0


def test_transient_failures_are_retried_not_surfaced(fake_server):
    url, server = fake_server(fail_pct=30)
    client, recorder = _client(url, patience=60)
    for _ in range(10):
        assert client.completion("mission_selection", "m", MESSAGES, temperature=1.0).choices[0].message.content == "1"
    assert server.state.failures_injected > 0
    assert recorder.stats()["transport_retries"] == server.state.failures_injected
    assert client.transport.healthy.is_set()


def test_dead_endpoint_raises_endpoint_down_after_patience():
    client, _ = _client(_dead_url(), patience=1.5)
    with pytest.raises(EndpointDown):
        client.completion("mission_selection", "m", MESSAGES, temperature=1.0)
    assert not client.transport.healthy.is_set()
    assert client.transport.gate.snapshot()["in_use"] == 0


def test_an_outage_cannot_pass_as_no_match(snapshot):
    """The grounder turns ordinary exceptions into "no match"; a dead endpoint must not
    take that path, or an outage would read as papers without instruments."""
    client, _ = _client(_dead_url(), patience=1.0)
    grounder = InstrumentGrounder(
        finder=SnapshotInstrumentFinder(snapshot), llm_client=client, llm_config=get_llm_configuration("vllm-gemma4-batch")
    )
    with pytest.raises(EndpointDown):
        grounder.ground_instrument({"name": "EIT on board SOHO", "general_comments": "", "data_collection_periods": []})


def test_request_rejected_by_the_server_is_an_ordinary_error(fake_server, tmp_path):
    replay = tmp_path / "calls.jsonl"
    replay.write_text(json.dumps({"mh": message_hash(MESSAGES), "content": "an\x00swer <think>hidden</think>", "finish_reason": "stop"}) + "\n")
    url, server = fake_server(mode="replay", replay=str(replay))
    client, recorder = _client(url)
    # NUL bytes and leaked reasoning tags are removed from the answer.
    assert client.completion("x", "m", MESSAGES).choices[0].message.content == "answer"
    with pytest.raises(ModelRequestError):
        client.completion("x", "m", [{"role": "user", "content": "never recorded"}])
    assert recorder.stats()["call_errors"] == 1 and server.state.replay_misses == 1


def test_answer_cut_off_by_runaway_reasoning_is_sampled_again(fake_server, tmp_path):
    """Reasoning that runs to max_tokens leaves no answer. Passed on as it is, a linker
    would take it for a failed call and drop the instrument."""
    runaway = {"mh": message_hash(MESSAGES), "content": None, "finish_reason": "length", "completion_tokens": 16000}
    replay = tmp_path / "calls.jsonl"
    replay.write_text(json.dumps(runaway) + "\n" + json.dumps({**runaway, "content": "SOHO(1)", "finish_reason": "stop"}) + "\n")
    url, server = fake_server(mode="replay", replay=str(replay))
    log = _Rows()
    client, recorder = _client(url, log)
    response = client.completion("mission_identification", "m", MESSAGES, max_tokens=16000)
    assert response.choices[0].message.content == "SOHO(1)"
    assert recorder.stats()["calls"] == 2 and recorder.stats()["resamples"] == 1
    assert [row["finish_reason"] for row in log] == ["length", "stop"]
    # Every row says when the answer arrived and how long the call queued.
    assert all(row["ts"].endswith("+00:00") and row["gate_ms"] >= 0 for row in log)

    # A call that never answers is handed on after the last resample, not retried forever.
    replay.write_text(json.dumps(runaway) + "\n")
    url, server = fake_server(mode="replay", replay=str(replay))
    client, recorder = _client(url)
    assert client.completion("mission_identification", "m", MESSAGES, max_tokens=16000).choices[0].message.content is None
    assert recorder.stats()["calls"] == 3
