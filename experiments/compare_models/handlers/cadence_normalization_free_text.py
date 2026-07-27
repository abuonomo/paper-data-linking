"""
Free-text handler for cadence normalization (without Pydantic schema).

This handler expects the model to return plain ISO 8601 duration strings
instead of JSON, reducing parse errors.
"""

from typing import Optional, Dict, Any, List
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class CadenceNormalizationFreeTextHandler(CallTypeHandler):
    """
    Handler for cadence normalization without Pydantic schema enforcement.

    Expected response format: Plain text ISO 8601 duration(s) or "NONE"
    Examples:
        - PT3S
        - PT5M, PT10M
        - PT12S/PT16S
        - NONE
    """

    def get_call_type_name(self) -> str:
        return "cadence_normalization"

    def get_response_format(self) -> Optional[type]:
        """No Pydantic schema - allow free-text responses."""
        return None

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse free-text response into structured format.

        Expected response format: ISO 8601 duration string(s) or "NONE"

        Returns:
            Dict with 'cadences' list, or None if parse fails
        """
        if not response:
            return None

        # Strip whitespace and quotes
        cleaned = response.strip().strip('"').strip("'").strip()

        # Empty response = parse failure
        if not cleaned:
            return None

        # Handle "NONE" case
        if cleaned.upper() == "NONE":
            return {
                'cadences': [],
                'raw_response': cleaned
            }

        # Split by comma for multiple cadences
        cadence_strings = [c.strip() for c in cleaned.split(',')]

        # Filter out empty strings
        cadence_strings = [c for c in cadence_strings if c]

        if not cadence_strings:
            return {
                'cadences': [],
                'raw_response': cleaned
            }

        return {
            'cadences': cadence_strings,
            'raw_response': cleaned
        }

    def compare_responses(
        self,
        resp1: Optional[Dict[str, Any]],
        resp2: Optional[Dict[str, Any]]
    ) -> ComparisonResult:
        """
        Compare two parsed responses for agreement.

        Responses agree if they have the same set of cadences.
        """
        # Handle None cases
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Extract cadences
        cad1 = resp1.get('cadences', [])
        cad2 = resp2.get('cadences', [])

        # Normalize to sets for comparison (order-independent)
        set1 = set(cad1)
        set2 = set(cad2)

        # Compare
        agree = (set1 == set2)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=f"cad1={sorted(list(set1))} vs cad2={sorted(list(set2))}"
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

        cadences = response.get('cadences', [])

        if not cadences:
            display = "NONE"
            color = "orange" if is_agreement else "red"
        else:
            display = ", ".join(cadences)
            color = "green" if is_agreement else "red"

        return f'<span style="color: {color};">{display}</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """
        Get brief summary for logging.
        """
        if response is None:
            return "PARSE_FAILURE"

        cadences = response.get('cadences', [])
        if not cadences:
            return "NONE"

        return ", ".join(cadences)

    def render_user_message(self, test_case: dict) -> str:
        """
        Render user message from test case data using prompt template.

        Loads from the cadence_normalization prompt directory.
        """
        # Extract render context from test case
        render_ctx = test_case.get('render_context', {})

        raw_cadence_context = render_ctx.get('raw_cadence_context', '')

        # Render using template
        _, user_msg = load_and_render_prompt(
            "cadence_normalization",
            raw_cadence_context=raw_cadence_context
        )

        return user_msg
