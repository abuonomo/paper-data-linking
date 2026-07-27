# paper_data_linking/linkers/general/normalizers/base_normalizer.py

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from .normalization_context import NormalizationContext


class BaseNormalizer(ABC):
    """
    Abstract base class for all normalizer implementations.
    
    All normalizers now receive a unified NormalizationContext object containing
    all the data they might need. Each normalizer extracts the specific fields
    it requires from the context, making the interface consistent and self-documenting.
    """
    
    def __init__(self, llm_client: Optional[LiteLLMClient] = None):
        """Initialize normalizer with optional LLM client."""
        self.llm_client = llm_client or LiteLLMClient()
    
    @abstractmethod
    def normalize(self, context: NormalizationContext) -> Dict[str, Any]:
        """
        Normalize data from context and return structured dictionary.
        
        All normalizers receive the same rich context object and extract
        the specific fields they need:
        - TimeRangeNormalizer: uses context.get_time_range()
        - WavelengthNormalizer: uses context.get_wavelengths()
        - PhysObsNormalizer: uses context.instrument_code and context.get_physical_observable()
        - QuoteNormalizer: uses context.get_categorized_quotes()
        
        Args:
            context: NormalizationContext containing all normalization data
            
        Returns:
            Dict containing normalized data structure
        """
        pass