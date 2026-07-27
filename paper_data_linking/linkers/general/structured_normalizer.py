# paper_data_linking/linkers/general/structured_normalizer.py

import warnings
import logging
from typing import Optional, List, Dict
from paper_data_linking.config.paths import DATA_ASSETS_DIR
from paper_data_linking.clients.litellm_client import LiteLLMClient
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.catalogue_models import CatalogueEntry
from paper_data_linking.linkers.general.normalizers import NormalizerRegistry, QuoteNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.schema_conversion import dict_to_internal_instruments
from paper_data_linking.pipeline_context import node_stage, current_pipeline_node


logger = logging.getLogger(__name__)


class StructuredNormalizer:
    """
    Delegates each normalization subtask to specialized classes selected via registry:
      - Instrument grounding → already in InstrumentGrounder
      - Time‐range parsing → TimeRangeNormalizer (supports vso, cdaweb)
      - Wavelength parsing → WavelengthNormalizer (vso only)
      - Physobs selection → PhysObsNormalizer (data source specific variants)
      - Quote normalization → QuoteNormalizer (adds PDF coordinates)
    """

    def __init__(
        self,
        instrument_grounder: InstrumentGrounder,
        llm_client: Optional[LiteLLMClient] = None,
        llm_config=None,
        phenomena: Optional[List[Dict]] = None,
    ):
        self.instrument_grounder = instrument_grounder
        self.llm_client = llm_client or LiteLLMClient()
        self.llm_config = llm_config
        self.phenomena = phenomena or []
        
    def _run_dynamic_normalizers(self, period_data, grounding_result: Dict,
                                instrument_name: str, period_name: str, 
                                instrument_general_comments: str = None,
                                all_periods_data: List = None,
                                pdf_path=None) -> Dict[str, Dict]:
        """
        Dynamically discover and run all normalizers applicable to the data source.
        
        Creates a typed NormalizationContext with InternalDataCollectionPeriod 
        and passes it to each applicable normalizer.
        
        Args:
            period_data: InternalDataCollectionPeriod from internal models
            grounding_result: Complete instrument grounding result
            instrument_name: Name of instrument for context
            period_name: Name of period for context
            pdf_path: Path to PDF for coordinate extraction
            
        Returns:
            Dict mapping normalizer types to their normalized results
        """
        # Extract data system from grounding result - no defaults allowed
        data_system = grounding_result.get("data_system")
        if not data_system:
            raise ValueError(
                f"Missing data_system in grounding result for instrument: {instrument_name}. "
                f"Grounding result: {grounding_result}. "
                f"This indicates a bug in the instrument grounding process."
            )
        
        inst_code = grounding_result.get("matched_instrument_code", "unknown")
        
        # Ensure all required fields are present for GroundingResult
        safe_grounding_result = {
            "matched_instrument_code": grounding_result.get("matched_instrument_code"),
            "matched_mission_code": grounding_result.get("matched_mission_code"),
            "matched_instrument_name": grounding_result.get("matched_instrument_name"),
            "matched_mission_name": grounding_result.get("matched_mission_name"),
            "data_system": data_system,
            "reasoning": grounding_result.get("reasoning", "")
        }
        
        # Create rich typed context object for normalizers
        grounding_obj = GroundingResult(**safe_grounding_result)
        context = NormalizationContext(
            period_data=period_data,
            instrument_code=inst_code,
            instrument_name=instrument_name,
            instrument_general_comments=instrument_general_comments,
            all_periods_data=all_periods_data,
            data_system=data_system,
            period_name=period_name,
            grounding_result=grounding_obj,
            pdf_path=pdf_path,
            phenomena=self.phenomena or None,
        )
        
        # Get all available normalizers for this data source
        available_normalizers = NormalizerRegistry.get_available_normalizers_for_data_source(
            data_system.lower()
        )

        # Phenomena are INTENTIONAL-ONLY: extraction never runs as part of the
        # standard chain (it was ~20% of downstream LLM calls, largely spent on
        # ungrounded/out-of-scope instruments, and feeds a less-hardened
        # subsystem). Run `run_phenomena_enrichment` deliberately over a chosen
        # paper set instead; the normalizer stays registered for that path.
        available_normalizers.pop("phenomenon", None)

        logger.info(f"Found {len(available_normalizers)} normalizers for data system '{data_system}': {list(available_normalizers.keys())}")
        
        normalized_results = {}

        for normalizer_type, normalizer_class in available_normalizers.items():
            try:
                # Check if normalizer should run based on required fields
                should_run = self._should_run_normalizer(normalizer_type, context)
                if not should_run:
                    logger.info(f"Skipping {normalizer_type} normalizer - required fields not present")
                    with node_stage('normalizer', normalizer_type, skip=True,
                                    skip_reason='required field not present in structured data'):
                        pass
                    continue

                # Instantiate normalizer and run with context
                # Check if normalizer requires llm_config parameter
                import inspect
                sig = inspect.signature(normalizer_class.__init__)
                if 'llm_config' in sig.parameters:
                    normalizer = normalizer_class(llm_client=self.llm_client, llm_config=self.llm_config)
                else:
                    normalizer = normalizer_class(llm_client=self.llm_client)
                logger.info(f"Running {normalizer_type} normalizer")

                with node_stage('normalizer', normalizer_type):
                    result = normalizer.normalize(context)
                    # Serialize Pydantic models to avoid JSON serialization issues in Celery
                    if hasattr(result, 'model_dump'):
                        result = result.model_dump()
                    normalized_results[normalizer_type] = result

                logger.debug(f"Normalized result for {normalizer_type}: {type(result)}")

            except Exception as e:
                logger.error(f"Error running {normalizer_type} normalizer: {e}")
                normalized_results[normalizer_type] = None

        return normalized_results
    
    def _should_run_normalizer(self, normalizer_type: str, context: NormalizationContext) -> bool:
        """Determine if a normalizer should run based on available data using direct field access."""
        if normalizer_type == "time_range":
            return bool(context.period_data.time_range)
        elif normalizer_type == "wavelength":
            return bool(context.period_data.wavelengths)
        elif normalizer_type == "physobs":
            return bool(context.period_data.physical_observable)
        elif normalizer_type == "quotes":
            # Quotes normalizer can always run (handles empty quote lists)
            return True
        elif normalizer_type == "cadence":
            return True
        elif normalizer_type == "phenomenon":
            return bool(context.period_data.physical_observable) and bool(context.phenomena)
        else:
            # For unknown normalizer types, assume they can run
            return True

    def forward(self, structured_instruments: dict, pdf_path=None) -> dict:
        """
        Normalize all fields in structured instrument data with typed internal models.
        
        Args:
            structured_instruments: Raw structured instrument data (API format)
            pdf_path: Optional path to PDF for quote coordinate extraction
            
        Returns:
            Normalized instrument data with backward-compatible structure
        """
        # Convert API format to typed internal representation at entry point
        logger.info("Converting API format to internal typed representation")
        internal_data = dict_to_internal_instruments(structured_instruments)
        logger.info(f"Successfully converted {len(internal_data.instruments)} instruments to internal format")

        normalized = {
            "paper_summary": internal_data.paper_summary,
            "instruments": []
        }

        # Process each instrument from the internal typed data
        for instrument in internal_data.instruments:
            processed_instruments = self._process_instrument(instrument, pdf_path)
            normalized["instruments"].extend(processed_instruments)

        return normalized

    def _process_instrument(self, instrument, pdf_path=None) -> List[dict]:
        """
        Process a single instrument, handling potential multiple grounding matches.

        Args:
            instrument: InternalInstrument from typed internal models
            pdf_path: Optional path to PDF for quote coordinate extraction

        Returns:
            List of normalized instrument dictionaries (one per grounding match)
        """
        with node_stage('instrument', instrument.name):
            with node_stage('grounding', 'Grounding'):
                # Ground instrument name - returns List[CatalogueEntry] or None
                grounding_result = self._normalize_instrument_name(instrument)

                # Handle None result (no grounding matches found)
                if grounding_result is None:
                    logger.warning(f"No grounding matches found for instrument: {instrument.name}, running phenomenon-only pass")
                    return self._process_ungrounded_instrument(instrument, pdf_path)

                # grounding_result is now always List[CatalogueEntry]
                catalogue_entries = grounding_result

                processed_instruments = []

                for catalogue_entry in catalogue_entries:
                    # Route match node under the data system node if the grounder set one
                    ds_node_id = getattr(catalogue_entry, 'pipeline_node_id', None)
                    parent_token = None
                    if ds_node_id is not None:
                        parent_token = current_pipeline_node.set(ds_node_id)
                    try:
                        node_label = catalogue_entry.instrument_code or f"[mission:{catalogue_entry.mission_code}]"
                        with node_stage('grounding_match', node_label,
                                        data_system=catalogue_entry.data_system,
                                        mission_code=catalogue_entry.mission_code):
                            # No validation needed - CatalogueEntry objects are already validated
                            # Process this specific catalogue entry
                            processed_instrument = self._process_single_grounding_match(
                                instrument, catalogue_entry, pdf_path
                            )
                            processed_instruments.append(processed_instrument)
                    finally:
                        if parent_token is not None:
                            current_pipeline_node.reset(parent_token)

                return processed_instruments

