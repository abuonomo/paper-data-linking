from pydantic import BaseModel, Field
from typing import Any, Dict, List, Union


class DataCollectionPeriod(BaseModel):
    """Represents a specific data collection period for an instrument"""
    period_name: str = Field(description="Name or description of this data collection period")
    time_range: str = Field(description="Time range for the observations (e.g., '1996-2007', 'January 2020')")
    time_quotes: List[str] = Field(default=[], description="Quotes specifically supporting the time range information")
    wavelengths: Union[str, None] = Field(default=None, description="Wavelength range or specific wavelengths observed")
    wavelength_quotes: List[str] = Field(default=[], description="Quotes specifically supporting wavelength information")
    physical_observable: str = Field(description="What physical quantities or phenomena were observed")
    physobs_quotes: List[str] = Field(default=[], description="Quotes specifically supporting physical observable information")
    general_quotes: List[str] = Field(default=[], description="General quotes about this data collection period")
    additional_comments: Union[str, None] = Field(default=None, description="Any additional relevant information")


class Instrument(BaseModel):
    """Represents a scientific instrument used in the study"""
    name: str = Field(description="Full name of the instrument or observatory")
    general_comments: str = Field(description="General description of the instrument's role and capabilities")
    general_quotes: List[str] = Field(default=[], description="Quotes supporting the instrument identification and general capabilities")
    data_collection_periods: List[DataCollectionPeriod] = Field(description="Specific observation periods and their details")


class StructuredInstrumentDetails(BaseModel):
    """Complete structured representation of instrumentation details from a scientific paper"""
    paper_summary: str = Field(description="Brief summary of the paper's content and objectives")
    instruments: List[Instrument] = Field(description="List of all instruments/observatories used in the study")
    # metadata: Dict[str, Any] = Field(description="Additional metadata about the analysis")