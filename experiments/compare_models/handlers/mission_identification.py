import re
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class MissionIdentificationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "mission_identification"

    def get_response_format(self) -> Optional[type]:
        return None  # Text-based response

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse mission identification response.
        Expected format: comma-separated numbers (e.g., "9,10") or "UNKNOWN"
        """
        try:
            response = response.strip()

            # Check if response is "UNKNOWN" (case insensitive)
            if response.upper() == "UNKNOWN":
                return {
                    'mission_indices': [],
                    'is_unknown': True,
                    'raw_response': response
                }

            # Extract numbers from response.
            # Prefer parenthesized indices (ShortCode(index) format) to avoid
            # confusing numbers in mission names (e.g., GOES-13) with list indices.
            # Falls back to bare-number extraction for backwards compatibility.
            parens_numbers = re.findall(r'\((\d+)\)', response)
            numbers = parens_numbers if parens_numbers else re.findall(r'\b(\d+)\b', response)
            if not numbers:
                return None

            # Convert to integers
            mission_indices = [int(n) for n in numbers]

            return {
                'mission_indices': mission_indices,
                'is_unknown': False,
                'raw_response': response
            }
        except Exception as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two mission identification responses with multiple metrics.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Check if both are UNKNOWN
        is_unknown1 = resp1.get('is_unknown', False)
        is_unknown2 = resp2.get('is_unknown', False)

        if is_unknown1 and is_unknown2:
            return ComparisonResult(
                agree=True,
                resp1=resp1,
                resp2=resp2,
                details="Both returned UNKNOWN"
            )

        # If one is UNKNOWN and the other is not, they disagree
        if is_unknown1 or is_unknown2:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details=f"One returned UNKNOWN, other returned mission(s)"
            )

        indices1 = set(resp1['mission_indices'])
        indices2 = set(resp2['mission_indices'])

        # Exact match (strictest)
        exact_match = (indices1 == indices2)

        # Set overlap metrics
        if indices1 and indices2:
            overlap = indices1 & indices2
            union = indices1 | indices2
            jaccard = len(overlap) / len(union) if union else 0
            has_overlap = len(overlap) > 0
        else:
            jaccard = 0
            has_overlap = False

        # Top-1 match (did they agree on the primary mission?)
        top1_match = False
        if resp1['mission_indices'] and resp2['mission_indices']:
            top1_match = resp1['mission_indices'][0] == resp2['mission_indices'][0]

        # Overall agreement: exact match
        agree = exact_match

        # Build detailed comparison
        details_parts = []
        details_parts.append(f"Response 1: {sorted(indices1)}")
        details_parts.append(f"Response 2: {sorted(indices2)}")
        details_parts.append(f"Exact match: {exact_match}")
        details_parts.append(f"Top-1 match: {top1_match}")
        details_parts.append(f"Overlap: {overlap if has_overlap else 'none'}")
        details_parts.append(f"Jaccard similarity: {jaccard:.2f}")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format mission identification for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        if response.get('is_unknown', False):
            color = "#f59e0b"  # Amber for UNKNOWN
            return f'<span style="color: {color}; font-weight: bold;">UNKNOWN</span>'

        color = "#2563eb" if is_agreement else "#dc2626"

        missions_str = ", ".join(str(i) for i in sorted(response['mission_indices']))
        return f'<span style="color: {color}; font-weight: bold;">Missions: [{missions_str}]</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        if response.get('is_unknown', False):
            return "UNKNOWN"

        return ",".join(str(i) for i in sorted(response['mission_indices']))

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        mission_context = render_ctx.get('mission_context', '')
        missions_text = render_ctx.get('missions_text', '')
        mission_count = render_ctx.get('mission_count', 0)
        top_k = render_ctx.get('top_k', 10)

        # Render using template
        _, user_msg = load_and_render_prompt(
            "mission_identification",
            mission_context=mission_context,
            missions_text=missions_text,
            mission_count=mission_count,
            top_k=top_k
        )

        return user_msg
