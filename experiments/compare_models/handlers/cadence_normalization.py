import json
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedCadence


class CadenceNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "cadence_normalization"

    def get_response_format(self) -> Optional[type]:
        return NormalizedCadence  # Use Pydantic schema for structured output

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse cadence normalization response.
        Expected format: JSON with {"cadences": [...], "original_text": "..."}
        """
        try:
            response = response.strip()
            parsed = json.loads(response)

            # Basic validation
            if not isinstance(parsed, dict) or 'cadences' not in parsed:
                return None

            cadences = parsed['cadences']

            # cadences should be a list
            if not isinstance(cadences, list):
                return None

            return {
                'cadences': cadences,
                'original_text': parsed.get('original_text'),
                'raw_response': response
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two cadence normalization responses.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        cadences1 = set(resp1.get('cadences', []))
        cadences2 = set(resp2.get('cadences', []))

        # Exact match
        exact_match = (cadences1 == cadences2)

        # Both empty
        both_empty = (len(cadences1) == 0 and len(cadences2) == 0)

        # Overall agreement
        agree = exact_match

        details_parts = []
        details_parts.append(f"Cadences 1: {sorted(cadences1) if cadences1 else '[]'}")
        details_parts.append(f"Cadences 2: {sorted(cadences2) if cadences2 else '[]'}")
        details_parts.append(f"Exact match: {exact_match}")

        if both_empty:
            details_parts.append("Both responses returned empty cadences")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format cadence normalization for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "#2563eb" if is_agreement else "#dc2626"
        cadences = response.get('cadences', [])

        if not cadences:
            return f'<span style="color: {color}; font-weight: bold;">[] (no cadence)</span>'

        cadences_str = ", ".join(cadences)
        return f'<span style="color: {color}; font-weight: bold;">[{cadences_str}]</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        cadences = response.get('cadences', [])
        if not cadences:
            return "[]"

        return f"[{','.join(cadences[:3])}{'...' if len(cadences) > 3 else ''}]"

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        raw_cadence_context = render_ctx.get('raw_cadence_context', '')

        # Render using template
        _, user_msg = load_and_render_prompt(
            "cadence_normalization",
            raw_cadence_context=raw_cadence_context
        )

        return user_msg
