"""Deterministic structure analyzer: parser + validator pipeline."""

import logging
from typing import Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.paper_analysis_output_parser import (
    parse_instrument_markdown,
)
from paper_data_linking.linkers.general.structured_instruments_analyzer import (
    StructuredInstrumentsOutput,
)
from paper_data_linking.linkers.general.validators.pipeline import (
    StructureValidatorPipeline,
)

logger = logging.getLogger(__name__)


class DeterministicStructureAnalyzer:
    """
    Primary structuring step: deterministic parser + validator pipeline.

    Errors propagate directly — no silent LLM fallback.
    """

    def __init__(
        self,
        llm_client: Optional[LiteLLMClient] = None,
        websocket_callback=None,
        llm_config=None,
    ):
        from paper_data_linking.config.settings import LLMPipelineConfig
        self.llm_client = llm_client or LiteLLMClient()
        self.websocket_callback = websocket_callback
        if llm_config is None:
            raise ValueError(
                "llm_config is required - no fallback to default "
                "to ensure explicit configuration"
            )
        if not isinstance(llm_config, LLMPipelineConfig):
            raise ValueError(
                f"llm_config must be LLMPipelineConfig, got {type(llm_config)}"
            )
        self.llm_config = llm_config

    def forward(
        self, instruments_details_text: str
    ) -> StructuredInstrumentsOutput:
        # Phase 1: Deterministic parse
        parsed = parse_instrument_markdown(instruments_details_text)

        # Phase 2: Validate and fix
        pipeline = StructureValidatorPipeline(
            llm_client=self.llm_client,
            llm_config=self.llm_config,
        )
        vresult = pipeline.run(parsed, instruments_details_text)

        structured_dict = vresult.structured.model_dump()
        structured_dict["_structuring_metadata"] = {
            "method": "deterministic_parser",
            "validator_issues_found": vresult.total_issues_found,
            "validator_issues_fixed": vresult.total_issues_fixed,
            "validator_llm_calls": vresult.total_llm_calls,
        }

        return StructuredInstrumentsOutput(
            structured_data=structured_dict,
            metadata={
                "parsing_successful": True,
                "method": "parser",
                "instruments_count": len(
                    structured_dict.get("instruments", [])
                ),
                "total_data_periods": sum(
                    len(inst.get("data_collection_periods", []))
                    for inst in structured_dict.get("instruments", [])
                ),
                "parser_instruments_count": len(parsed.instruments),
                "validator_issues_found": vresult.total_issues_found,
                "validator_issues_fixed": vresult.total_issues_fixed,
                "validator_llm_calls": vresult.total_llm_calls,
                "validator_all_skipped": vresult.all_skipped,
            },
            success=True,
        )
