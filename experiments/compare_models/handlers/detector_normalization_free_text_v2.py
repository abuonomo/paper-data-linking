"""
Free-text handler for detector normalization v2 (with stricter UNCERTAIN guidance).
"""

import json
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class DetectorNormalizationFreeTextV2Handler(CallTypeHandler):
    """
    Handler for detector normalization v2 with stricter UNCERTAIN guidance.

    V2 changes:
    - More explicit guidance on when to return UNCERTAIN
    - Clarifies behavior for multi-detector mentions
    - Clarifies behavior for generic measurement descriptions

    Model outputs just the detector name or "UNCERTAIN" as plain text.
    """

    def get_call_type_name(self) -> str:
        return "detector_normalization"

    def get_response_format(self) -> Optional[type]:
        """No Pydantic schema - allow free-text responses."""
        return None

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse free-text response into structured format.

        Expected response format: Just the detector name or "UNCERTAIN"

        Returns:
            Dict with 'detector' key, or None if parse fails
        """
        if not response:
            return None

        # Strip whitespace and quotes
        cleaned = response.strip().strip('"').strip("'").strip()

        # Empty response = parse failure
        if not cleaned:
            return None

        # Return the cleaned response as the detector
        # Could be a detector name or "UNCERTAIN"
        return {
            'detector': cleaned
        }

    def compare_responses(
        self,
        resp1: Optional[Dict[str, Any]],
        resp2: Optional[Dict[str, Any]]
    ) -> ComparisonResult:
        """
        Compare two parsed responses for agreement.

        Responses agree if they have the same detector value.
        """
        # Handle None cases
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Extract detectors
        det1 = resp1.get('detector')
        det2 = resp2.get('detector')

        # Compare (case-sensitive exact match)
        agree = (det1 == det2)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=f"det1='{det1}' vs det2='{det2}'"
        )

    def format_for_html(
        self,
        response: Optional[Dict[str, Any]],
        is_agreement: bool = True
    ) -> str:
        """
        Format response for HTML display.
        """
        if response is None:
            return '<span style="color: red;">PARSE_FAILURE</span>'

        det = response.get('detector', 'UNKNOWN')

        # Color code based on agreement and value
        if not is_agreement:
            color = "red"
        elif det == "UNCERTAIN":
            color = "orange"
        else:
            color = "green"

        return f'<span style="color: {color};">{det}</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """
        Get brief summary for logging.
        """
        if response is None:
            return "PARSE_FAILURE"

        return response.get('detector', 'UNKNOWN')

    def render_user_message(self, test_case: dict) -> str:
        """
        Render user message from test case data using prompt template.
        """
        # Extract render context from test case
        render_ctx = test_case.get('render_context', {})

        instrument_code = render_ctx.get('instrument_code', '')
        raw_detector_context = render_ctx.get('raw_detector_context', '')
        candidates = render_ctx.get('candidates', [])

        # Render using v2 template
        _, user_msg = load_and_render_prompt(
            "detector_normalization",
            instrument_code=instrument_code,
            raw_detector_context=raw_detector_context,
            candidates=candidates
        )

        return user_msg
