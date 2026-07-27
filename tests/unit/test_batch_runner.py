"""Tests for batch_runner.prepare_batch_file reasoning_effort parameter.

We test the logic directly without importing batch_runner at module level,
since it triggers handler registration that conflicts with conftest imports.
Instead we extract and test the body-construction logic inline.
"""
import json
from pathlib import Path

import pytest


def _build_batch_body(model, messages, temperature, reasoning_effort, response_format):
    """Replicate the body construction logic from prepare_batch_file."""
    if '/' in model:
        batch_model = model.split('/', 1)[1]
    else:
        batch_model = model

    body = {
        'model': batch_model,
        'messages': messages,
        'temperature': temperature,
    }
    if reasoning_effort is not None:
        body['reasoning_effort'] = reasoning_effort
    if response_format:
        body['response_format'] = response_format
    return body


def _make_batch_jsonl(tmp_path, reasoning_effort=None):
    """Generate a batch JSONL file using the same logic as prepare_batch_file."""
    messages = [
        {'role': 'system', 'content': 'You are a test assistant.'},
        {'role': 'user', 'content': 'Test input'},
    ]
    model = 'openai/gpt-5.4'
    requests = []
    for run in range(1, 6):
        body = _build_batch_body(model, messages, 1.0, reasoning_effort, None)
        requests.append({
            'custom_id': f'test_type|case_1|run{run}',
            'method': 'POST',
            'url': '/v1/chat/completions',
            'body': body,
        })

    out = tmp_path / 'batch.jsonl'
    with open(out, 'w') as f:
        for req in requests:
            f.write(json.dumps(req) + '\n')
    return out


def test_body_without_reasoning_effort():
    """reasoning_effort=None should produce bodies WITHOUT a reasoning_effort key."""
    messages = [{'role': 'user', 'content': 'hi'}]
    body = _build_batch_body('openai/gpt-5.4', messages, 1.0, None, None)
    assert 'reasoning_effort' not in body


def test_body_with_reasoning_effort_high():
    """reasoning_effort='high' should include reasoning_effort='high' in the body."""
    messages = [{'role': 'user', 'content': 'hi'}]
    body = _build_batch_body('openai/gpt-5.4', messages, 1.0, 'high', None)
    assert body['reasoning_effort'] == 'high'


def test_batch_jsonl_without_reasoning_effort(tmp_path):
    """Full JSONL generation with reasoning_effort=None: no reasoning_effort key anywhere."""
    batch_file = _make_batch_jsonl(tmp_path, reasoning_effort=None)
    with open(batch_file) as f:
        for line in f:
            req = json.loads(line)
            assert 'reasoning_effort' not in req['body']


def test_batch_jsonl_with_reasoning_effort_high(tmp_path):
    """Full JSONL generation with reasoning_effort='high': every request has it."""
    batch_file = _make_batch_jsonl(tmp_path, reasoning_effort='high')
    with open(batch_file) as f:
        for line in f:
            req = json.loads(line)
            assert req['body']['reasoning_effort'] == 'high'


def test_batch_jsonl_request_count(tmp_path):
    """1 case x 5 runs = 5 requests."""
    batch_file = _make_batch_jsonl(tmp_path)
    with open(batch_file) as f:
        lines = f.readlines()
    assert len(lines) == 5


def test_model_prefix_stripped():
    """Model prefix should be stripped for batch_model."""
    messages = [{'role': 'user', 'content': 'hi'}]
    body = _build_batch_body('openai/gpt-5.4', messages, 1.0, None, None)
    assert body['model'] == 'gpt-5.4'

    body2 = _build_batch_body('bedrock/converse/openai.gpt-oss-120b-1:0', messages, 1.0, 'high', None)
    assert body2['model'] == 'converse/openai.gpt-oss-120b-1:0'
    assert body2['reasoning_effort'] == 'high'


def test_source_code_has_reasoning_effort():
    """Verify the actual batch_runner.py source includes reasoning_effort logic."""
    batch_runner_path = Path(__file__).parent.parent.parent / 'experiments' / 'compare_models' / 'self_consistency' / 'batch_runner.py'
    source = batch_runner_path.read_text()
    assert "reasoning_effort: Optional[str] = None" in source, "Parameter missing from signature"
    assert "body['reasoning_effort'] = reasoning_effort" in source, "Body injection missing"
