"""
Quote categorization utilities for the paper data linking system.

This module provides functions to categorize support quotes based on their
parameter field which contains explicit parameter-specific information from
the structured analysis.
"""

from .models import QuoteCategory


def categorize_quote_from_parameter(quote_parameter: str) -> QuoteCategory:
    """
    Determine quote category based on the parameter field from SupportQuote.
    
    The parameter field contains explicit categorization:
    - "general" for instrument-level quotes
    - "Period Name:time" for time-specific quotes  
    - "Period Name:wavelength" for wavelength-specific quotes
    - "Period Name:physobs" for physical observable quotes
    - "Period Name:general" for general period quotes
    - Legacy period names for backward compatibility
    
    Args:
        quote_parameter: The 'parameter' field from SupportQuote
    
    Returns:
        QuoteCategory enum value
    """
    if not quote_parameter:
        return QuoteCategory.GENERAL
    
    param_lower = quote_parameter.lower().strip()
    
    # Direct mapping for instrument-level quotes
    if param_lower == 'general':
        return QuoteCategory.INSTRUMENT
    
    # Handle explicit parameter-specific categorization
    if ':' in param_lower:
        _, param_type = param_lower.split(':', 1)
        if param_type == 'time':
            return QuoteCategory.TIME_RANGE
        elif param_type == 'wavelength':
            return QuoteCategory.WAVELENGTH
        elif param_type == 'physobs':
            return QuoteCategory.PHYSICAL_OBSERVABLE
        elif param_type == 'general':
            return QuoteCategory.TIME_RANGE  # General period quotes are temporal
    
    # Legacy fallback for old data (pre-schema update)
    return QuoteCategory.TIME_RANGE


def create_categorized_quote_usage_links(dataset_usage, supporting_quotes):
    """
    Create QuoteUsageLink records with proper categorization based on quote parameters.
    
    Args:
        dataset_usage: DatasetUsage instance
        supporting_quotes: QuerySet of SupportQuote instances
    
    Returns:
        int: Number of QuoteUsageLink records created
    """
    from .models import QuoteUsageLink
    
    links_created = 0
    
    for quote in supporting_quotes:
        category = categorize_quote_from_parameter(quote.parameter)
        
        # Create the categorized link (avoid duplicates)
        QuoteUsageLink.objects.get_or_create(
            quote=quote,
            dataset_usage=dataset_usage,
            support_category=category,
            defaults={}
        )
        links_created += 1
    
    return links_created


def get_quote_category_display_info():
    """
    Get display information for quote categories.
    
    Returns:
        Dictionary with category info for UI display
    """
    return {
        QuoteCategory.INSTRUMENT: {
            'icon': '🔧',
            'color': 'blue',
            'description': 'Evidence about instrument identification or capabilities'
        },
        QuoteCategory.TIME_RANGE: {
            'icon': '⏰', 
            'color': 'green',
            'description': 'Evidence about time ranges, periods, or temporal aspects'
        },
        QuoteCategory.WAVELENGTH: {
            'icon': '🌊',
            'color': 'purple', 
            'description': 'Evidence about wavelengths, frequencies, or energy ranges'
        },
        QuoteCategory.PHYSICAL_OBSERVABLE: {
            'icon': '📊',
            'color': 'orange',
            'description': 'Evidence about physical quantities or observables measured'
        },
        QuoteCategory.GENERAL: {
            'icon': '📝',
            'color': 'gray',
            'description': 'General references or uncategorized evidence'
        }
    }