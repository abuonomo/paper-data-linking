# paper_data_linking/linkers/general/normalizers/quote_normalizer.py

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from paper_data_linking.processing.pdf_annotator import PDFAnnotator
try:
    from paper_data_linking.processing.pdf_text_search import PDFTextSearcher
except ImportError:
    PDFTextSearcher = None
from paper_data_linking.linkers.general.normalizers.base_normalizer import BaseNormalizer
from paper_data_linking.linkers.general.normalizers.normalizer_registry import NormalizerRegistry
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedQuote, NormalizedQuoteCollection

logger = logging.getLogger(__name__)


@NormalizerRegistry.register("quotes", version="1.0", data_sources=["vso", "cdaweb"])
class QuoteNormalizer(BaseNormalizer):
    """Normalizes supporting quotes by adding PDF location coordinates."""
    
    def __init__(self, llm_client=None):
        """Initialize quote normalizer."""
        # QuoteNormalizer doesn't use LLM client, but inherit signature for consistency
        super().__init__(llm_client)
    
    def normalize(self, context: NormalizationContext) -> NormalizedQuoteCollection:
        """
        Normalize quotes using direct field access with full type safety.
        
        This method processes each quote category explicitly using direct field access
        to the typed InternalDataCollectionPeriod, eliminating helper methods and
        providing maximum type safety and IDE support.
        
        Args:
            context: NormalizationContext with typed period_data
            
        Returns:
            NormalizedQuoteCollection with categorized and flattened quote data
        """
        normalized_by_category = {}
        original_by_category = {}
        
        # Process time quotes using direct field access
        if context.period_data.time_quotes:
            logger.info(f"QuoteNormalizer: Processing {len(context.period_data.time_quotes)} time quotes")
            normalized_by_category["time"] = self._normalize_quote_list(
                context.period_data.time_quotes,
                category="time",
                instrument_name=context.instrument_name,
                parameter=f"{context.period_name}:time",
                pdf_path=context.pdf_path
            )
            original_by_category["time"] = context.period_data.time_quotes
            
        # Process wavelength quotes using direct field access
        if context.period_data.wavelength_quotes:
            logger.info(f"QuoteNormalizer: Processing {len(context.period_data.wavelength_quotes)} wavelength quotes")
            normalized_by_category["wavelength"] = self._normalize_quote_list(
                context.period_data.wavelength_quotes,
                category="wavelength",
                instrument_name=context.instrument_name,
                parameter=f"{context.period_name}:wavelength",
                pdf_path=context.pdf_path
            )
            original_by_category["wavelength"] = context.period_data.wavelength_quotes
            
        # Process physobs quotes using direct field access
        if context.period_data.physobs_quotes:
            logger.info(f"QuoteNormalizer: Processing {len(context.period_data.physobs_quotes)} physobs quotes")
            normalized_by_category["physobs"] = self._normalize_quote_list(
                context.period_data.physobs_quotes,
                category="physobs",
                instrument_name=context.instrument_name,
                parameter=f"{context.period_name}:physobs",
                pdf_path=context.pdf_path
            )
            original_by_category["physobs"] = context.period_data.physobs_quotes
            
        # Process general quotes using direct field access
        if context.period_data.general_quotes:
            logger.info(f"QuoteNormalizer: Processing {len(context.period_data.general_quotes)} general quotes")
            normalized_by_category["general"] = self._normalize_quote_list(
                context.period_data.general_quotes,
                category="general",
                instrument_name=context.instrument_name,
                parameter=f"{context.period_name}:general",
                pdf_path=context.pdf_path
            )
            original_by_category["general"] = context.period_data.general_quotes
        
        # Log processing summary
        total_categories = len(original_by_category)
        total_quotes = sum(len(quotes) for quotes in original_by_category.values())
        if total_categories == 0:
            logger.info("QuoteNormalizer: No quotes found in any category")
        else:
            logger.info(f"QuoteNormalizer: Processed {total_quotes} quotes across {total_categories} categories: {list(original_by_category.keys())}")
        
        # Create flattened versions for backward compatibility
        all_original_quotes = []
        all_normalized_quotes = []
        
        # Flatten original quotes
        for category_quotes in original_by_category.values():
            all_original_quotes.extend(category_quotes)
            
        # Flatten normalized quotes  
        for category_quotes in normalized_by_category.values():
            all_normalized_quotes.extend(category_quotes)
        
        return NormalizedQuoteCollection(
            original=original_by_category,
            normalized=normalized_by_category,
            original_flattened=all_original_quotes,
            normalized_flattened=all_normalized_quotes
        )
    
    def _normalize_quote_list(self, raw_quotes: List[str], category: str,
                             instrument_name: str, parameter: str, pdf_path: Optional[str]) -> List[NormalizedQuote]:
        """Normalize a list of quotes with PDF coordinate extraction."""
        if not raw_quotes:
            return []
        
        # If we have PDF content (bytes) or a valid file path, find coordinates
        has_pdf = pdf_path is not None and (
            isinstance(pdf_path, bytes) or
            (isinstance(pdf_path, str) and Path(pdf_path).exists())
        )
        if has_pdf:
            logger.debug(f"Finding coordinates for {len(raw_quotes)} quotes (parameter: {parameter})")
            
            # Prepare quotes for PDFAnnotator
            quote_objects = [
                {
                    'quote': quote_text,
                    'instrument': instrument_name,
                    'parameter': parameter
                }
                for quote_text in raw_quotes
                if isinstance(quote_text, str)
            ]
            
            try:
                processed_quotes = None
                # Prefer the fast text searcher if available
                if PDFTextSearcher is not None:
                    try:
                        searcher = PDFTextSearcher(pdf_path)
                        # Use the fast method for better performance (change to 'ir' for higher accuracy)
                        method = 'original'  # Options: 'original', 'ir', 'legacy'
                        
                        if method == 'original':
                            processed_quotes = searcher.find_quotes_original(quote_objects, debug=False)
                        elif method == 'ir':
                            processed_quotes = searcher.find_quotes_ir(quote_objects, debug=False)
                        else:  # legacy
                            processed_quotes = searcher.find_quotes(quote_objects)
                        searcher.close()
                    except Exception as e:
                        logger.warning(f"PDFTextSearcher {method} method failed, trying fallback methods: {e}")
                        try:
                            searcher = PDFTextSearcher(pdf_path)
                            # Try original method as fallback
                            processed_quotes = searcher.find_quotes_original(quote_objects)
                            searcher.close()
                        except Exception as e2:
                            logger.warning(f"PDFTextSearcher fast fallback also failed, using PDFAnnotator: {e2}")
                            processed_quotes = None
                if processed_quotes is None:
                    # Fallback to existing annotator (may mutate PDF, slower)
                    pdf_annotator = PDFAnnotator(pdf_path)
                    processed_quotes = pdf_annotator.process_quotes(quote_objects)
                
                # Convert to normalized format using Pydantic models
                normalized_quotes = []
                for processed_quote in processed_quotes:
                    location_data = processed_quote.get('location')
                    
                    # Create coordinate box if location data exists
                    coordinates = None
                    if location_data:
                        from paper_data_linking.linkers.general.normalizers.normalizer import CoordinateBox
                        coordinates = CoordinateBox(
                            x0=location_data['x0'],
                            y0=location_data['y0'],
                            x1=location_data['x1'],
                            y1=location_data['y1']
                        )
                        logger.debug(f"Found coordinates for {parameter} quote: {processed_quote['quote'][:50]}...")
                    else:
                        logger.debug(f"No coordinates found for {parameter} quote: {processed_quote['quote'][:50]}...")
                    
                    # Create typed NormalizedQuote object
                    normalized_quote = NormalizedQuote(
                        text=processed_quote['quote'],
                        location=location_data,
                        page_number=location_data.get('page_number') if location_data else None,
                        coordinates=coordinates,
                        category=category
                    )
                    
                    normalized_quotes.append(normalized_quote)
                
                found_count = sum(1 for q in normalized_quotes if q.location)
                logger.debug(f"Found coordinates for {found_count}/{len(raw_quotes)} {parameter} quotes")
                
                # Clean up PDF resources
                # Close any PDF handles we created
                try:
                    if 'pdf_annotator' in locals() and hasattr(pdf_annotator, 'pdf_document'):
                        pdf_annotator.pdf_document.close()
                except Exception:
                    pass
                
                return normalized_quotes
                
            except Exception as e:
                logger.error(f"QuoteNormalizer: Error processing {parameter} quotes with PDF: {e}")
                # Fallback to basic normalization without coordinates
                return self._create_basic_normalized_quotes(raw_quotes, category)
        else:
            # No PDF available, create basic normalized structure
            return self._create_basic_normalized_quotes(raw_quotes, category)
    
    def _create_basic_normalized_quotes(self, raw_quotes: List[str], category: str = "general") -> List[NormalizedQuote]:
        """Create basic normalized quote structure without coordinates.
        
        Args:
            raw_quotes: List of raw quote strings
            category: Quote category (time, wavelength, physobs, general)
            
        Returns:
            List of NormalizedQuote objects without coordinate data
        """
        return [
            NormalizedQuote(
                text=quote_text,
                location=None,
                page_number=None,
                coordinates=None,
                category=category
            )
            for quote_text in raw_quotes
            if isinstance(quote_text, str)
        ]
    
