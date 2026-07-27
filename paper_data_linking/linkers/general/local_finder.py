# paper_data_linking/linkers/general/local_finder.py

import json
import numpy as np
import logging
from typing import List, Tuple, Dict

from .finders import AbstractInstrumentFinder
from .catalogue_models import (
    validate_catalogue_entries, CatalogueEntry, Mission,
    validate_missions, CatalogueValidationError
)
from paper_data_linking.config.paths import DATA_ASSETS_DIR

logger = logging.getLogger(__name__)


class LocalInstrumentFinder(AbstractInstrumentFinder):
    """
    A non-Django finder for testing purposes that reads instrument data
    directly from the project's JSON catalog and NumPy embeddings files.
    """

    def __init__(self):
        self._catalog: List[CatalogueEntry] = []
        self.catalog_embeddings = np.array([])
        self._load_data()
    
    @property 
    def catalog(self) -> List[CatalogueEntry]:
        """Return the loaded catalog as CatalogueEntry objects."""
        return self._catalog

    def _load_data(self):
        """Load the catalog and embeddings from local files with validation."""
        data_dir = DATA_ASSETS_DIR / "vso"

        # Try merged catalog first, fall back to original if not available
        merged_catalog_path = data_dir / "merged_instrument_catalog.json"
        original_catalog_path = data_dir / "enhanced_instrument_catalog.json"
        
        if merged_catalog_path.exists():
            catalog_path = merged_catalog_path
            logger.info(f"Using merged catalog: {catalog_path}")
        elif original_catalog_path.exists():
            catalog_path = original_catalog_path
            logger.info(f"Using original catalog: {catalog_path}")
        else:
            raise FileNotFoundError(f"No catalog found at {merged_catalog_path} or {original_catalog_path}")
            
        # Load raw catalog data
        with open(catalog_path, 'r', encoding='utf-8') as f:
            raw_catalog = json.load(f)
        
        logger.info(f"Loaded {len(raw_catalog)} raw instruments from {catalog_path}")
        
        try:
            # Validate all entries against the schema and store as CatalogueEntry objects
            self._catalog = validate_catalogue_entries(raw_catalog)
            
            logger.info(f"Successfully validated {len(self._catalog)} instruments")
            
        except CatalogueValidationError as e:
            logger.error(f"Catalog validation failed: {str(e)}")
            raise

        embeddings_path = data_dir / "instrument_embeddings.npy"
        if embeddings_path.exists():
            self.catalog_embeddings = np.load(embeddings_path)
            if len(self.catalog_embeddings) != len(self._catalog):
                logger.warning(
                    f"Embedding count ({len(self.catalog_embeddings)}) doesn't match catalog size ({len(self._catalog)}). "
                    f"Please regenerate embeddings with: python manage_local_catalog.py regenerate --all"
                )
        else:
            raise FileNotFoundError(f"Local embeddings not found: {embeddings_path}")

    def find_candidates(self, query_embedding: np.ndarray, top_k: int) -> Tuple[List[CatalogueEntry], List[float]]:
        """Finds top candidates using in-memory numpy cosine similarity."""
        if not self._catalog or self.catalog_embeddings.size == 0:
            return [], []

        catalog_norms = np.linalg.norm(self.catalog_embeddings, axis=1)
        query_norm = np.linalg.norm(query_embedding)

        # Avoid division by zero
        if query_norm == 0 or np.any(catalog_norms == 0):
            return [], []

        dot_products = np.dot(self.catalog_embeddings, query_embedding)
        similarities = dot_products / (catalog_norms * query_norm)

        # Get the indices of the top_k highest scores
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        # Return CatalogueEntry objects directly
        candidates = [self._catalog[i] for i in top_indices]
        scores = similarities[top_indices].tolist()

        return candidates, scores

    def get_instrument_by_codes(self, mission_code: str, instrument_code: str) -> CatalogueEntry | None:
        """Finds an instrument by codes by searching the catalogue."""
        for inst in self._catalog:
            if (inst.instrument_code == instrument_code and
                    inst.mission_code == mission_code):
                return inst
        return None
    
    def _load_mission_descriptions(self) -> Dict[str, str]:
        """Load mission descriptions from Django Observatory model if available."""
        try:
            from vso_query_builder.models import Observatory
            return dict(Observatory.objects.values_list('name', 'description'))
        except Exception:
            logger.debug("Could not load Observatory descriptions (Django not available)")
            return {}

    def get_unique_missions(self) -> List[Mission]:
        """Get unique missions from catalog efficiently with caching."""
        if not hasattr(self, '_cached_missions'):
            descriptions = self._load_mission_descriptions()
            unique_missions = {}
            for inst in self._catalog:
                mission_name = inst.mission_name
                if mission_name and mission_name not in unique_missions:
                    mission = Mission(
                        mission_code=inst.mission_code,
                        mission_name=mission_name,
                        data_system=inst.data_system,
                        description=descriptions.get(mission_name) or None,
                    )
                    unique_missions[mission_name] = mission
            self._cached_missions = list(unique_missions.values())
            logger.info(f"Cached {len(self._cached_missions)} unique missions")
        return self._cached_missions
    
    def get_instruments_for_missions(self, mission_names: List[str]) -> List[CatalogueEntry]:
        """Get all instruments for specified missions with efficient filtering."""
        if not mission_names:
            return []
        
        # Convert to lowercase for case-insensitive matching
        mission_names_lower = {name.lower() for name in mission_names}
        
        filtered_instruments = []
        for inst in self._catalog:
            if inst.mission_name.lower() in mission_names_lower:
                filtered_instruments.append(inst)
        
        logger.info(f"Found {len(filtered_instruments)} instruments for {len(mission_names)} missions")
        return filtered_instruments