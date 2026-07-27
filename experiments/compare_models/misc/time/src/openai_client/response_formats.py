from pydantic import BaseModel, Field
from typing import Optional

class NormalizedTimeRange(BaseModel):
    """Pydantic model for structured time range output"""
    start_datetime: Optional[str] = Field(description="ISO format start datetime")
    end_datetime: Optional[str] = Field(description="ISO format end datetime") 
    precision: str = Field(description="year|month|day|hour|minute|second")
    is_approximate: bool = Field(description="Whether the time is approximate")
    original_text: str = Field(description="Original time range text")
