import logging
from typing import Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


@NormalizerRegistry.register("phenomenon", version="1.0", data_sources=["vso", "cdaweb"])
class PhenomenonNormalizer(BaseNormalizer):
    """
    Matches the physical observable for an instrument/period against the
    HelioKnow phenomenon vocabulary. Returns a list of matched phenomena.

    Requires context.phenomena (list of {id, name, iri} dicts) to be populated
    by the caller (loaded from the Phenomenon DB table via StructuredNormalizer).
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, llm_config=None):
        super().__init__(llm_client)
        if llm_config is None:
            raise ValueError("llm_config is required for PhenomenonNormalizer")
        self.llm_config = llm_config

    def normalize(self, context: NormalizationContext) -> dict:
        physical_observable = context.period_data.physical_observable
        physobs_quotes = context.period_data.physobs_quotes or []
        phenomena = context.phenomena or []

        if not physical_observable or not phenomena:
            return {"phenomena": []}

        phenomena_by_number = {i + 1: p for i, p in enumerate(phenomena)}
        phenomena_text = "\n".join(f"{i}. {p['name']}" for i, p in phenomena_by_number.items())

        config = self.llm_config.normalization.physical_observable

        system_msg, user_msg = load_and_render_prompt(
            "phenomenon_extraction",
            instrument_name=context.instrument_name,
            period_name=context.period_name,
            physical_observable=physical_observable,
            physobs_quotes=physobs_quotes,
            phenomena_text=phenomena_text,
        )

        prompt_context = {
            "template_name": "phenomenon_extraction",
            "instrument_name": context.instrument_name,
            "period_name": context.period_name,
            "physical_observable": physical_observable,
            "physobs_quotes": physobs_quotes,
        }

        try:
            response = self.llm_client.completion(
                call_type="phenomenon_extraction",
                model=config.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                **config.to_kwargs(prompt_context=prompt_context),
            )
            response_text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"PhenomenonNormalizer: LLM call failed for {context.instrument_name}/{context.period_name}: {e}")
            return {"phenomena": []}

        if not response_text or response_text.upper() == "NONE":
            return {"phenomena": []}

        matched = []
        for tok in response_text.split(","):
            try:
                num = int(tok.strip())
            except ValueError:
                logger.warning(f"PhenomenonNormalizer: could not parse token '{tok.strip()}' as int")
                continue
            if num in phenomena_by_number:
                p = phenomena_by_number[num]
                matched.append({"iri": p["iri"], "name": p["name"]})
            else:
                logger.warning(f"PhenomenonNormalizer: number {num} out of range (max {len(phenomena_by_number)})")

        logger.info(f"PhenomenonNormalizer: {context.instrument_name}/{context.period_name} → {len(matched)} phenomena")
        return {"phenomena": matched}
