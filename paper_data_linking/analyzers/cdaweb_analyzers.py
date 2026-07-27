"""CDAWEB-specific analyzer implementations for dataset usage snippets."""

import logging
from typing import Dict, Any

from .base import BaseDatasetUsageAnalyzer
from .registry import DatasetUsageAnalyzerRegistry

logger = logging.getLogger(__name__)


@DatasetUsageAnalyzerRegistry.register("QueryExecution.cdaweb", data_sources=["cdaweb"])
class CDAWebQueryExecutionAnalyzer(BaseDatasetUsageAnalyzer):
    """
    Executes individual CDAWeb/SunPy query snippets and captures results.

    Expects SunPy Fido.search scripts and parses UnifiedResponse results.
    """

    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        """
        Execute a SunPy Fido.search snippet and analyze results.

        Args:
            dataset_usage: DatasetUsage model instance
            snippet: Generated SunPy Python code snippet as string

        Returns:
            Dictionary containing execution analysis results
        """
        results = {
            'execution_successful': False,
            'execution_error': '',
            'total_datasets_found': 0,
            'total_records_found': 0,
            'query_response_summary': {},
            'analyzer_name': 'CDAWebQueryExecutionAnalyzer'
        }

        # Check if SunPy is available
        try:
            from sunpy.net import Fido, attrs as a
        except ImportError as e:
            results['execution_error'] = f'SunPy not available for execution: {str(e)}'
            return results

        if not snippet or not snippet.strip():
            results['execution_error'] = 'Empty snippet'
            return results

        # Check if this is a "no datasets found" snippet
        if snippet.strip().startswith('# No CDAWeb datasets found'):
            results['execution_error'] = 'No datasets were discovered via HDPWS'
            results['query_response_summary'] = {
                'message': 'HDPWS discovery found no matching datasets'
            }
            return results

        # SECURITY CHECK: Only execute if security validation passes
        security_check = self._run_security_check(snippet)
        if not security_check['is_safe']:
            results['execution_error'] = f"Security check failed - execution blocked: {security_check['security_issues']}"
            results['security_check_results'] = security_check
            return results

        # SYNTAX CHECK: Only execute if syntax is valid
        syntax_check = self._run_syntax_check(snippet)
        if not syntax_check['is_valid']:
            results['execution_error'] = f"Syntax check failed - execution blocked: {syntax_check['syntax_error']}"
            results['syntax_check_results'] = syntax_check
            return results

        try:
            # Execute the SunPy snippet
            exec_globals = {
                '__builtins__': __builtins__,
                'Fido': Fido,
                'a': a,
            }
            exec_locals = {}

            # Execute the snippet
            exec(snippet, exec_globals, exec_locals)

            # Find all Fido.search results (UnifiedResponse objects)
            fido_results = []
            for var_name, var_value in exec_locals.items():
                # Check if this is a UnifiedResponse from Fido.search
                if hasattr(var_value, '__class__') and 'UnifiedResponse' in var_value.__class__.__name__:
                    fido_results.append({
                        'variable': var_name,
                        'response': var_value
                    })

            if fido_results:
                # Analyze all Fido search results
                total_records = 0
                dataset_summaries = []

                for fido_result in fido_results:
                    response = fido_result['response']
                    var_name = fido_result['variable']

                    # Extract info from UnifiedResponse
                    summary = self._extract_fido_response_info(response, var_name)
                    dataset_summaries.append(summary)
                    total_records += summary.get('record_count', 0)

                results['total_datasets_found'] = len(fido_results)
                results['total_records_found'] = total_records
                results['query_response_summary'] = {
                    'fido_searches': len(fido_results),
                    'total_records': total_records,
                    'datasets': dataset_summaries
                }
                results['execution_successful'] = True

                logger.info(f"SunPy execution found {len(fido_results)} datasets with {total_records} total records")
            else:
                results['execution_error'] = 'No Fido.search results found in executed snippet'
                # Debug info
                results['debug_variables'] = {k: type(v).__name__ for k, v in exec_locals.items()}

        except Exception as e:
            results['execution_error'] = f"Execution failed: {str(e)}"
            import traceback
            results['execution_traceback'] = traceback.format_exc()
            logger.error(f"SunPy snippet execution failed: {e}")

        return results

    def _extract_fido_response_info(self, response, variable_name: str) -> Dict[str, Any]:
        """
        Extract information from a SunPy UnifiedResponse object.

        Args:
            response: UnifiedResponse from Fido.search
            variable_name: Name of the variable containing the response

        Returns:
            Dictionary with response summary
        """
        try:
            info = {
                'variable': variable_name,
                'record_count': 0,
                'tables': []
            }

            # UnifiedResponse contains a list of response tables
            # Each table corresponds to a data provider (e.g., CDAWeb)
            if hasattr(response, '__len__'):
                for i, table in enumerate(response):
                    # Get provider name as string (not the client object)
                    provider = getattr(table, 'client', None)
                    provider_name = type(provider).__name__ if provider else type(table).__name__

                    table_info = {
                        'index': i,
                        'provider': provider_name,
                    }

                    # Get record count
                    if hasattr(table, '__len__'):
                        table_info['record_count'] = len(table)
                        info['record_count'] += len(table)

                    # Try to extract column info if available
                    if hasattr(table, 'colnames'):
                        table_info['columns'] = list(table.colnames)

                    # Try to get a sample of the data
                    if hasattr(table, '__len__') and len(table) > 0:
                        try:
                            # Get first few records as sample
                            sample_records = []
                            for j in range(min(3, len(table))):
                                record = {}
                                if hasattr(table, 'colnames'):
                                    for col in table.colnames[:5]:  # First 5 columns
                                        try:
                                            record[col] = str(table[j][col])
                                        except Exception:
                                            pass
                                sample_records.append(record)
                            table_info['sample_records'] = sample_records
                        except Exception:
                            pass

                    info['tables'].append(table_info)

            return info

        except Exception as e:
            logger.debug(f"Failed to extract Fido response info: {e}")
            return {
                'variable': variable_name,
                'error': str(e),
                'record_count': 0
            }

    def _run_security_check(self, snippet: str) -> Dict[str, Any]:
        """Run security analysis before execution."""
        from .implementations import QuerySecurityAnalyzer
        security_analyzer = QuerySecurityAnalyzer()
        return security_analyzer.analyze_snippet(None, snippet)

    def _run_syntax_check(self, snippet: str) -> Dict[str, Any]:
        """Run syntax validation before execution."""
        from .implementations import QuerySyntaxAnalyzer
        syntax_analyzer = QuerySyntaxAnalyzer()
        return syntax_analyzer.analyze_snippet(None, snippet)
