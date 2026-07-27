"""
Handler for instrument validation LLM calls.

Validates whether a proposed instrument match is valid given the description.
Response is binary: valid or invalid.
"""
import re
from typing import Optional
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult


class InstrumentValidationHandler(CallTypeHandler):
    """
    Handler for instrument validation tasks.

    Expected response format from LLM:
        VALIDATION ANALYSIS:
        - Name/Type alignment: ... → pass/fail
        ...
        FINAL DECISION: valid/invalid
    """

    def get_call_type_name(self) -> str:
        return "instrument_validation"

    def parse_response(self, response: str) -> Optional[str]:
        """
        Extract 'valid' or 'invalid' from response text.

        Returns:
            'valid', 'invalid', or None if not found
        """
        # Handle both plain text and markdown bold formatting
        match = re.search(
            r'FINAL\s+DECISION:\s*\*?\*?(valid|invalid)\*?\*?',
            response,
            re.IGNORECASE
        )
        if match:
            return match.group(1).lower()
        return None

    def compare_responses(self, resp1: Optional[str], resp2: Optional[str]) -> ComparisonResult:
        """Compare two validation decisions."""
        agree = (resp1 == resp2)
        details = None

        if not agree:
            details = f"Disagreement: {resp1} vs {resp2}"

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[str], is_agreement: bool = True) -> str:
        """Format validation decision for HTML display."""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "green" if response == "valid" else "red"
        return f'<span style="color: {color}; font-weight: bold;">{response.upper()}</span>'

    def get_short_summary(self, response: Optional[str]) -> str:
        """Brief summary for logging."""
        if response is None:
            return "UNPARSEABLE"
        return response.upper()
