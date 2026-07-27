"""Registry system for data source-specific snippet generators."""

from typing import Dict, Type, Optional, List
from dataclasses import dataclass

from .snippet_generator_base import BaseDatasetUsageSnippetGenerator


class UnsupportedDataSourceError(Exception):
    """
    Exception raised when trying to generate snippets for an unsupported data source.

    This allows for clean error handling when a data source doesn't have an
    implemented snippet generator, rather than returning sentinel values.
    """

    def __init__(self, data_source: str, available_sources: Optional[List[str]] = None):
        self.data_source = data_source
        self.available_sources = available_sources or []

        if self.available_sources:
            available_str = ", ".join(self.available_sources)
            message = f"No snippet generator found for data source '{data_source}'. Available: {available_str}"
        else:
            message = f"No snippet generator found for data source '{data_source}'"

        super().__init__(message)


@dataclass
class SnippetGeneratorInfo:
    """Metadata for a registered snippet generator implementation."""
    class_ref: Type[BaseDatasetUsageSnippetGenerator]
    version: str = "1.0"
    description: str = ""
    data_sources: List[str] = None  # Data sources this generator supports


class DataSourceSnippetGeneratorRegistry:
    """Registry for data source-specific snippet generators following the normalizer pattern."""

    _registry: Dict[str, SnippetGeneratorInfo] = {}

    @classmethod
    def register(cls, name: str, version: str = "1.0", data_sources: Optional[List[str]] = None):
        """
        Register a snippet generator implementation with metadata.

        Args:
            name: Generator name (e.g., "vso", "cdaweb", "vso_dataset_usage")
            version: Version string for the implementation
            data_sources: List of data sources this generator supports
        """
        def wrapper(generator_class: Type[BaseDatasetUsageSnippetGenerator]):
            cls._registry[name] = SnippetGeneratorInfo(
                class_ref=generator_class,
                version=version,
                description=generator_class.__doc__ or f"Description for {name}",
                data_sources=data_sources or []
            )
            return generator_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[BaseDatasetUsageSnippetGenerator]:
        """Get a registered snippet generator class."""
        if name not in cls._registry:
            raise ValueError(f"Snippet generator {name} not found in registry")
        return cls._registry[name].class_ref

    @classmethod
    def get_info(cls, name: str) -> SnippetGeneratorInfo:
        """Get metadata for a registered snippet generator."""
        if name not in cls._registry:
            raise ValueError(f"Snippet generator {name} not found in registry")
        return cls._registry[name]

    @classmethod
    def list(cls) -> List[str]:
        """List all registered snippet generator names."""
        return list(cls._registry.keys())

    @classmethod
    def get_generator_for_data_source(cls, data_source: str) -> Type[BaseDatasetUsageSnippetGenerator]:
        """
        Get a snippet generator implementation for a specific data source.

        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")

        Returns:
            Snippet generator class

        Raises:
            UnsupportedDataSourceError: If no generator is found for the data source
        """
        # Try direct data source match first
        if data_source in cls._registry:
            return cls._registry[data_source].class_ref

        # Try finding a generator that supports this data source
        for name, info in cls._registry.items():
            if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                return info.class_ref

        # Get available data sources for helpful error message
        available_sources = []
        for info in cls._registry.values():
            if info.data_sources:
                available_sources.extend(info.data_sources)

        raise UnsupportedDataSourceError(data_source, list(set(available_sources)))

    @classmethod
    def get_available_generators_for_data_source(cls, data_source: str) -> Dict[str, Type[BaseDatasetUsageSnippetGenerator]]:
        """
        Get all available snippet generators for a given data source.

        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")

        Returns:
            Dict mapping generator name to generator class
        """
        available_generators = {}

        for name, info in cls._registry.items():
            # Check if this generator supports the data source
            if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                available_generators[name] = info.class_ref

        return available_generators

    @classmethod
    def get_data_source_coverage(cls) -> Dict[str, List[str]]:
        """
        Get a mapping of data sources to the snippet generators they support.

        Returns:
            Dict mapping data source names to lists of supported generator names
        """
        coverage = {}

        # Collect all unique data sources mentioned in registry
        all_data_sources = set()
        for info in cls._registry.values():
            if info.data_sources:
                all_data_sources.update(info.data_sources)

        # For each data source, find supported generators
        for data_source in all_data_sources:
            generators = []
            for name, info in cls._registry.items():
                if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                    generators.append(name)
            coverage[data_source] = generators

        return coverage
