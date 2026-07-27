"""Service for generating individual Python snippets from DatasetUsage records."""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

from .snippet_generator_registry import DataSourceSnippetGeneratorRegistry, UnsupportedDataSourceError

logger = logging.getLogger(__name__)


class DatasetUsageSnippetGenerator:
    """
    Generates individual Python snippets for DatasetUsage records using data source-specific generators.
    Updated to use registry pattern for extensibility across different data sources.
    """
    
    def generate_snippet(self, dataset_usage, query_name: Optional[str] = None, include_imports: bool = True) -> str:
        """
        Generate an individual Python snippet for a single DatasetUsage using appropriate data source generator.
        
        Args:
            dataset_usage: DatasetUsage model instance
            query_name: Optional name for the query variable
            include_imports: Whether to include necessary imports (default: True)
            
        Returns:
            Python code snippet as string
        """
        if not query_name:
            query_name = "query"

        # Get data source from dataset usage
        data_source = dataset_usage.instrument.observatory.datasource.slug
        
        # Get appropriate generator for this data source (raises exception if not found)
        generator_class = DataSourceSnippetGeneratorRegistry.get_generator_for_data_source(data_source)
        
        # Instantiate and use the generator
        generator = generator_class()
        return generator.generate_snippet(dataset_usage, query_name, include_imports)
    
    def generate_snippets_for_paper(self, paper) -> Dict[str, str]:
        """
        Generate snippets for all DatasetUsage records in a paper using data source-specific generators.
        
        Args:
            paper: Paper model instance
            
        Returns:
            Dictionary mapping dataset_usage.id to Python snippet
        """
        usages = paper.dataset_usages.order_by(
            'instrument__observatory__short_name',
            'instrument__short_name', 
            'observation_window'
        ).select_related('instrument__observatory__datasource')
        
        snippets = {}
        query_count = 0
        
        for usage in usages:
            data_source = usage.instrument.observatory.datasource.slug
            try:
                generator_class = DataSourceSnippetGeneratorRegistry.get_generator_for_data_source(data_source)
                query_count += 1
                query_name = f"query{query_count}"
                generator = generator_class()
                snippet = generator.generate_snippet(usage, query_name, include_imports=False)
                snippets[str(usage.id)] = snippet
            except UnsupportedDataSourceError:
                logger.debug(f"Skipping usage {usage.id} for unsupported data source: {data_source}")
                continue
        
        return snippets
    
    def generate_snippets_for_usages(self, usages: QuerySet) -> Dict[str, str]:
        """
        Generate snippets for a queryset of DatasetUsage records using data source-specific generators.
        
        Args:
            usages: QuerySet of DatasetUsage instances
            
        Returns:
            Dictionary mapping dataset_usage.id to Python snippet
        """
        snippets = {}
        query_count = 0
        
        for usage in usages:
            data_source = usage.instrument.observatory.datasource.slug
            try:
                generator_class = DataSourceSnippetGeneratorRegistry.get_generator_for_data_source(data_source)
                query_count += 1
                query_name = f"query{query_count}"
                generator = generator_class()
                snippet = generator.generate_snippet(usage, query_name, include_imports=False)
                snippets[str(usage.id)] = snippet
            except UnsupportedDataSourceError:
                logger.debug(f"Skipping usage {usage.id} for unsupported data source: {data_source}")
                continue
        
        return snippets