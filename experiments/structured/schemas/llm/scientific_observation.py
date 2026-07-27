from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

# New helper models for encapsulating values with their supporting quotes
class QuotedStr(BaseModel):
    value: str = Field(..., description="The parameter value.")
    supporting_quote: str = Field(..., description="A complete supporting quote DIRECTLY from the paper providing context for the value.")

class QuotedList(BaseModel):
    values: List[str] = Field(..., description="The list of values.")
    supporting_quote: str = Field(..., description="A complete supporting quote DIRECTLY from the paper providing context for the list of values.")

class Summary(BaseModel):
    content_summary: str = Field(
        ...,
        description="A detailed data-centric summary of the paper's content, outlining ALL missions and instruments used and how they were used. Must exhaustively contain ALL missions and instruments used."
    )

class DataCollectionPeriod(BaseModel):
    description: str = Field(
        ...,
        description="A brief description of what was observed or the specific focus during this data collection period."
    )
    start_time: QuotedStr = Field(
        ...,
        description="The start time (and date, if applicable) for this data collection period along with a supporting quote."
    )
    end_time: Optional[QuotedStr] = Field(
        None,
        description="The end time (and date, if applicable) for this data collection period along with a supporting quote."
    )
    wavelengths: QuotedList = Field(
        ...,
        description="List of wavelengths used during this data collection period along with a supporting quote."
    )
    physical_observable: QuotedStr = Field(
        ...,
        description="The physical observable measured during this data collection period along with a supporting quote."
    )
    additional_comments: str = Field(
        ...,
        description="Any additional comments relevant to this data collection period."
    )

class InstrumentUsage(str, Enum):
    primary = "primary"
    contextual = "contextual"
    referenced = "referenced"

class InstrumentationDetails(BaseModel):
    instrument_name: str = Field(
        ...,
        description="The name of the instrument."
    )
    spacecraft: str = Field(
        ...,
        description="The spacecraft or facility associated with this instrument."
    )
    general_comments: QuotedStr = Field(
        ...,
        description="General comments describing the role and capabilities of the instrument along with a supporting quote."
    )
    detectors: Optional[QuotedList] = Field(
        None,
        description="List of detectors associated with the instrument, if applicable, along with a supporting quote."
    )
    data_collection_periods: List[DataCollectionPeriod] = Field(
        ...,
        description="A list of data collection periods for this instrument, including all relevant details."
    )
    usage_category: InstrumentUsage = Field(
        ...,
        description=(
            "The usage category of this instrument in the study: "
            "'primary' if the data is actively analyzed and crucial to the study's findings, "
            "'contextual' if the data is included to provide supporting information, "
            "'referenced' if the instrument is only mentioned without showing or using its data in the study."
        )
    )

class ScientificObservationForm(BaseModel):
    title: str = Field(
        ...,
        description="The title of the study or observation form."
    )
    summary: Summary
    instrumentation_details: List[InstrumentationDetails] = Field(
        ...,
        description="Detailed information on all instruments used or referenced in the study."
    )
