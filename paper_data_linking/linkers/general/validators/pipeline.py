import inspect
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.schemas.structured_instruments import (
    StructuredInstrumentDetails,
)

from .base_validator import ValidationResult
from .validator_registry import StructureValidatorRegistry

logger = logging.getLogger(__name__)

MAX_FIX_ITERATIONS = 3


@dataclass
class PipelineResult:
    """Full result from running the validation pipeline."""

    structured: StructuredInstrumentDetails
    validation_results: List[ValidationResult] = field(default_factory=list)
    total_issues_found: int = 0
    total_issues_fixed: int = 0
    total_llm_calls: int = 0
    all_skipped: bool = True  # True if no validator found any issues


class StructureValidatorPipeline:
    """
    Runs all registered validators in priority order.

    For each validator:
    1. detect() -- cheap, no LLM
    2. If issues found, fix() -- may use LLM
    3. Re-detect to verify fix, loop up to MAX_FIX_ITERATIONS
    4. If no issues found, skip entirely (fast path for ~96% of cases)
    """

    def __init__(
        self,
        llm_client: Optional[LiteLLMClient] = None,
        llm_config=None,
    ):
        self.llm_client = llm_client
        self.llm_config = llm_config

    def run(
        self,
        structured: StructuredInstrumentDetails,
        original_markdown: str,
    ) -> PipelineResult:
        result = PipelineResult(structured=structured)

        ordered_names = StructureValidatorRegistry.list_ordered()
        if not ordered_names:
            logger.info("No structure validators registered, skipping validation")
            return result

        logger.info(
            f"Running {len(ordered_names)} structure validators: {ordered_names}"
        )

        for name in ordered_names:
            validator_cls = StructureValidatorRegistry.get(name)

            # Instantiate with LLM plumbing (same pattern as normalizers)
            kwargs = {}
            sig = inspect.signature(validator_cls.__init__)
            if "llm_client" in sig.parameters:
                kwargs["llm_client"] = self.llm_client
            if "llm_config" in sig.parameters:
                kwargs["llm_config"] = self.llm_config
            validator = validator_cls(**kwargs)

            vr = ValidationResult(validator_name=name)

            # Phase 1: Detect
            issues = validator.detect(result.structured, original_markdown)
            vr.issues_found = len(issues)
            result.total_issues_found += len(issues)

            if not issues:
                vr.skipped = True
                result.validation_results.append(vr)
                logger.info(f"Validator '{name}': no issues detected, skipping")
                continue

            result.all_skipped = False
            logger.info(f"Validator '{name}': detected {len(issues)} issues")

            # Phase 2: Fix with retry loop
            for iteration in range(MAX_FIX_ITERATIONS):
                logger.info(
                    f"Validator '{name}': fix iteration "
                    f"{iteration + 1}/{MAX_FIX_ITERATIONS}"
                )

                prev_field_paths = {i.field_path for i in issues}

                try:
                    result.structured = validator.fix(
                        result.structured, issues, original_markdown
                    )
                    vr.llm_calls_made += 1
                    result.total_llm_calls += 1
                except Exception:
                    logger.exception(
                        f"Validator '{name}': fix() failed on iteration "
                        f"{iteration + 1}"
                    )
                    break

                # Re-detect to verify fix
                remaining_issues = validator.detect(
                    result.structured, original_markdown
                )
                fixed_count = len(issues) - len(remaining_issues)
                vr.issues_fixed += fixed_count

                if not remaining_issues:
                    logger.info(
                        f"Validator '{name}': all issues fixed after "
                        f"{iteration + 1} iteration(s)"
                    )
                    break

                # If the same issues remain, they're unfixable — stop retrying
                remaining_paths = {i.field_path for i in remaining_issues}
                if remaining_paths == prev_field_paths:
                    logger.info(
                        f"Validator '{name}': {len(remaining_issues)} unfixable "
                        f"issues, stopping retries"
                    )
                    break

                issues = remaining_issues
                logger.info(
                    f"Validator '{name}': {len(remaining_issues)} issues "
                    f"remain after iteration {iteration + 1}"
                )

            result.total_issues_fixed += vr.issues_fixed
            result.validation_results.append(vr)

        return result
