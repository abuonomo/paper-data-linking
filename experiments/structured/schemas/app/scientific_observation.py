from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class PDFQuoteLocation(BaseModel):
    page_number: int = Field(..., description="Page number where the quote was found.")
    x0: float = Field(..., description="x-coordinate of the upper-left corner of the block.")
    y0: float = Field(..., description="y-coordinate of the upper-left corner of the block.")
    x1: float = Field(..., description="x-coordinate of the lower-right corner of the block.")
    y1: float = Field(..., description="y-coordinate of the lower-right corner of the block.")
    vertical_middle: float = Field(..., description="Vertical midpoint of the block.")
    excerpt_image: Optional[str] = Field(None, description="Path to the image excerpt of the match.")


# Location metadata for quotes
class QuoteLocation(BaseModel):
    start: int = Field(..., description="The start index of the quote within the text.")
    end: int = Field(..., description="The end index of the quote within the text.")
    score: int = Field(..., description="The fuzzy matching score for the quote.")
    excerpt: str = Field(..., description="The actual text excerpt that was matched.")


# Enhanced models with location metadata
class AppQuotedStr(BaseModel):
    value: str = Field(..., description="The parameter value.")
    supporting_quote: str = Field(...,
                                  description="A complete supporting quote from the paper providing context for the value.")
    location: Optional[QuoteLocation] = Field(None,
                                              description="Location metadata for this quote in the original text.")
    pdf_locations: Optional[List[PDFQuoteLocation]] = Field(default_factory=list,
                                                  description="List of PDF block locations where the quote appears.")


class AppQuotedList(BaseModel):
    values: List[str] = Field(..., description="The list of values.")
    supporting_quote: str = Field(...,
                                  description="A complete supporting quote from the paper providing context for the list of values.")
    location: Optional[QuoteLocation] = Field(None,
                                              description="Location metadata for this quote in the original text.")
    pdf_locations: Optional[List[PDFQuoteLocation]] = Field(default_factory=list,
                                                  description="List of PDF block locations where the quote appears.")


class AppSummary(BaseModel):
    content_summary: str = Field(
        ...,
        description="A detailed data-centric summary of the paper's content, outlining all missions and instruments used."
    )


class AppDataCollectionPeriod(BaseModel):
    description: str = Field(
        ...,
        description="A brief description of what was observed during this data collection period."
    )
    start_time: AppQuotedStr = Field(
        ...,
        description="The start time for this data collection period with location metadata."
    )
    end_time: Optional[AppQuotedStr] = Field(
        None,
        description="The end time for this data collection period with location metadata."
    )
    wavelengths: AppQuotedList = Field(
        ...,
        description="List of wavelengths used during this data collection period with location metadata."
    )
    physical_observable: AppQuotedStr = Field(
        ...,
        description="The physical observable measured during this data collection period with location metadata."
    )
    additional_comments: str = Field(
        ...,
        description="Any additional comments relevant to this data collection period."
    )


class AppInstrumentUsage(str, Enum):
    primary = "primary"
    contextual = "contextual"
    referenced = "referenced"


class AppInstrumentationDetails(BaseModel):
    instrument_name: str = Field(
        ...,
        description="The name of the instrument."
    )
    spacecraft: str = Field(
        ...,
        description="The spacecraft or facility associated with this instrument."
    )
    general_comments: AppQuotedStr = Field(
        ...,
        description="General comments describing the role and capabilities of the instrument with location metadata."
    )
    detectors: Optional[AppQuotedList] = Field(
        None,
        description="List of detectors associated with the instrument with location metadata."
    )
    data_collection_periods: List[AppDataCollectionPeriod] = Field(
        ...,
        description="A list of data collection periods for this instrument, including all relevant details."
    )
    usage_category: AppInstrumentUsage = Field(
        ...,
        description="The usage category of this instrument in the study."
    )

    # Additional application-specific fields
    normalized_name: Optional[str] = Field(
        None,
        description="Normalized instrument name for database consistency."
    )
    instrument_id: Optional[str] = Field(
        None,
        description="Reference ID to a canonical instrument database entry if available."
    )


class AppScientificObservationForm(BaseModel):
    title: str = Field(
        ...,
        description="The title of the study or observation form."
    )
    summary: AppSummary
    instrumentation_details: List[AppInstrumentationDetails] = Field(
        ...,
        description="Detailed information on all instruments used or referenced in the study, with location metadata."
    )

    # Additional application-specific fields
    paper_id: Optional[str] = Field(
        None,
        description="Reference to the associated paper in the database."
    )
    bibcode: Optional[str] = Field(
        None,
        description="Bibliographic code of the paper."
    )
    extraction_timestamp: Optional[str] = Field(
        None,
        description="When this data was extracted from the paper."
    )
    processed_by: Optional[str] = Field(
        None,
        description="Identifier for the system or user who processed this data."
    )