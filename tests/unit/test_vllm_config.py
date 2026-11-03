"""The self-hosted vLLM config routes every LLM stage to one endpoint with thinking on."""

from paper_data_linking.config.settings import LLMCallConfig, get_llm_configuration


def _stages(obj, prefix=""):
    for field in type(obj).model_fields:
        value = getattr(obj, field)
        if isinstance(value, LLMCallConfig):
            yield f"{prefix}{field}", value
        elif hasattr(value, "model_fields"):
            yield from _stages(value, f"{prefix}{field}.")


def test_every_llm_stage_uses_vllm_gemma_with_thinking():
    config = get_llm_configuration("vllm-gemma4@e2e1")
    stages = dict(_stages(config))
    assert stages["embeddings"].model == "openai/text-embedding-3-small"
    llm_stages = {k: v for k, v in stages.items() if k != "embeddings"}
    assert len(llm_stages) >= 15
    for name, stage in llm_stages.items():
        assert stage.model == "hosted_vllm/google/gemma-4-26B-A4B-it", name
        assert stage.reasoning_effort is None and stage.aws_region_name is None, name
        kwargs = stage.to_kwargs()
        assert kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}, name


def test_stage_copies_are_independent():
    config = get_llm_configuration("vllm-gemma4")
    config.normalization.time_range.extra_body["chat_template_kwargs"]["enable_thinking"] = False
    try:
        assert config.normalization.cadence.extra_body["chat_template_kwargs"]["enable_thinking"] is True
    finally:
        config.normalization.time_range.extra_body["chat_template_kwargs"]["enable_thinking"] = True


def test_to_kwargs_omits_extra_body_when_unset():
    assert "extra_body" not in LLMCallConfig(model="openai/gpt-5", temperature=1.0).to_kwargs()
