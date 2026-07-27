# paper_data_linking/linkers/general/normalizers/schema_conversion.py

"""
Conversion utilities between API schemas and internal models.

This module provides type-safe conversion functions to transform data from the
OpenAI API response format (structured_instruments.py) to the internal processing
format (normalization_models.py).

Key principles:
- Lightweight, direct field mapping
- Full type safety with Pydantic validation
- Clear error handling for malformed data
- Preserve all data integrity during conversion
"""

import logging
from typing import Dict, Any

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    StructuredInstrumentDetails,
    Instrument,
    DataCollectionPeriod
)
from paper_data_linking.linkers.general.normalizers.normalization_models import (
    InternalStructuredInstruments,
    InternalInstrument,
    InternalDataCollectionPeriod
)

logger = logging.getLogger(__name__)


def api_to_internal_period(api_period: DataCollectionPeriod) -> InternalDataCollectionPeriod:
    """
    Convert API DataCollectionPeriod to internal representation.
    
    Args:
        api_period: DataCollectionPeriod from OpenAI API response
        
    Returns:
        InternalDataCollectionPeriod with full type safety and validation
        
    Raises:
        ValidationError: If the API data doesn't match expected schema
    """
    logger.debug(f"Converting API period: {api_period.period_name}")
    
    # Direct field mapping with Pydantic validation
    return InternalDataCollectionPeriod(
        period_name=api_period.period_name,
        time_range=api_period.time_range,
        time_quotes=api_period.time_quotes,
        wavelengths=api_period.wavelengths,
        wavelength_quotes=api_period.wavelength_quotes,
        physical_observable=api_period.physical_observable,
        physobs_quotes=api_period.physobs_quotes,
        general_quotes=api_period.general_quotes,
        additional_comments=api_period.additional_comments,
        # CDAWeb-specific fields default to None (will be populated by future CDAWeb normalizers)
        cadence=None,
        instrument_type=None
    )


def api_to_internal_instrument(api_instrument: Instrument) -> InternalInstrument:
    """
    Convert API Instrument to internal representation.
    
    Args:
        api_instrument: Instrument from OpenAI API response
        
    Returns:
        InternalInstrument with full type safety and validation
        
    Raises:
        ValidationError: If the API data doesn't match expected schema
    """
    logger.debug(f"Converting API instrument: {api_instrument.name}")
    
    # Convert all data collection periods
    internal_periods = [
        api_to_internal_period(period) 
        for period in api_instrument.data_collection_periods
    ]
    
    return InternalInstrument(
        name=api_instrument.name,
        general_comments=api_instrument.general_comments,
        general_quotes=api_instrument.general_quotes,
        data_collection_periods=internal_periods
    )


def api_to_internal_instruments(api_data: StructuredInstrumentDetails) -> InternalStructuredInstruments:
    """
    Convert complete API response to internal representation.
    
    This is the main conversion function that transforms the entire structured
    instrument data from OpenAI API format to the internal processing format.
    
    Args:
        api_data: Complete StructuredInstrumentDetails from OpenAI API
        
    Returns:
        InternalStructuredInstruments with full type safety and validation
        
    Raises:
        ValidationError: If the API data doesn't match expected schema
    """
    logger.info(f"Converting API data with {len(api_data.instruments)} instruments")
    
    # Convert all instruments
    internal_instruments = [
        api_to_internal_instrument(instrument)
        for instrument in api_data.instruments
    ]
    
    logger.info(f"Successfully converted {len(internal_instruments)} instruments to internal format")
    
    return InternalStructuredInstruments(
        paper_summary=api_data.paper_summary,
        instruments=internal_instruments
    )


def dict_to_internal_instruments(raw_dict: Dict[str, Any]) -> InternalStructuredInstruments:
    """
    Convert raw dictionary (from JSON or similar) to internal representation.
    
    This function first validates the raw data against the API schema, then
    converts to internal representation. This ensures that all data meets
    the API contract before entering the internal processing pipeline.
    
    Args:
        raw_dict: Raw dictionary data (e.g., from JSON deserialization)
        
    Returns:
        InternalStructuredInstruments with full validation
        
    Raises:
        ValidationError: If the raw data doesn't match API schema
    """
    logger.debug("Converting raw dictionary to internal representation")
    
    # First validate against API schema
    api_data = StructuredInstrumentDetails(**raw_dict)
    
    # Then convert to internal representation
    return api_to_internal_instruments(api_data)


# Convenience functions for common use cases

def validate_and_convert(raw_data: Dict[str, Any]) -> InternalStructuredInstruments:
    """
    One-step validation and conversion from raw data to internal representation.
    
    This is the recommended function for most use cases where you have raw
    structured instrument data and want to convert it for internal processing.
    
    Args:
        raw_data: Raw structured instrument data
        
    Returns:
        Validated and converted internal representation
    """
    return dict_to_internal_instruments(raw_data)


def conversion_summary(internal_data: InternalStructuredInstruments) -> Dict[str, Any]:
    """
    Generate a summary of the conversion process for logging/debugging.
    
    Args:
        internal_data: Converted internal representation
        
    Returns:
        Summary dictionary with conversion statistics
    """
    total_periods = sum(len(inst.data_collection_periods) for inst in internal_data.instruments)
    total_quotes = sum(
        len(period.time_quotes) + len(period.wavelength_quotes) + 
        len(period.physobs_quotes) + len(period.general_quotes)
        for inst in internal_data.instruments
        for period in inst.data_collection_periods
    )
    
    return {
        "instruments_converted": len(internal_data.instruments),
        "total_periods": total_periods,
        "total_quotes": total_quotes,
        "has_paper_summary": bool(internal_data.paper_summary),
        "instrument_names": [inst.name for inst in internal_data.instruments]
    }