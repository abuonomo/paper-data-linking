import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Any, Optional
from dotenv import load_dotenv, find_dotenv

# Load environment variables
load_dotenv(find_dotenv())

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

logger = logging.getLogger(__name__)


class DirectPaperAnalyzer:
    """Paper analyzer using LiteLLM with XML templates"""

    def __init__(self, llm_client: Optional[LiteLLMClient] = None, websocket_callback=None, llm_config=None):
        from paper_data_linking.config.settings import LLMPipelineConfig
        self.llm_client = llm_client or LiteLLMClient()
        self.websocket_callback = websocket_callback
        if llm_config is None:
            raise ValueError("llm_config is required - no fallback to default to ensure explicit configuration")
        if not isinstance(llm_config, LLMPipelineConfig):
            raise ValueError(f"llm_config must be LLMPipelineConfig, got {type(llm_config)}")
        self.llm_config = llm_config
    
    def send_websocket_message(self, message: str):
        """Send websocket message if callback is available"""
        if self.websocket_callback:
            self.websocket_callback(message)
    
    def _make_litellm_request(self, system_prompt: str, user_prompt: str, prompt_context: dict = None):
        """Make LiteLLM API request with error handling using injected client"""
        try:
            self.send_websocket_message("Analyzing paper with LiteLLM...")

            # Use injected configuration for paper analysis
            config = self.llm_config.paper_analysis

            # Use injected client instead of direct litellm call
            response = self.llm_client.completion(
                call_type="paper_analysis",
                model=config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                **config.to_kwargs(prompt_context=prompt_context)
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"LiteLLM API request failed: {e}")
            self.send_websocket_message(f"Error in paper analysis: {e}")
            raise
    
    def forward(self, text: str, infile):
        """
        Analyze paper text and generate instrument details using LiteLLM

        Args:
            text: Full paper text
            infile: PDF content (path string, bytes, or file-like object)

        Returns:
            SimpleNamespace with context, instruments_details, metadata, and annotated_pdf
        """
        try:
            # Load system prompt template only
            import xml.etree.ElementTree as ET
            module_dir = Path(__file__).parent
            prompts_dir = module_dir / "prompts" / "paper_analysis"
            
            with open(prompts_dir / "system.xml", 'r', encoding='utf-8') as f:
                system_content = f.read()
            
            # Parse and extract system prompt content
            system_root = ET.fromstring(system_content)
            system_prompt = ET.tostring(system_root, encoding='unicode', method='xml').strip()
            if system_prompt.startswith('<?xml'):
                system_prompt = system_prompt.split('?>', 1)[1].strip()
            
            # Create simple user prompt without XML parsing
            user_prompt = text

            # Capture render context (no template variables - system is XML, user is raw text)
            prompt_context = {
                'template_name': 'paper_analysis',
                'paper_text': text  # The full paper text used as input
            }

            # Make LiteLLM API call
            instruments_details = self._make_litellm_request(system_prompt, user_prompt, prompt_context)
            
            self.send_websocket_message("Paper analysis complete.")
            
            # Return same structure as original PaperAnalyzer for compatibility
            # Support quotes and PDF annotation are handled by separate tasks
            result = SimpleNamespace(
                context=[text],  # Keep as list for compatibility
                instruments_details=instruments_details,
                metadata={
                    "token_usage": {},  # LLM tracking handled by callback pattern
                    "analyzer_type": "litellm"
                },
                annotated_pdf=None  # Will be handled by separate tasks
            )
            
            return result
            
        except Exception as e:
            logger.exception(f"Failed to analyze paper with LiteLLM approach")
            self.send_websocket_message(f"Paper analysis failed: {e}")
            raise