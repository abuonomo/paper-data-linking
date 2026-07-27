from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class NormalizedTimeRange(BaseModel):
    start_datetime: Optional[str] = Field(description="ISO format start datetime")
    end_datetime: Optional[str] = Field(description="ISO format end datetime")
    precision: str = Field(description="year|month|day|hour|minute")
    is_approximate: bool = Field(description="Whether the time is approximate")
    original_text: str = Field(description="Original time range text")


class WavelengthRange(BaseModel):
    """A single wavelength value or range with its unit.

    For discrete values, min and max are the same.
    For ranges, min < max.
    Each range carries its own unit to allow mixed units.
    """
    min: float = Field(description="Minimum wavelength value (or exact value for discrete)")
    max: float = Field(description="Maximum wavelength value (same as min for discrete)")
    unit: str = Field(description="angstrom|nm|keV|kHz|MHz|GHz|Hz")


class NormalizedWavelength(BaseModel):
    """Normalized wavelength representation supporting discrete values and multiple ranges.

    Examples:
        Discrete values: [{"min": 211, "max": 211, "unit": "angstrom"}, {"min": 193, "max": 193, "unit": "angstrom"}]
        Single range: [{"min": 1, "max": 8, "unit": "angstrom"}]
        Multiple ranges: [{"min": 5, "max": 10, "unit": "keV"}, {"min": 25, "max": 50, "unit": "keV"}]
        Mixed units (if needed): [{"min": 1, "max": 8, "unit": "angstrom"}, {"min": 0.1, "max": 1, "unit": "keV"}]
        Not applicable: ranges=[]
    """
    ranges: List[WavelengthRange] = Field(description="List of wavelength ranges, each with its own unit")
    original_text: str = Field(description="Original wavelength text")


class NormalizedObservable(BaseModel):
    physical_observable: Optional[str] = Field(description="Chosen observable or None if no match")
    original_text: Optional[str] = Field(default=None, description="Original context text used for selection")


class NormalizedInstrument(BaseModel):
    canonical_name: str = Field(description="Standardized instrument name")
    mission: Optional[str] = Field(description="Mission/observatory name")
    instrument_type: str = Field(description="Type of instrument")


class CoordinateBox(BaseModel):
    """PDF coordinate box for quote location."""
    x0: float = Field(description="Left coordinate")
    y0: float = Field(description="Bottom coordinate")  
    x1: float = Field(description="Right coordinate")
    y1: float = Field(description="Top coordinate")


class NormalizedQuote(BaseModel):
    """
    Rich quote representation with full metadata.
    
    This model represents a normalized quote with location information,
    category classification, and optional confidence scoring.
    """
    text: str = Field(description="The quote text")
    location: Optional[Dict[str, Any]] = Field(
        default=None,
        description="PDF location metadata from PDFAnnotator"
    )
    page_number: Optional[int] = Field(
        default=None,
        description="Page number where quote was found"
    )
    coordinates: Optional[CoordinateBox] = Field(
        default=None,
        description="PDF coordinate box for the quote"
    )
    category: str = Field(
        description="Quote category (time, wavelength, physobs, general)"
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score for quote extraction (0.0-1.0)"
    )


class NormalizedQuoteCollection(BaseModel):
    """
    Complete quote normalization result with categorized and flattened views.
    
    This model provides both the new categorized structure for advanced processing
    and backward compatibility with existing flattened quote processing.
    """
    # New categorized structure
    original: Dict[str, List[str]] = Field(
        description="Original quotes organized by category"
    )
    normalized: Dict[str, List[NormalizedQuote]] = Field(
        description="Normalized quotes organized by category"
    )
    
    # Backward compatibility
    original_flattened: List[str] = Field(
        description="All original quotes in a single list (backward compatibility)"
    )
    normalized_flattened: List[NormalizedQuote] = Field(
        description="All normalized quotes in a single list (backward compatibility)"
    )


class NormalizedDetector(BaseModel):
    """
    Normalized detector selection for a given instrument/period.
    
    The selected detector must be one of the valid options for the instrument
    as defined by the data source metadata (e.g., VSO metadata).
    """
    detector: Optional[str] = Field(description="Chosen detector name or None if no match")
    original_text: Optional[str] = Field(default=None, description="Original context text used for selection")

class NormalizedCadence(BaseModel):
    """
    Normalized cadences in ISO 8601 format for a give instrument/period
    """
    cadences: Optional[List[str]] = Field(description="List of normalized cadences or None if no cadences found")
    original_text: Optional[str] = Field(default=None, description="Original context text used for selection")
