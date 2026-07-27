"""
Abstract base class for handling different LLM call types.

This provides a plugin architecture for extending prompt experimentation to
different types of LLM calls (validation, normalization, extraction, etc.).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Type
from pydantic import BaseModel


@dataclass
class ComparisonResult:
    """Result of comparing two responses."""
    agree: bool
    resp1: Any
    resp2: Any
    details: Optional[str] = None  # Human-readable explanation of comparison


class CallTypeHandler(ABC):
    """
    Abstract base class for handling specific LLM call types.

    Each call type (e.g., instrument_validation, wavelength_normalization)
    should implement this interface to provide:
    - Response parsing logic
    - Response comparison logic
    - HTML formatting logic
    - Optional structured output schema
    """

    @abstractmethod
    def get_call_type_name(self) -> str:
        """
        Return the unique identifier for this call type.

        Example: "instrument_validation", "wavelength_normalization"
        """
        pass

    def get_response_format(self) -> Optional[Type[BaseModel]]:
        """
        Return Pydantic model for structured output, or None for plain text.

        If provided, this will be passed to the LLM client as response_format
        to request structured JSON output.
        """
        return None

    @abstractmethod
    def parse_response(self, response: str) -> Any:
        """
        Parse LLM response text into structured format.

        Args:
            response: Raw text output from LLM

        Returns:
            Parsed/structured representation appropriate for this call type.
            Could be a string, dict, Pydantic model, etc.
        """
        pass

    @abstractmethod
    def compare_responses(self, resp1: Any, resp2: Any) -> ComparisonResult:
        """
        Compare two parsed responses for agreement.

        Args:
            resp1: First parsed response (from parse_response)
            resp2: Second parsed response (from parse_response)

        Returns:
            ComparisonResult with agreement status and details
        """
        pass

    @abstractmethod
    def format_for_html(self, response: Any, is_agreement: bool = True) -> str:
        """
        Format parsed response for HTML display.

        Args:
            response: Parsed response (from parse_response)
            is_agreement: Whether this response agrees with others (for styling)

        Returns:
            HTML string for displaying this response
        """
        pass

    def get_short_summary(self, response: Any) -> str:
        """
        Get a brief summary of the response for logging/display.

        Default implementation converts to string. Override for custom summary.
        """
        return str(response)

    def render_user_message(self, test_case: dict) -> str:
        """
        Render user message from raw test case data.

        This method takes a test case from the new export format (with raw_inputs)
        and renders it into a user message string for the LLM.

        Args:
            test_case: Dictionary containing 'raw_inputs', 'canonical_instrument',
                      'vso_metadata', etc.

        Returns:
            Rendered user message string

        Note: Override this in subclasses to handle call-type-specific rendering.
        Default implementation just returns the first raw input value.
        """
        raw_inputs = test_case.get('raw_inputs', {})
        # Default: return first value from raw_inputs
        if raw_inputs:
            return list(raw_inputs.values())[0]
        return ""
