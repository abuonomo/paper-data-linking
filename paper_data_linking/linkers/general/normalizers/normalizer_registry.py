# paper_data_linking/linkers/general/normalizers/normalizer_registry.py

from typing import Type, Dict, Optional, List
from dataclasses import dataclass

from .base_normalizer import BaseNormalizer


@dataclass
class NormalizerInfo:
    """Metadata for a registered normalizer implementation."""
    class_ref: Type[BaseNormalizer]
    version: str = "1.0"
    description: str = ""
    data_sources: List[str] = None  # Data sources this normalizer supports (e.g., ["vso", "cdaweb"])


class NormalizerRegistry:
    """Registry for normalizer implementations.

    Each normalizer is registered with a name and a list of supported data sources.
    """

    _registry: Dict[str, NormalizerInfo] = {}

    @classmethod
    def register(cls, name: str, version: str = "1.0", data_sources: Optional[List[str]] = None):
        """
        Register a normalizer implementation with metadata.

        Normalizer names must be globally unique. If attempting to register a name that
        already exists, a ValueError is raised.

        Args:
            name: Normalizer name (e.g., "time_range", "wavelength", "detector", "physobs")
                  Must be unique across all normalizers.
            version: Version string for the implementation
            data_sources: List of data sources this normalizer supports (e.g., ["vso", "cdaweb"])

        Raises:
            ValueError: If the name is already registered
        """
        def wrapper(normalizer_class: Type[BaseNormalizer]):
            if name in cls._registry:
                existing_class = cls._registry[name].class_ref
                raise ValueError(
                    f"Normalizer name '{name}' is already registered by {existing_class.__module__}.{existing_class.__name__}. "
                    f"Normalizer names must be globally unique."
                )
            cls._registry[name] = NormalizerInfo(
                class_ref=normalizer_class,
                version=version,
                description=normalizer_class.__doc__ or f"Description for {name}",
                data_sources=data_sources or []
            )
            return normalizer_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[BaseNormalizer]:
        """Get a registered normalizer class."""
        if name not in cls._registry:
            raise ValueError(f"Normalizer {name} not found in registry")
        return cls._registry[name].class_ref

    @classmethod
    def get_info(cls, name: str) -> NormalizerInfo:
        """Get metadata for a registered normalizer."""
        if name not in cls._registry:
            raise ValueError(f"Normalizer {name} not found in registry")
        return cls._registry[name]

    @classmethod
    def list(cls) -> List[str]:
        """List all registered normalizer names."""
        return list(cls._registry.keys())

    @classmethod
    def get_normalizer_for_data_source(cls, normalizer_type: str, data_source: str) -> Optional[Type[BaseNormalizer]]:
        """
        Get a normalizer implementation for a specific data source and type.

        Returns the normalizer if it supports the requested data source
        (as specified in its data_sources list).

        Args:
            normalizer_type: Normalizer type (e.g., "physobs", "detector", "time_range")
            data_source: Data source name (e.g., "vso", "cdaweb")

        Returns:
            Normalizer class or None if not found or doesn't support this data source
        """
        if normalizer_type not in cls._registry:
            return None

        info = cls._registry[normalizer_type]
        if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
            return info.class_ref

        return None

    @classmethod
    def get_registered_types(cls) -> List[str]:
        """Get list of all registered normalizer types."""
        return sorted(list(cls._registry.keys()))

    @classmethod
    def get_normalizer_types_for_data_source(cls, data_source: str) -> List[str]:
        """
        Get all normalizer types that support a given data source.

        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")

        Returns:
            List of normalizer types that support this data source
        """
        supported_types = set()

        for name, info in cls._registry.items():
            # Check if this normalizer supports the data source
            if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                supported_types.add(name)

        return sorted(list(supported_types))

    @classmethod
    def get_available_normalizers_for_data_source(cls, data_source: str) -> Dict[str, Type[BaseNormalizer]]:
        """
        Get all available normalizers for a given data source.
        
        Returns a dictionary mapping base normalizer types to their implementations
        for the specified data source.
        
        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")
            
        Returns:
            Dict mapping normalizer type to normalizer class
        """
        available_normalizers = {}
        
        # Get all base types that support this data source
        supported_types = cls.get_normalizer_types_for_data_source(data_source)
        
        # For each supported type, get the best normalizer implementation
        for normalizer_type in supported_types:
            normalizer_class = cls.get_normalizer_for_data_source(normalizer_type, data_source)
            if normalizer_class:
                available_normalizers[normalizer_type] = normalizer_class
        
        return available_normalizers

    @classmethod
    def get_data_source_coverage(cls) -> Dict[str, List[str]]:
        """
        Get a mapping of data sources to the normalizer types they support.
        
        Returns:
            Dict mapping data source names to lists of supported normalizer types
        """
        coverage = {}
        
        # Collect all unique data sources mentioned in registry
        all_data_sources = set()
        for info in cls._registry.values():
            if info.data_sources:
                all_data_sources.update(info.data_sources)
        
        # For each data source, find supported normalizer types
        for data_source in all_data_sources:
            coverage[data_source] = cls.get_normalizer_types_for_data_source(data_source)
        
        return coverage