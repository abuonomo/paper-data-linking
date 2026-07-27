import json
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt


class NormalizedObservable(BaseModel):
    """Pydantic model matching the production schema"""
    physical_observable: str = Field(description="imaging|spectroscopy|photometry|ranging|simulation")
    original_text: str = Field(description="Original observable text")


class PhysObsNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "physobs_normalization"

    def get_response_format(self) -> Optional[type[BaseModel]]:
        return NormalizedObservable

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response into dictionary"""
        try:
            data = json.loads(response)
            # Validate it matches the schema
            NormalizedObservable(**data)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            return None

    def compare_responses(self, resp1: Optional[Dict[str, Any]], resp2: Optional[Dict[str, Any]]) -> ComparisonResult:
        """Compare two physobs normalization responses"""
        # If either failed to parse, they disagree
        if resp1 is None or resp2 is None:
            return ComparisonResult(
                agree=False,
                resp1=resp1,
                resp2=resp2,
                details="One or both responses failed to parse"
            )

        # Compare the chosen physical observable (case-insensitive)
        physobs1 = resp1.get('physical_observable', '').lower()
        physobs2 = resp2.get('physical_observable', '').lower()
        physobs_match = physobs1 == physobs2

        if not physobs_match:
            details = f"physobs: {resp1.get('physical_observable')} vs {resp2.get('physical_observable')}"
        else:
            details = None

        return ComparisonResult(agree=physobs_match, resp1=resp1, resp2=resp2, details=details)

    def format_for_html(self, response: Optional[Dict[str, Any]], is_agreement: bool = True) -> str:
        """Format physobs data for HTML display"""
        if response is None:
            return '<span style="color: gray;">UNPARSEABLE</span>'

        physobs = response.get('physical_observable', 'unknown')
        original = response.get('original_text', '')

        # Color code by type
        color = "#2563eb" if is_agreement else "#dc2626"

        parts = []
        parts.append(f'<span style="color: {color}; font-weight: bold;">{physobs}</span>')
        parts.append(f'<br><span style="color: #6b7280; font-size: 0.9em;">"{original}"</span>')

        return '<br>'.join(parts)

    def get_short_summary(self, response: Optional[Dict[str, Any]]) -> str:
        """Brief summary for logging"""
        if response is None:
            return "UNPARSEABLE"

        physobs = response.get('physical_observable', 'unknown')
        return physobs

    def render_user_message(self, test_case: dict) -> str:
        """Render user message from test case data using prompt template"""
        # Extract data from test case
        raw_inputs = test_case.get('raw_inputs', {})
        canonical_instrument = test_case.get('canonical_instrument', {})
        vso_metadata = test_case.get('vso_metadata', {})

        # Map to template variables
        instrument_code = canonical_instrument.get('code', '')
        raw_observable = raw_inputs.get('raw_observable', '')
        candidates = vso_metadata.get('valid_physobs_candidates', [])

        # Render using template
        _, user_msg = load_and_render_prompt(
            "physobs_normalization",
            instrument_code=instrument_code,
            candidates=candidates,
            raw_observable=raw_observable
        )

        return user_msg
