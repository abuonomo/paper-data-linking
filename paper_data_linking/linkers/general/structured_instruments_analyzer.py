from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import logging

from paper_data_linking.config import paths
from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.schemas.structured_instruments import StructuredInstrumentDetails
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


@dataclass
class StructuredInstrumentsOutput:
    """Output structure for the structured instruments analyzer"""
    structured_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None
    call_data: Optional[Dict[str, Any]] = None  # Add call_data for LLM tracking


class StructuredInstrumentsAnalyzer:
    """
    Uses LiteLLM's Structured Outputs to parse unstructured
    instrument details into a structured JSON format.
    """

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, websocket_callback=None, llm_config=None):
        from paper_data_linking.config.settings import LLMPipelineConfig
        self.llm_client = llm_client or LiteLLMClient()
        self.websocket_callback = websocket_callback
        if llm_config is None:
            raise ValueError("llm_config is required - no fallback to default to ensure explicit configuration")
        if not isinstance(llm_config, LLMPipelineConfig):
            raise ValueError(f"llm_config must be LLMPipelineConfig, got {type(llm_config)}")
        self.llm_config = llm_config

    def forward(self, instruments_details_text: str) -> StructuredInstrumentsOutput:
        """
        Parse unstructured instrument details text into structured JSON format.

        Args:
            instruments_details_text: Raw markdown text containing instrument details

        Returns:
            StructuredInstrumentsOutput containing structured data and metadata
        """
        try:
            # Load and render prompts from XML templates
            template_name = "structured_parsing"
            system_prompt, user_prompt = load_and_render_prompt(
                template_name,
                instruments_details_text=instruments_details_text
            )

            # Capture template variables for render_context
            prompt_context = {
                'template_name': template_name,
                'instruments_details_text': instruments_details_text
            }

            # Call LiteLLM with manual retry logic for Pydantic validation
            config = self.llm_config.structured_parsing

            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    logger.info(f"Structured analysis attempt {attempt + 1}/{max_retries}")

                    # Use regular LiteLLMClient with structured output
                    response = self.llm_client.completion(
                        call_type="structure_analysis",
                        model=config.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        prompt_context=prompt_context,
                        **config.to_kwargs(response_format=StructuredInstrumentDetails)
                    )

                    # Debug: Log the raw response to understand Bedrock's format
                    logger.info(f"Raw response object: {response}")
                    logger.info(f"Response choices: {response.choices if hasattr(response, 'choices') else 'No choices'}")
                    if response.choices:
                        logger.info(f"Message object: {response.choices[0].message}")
                        logger.info(f"Message content: '{response.choices[0].message.content}'")
                        logger.info(f"Message content type: {type(response.choices[0].message.content)}")
                        # Check if there are tool_calls or function_call fields
                        if hasattr(response.choices[0].message, 'tool_calls'):
                            logger.info(f"Tool calls: {response.choices[0].message.tool_calls}")
                        if hasattr(response.choices[0].message, 'function_call'):
                            logger.info(f"Function call: {response.choices[0].message.function_call}")

                    # Extract and validate the response using Pydantic
                    structured_output = StructuredInstrumentDetails.model_validate_json(response.choices[0].message.content)

                    # Warning for instruments without data_collection_periods
                    for i, instrument in enumerate(structured_output.instruments):
                        if not instrument.data_collection_periods:
                            logger.warning(f"Instrument {i} ({instrument.name}) has no data_collection_periods")

                    logger.info(f"Structured analysis succeeded on attempt {attempt + 1}")
                    break
                    
                except (ValueError, Exception) as e:
                    last_error = e
                    logger.warning(f"Structured analysis attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying... ({attempt + 2}/{max_retries})")
                        continue
                    else:
                        logger.error(f"All {max_retries} attempts failed. Last error: {e}")
                        raise last_error

            # Convert to dictionary for storage
            structured_dict = structured_output.model_dump()

            return StructuredInstrumentsOutput(
                structured_data=structured_dict,
                metadata={
                    "token_usage": {},  # LLM tracking handled by callback pattern
                    "model_used": config.model,
                    "parsing_successful": True,
                    "instruments_count": len(structured_dict.get("instruments", [])),
                    "total_data_periods": sum(
                        len(instrument.get("data_collection_periods", []))
                        for instrument in structured_dict.get("instruments", [])
                    ),
                    "retries_used": attempt + 1  # Track how many attempts were needed
                },
                success=True
            )

        except Exception as e:
            error_msg = f"Failed to parse instrument details: {str(e)}"
            return StructuredInstrumentsOutput(
                success=False,
                error_message=error_msg,
                metadata={
                    "token_usage": {"token_usage": {"by_model": {}}},  # Empty usage on error
                    "parsing_successful": False,
                    "error": error_msg
                }
            )
