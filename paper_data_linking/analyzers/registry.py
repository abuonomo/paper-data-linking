"""Registry system for dataset usage analyzers."""

from typing import Dict, Type, Optional, List
from dataclasses import dataclass
from .base import BaseDatasetUsageAnalyzer


@dataclass
class AnalyzerInfo:
    """Metadata for a registered analyzer implementation."""
    class_ref: Type[BaseDatasetUsageAnalyzer]
    version: str = "1.0"
    description: str = ""
    data_sources: List[str] = None  # Data sources this analyzer supports (e.g., ["vso", "cdaweb"])


class DatasetUsageAnalyzerRegistry:
    """Registry for dataset usage analyzers with support for data source-specific variants."""
    
    _analyzers: Dict[str, AnalyzerInfo] = {}
    
    @classmethod
    def register(cls, name: str, version: str = "1.0", data_sources: Optional[List[str]] = None):
        """
        Decorator to register a dataset usage analyzer with metadata.
        
        Args:
            name: Analyzer name (e.g., "QuerySyntax", "QueryExecution.vso", "QueryExecution.cdaweb")
            version: Version of the analyzer
            data_sources: List of data sources this analyzer supports
        """
        def decorator(analyzer_class: Type[BaseDatasetUsageAnalyzer]):
            key = f"{name}:{version}"
            cls._analyzers[key] = AnalyzerInfo(
                class_ref=analyzer_class,
                version=version,
                description=analyzer_class.__doc__ or f"Description for {name}",
                data_sources=data_sources or []
            )
            return analyzer_class
        return decorator
    
    @classmethod
    def get_analyzer(cls, name: str, version: str = "1.0") -> Optional[Type[BaseDatasetUsageAnalyzer]]:
        """Get an analyzer by name and version."""
        key = f"{name}:{version}"
        analyzer_info = cls._analyzers.get(key)
        return analyzer_info.class_ref if analyzer_info else None
    
    @classmethod
    def get_analyzer_info(cls, name: str, version: str = "1.0") -> Optional[AnalyzerInfo]:
        """Get metadata for a registered analyzer."""
        key = f"{name}:{version}"
        return cls._analyzers.get(key)
    
    @classmethod
    def get_all_analyzers(cls) -> Dict[str, Type[BaseDatasetUsageAnalyzer]]:
        """Get all registered analyzers."""
        return {key: info.class_ref for key, info in cls._analyzers.items()}
    
    @classmethod
    def list_analyzers(cls) -> list:
        """List all registered analyzer names."""
        return list(cls._analyzers.keys())
    
    @classmethod
    def get_analyzer_for_data_source(cls, analyzer_type: str, data_source: str, version: str = "1.0") -> Optional[Type[BaseDatasetUsageAnalyzer]]:
        """
        Get an analyzer implementation for a specific data source and type.
        
        First tries to find a data source-specific variant (e.g., "QueryExecution.vso"),
        then falls back to the general analyzer (e.g., "QueryExecution").
        
        Args:
            analyzer_type: Base analyzer type (e.g., "QueryExecution", "QuerySyntax")
            data_source: Data source name (e.g., "vso", "cdaweb")
            version: Version of the analyzer
            
        Returns:
            Analyzer class or None if not found
        """
        # Try data source-specific variant first
        specific_name = f"{analyzer_type}.{data_source}"
        specific_key = f"{specific_name}:{version}"
        if specific_key in cls._analyzers:
            return cls._analyzers[specific_key].class_ref
        
        # Fall back to general analyzer if it supports this data source
        general_key = f"{analyzer_type}:{version}"
        if general_key in cls._analyzers:
            info = cls._analyzers[general_key]
            if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                return info.class_ref
        
        return None
    
    @classmethod
    def get_analyzer_types_for_data_source(cls, data_source: str) -> List[str]:
        """
        Get all analyzer types (base types) that support a given data source.
        
        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")
            
        Returns:
            List of base analyzer types that support this data source
        """
        supported_types = set()
        
        for key, info in cls._analyzers.items():
            name = key.split(':')[0]  # Remove version suffix
            # Check if this analyzer supports the data source
            if not info.data_sources or data_source.lower() in [ds.lower() for ds in info.data_sources]:
                # Extract base type (everything before first dot)
                base_type = name.split('.')[0]
                supported_types.add(base_type)
        
        return sorted(list(supported_types))
    
    @classmethod
    def get_available_analyzers_for_data_source(cls, data_source: str, version: str = "1.0") -> Dict[str, Type[BaseDatasetUsageAnalyzer]]:
        """
        Get all available analyzers for a given data source.
        
        Returns a dictionary mapping base analyzer types to their implementations
        for the specified data source.
        
        Args:
            data_source: Data source name (e.g., "vso", "cdaweb")
            version: Version of analyzers to get
            
        Returns:
            Dict mapping analyzer type to analyzer class
        """
        available_analyzers = {}
        
        # Get all base types that support this data source
        supported_types = cls.get_analyzer_types_for_data_source(data_source)
        
        # For each supported type, get the best analyzer implementation
        for analyzer_type in supported_types:
            analyzer_class = cls.get_analyzer_for_data_source(analyzer_type, data_source, version)
            if analyzer_class:
                available_analyzers[analyzer_type] = analyzer_class
        
        return available_analyzers