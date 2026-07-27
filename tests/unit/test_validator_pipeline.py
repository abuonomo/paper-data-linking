"""Tests for StructureValidatorPipeline orchestration."""

from unittest.mock import Mock, patch

import pytest

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    DataCollectionPeriod,
    Instrument,
    StructuredInstrumentDetails,
)
from paper_data_linking.linkers.general.validators.base_validator import (
    BaseStructureValidator,
    ValidationIssue,
)
from paper_data_linking.linkers.general.validators.pipeline import (
    StructureValidatorPipeline,
)
from paper_data_linking.linkers.general.validators.validator_registry import (
    StructureValidatorRegistry,
)


def _structured():
    return StructuredInstrumentDetails(
        paper_summary="test",
        instruments=[
            Instrument(
                name="Inst",
                general_comments="",
                general_quotes=[],
                data_collection_periods=[
                    DataCollectionPeriod(
                        period_name="P1",
                        time_range="no date",
                        time_quotes=[],
                        wavelengths=None,
                        wavelength_quotes=[],
                        physical_observable="obs",
                        physobs_quotes=[],
                        general_quotes=[],
                        additional_comments=None,
                    )
                ],
            )
        ],
    )


class TestPipeline:
    def test_no_validators(self):
        """With no validators registered, returns input unchanged."""
        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=[]
        ):
            pipeline = StructureValidatorPipeline()
            s = _structured()
            result = pipeline.run(s, "markdown")
            assert result.structured is s
            assert result.total_issues_found == 0
            assert result.total_llm_calls == 0
            assert result.all_skipped is True

    def test_no_issues(self):
        """Validator that finds no issues → skipped."""

        class CleanValidator(BaseStructureValidator):
            def detect(self, structured, original_markdown):
                return []

            def fix(self, structured, issues, original_markdown):
                return structured

        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=["clean"]
        ), patch.object(
            StructureValidatorRegistry, "get", return_value=CleanValidator
        ):
            pipeline = StructureValidatorPipeline()
            result = pipeline.run(_structured(), "md")
            assert result.total_issues_found == 0
            assert result.total_llm_calls == 0
            assert result.all_skipped is True

    def test_issues_fixed_in_one_iteration(self):
        """Validator detects issue, fix resolves it, re-detect finds nothing."""
        detect_call_count = 0

        class FixableValidator(BaseStructureValidator):
            def detect(self, structured, original_markdown):
                nonlocal detect_call_count
                detect_call_count += 1
                if detect_call_count == 1:
                    return [
                        ValidationIssue(
                            field_path="instruments[0].data_collection_periods[0].time_range",
                            issue_type="missing_date",
                            description="no date",
                            current_value="no date",
                        )
                    ]
                return []

            def fix(self, structured, issues, original_markdown):
                patched = structured.model_copy(deep=True)
                patched.instruments[0].data_collection_periods[0].time_range = (
                    "2020-01-01"
                )
                return patched

        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=["fixable"]
        ), patch.object(
            StructureValidatorRegistry, "get", return_value=FixableValidator
        ):
            pipeline = StructureValidatorPipeline(
                llm_client=Mock(), llm_config=Mock()
            )
            result = pipeline.run(_structured(), "md")
            assert result.total_issues_found == 1
            assert result.total_issues_fixed == 1
            assert result.total_llm_calls == 1

    def test_unfixable_stops_retrying(self):
        """When same issues remain after fix, stops after 1 LLM call."""
        fix_call_count = 0

        class UnfixableValidator(BaseStructureValidator):
            def detect(self, structured, original_markdown):
                return [
                    ValidationIssue(
                        field_path="instruments[0].data_collection_periods[0].time_range",
                        issue_type="missing_date",
                        description="unfixable",
                        current_value="no date",
                    )
                ]

            def fix(self, structured, issues, original_markdown):
                nonlocal fix_call_count
                fix_call_count += 1
                return structured  # no changes

        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=["unfixable"]
        ), patch.object(
            StructureValidatorRegistry, "get", return_value=UnfixableValidator
        ):
            pipeline = StructureValidatorPipeline(
                llm_client=Mock(), llm_config=Mock()
            )
            result = pipeline.run(_structured(), "md")
            assert fix_call_count == 1  # Only 1 attempt, not 3
            assert result.total_llm_calls == 1
            assert result.total_issues_fixed == 0

    def test_fix_exception_stops_retrying(self):
        """If fix() raises, the pipeline stops retrying that validator."""

        class BrokenValidator(BaseStructureValidator):
            def detect(self, structured, original_markdown):
                return [
                    ValidationIssue(
                        field_path="x",
                        issue_type="test",
                        description="test",
                        current_value="v",
                    )
                ]

            def fix(self, structured, issues, original_markdown):
                raise RuntimeError("LLM call failed")

        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=["broken"]
        ), patch.object(
            StructureValidatorRegistry, "get", return_value=BrokenValidator
        ):
            pipeline = StructureValidatorPipeline(
                llm_client=Mock(), llm_config=Mock()
            )
            result = pipeline.run(_structured(), "md")
            assert result.total_issues_found == 1
            assert result.total_issues_fixed == 0

    def test_metrics_accumulated(self):
        """Verify total counts accumulate correctly."""
        detect_calls = 0

        class CountingValidator(BaseStructureValidator):
            def detect(self, structured, original_markdown):
                nonlocal detect_calls
                detect_calls += 1
                if detect_calls <= 1:
                    return [
                        ValidationIssue(
                            field_path="a", issue_type="t",
                            description="d", current_value="v",
                        ),
                        ValidationIssue(
                            field_path="b", issue_type="t",
                            description="d", current_value="v",
                        ),
                    ]
                # After fix, 1 remains
                return [
                    ValidationIssue(
                        field_path="b", issue_type="t",
                        description="d", current_value="v",
                    )
                ]

            def fix(self, structured, issues, original_markdown):
                return structured

        with patch.object(
            StructureValidatorRegistry, "list_ordered", return_value=["counting"]
        ), patch.object(
            StructureValidatorRegistry, "get", return_value=CountingValidator
        ):
            pipeline = StructureValidatorPipeline(
                llm_client=Mock(), llm_config=Mock()
            )
            result = pipeline.run(_structured(), "md")
            assert result.total_issues_found == 2
            assert result.total_llm_calls >= 1
