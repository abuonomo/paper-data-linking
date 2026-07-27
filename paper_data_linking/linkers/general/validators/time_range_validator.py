import logging
import re
from typing import List

from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt
from paper_data_linking.linkers.general.schemas.structured_instruments import (
    StructuredInstrumentDetails,
)

from .base_validator import BaseStructureValidator, ValidationIssue
from .fix_schemas import TimeRangeFixResponse
from .patch_utils import apply_patch
from .validator_registry import StructureValidatorRegistry

logger = logging.getLogger(__name__)

# If a time_range contains a 4-digit year, it has a real date — no fix needed.
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


@StructureValidatorRegistry.register(
    "time_range_date_check", version="1.0", priority=0
)
class TimeRangeDateValidator(BaseStructureValidator):
    """
    Detects data collection periods whose time_range is descriptive text
    rather than actual dates, and attempts to resolve them from document context.
    """

    def detect(
        self,
        structured: StructuredInstrumentDetails,
        original_markdown: str,
    ) -> List[ValidationIssue]:
        issues = []
        for i, instrument in enumerate(structured.instruments):
            for j, period in enumerate(instrument.data_collection_periods):
                tr = (period.time_range or "").strip()

                if not tr:
                    continue

                # Has a real date — no fix needed
                if _YEAR_PATTERN.search(tr):
                    continue

                # No year and not genuinely dateless — flag for LLM resolution
                issues.append(
                    ValidationIssue(
                        field_path=(
                            f"instruments[{i}]"
                            f".data_collection_periods[{j}]"
                            f".time_range"
                        ),
                        issue_type="missing_date",
                        description=(
                            f"Instrument '{instrument.name}', "
                            f"period '{period.period_name}': "
                            f"time_range has no date ('{tr}')."
                        ),
                        current_value=tr,
                    )
                )
        return issues

    def fix(
        self,
        structured: StructuredInstrumentDetails,
        issues: List[ValidationIssue],
        original_markdown: str,
    ) -> StructuredInstrumentDetails:
        """Use a targeted LLM call to resolve descriptive time ranges."""
        if not issues:
            return structured

        structure_validation_config = self.llm_config.structure_validation

        issues_description = "\n".join(
            f"- {issue.field_path}: current value = \"{issue.current_value}\""
            for issue in issues
        )

        system_msg, user_msg = load_and_render_prompt(
            "structure_validation/time_range_fix",
            original_markdown=original_markdown,
            structured_json=structured.model_dump_json(indent=2),
            issues_description=issues_description,
        )

        response = self.llm_client.completion(
            call_type="structure_validation_time_range",
            model=structure_validation_config.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            prompt_context={
                "template_name": "structure_validation/time_range_fix",
                "issues_count": len(issues),
            },
            **structure_validation_config.to_kwargs(
                response_format=TimeRangeFixResponse
            ),
        )

        try:
            fix_response = TimeRangeFixResponse.model_validate_json(
                response.choices[0].message.content
            )
        except Exception:
            logger.exception("Failed to parse LLM fix response")
            return structured

        # Apply patches
        patched = structured.model_copy(deep=True)
        for patch in fix_response.patches:
            try:
                apply_patch(patched, patch.field_path, patch.new_value)
                logger.info(
                    f"Applied patch: {patch.field_path} = '{patch.new_value}' "
                    f"(reason: {patch.reasoning})"
                )
            except (AttributeError, IndexError, TypeError):
                logger.warning(
                    f"Failed to apply patch at {patch.field_path}, skipping"
                )

        if fix_response.unfixable_paths:
            logger.info(
                f"Unfixable paths: {fix_response.unfixable_paths}"
            )

        return patched
