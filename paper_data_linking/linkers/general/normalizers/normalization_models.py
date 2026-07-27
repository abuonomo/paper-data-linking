# paper_data_linking/linkers/general/normalizers/normalization_models.py

"""
Internal Pydantic models for normalization pipeline.

These models are separate from the OpenAI API schemas in structured_instruments.py
and are optimized for internal processing with rich typing, validation, and extensibility.

Key differences from API schemas:
- Full type safety with Optional types where appropriate
- Extensible for data source-specific fields (VSO, CDAWeb, etc.)
- Integration-optimized with direct field access (no computed properties)
- Rich validation and error handling
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class InternalDataCollectionPeriod(BaseModel):
    """
    Internal representation of a data collection period with rich typing and extensibility.
    
    This model provides full type safety for the normalization pipeline while being
    extensible for data source-specific fields like CDAWeb's cadence or instrument_type.
    
    Design principles:
    - Direct field access only (no computed properties or helper methods)
    - Optional types where data might be missing
    - Default factories for list fields to prevent mutation issues
    - Extensible for future data source requirements
    """
    
    period_name: str = Field(
        description="Name or description of this data collection period"
    )
    
    # Core temporal information
    time_range: Optional[str] = Field(
        default=None,
        description="Time range for the observations (e.g., '1996-2007', 'January 2020')"
    )
    time_quotes: List[str] = Field(
        default_factory=list,
        description="Quotes specifically supporting the time range information"
    )
    
    # Wavelength information (VSO-specific)
    wavelengths: Optional[str] = Field(
        default=None,
        description="Wavelength range or specific wavelengths observed"
    )
    wavelength_quotes: List[str] = Field(
        default_factory=list,
        description="Quotes specifically supporting wavelength information"
    )
    
    # Physical observable information
    physical_observable: Optional[str] = Field(
        default=None,
        description="What physical quantities or phenomena were observed"
    )
    physobs_quotes: List[str] = Field(
        default_factory=list,
        description="Quotes specifically supporting physical observable information"
    )
    
    # General information
    general_quotes: List[str] = Field(
        default_factory=list,
        description="General quotes about this data collection period"
    )
    additional_comments: Optional[str] = Field(
        default=None,
        description="Any additional relevant information"
    )
    
    # Future CDAWeb-specific fields
    # These will be populated when CDAWeb normalization is implemented
    cadence: Optional[str] = Field(
        default=None,
        description="Data cadence/sampling rate (CDAWeb-specific)"
    )
    instrument_type: Optional[str] = Field(
        default=None,
        description="Type of instrument (CDAWeb-specific)"
    )
    
    # Future extensibility for other data sources
    # Can add fields like:
    # - energy_range: Optional[str] = None  # For particle data
    # - spatial_resolution: Optional[str] = None  # For imaging data
    # - spectral_resolution: Optional[str] = None  # For spectroscopic data


class InternalInstrument(BaseModel):
    """
    Internal representation of a scientific instrument.
    
    Provides full type safety and validation for instrument data used throughout
    the normalization pipeline.
    """
    
    name: str = Field(
        description="Full name of the instrument or observatory"
    )
    general_comments: str = Field(
        description="General description of the instrument's role and capabilities"
    )
    general_quotes: List[str] = Field(
        default_factory=list,
        description="Quotes supporting the instrument identification and general capabilities"
    )
    data_collection_periods: List[InternalDataCollectionPeriod] = Field(
        description="Specific observation periods and their details"
    )


class InternalStructuredInstruments(BaseModel):
    """
    Complete internal representation of instrumentation details from a scientific paper.
    
    This is the top-level model for the internal normalization pipeline, providing
    full type safety and validation for all structured instrument data.
    """
    
    paper_summary: str = Field(
        description="Brief summary of the paper's content and objectives"
    )
    instruments: List[InternalInstrument] = Field(
        description="List of all instruments/observatories used in the study"
    )
    
    # Future metadata fields can be added here
    # extraction_metadata: Optional[ExtractionMetadata] = None
    # validation_results: Optional[ValidationResults] = None