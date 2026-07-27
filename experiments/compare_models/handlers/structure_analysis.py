import json
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.schemas.structured_instruments import StructuredInstrumentDetails
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class StructureAnalysisHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "structure_analysis"

    def get_response_format(self) -> Optional[type]:
        return StructuredInstrumentDetails  # Use Pydantic schema for structured output

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse structure_analysis response.
        Expected format: JSON with paper_summary and instruments list
        """
        try:
            parsed = json.loads(response)

            if not isinstance(parsed, dict):
                return None

            # Extract basic structure
            paper_summary = parsed.get('paper_summary', '')
            instruments = parsed.get('instruments', [])

            if not isinstance(instruments, list):
                return None

            # Extract instrument names and period counts
            instrument_names = []
            total_periods = 0
            period_counts = {}

            for inst in instruments:
                if isinstance(inst, dict):
                    name = inst.get('name', '')
                    if name:
                        instrument_names.append(name)
                        periods = inst.get('data_collection_periods', [])
                        period_count = len(periods) if isinstance(periods, list) else 0
                        period_counts[name] = period_count
                        total_periods += period_count

            return {
                'paper_summary': paper_summary,
                'instrument_count': len(instrument_names),
                'instrument_names': instrument_names,
                'total_periods': total_periods,
                'period_counts': period_counts,
                'raw_response': response
            }
        except Exception as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """
        Compare two structure_analysis responses with multiple metrics.
        Focus on top-level statistics rather than deep semantic comparison.
        """
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Extract comparison metrics
        inst_count_1 = resp1['instrument_count']
        inst_count_2 = resp2['instrument_count']
        names_1 = set(resp1['instrument_names'])
        names_2 = set(resp2['instrument_names'])
        total_periods_1 = resp1['total_periods']
        total_periods_2 = resp2['total_periods']

        # Instrument count match
        count_match = (inst_count_1 == inst_count_2)

        # Name overlap metrics
        if names_1 or names_2:
            overlap = names_1 & names_2
            union = names_1 | names_2
            jaccard = len(overlap) / len(union) if union else 0
            has_overlap = len(overlap) > 0
        else:
            jaccard = 1.0 if (not names_1 and not names_2) else 0
            has_overlap = False
            overlap = set()

        # Exact name match
        exact_name_match = (names_1 == names_2)

        # Period count comparison for overlapping instruments
        overlapping_period_diffs = {}
        if overlap:
            for name in overlap:
                p1 = resp1['period_counts'].get(name, 0)
                p2 = resp2['period_counts'].get(name, 0)
                if p1 != p2:
                    overlapping_period_diffs[name] = f"{p1} vs {p2}"

        # Overall agreement: exact name match
        agree = exact_name_match

        # Build detailed comparison
        details_parts = []
        details_parts.append(f"Instrument counts: {inst_count_1} vs {inst_count_2}")
        details_parts.append(f"Exact name match: {exact_name_match}")
        details_parts.append(f"Name Jaccard: {jaccard:.2f}")
        details_parts.append(f"Overlapping names: {len(overlap)}")
        details_parts.append(f"Total periods: {total_periods_1} vs {total_periods_2}")

        if overlapping_period_diffs:
            period_diff_summary = "; ".join([f"{k}: {v}" for k, v in list(overlapping_period_diffs.items())[:3]])
            details_parts.append(f"Period count diffs: {period_diff_summary}")

        details = " | ".join(details_parts)

        return ComparisonResult(
            agree=agree,
            resp1=resp1,
            resp2=resp2,
            details=details
        )

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format structure_analysis for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        color = "#2563eb" if is_agreement else "#dc2626"

        inst_count = response['instrument_count']
        total_periods = response['total_periods']
        names = response['instrument_names'][:3]  # Show first 3
        names_str = ", ".join(names)
        if response['instrument_count'] > 3:
            names_str += f", ... (+{response['instrument_count'] - 3} more)"

        return f'<span style="color: {color}; font-weight: bold;">{inst_count} instruments, {total_periods} periods</span><br/><span style="color: {color}; font-size: 0.9em;">{names_str}</span>'

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        inst_count = response['instrument_count']
        total_periods = response['total_periods']
        return f"{inst_count} instruments, {total_periods} periods"

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract render_context
        render_ctx = test_case.get('render_context', {})

        instruments_details_text = render_ctx.get('instruments_details_text', '')

        # Render using template
        _, user_msg = load_and_render_prompt(
            "structured_parsing",
            instruments_details_text=instruments_details_text
        )

        return user_msg
