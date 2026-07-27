from pydantic import BaseModel, Field
from typing import List


class FieldPatch(BaseModel):
    """A single field-level fix."""

    field_path: str = Field(
        description=(
            "JSON path to the field, e.g. "
            "'instruments[2].data_collection_periods[0].time_range'"
        )
    )
    new_value: str = Field(description="The corrected value for this field")
    reasoning: str = Field(
        description="Brief explanation of how this value was determined from the document"
    )


class TimeRangeFixResponse(BaseModel):
    """LLM response for time_range fixes -- returns JSON patches, not full doc."""

    patches: List[FieldPatch] = Field(
        description="List of field patches. Empty list if nothing can be fixed."
    )
    unfixable_paths: List[str] = Field(
        default=[],
        description=(
            "Field paths that could not be resolved "
            "(e.g., lab experiments with no dates)"
        ),
    )
