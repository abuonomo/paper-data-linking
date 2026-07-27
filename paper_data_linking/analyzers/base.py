"""Base classes for dataset usage analyzers."""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseDatasetUsageAnalyzer(ABC):
    """Base class for analyzing individual dataset usage snippets."""
    
    @abstractmethod
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        """
        Analyze a single Python snippet for a DatasetUsage record.
        
        Args:
            dataset_usage: DatasetUsage model instance
            snippet: Generated Python code snippet as string
            
        Returns:
            Dictionary containing analysis results
        """
        pass
    
    def get_name(self) -> str:
        """Get the analyzer name for registry purposes."""
        return self.__class__.__name__