"""
Free-text handler for physobs normalization v2 (with stricter UNCERTAIN guidance).
"""

import json
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class PhysObsNormalizationFreeTextV2Handler(CallTypeHandler):
    """
    Handler for physobs normalization v2 with stricter UNCERTAIN guidance.

    V2 changes:
    - More explicit guidance on when to return UNCERTAIN
    - Clarifies behavior for derived/inferred quantities
    - Clarifies behavior for indirect language indicating processing

    Model outputs just the physical observable name or "UNCERTAIN" as plain text.
    """

    def get_call_type_name(self) -> str:
        return "physobs_normalization"

    def get_response_format(self) -> Optional[type]:
        """No Pydantic schema - allow free-text responses."""
        return None

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse free-text response into structured format.

        Expected response format: Just the candidate string or "UNCERTAIN"

        Returns:
            Dict with 'physical_observable' key, or None if parse fails
        """
        if not response:
            return None

        # Strip whitespace and quotes
        cleaned = response.strip().strip('"').strip("'").strip()

        # Empty response = parse failure
        if not cleaned:
            return None

        # Return the cleaned response as the physical_observable
        return {
            'physical_observable': cleaned
        }

    def compare_responses(
        self,
        resp1: Optional[Dict[str, Any]],
        resp2: Optional[Dict[str, Any]]
    ) -> ComparisonResult:
        """
        Compare two parsed responses for agreement.

        Responses agree if they have the same physical_observable value.
        """
        # Handle None cases
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Extract physical observables
        obs1 = resp1.get('physical_observable')
        obs2 = resp2.get('physical_observable')

        # Compare (case-sensitive exact match)
        agree = (obs1 == obs2)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=f"obs1='{obs1}' vs obs2='{obs2}'"
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

        obs = response.get('physical_observable', 'UNKNOWN')

        # Color code based on agreement and value
        if not is_agreement:
            color = "red"
        elif obs == "UNCERTAIN":
            color = "orange"
        else:
            color = "green"

        return f'<span style="color: {color};">{obs}</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """
        Get brief summary for logging.
        """
        if response is None:
            return "PARSE_FAILURE"

        return response.get('physical_observable', 'UNKNOWN')

    def render_user_message(self, test_case: dict) -> str:
        """
        Render user message from test case data using prompt template.
        """
        # Extract render context from test case
        render_ctx = test_case.get('render_context', {})

        instrument_code = render_ctx.get('instrument_code', '')
        raw_observable = render_ctx.get('raw_observable', '')
        candidates = render_ctx.get('candidates', [])

        # Render using v2 template
        _, user_msg = load_and_render_prompt(
            "physobs_normalization",
            instrument_code=instrument_code,
            raw_observable=raw_observable,
            candidates=candidates
        )

        return user_msg
