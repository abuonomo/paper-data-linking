import json
from typing import Optional, Dict, Any
from datetime import datetime
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedTimeRange


class TimeNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "time_normalization"

    def get_response_format(self) -> Optional[type]:
        return NormalizedTimeRange  # Use Pydantic schema for structured output

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse time normalization response.
        Expected format: JSON with start_datetime, end_datetime, precision, is_approximate, error fields
        """
        try:
            response = response.strip()
            parsed = json.loads(response)

            # Basic validation
            if not isinstance(parsed, dict):
                return None

            # Extract fields (all optional except precision)
            result = {
                'start_datetime': parsed.get('start_datetime'),
                'end_datetime': parsed.get('end_datetime'),
                'precision': parsed.get('precision'),
                'is_approximate': parsed.get('is_approximate', False),
                'error': parsed.get('error', False),
                'error_message': parsed.get('error_message'),
                'original_text': parsed.get('original_text'),
                'raw_response': response
            }

            return result
        except (json.JSONDecodeError, TypeError) as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two time normalization responses.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Check if both errored
        both_error = resp1.get('error') and resp2.get('error')

        # Check datetime agreement
        start_match = (resp1.get('start_datetime') == resp2.get('start_datetime'))
        end_match = (resp1.get('end_datetime') == resp2.get('end_datetime'))
        precision_match = (resp1.get('precision') == resp2.get('precision'))

        # Overall agreement: both errored OR all fields match
        exact_match = start_match and end_match and precision_match
        agree = both_error or exact_match

        details_parts = []
        details_parts.append(f"Start: {resp1.get('start_datetime')} vs {resp2.get('start_datetime')}")
        details_parts.append(f"End: {resp1.get('end_datetime')} vs {resp2.get('end_datetime')}")
        details_parts.append(f"Precision: {resp1.get('precision')} vs {resp2.get('precision')}")

        if both_error:
            details_parts.append("Both responses returned error")

        if resp1.get('is_approximate') or resp2.get('is_approximate'):
            details_parts.append(f"Approximate: {resp1.get('is_approximate')} vs {resp2.get('is_approximate')}")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format time normalization for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "#2563eb" if is_agreement else "#dc2626"

        if response.get('error'):
            error_msg = response.get('error_message', 'Unknown error')
            return f'<span style="color: {color}; font-weight: bold;">ERROR: {error_msg}</span>'

        start = response.get('start_datetime', 'null')
        end = response.get('end_datetime', 'null')
        precision = response.get('precision', 'unknown')
        approx = " (approx)" if response.get('is_approximate') else ""

        return f'<span style="color: {color};">{start} → {end} ({precision}){approx}</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        if response.get('error'):
            return f"ERROR: {response.get('error_message', 'Unknown')}"

        precision = response.get('precision', '?')
        approx = " (approx)" if response.get('is_approximate') else ""
        return f"{precision}{approx}"

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        raw_time = render_ctx.get('raw_time', '')

        # Render using template
        _, user_msg = load_and_render_prompt(
            "time_normalization",
            raw_time=raw_time
        )

        return user_msg
