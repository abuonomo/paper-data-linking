from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class NormalizedTimeRange(BaseModel):
    start_datetime: Optional[str] = Field(description="ISO 8601 instant or null")
    end_datetime: Optional[str] = Field(description="ISO 8601 instant or null")
    precision: Optional[str] = Field(description="year|month|day|hour|minute|second")
    is_approximate: bool
    original_text: str


# Placeholders for other call types (document shape as it stabilizes)
class NormalizedWavelength(BaseModel):
    # Example keys; adjust when schema is defined
    start: Optional[float] = None
    end: Optional[float] = None
    unit: Optional[str] = None
    original_text: str

