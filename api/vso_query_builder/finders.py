# api/vso_query_builder/finders.py

import numpy as np
from typing import List, Tuple, Dict
import logging

from pgvector.django.functions import CosineDistance
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from paper_data_linking.linkers.general.finders import AbstractInstrumentFinder
from paper_data_linking.linkers.general.catalogue_models import (
    validate_catalogue_entries, CatalogueEntry, Mission,
    CatalogueValidationError
)
from .models import Instrument

logger = logging.getLogger(__name__)


class DjangoInstrumentFinder(AbstractInstrumentFinder):
    """
    A concrete implementation of AbstractInstrumentFinder that uses the Django ORM
    and a pgvector-enabled database to find instruments.
    """
    
    @property
    def catalog(self) -> List[CatalogueEntry]:
        """
        Returns the complete instrument catalog as a list of validated CatalogueEntry objects.
        This is cached to prevent repeated expensive DB queries during grounding.
        """
        # Use simple caching to avoid repeated DB queries
        if not hasattr(self, '_cached_catalog'):
            try:
                logger.info("Loading and validating instrument catalog from database")
                raw_entries = []
                invalid_instruments = []
                
                for inst in Instrument.objects.select_related('observatory__datasource').all():
                    try:
                        raw_entries.append(inst.to_catalog_dict)
                    except ValueError as e:
                        invalid_instruments.append(f"Instrument {inst.short_name}: {str(e)}")
                
                if invalid_instruments:
                    logger.error(
                        f"Found {len(invalid_instruments)} instruments with missing required data:\n" +
                        "\n".join(invalid_instruments[:5])  # Show first 5 errors
                    )
                    raise CatalogueValidationError(
                        f"Database contains instruments with missing required data. "
                        f"Please fix these instruments before continuing:\n" +
                        "\n".join(invalid_instruments[:5])
                    )
                
                # Validate all entries against the schema and store as CatalogueEntry objects
                self._cached_catalog = validate_catalogue_entries(raw_entries)
                
                logger.info(f"Successfully loaded and validated {len(self._cached_catalog)} instruments")
                
            except Exception as e:
                logger.error(f"Failed to load instrument catalog: {str(e)}")
                raise
        
        return self._cached_catalog
    
    def find_candidates(self, query_embedding: np.ndarray, top_k: int) -> Tuple[List[CatalogueEntry], List[float]]:
        candidate_instruments = Instrument.objects.select_related('observatory__datasource').annotate(
            distance=CosineDistance('embedding', query_embedding)
        ).order_by('distance')[:top_k]

        # Convert to CatalogueEntry objects
        candidates = []
        invalid_instruments = []
        
        for inst in candidate_instruments:
            try:
                # Create CatalogueEntry directly from the raw dict
                catalog_dict = inst.to_catalog_dict
                candidate = CatalogueEntry(**catalog_dict)
                candidates.append(candidate)
            except ValueError as e:
                invalid_instruments.append(f"Instrument {inst.short_name}: {str(e)}")
        
        if invalid_instruments:
            logger.warning(
                f"Found {len(invalid_instruments)} invalid instruments in find_candidates:\n" +
                "\n".join(invalid_instruments[:3])
            )
        
        scores = [(1 - inst.distance) for inst in candidate_instruments[:len(candidates)]]
        return candidates, scores

    def get_instrument_by_codes(self, mission_code: str, instrument_code: str) -> CatalogueEntry | None:
        try:
            inst = Instrument.objects.select_related('observatory__datasource').get(
                observatory__short_name=mission_code.upper(),
                short_name=instrument_code.upper()
            )
            # Convert to CatalogueEntry object
            catalog_dict = inst.to_catalog_dict
            return CatalogueEntry(**catalog_dict)
        except ObjectDoesNotExist:
            return None
        except ValueError as e:
            logger.error(f"Invalid instrument data for {instrument_code}/{mission_code}: {str(e)}")
            return None
    
    def get_unique_missions(self) -> List[Mission]:
        """Get unique missions efficiently using DB aggregation with caching."""
        if not hasattr(self, '_cached_missions'):
            from django.db import models
            
            # Use DB aggregation to get unique missions efficiently
            unique_missions_query = (
                Instrument.objects
                .select_related('observatory__datasource')
                .filter(observatory__isnull=False, observatory__datasource__isnull=False)
                .values('observatory__name', 'observatory__short_name', 'observatory__datasource__slug', 'observatory__description')
                .distinct()
            )

            # Use dict to deduplicate by mission_name while preserving order
            # This handles cases where multiple observatory records have same name
            # but different short_name or datasource
            missions_dict = {}
            for mission_data in unique_missions_query:
                mission_name = mission_data['observatory__name']

                # Only add if not already present (first occurrence wins)
                if mission_name not in missions_dict:
                    mission = Mission(
                        mission_code=mission_data['observatory__short_name'].upper(),
                        mission_name=mission_name,
                        data_system=mission_data['observatory__datasource__slug'],
                        description=mission_data.get('observatory__description') or None
                    )
                    missions_dict[mission_name] = mission

            missions = list(missions_dict.values())
            self._cached_missions = missions
            logger.info(f"Cached {len(self._cached_missions)} unique missions from database")
        
        return self._cached_missions
    
    def get_instruments_for_missions(self, mission_names: List[str]) -> List[CatalogueEntry]:
        """Get instruments for specified missions using efficient DB filtering."""
        if not mission_names:
            return []
        
        # Use DB filtering instead of loading all instruments
        instruments_query = (
            Instrument.objects
            .select_related('observatory__datasource')
            .filter(
                observatory__name__in=mission_names,
                observatory__isnull=False,
                observatory__datasource__isnull=False
            )
        )
        
        filtered_instruments = []
        invalid_instruments = []
        
        for inst in instruments_query:
            try:
                # Create CatalogueEntry objects directly
                catalog_dict = inst.to_catalog_dict
                catalogue_entry = CatalogueEntry(**catalog_dict)
                filtered_instruments.append(catalogue_entry)
            except ValueError as e:
                invalid_instruments.append(f"Instrument {inst.short_name}: {str(e)}")
        
        if invalid_instruments:
            logger.warning(
                f"Found {len(invalid_instruments)} instruments with missing data for missions {mission_names}:\n" +
                "\n".join(invalid_instruments[:3])
            )
        
        logger.info(f"Found {len(filtered_instruments)} valid instruments for {len(mission_names)} missions")
        return filtered_instruments
    
    def get_available_data_systems(self) -> List[str]:
        """Get all unique data systems available in the database."""
        if not hasattr(self, '_cached_data_systems'):
            data_systems = (
                Instrument.objects
                .select_related('observatory__datasource')
                .filter(observatory__datasource__isnull=False)
                .values_list('observatory__datasource__slug', flat=True)
                .distinct()
            )
            self._cached_data_systems = list(data_systems)
            logger.info(f"Found {len(self._cached_data_systems)} data systems: {self._cached_data_systems}")
        return self._cached_data_systems
    
    def get_catalog_for_data_system(self, data_system: str) -> List[CatalogueEntry]:
        """Get complete catalog filtered by specific data system."""
        if not data_system:
            return []
            
        instruments_query = (
            Instrument.objects
            .select_related('observatory__datasource')
            .filter(
                observatory__datasource__slug=data_system,
                observatory__isnull=False,
                observatory__datasource__isnull=False
            )
        )
        
        catalog_entries = []
        invalid_instruments = []
        
        for inst in instruments_query:
            try:
                catalog_dict = inst.to_catalog_dict
                catalogue_entry = CatalogueEntry(**catalog_dict)
                catalog_entries.append(catalogue_entry)
            except ValueError as e:
                invalid_instruments.append(f"Instrument {inst.short_name}: {str(e)}")
        
        if invalid_instruments:
            logger.warning(
                f"Found {len(invalid_instruments)} invalid instruments for data system {data_system}:\n" +
                "\n".join(invalid_instruments[:3])
            )
        
        logger.info(f"Found {len(catalog_entries)} valid instruments for data system {data_system}")
        return catalog_entries
    
    def get_missions_for_data_system(self, data_system: str) -> List[Mission]:
        """Get unique missions filtered by specific data system."""
        if not data_system:
            return []
            
        unique_missions_query = (
            Instrument.objects
            .select_related('observatory__datasource')
            .filter(
                observatory__datasource__slug=data_system,
                observatory__isnull=False, 
                observatory__datasource__isnull=False
            )
            .values('observatory__name', 'observatory__short_name', 'observatory__datasource__slug')
            .distinct()
        )
        
        missions = []
        for mission_data in unique_missions_query:
            mission = Mission(
                mission_code=mission_data['observatory__short_name'].upper(),
                mission_name=mission_data['observatory__name'],
                data_system=mission_data['observatory__datasource__slug']
            )
            missions.append(mission)
        
        logger.info(f"Found {len(missions)} unique missions for data system {data_system}")
        return missions
    
    def get_instruments_for_missions_and_data_system(self, mission_names: List[str], data_system: str) -> List[CatalogueEntry]:
        """Get instruments for specified missions within a specific data system."""
        if not mission_names or not data_system:
            return []
        
        instruments_query = (
            Instrument.objects
            .select_related('observatory__datasource')
            .filter(
                observatory__name__in=mission_names,
                observatory__datasource__slug=data_system,
                observatory__isnull=False,
                observatory__datasource__isnull=False
            )
        )
        
        filtered_instruments = []
        invalid_instruments = []
        
        for inst in instruments_query:
            try:
                catalog_dict = inst.to_catalog_dict
                catalogue_entry = CatalogueEntry(**catalog_dict)
                filtered_instruments.append(catalogue_entry)
            except ValueError as e:
                invalid_instruments.append(f"Instrument {inst.short_name}: {str(e)}")
        
        if invalid_instruments:
            logger.warning(
                f"Found {len(invalid_instruments)} instruments with missing data for missions {mission_names} in {data_system}:\n" +
                "\n".join(invalid_instruments[:3])
            )
        
        logger.info(f"Found {len(filtered_instruments)} valid instruments for {len(mission_names)} missions in {data_system}")
        return filtered_instruments