# _validate_grounding_result method removed - no longer needed with CatalogueEntry objects

    def _process_ungrounded_instrument(self, instrument, pdf_path=None) -> List[dict]:
        """
        Ungrounded instruments produce no normalized entries in the standard chain.

        This used to run a phenomenon-only pass (phenomenon + quote normalizers)
        for every instrument that failed grounding — which meant paying LLM calls
        for the corpus's out-of-scope tail (astronomy/fusion contamination) and
        for groundings merely DEFERRED by the batch runner's frontier discovery.
        Phenomena are now intentional-only: `run_phenomena_enrichment` covers
        ungrounded instruments too, from the stored normalized output.
        """
        logger.info(f"Instrument '{instrument.name}' failed grounding; skipping "
                    "(phenomena via run_phenomena_enrichment if desired)")
        return []

    def _process_single_grounding_match(self, instrument, catalogue_entry: CatalogueEntry, pdf_path=None) -> dict:
        """
        Process a single catalogue entry for an instrument.
        
        Args:
            instrument: InternalInstrument from typed internal models
            catalogue_entry: CatalogueEntry object from grounding
            pdf_path: Optional path to PDF for quote coordinate extraction
            
        Returns:
            Complete normalized instrument dictionary
        """
        inst_code = catalogue_entry.instrument_code
        data_system = catalogue_entry.data_system

        logger.info(f"Processing instrument {inst_code} from data system: {data_system}")

        # For mission-only entries there is no specific instrument, so data collection
        # periods (which are instrument-specific) are meaningless — skip them.
        if inst_code is None:
            normalized_periods = []
        else:
            normalized_periods = self._process_data_collection_periods(
                instrument, catalogue_entry, pdf_path
            )
        
        # Process general quotes for the instrument
        norm_general_quotes = self._process_general_quotes(
            instrument, catalogue_entry, pdf_path
        )

        # Build final normalized instrument structure - create dictionary from CatalogueEntry
        normalized_dict = {
            "matched_instrument_code": catalogue_entry.instrument_code,
            "matched_mission_code": catalogue_entry.mission_code,
            "matched_instrument_name": catalogue_entry.instrument_name,
            "matched_mission_name": catalogue_entry.mission_name,
            "data_system": catalogue_entry.data_system
        }
        
        return {
            "name": {
                "original": instrument.name,
                "normalized": normalized_dict
            },
            "general_comments": instrument.general_comments,
            "supporting_quotes": norm_general_quotes,
            "data_collection_periods": normalized_periods
        }

    def _process_data_collection_periods(self, instrument, catalogue_entry: CatalogueEntry, pdf_path=None) -> List[dict]:
        """
        Process all data collection periods for an instrument.
        
        Args:
            instrument: InternalInstrument from typed internal models
            catalogue_entry: CatalogueEntry object from grounding
            pdf_path: Optional path to PDF for quote coordinate extraction
            
        Returns:
            List of normalized period dictionaries
        """
        normalized_periods = []

        for period in instrument.data_collection_periods:
            # Create grounding result dict for backward compatibility with normalizers
            grounding_result_dict = {
                "matched_instrument_code": catalogue_entry.instrument_code,
                "matched_mission_code": catalogue_entry.mission_code,
                "matched_instrument_name": catalogue_entry.instrument_name,
                "matched_mission_name": catalogue_entry.mission_name,
                "data_system": catalogue_entry.data_system
            }

            with node_stage('normalization', 'Normalization'):
                # Run all applicable normalizers for this data source
                normalized_results = self._run_dynamic_normalizers(
                    period_data=period,  # InternalDataCollectionPeriod (typed)
                    grounding_result=grounding_result_dict,
                    instrument_name=instrument.name,
                    period_name=period.period_name,
                    instrument_general_comments=instrument.general_comments,
                    all_periods_data=instrument.data_collection_periods,
                    pdf_path=pdf_path
                )

            # Build normalized period structure
            normalized_period = self._build_normalized_period_structure(period, normalized_results)
            normalized_periods.append(normalized_period)

        return normalized_periods

    def _build_normalized_period_structure(self, period, normalized_results: dict) -> dict:
        """
        Build the normalized period structure with legacy field mapping.
        
        Args:
            period: InternalDataCollectionPeriod from typed internal models
            normalized_results: Results from dynamic normalizers
            
        Returns:
            Normalized period dictionary with backward-compatible structure
        """
        # Start with basic period structure
        normalized_period = {
            "period_name": period.period_name,
            "additional_comments": period.additional_comments
        }
        
        # Map normalizer results to legacy field names for backward compatibility
        legacy_field_mapping = {
            "time_range": ("time_range", "time_range"),
            "wavelength": ("wavelengths", "wavelengths"),
            "physobs": ("physical_observable", "physical_observable"),
            "quotes": (None, "supporting_quotes"),  # Quotes map to supporting_quotes
            "cadence": ("cadence", "cadence"),
            "phenomenon": (None, "phenomenon"),  # Stored directly like quotes
        }
        
        # Add normalized results for each normalizer that ran
        for normalizer_type, result in normalized_results.items():
            if normalizer_type in legacy_field_mapping:
                original_field, legacy_field = legacy_field_mapping[normalizer_type]
                if original_field:  # Normal case - has original field
                    # Use typed field access for original value
                    original_value = getattr(period, original_field, "")
                    normalized_period[legacy_field] = {
                        "original": original_value,
                        "normalized": result
                    }
                else:  # Special case - quotes don't have simple original field
                    normalized_period[legacy_field] = result
            else:
                # For new normalizer types, add them with their type name
                original_value = getattr(period, normalizer_type, "")
                normalized_period[normalizer_type] = {
                    "original": original_value,
                    "normalized": result
                }
                
        return normalized_period

    def _process_general_quotes(self, instrument, catalogue_entry: CatalogueEntry, pdf_path=None) -> dict:
        """
        Process general supporting quotes for an instrument.
        
        Args:
            instrument: InternalInstrument from typed internal models  
            catalogue_entry: CatalogueEntry object from grounding
            pdf_path: Optional path to PDF for quote coordinate extraction
            
        Returns:
            Normalized general quotes structure or None if no quotes
        """
        # Use typed field access for general quotes
        general_quotes = instrument.general_quotes
        
        if not general_quotes:
            return None
            
        inst_code = catalogue_entry.instrument_code
        data_system = catalogue_entry.data_system
        
        # Create mock InternalDataCollectionPeriod with general quotes
        from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
        general_period_data = InternalDataCollectionPeriod(
            period_name="general",
            general_quotes=general_quotes
        )
        
        # Create context for general quotes normalization
        safe_grounding_result = {
            "matched_instrument_code": catalogue_entry.instrument_code,
            "matched_mission_code": catalogue_entry.mission_code,
            "matched_instrument_name": catalogue_entry.instrument_name,
            "matched_mission_name": catalogue_entry.mission_name,
            "data_system": catalogue_entry.data_system,
            "reasoning": ""  # No reasoning field needed anymore
        }
        grounding_obj = GroundingResult(**safe_grounding_result)
        general_context = NormalizationContext(
            period_data=general_period_data,
            instrument_code=inst_code,
            instrument_name=instrument.name,
            data_system=data_system,
            period_name="general",
            grounding_result=grounding_obj,
            pdf_path=pdf_path
        )
        
        # Find and run quotes normalizer
        quotes_normalizer_class = NormalizerRegistry.get_normalizer_for_data_source("quotes", data_system.lower())
        if quotes_normalizer_class:
            quotes_normalizer = quotes_normalizer_class(llm_client=self.llm_client)
            result = quotes_normalizer.normalize(general_context)
            # Serialize Pydantic models to avoid JSON serialization issues in Celery
            if hasattr(result, 'model_dump'):
                result = result.model_dump()
            return result
        else:
            logger.warning(f"No quotes normalizer available for data system: {data_system}")
            return {"original": general_quotes, "normalized": []}

    def _normalize_instrument_name(self, instrument_data) -> Optional[List[CatalogueEntry]]:
        """Ground instrument using full entry context from internal model and return CatalogueEntry objects"""
        # Convert internal model back to dict for InstrumentGrounder compatibility
        if hasattr(instrument_data, 'model_dump'):
            # It's a Pydantic model, convert to dict
            instrument_dict = instrument_data.model_dump()
        else:
            # It's already a dict
            instrument_dict = instrument_data
            
        return self.instrument_grounder.ground_instrument(instrument_dict)
