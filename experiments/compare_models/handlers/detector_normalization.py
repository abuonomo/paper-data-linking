import json
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedDetector


class DetectorNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "detector_normalization"

    def get_response_format(self) -> Optional[type]:
        return NormalizedDetector  # Use Pydantic schema for structured output

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse detector normalization response.
        Expected format: JSON with {"detector": "C2"} or {"detector": null}
        """
        try:
            response = response.strip()
            parsed = json.loads(response)

            # Validate structure
            if not isinstance(parsed, dict) or 'detector' not in parsed:
                return None

            detector = parsed['detector']

            # Detector should be string or None
            if detector is not None and not isinstance(detector, str):
                return None

            return {
                'detector': detector,
                'raw_response': response
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two detector normalization responses.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        detector1 = resp1.get('detector')
        detector2 = resp2.get('detector')

        # Exact match (including both null)
        exact_match = (detector1 == detector2)

        # Both null
        both_null = (detector1 is None and detector2 is None)

        details_parts = []
        details_parts.append(f"Response 1: {detector1 if detector1 else 'null'}")
        details_parts.append(f"Response 2: {detector2 if detector2 else 'null'}")
        details_parts.append(f"Exact match: {exact_match}")

        if both_null:
            details_parts.append("Both responses returned null (no detector match)")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=exact_match,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format detector normalization for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "#2563eb" if is_agreement else "#dc2626"
        detector = response.get('detector')

        if detector is None:
            return f'<span style="color: {color}; font-weight: bold;">NULL (no match)</span>'

        return f'<span style="color: {color}; font-weight: bold;">"{detector}"</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        detector = response.get('detector')
        if detector is None:
            return "NULL"

        return f'"{detector}"'

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        instrument_code = render_ctx.get('instrument_code', '')
        raw_detector_context = render_ctx.get('raw_detector_context', '')
        candidates = render_ctx.get('candidates', [])

        # Render using template
        _, user_msg = load_and_render_prompt(
            "detector_normalization",
            instrument_code=instrument_code,
            raw_detector_context=raw_detector_context,
            candidates=candidates
        )

        return user_msg
