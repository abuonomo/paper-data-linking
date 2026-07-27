import re
from typing import Optional, Dict, Any, Set
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class MissionSelectionHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "mission_selection"

    def get_response_format(self) -> Optional[type]:
        return None  # Text-based response

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse mission selection response.
        Expected format: single number (e.g., "1"), multiple numbers (e.g., "1,3"), or "0" for ambiguous
        """
        try:
            response = response.strip()

            # Extract all numbers from response
            numbers = re.findall(r'\b(\d+)\b', response)
            if not numbers:
                return None

            # Convert to integers
            mission_indices = [int(n) for n in numbers]

            # Check if ambiguous response
            is_ambiguous = (len(mission_indices) == 1 and mission_indices[0] == 0)

            return {
                'mission_indices': mission_indices,
                'is_ambiguous': is_ambiguous,
                'raw_response': response
            }
        except Exception as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two mission selection responses with multiple metrics.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        indices1 = set(resp1['mission_indices'])
        indices2 = set(resp2['mission_indices'])

        # Exact match (strictest)
        exact_match = (indices1 == indices2)

        # Check if both are ambiguous
        both_ambiguous = resp1['is_ambiguous'] and resp2['is_ambiguous']

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

        # Overall agreement: exact match OR both ambiguous
        agree = exact_match or both_ambiguous

        # Build detailed comparison
        details_parts = []
        details_parts.append(f"Response 1: {sorted(indices1)}")
        details_parts.append(f"Response 2: {sorted(indices2)}")
        details_parts.append(f"Exact match: {exact_match}")
        details_parts.append(f"Top-1 match: {top1_match}")
        details_parts.append(f"Overlap: {overlap if has_overlap else 'none'}")
        details_parts.append(f"Jaccard similarity: {jaccard:.2f}")

        if both_ambiguous:
            details_parts.append("Both responses marked as ambiguous")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format mission selection for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "#2563eb" if is_agreement else "#dc2626"

        if response['is_ambiguous']:
            return f'<span style="color: {color}; font-weight: bold;">AMBIGUOUS (0)</span>'

        missions_str = ", ".join(str(i) for i in sorted(response['mission_indices']))
        return f'<span style="color: {color}; font-weight: bold;">Missions: [{missions_str}]</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        if response['is_ambiguous']:
            return "AMBIGUOUS"

        return ",".join(str(i) for i in sorted(response['mission_indices']))

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        mission_context = render_ctx.get('mission_context', '')
        candidates_text = render_ctx.get('candidates_text', '')
        candidate_count = render_ctx.get('candidate_count', 0)

        # Render using template
        _, user_msg = load_and_render_prompt(
            "mission_selection",
            mission_context=mission_context,
            candidates_text=candidates_text,
            candidate_count=candidate_count
        )

        return user_msg
