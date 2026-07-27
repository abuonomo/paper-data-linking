"""Base classes for data source-specific snippet generators."""

from abc import ABC, abstractmethod
from typing import Optional


class BaseDatasetUsageSnippetGenerator(ABC):
    """Base class for generating snippets from DatasetUsage records for specific data sources."""
    
    @abstractmethod
    def generate_snippet(self, dataset_usage, query_name: Optional[str] = None, include_imports: bool = True) -> str:
        """
        Generate an individual Python snippet for a single DatasetUsage.
        
        Args:
            dataset_usage: DatasetUsage model instance
            query_name: Optional name for the query variable
            include_imports: Whether to include necessary imports (default: True)
            
        Returns:
            Python code snippet as string
        """
        pass
    
    def get_data_source(self) -> str:
        """Get the data source this generator supports."""
        return self.__class__.__name__.replace('_DatasetUsageSnippetGenerator', '').lower()
    
    def supports_data_source(self, data_source: str) -> bool:
        """Check if this generator supports a specific data source."""
        return self.get_data_source() == data_source.lower()