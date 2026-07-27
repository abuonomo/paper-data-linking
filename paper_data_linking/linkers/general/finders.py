# paper_data_linking/linkers/general/finders.py

from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Set
import numpy as np

from .catalogue_models import CatalogueEntry, Mission


class AbstractInstrumentFinder(ABC):
    """
    Abstract interface for finding instrument candidates from a data source.
    
    This interface supports both embedding-based candidate finding and targeted queries
    to avoid expensive full catalogue scans during instrument grounding.
    """
    
    @property
    @abstractmethod
    def catalog(self) -> List[CatalogueEntry]:
        """
        Returns the complete instrument catalog as a list of validated CatalogueEntry objects.
        
        This should be cached appropriately to avoid repeated expensive operations.
        All entries are validated Pydantic models.
        
        Returns:
            List of validated CatalogueEntry objects
        """
        pass
    
    @abstractmethod
    def find_candidates(self, query_embedding: np.ndarray, top_k: int) -> Tuple[List[CatalogueEntry], List[float]]:
        """
        Finds the top_k most similar instrument candidates for a given embedding.

        Returns:
            A tuple containing:
            - A list of CatalogueEntry objects.
            - A list of corresponding similarity scores.
        """
        pass

    @abstractmethod
    def get_instrument_by_codes(self, mission_code: str, instrument_code: str) -> CatalogueEntry | None:
        """
        Retrieves a single instrument's details using its mission and instrument codes.

        Returns:
            A CatalogueEntry object or None if not found.
        """
        pass
    
    @abstractmethod
    def get_unique_missions(self) -> List[Mission]:
        """
        Get unique missions from the catalog efficiently.
        
        This should be more efficient than scanning the full catalog for missions.
        
        Returns:
            List of unique Mission objects
        """
        pass
    
    @abstractmethod
    def get_instruments_for_missions(self, mission_names: List[str]) -> List[CatalogueEntry]:
        """
        Get all instruments that belong to the specified missions.
        
        This should be more efficient than loading the full catalog and filtering in memory.
        
        Args:
            mission_names: List of mission names to filter by
            
        Returns:
            List of CatalogueEntry objects for the specified missions
        """
        pass