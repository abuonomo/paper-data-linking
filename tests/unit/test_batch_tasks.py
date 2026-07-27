"""Tests for batch task helper logic.

Tests provider detection and model name stripping used by submit_batch_paper_analysis.
The Celery tasks themselves require Django and are tested via the running application.
"""

import pytest


class TestProviderDetection:
    """Test that provider is correctly detected from model names.

    This mirrors the logic in submit_batch_paper_analysis:
        provider = "bedrock" if model.startswith("bedrock/") else "openai"
    """

    def test_openai_model(self):
        model = "openai/gpt-5"
        provider = "bedrock" if model.startswith("bedrock/") else "openai"
        assert provider == "openai"

    def test_bedrock_converse_model(self):
        model = "bedrock/converse/openai.gpt-oss-120b-1:0"
        provider = "bedrock" if model.startswith("bedrock/") else "openai"
        assert provider == "bedrock"

    def test_bedrock_qwen_model(self):
        model = "bedrock/converse/qwen-2.5-72b"
        provider = "bedrock" if model.startswith("bedrock/") else "openai"
        assert provider == "bedrock"

    def test_bare_model_defaults_to_openai(self):
        model = "gpt-5"
        provider = "bedrock" if model.startswith("bedrock/") else "openai"
        assert provider == "openai"


class TestBatchModelNameStripping:
    """Test model name stripping for batch submission.

    submit_batch_paper_analysis uses rsplit to get the bare model name:
        batch_model = model.rsplit('/', 1)[1] if '/' in model else model
    """

    def test_openai_prefix(self):
        model = "openai/gpt-5"
        batch_model = model.rsplit('/', 1)[1] if '/' in model else model
        assert batch_model == "gpt-5"

    def test_bedrock_converse_prefix(self):
        model = "bedrock/converse/openai.gpt-oss-120b-1:0"
        batch_model = model.rsplit('/', 1)[1] if '/' in model else model
        assert batch_model == "openai.gpt-oss-120b-1:0"

    def test_no_prefix(self):
        model = "gpt-5"
        batch_model = model.rsplit('/', 1)[1] if '/' in model else model
        assert batch_model == "gpt-5"

    def test_deep_nested_prefix(self):
        model = "bedrock/converse/us/kimi-k2.5-chat"
        batch_model = model.rsplit('/', 1)[1] if '/' in model else model
        assert batch_model == "kimi-k2.5-chat"


class TestPrepareRequestsModelStripping:
    """Test model stripping used in BatchClient.prepare_requests().

    prepare_requests uses split (not rsplit) to strip only the first prefix:
        batch_model = model.split('/', 1)[1] if '/' in model else model
    """

    def test_openai_prefix(self):
        model = "openai/gpt-5"
        batch_model = model.split('/', 1)[1] if '/' in model else model
        assert batch_model == "gpt-5"

    def test_bedrock_converse_preserves_subpath(self):
        model = "bedrock/converse/openai.gpt-oss-120b-1:0"
        batch_model = model.split('/', 1)[1] if '/' in model else model
        assert batch_model == "converse/openai.gpt-oss-120b-1:0"
