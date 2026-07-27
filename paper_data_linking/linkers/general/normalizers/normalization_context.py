# paper_data_linking/linkers/general/normalizers/normalization_context.py

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Union

from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod


class GroundingResult(BaseModel):
    """Type-safe representation of instrument grounding results."""
    matched_instrument_code: Optional[str] = None
    matched_mission_code: Optional[str] = None
    matched_instrument_name: Optional[str] = None
    matched_mission_name: Optional[str] = None
    data_system: Optional[str] = None
    reasoning: str


class NormalizationContext(BaseModel):
    """
    Complete context object passed to all normalizers with deep type safety.
    
    This provides fully typed access to all data that normalizers need,
    with Pydantic validation throughout the entire data structure.
    
    Key improvements over previous version:
    - Uses typed InternalDataCollectionPeriod instead of Dict[str, Any]
    - Direct field access with full IDE support and type checking
    - No helper methods needed - all data is directly accessible
    - Extensible for data source-specific fields
    
    IMPORTANT: This uses internal models separate from the OpenAI API schemas
    in structured_instruments.py, which are specifically for LLM communication.
    """
    
    # Fully typed period data with deep Pydantic validation
    period_data: InternalDataCollectionPeriod = Field(
        description="Typed period data from internal normalization models"
    )
    
    # Instrument context
    instrument_code: Optional[str] = Field(
        default=None,
        description="Matched instrument code from grounding (None for mission-only matches)"
    )
    instrument_name: str = Field(
        description="Original instrument name from paper"
    )
    instrument_general_comments: Optional[str] = Field(
        default=None,
        description="Instrument-level general comments from the paper"
    )
    all_periods_data: Optional[List[InternalDataCollectionPeriod]] = Field(
        default=None,
        description="All data collection periods for this instrument (for cross-period analysis)"
    )
    data_system: str = Field(
        description="Data source system (e.g., 'VSO', 'CDAWeb')"
    )
    
    # Period context
    period_name: str = Field(
        description="Name of the data collection period"
    )
    
    # Full grounding result for advanced normalizers
    grounding_result: GroundingResult = Field(
        description="Complete instrument grounding result"
    )
    
    # Optional PDF content for quote processing (path, bytes, or file-like)
    pdf_path: Optional[Union[str, bytes]] = Field(
        default=None,
        description="PDF content for coordinate extraction (path string or bytes)"
    )

    # HelioKnow phenomenon vocabulary for phenomenon matching
    phenomena: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of {id, name, iri} dicts from the Phenomenon table, for the phenomenon normalizer"
    )

    model_config = {"arbitrary_types_allowed": True}
    
    # Direct typed access patterns (no helper methods needed):
    # - context.period_data.time_range (Optional[str])
    # - context.period_data.time_quotes (List[str])
    # - context.period_data.wavelengths (Optional[str]) 
    # - context.period_data.wavelength_quotes (List[str])
    # - context.period_data.physical_observable (Optional[str])
    # - context.period_data.physobs_quotes (List[str])
    # - context.period_data.general_quotes (List[str])
    # - context.period_data.additional_comments (Optional[str])
    # - context.period_data.cadence (Optional[str]) - CDAWeb future
    # - context.period_data.instrument_type (Optional[str]) - CDAWeb future