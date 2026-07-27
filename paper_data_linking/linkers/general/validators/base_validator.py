from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.schemas.structured_instruments import (
    StructuredInstrumentDetails,
)


@dataclass
class ValidationIssue:
    """A single detected issue in the structured data."""

    field_path: str  # e.g. "instruments[2].data_collection_periods[0].time_range"
    issue_type: str  # e.g. "descriptive_time_range"
    description: str  # Human-readable description
    current_value: Any  # The current field value
    severity: str = "warning"  # "warning" or "error"


@dataclass
class ValidationResult:
    """Result from running a single validator."""

    validator_name: str
    issues_found: int = 0
    issues_fixed: int = 0
    llm_calls_made: int = 0
    skipped: bool = False  # True when no issues detected (fast path)


class BaseStructureValidator(ABC):
    """
    Abstract base for structure-level validators.

    Validators operate on the FULL StructuredInstrumentDetails plus the
    original markdown text. They detect issues and optionally fix them
    via targeted LLM calls.
    """

    def __init__(
        self,
        llm_client: Optional[LiteLLMClient] = None,
        llm_config=None,
    ):
        self.llm_client = llm_client
        self.llm_config = llm_config

    @abstractmethod
    def detect(
        self,
        structured: StructuredInstrumentDetails,
        original_markdown: str,
    ) -> List[ValidationIssue]:
        """Detect issues. Must be cheap / deterministic (no LLM)."""
        ...

    @abstractmethod
    def fix(
        self,
        structured: StructuredInstrumentDetails,
        issues: List[ValidationIssue],
        original_markdown: str,
    ) -> StructuredInstrumentDetails:
        """Fix detected issues. May use targeted LLM calls."""
        ...
