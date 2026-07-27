"""Granular analyzer implementations for individual dataset usage snippets."""

import ast
import os
import signal
import subprocess
import sys
import tempfile
import traceback
import warnings
from contextlib import contextmanager
from io import StringIO
from typing import Dict, Any

from .base import BaseDatasetUsageAnalyzer
from .registry import DatasetUsageAnalyzerRegistry

# Hard caps on the hang-prone steps. `exec(snippet)` runs a live Fido network query
# and `bandit` is a subprocess — both had NO timeout, which deterministically wedged
# the worker at scale. These are the inner (defense-in-depth) limits; the Celery task
# soft/hard time_limit on the prefork `cpu` queue is the outer backstop.
EXEC_TIMEOUT_SECONDS = int(os.getenv("ANALYZE_EXEC_TIMEOUT", "45"))
BANDIT_TIMEOUT_SECONDS = int(os.getenv("ANALYZE_BANDIT_TIMEOUT", "30"))


class AnalyzerTimeout(Exception):
    """Raised when a hang-prone analyzer step exceeds its inner time limit."""


@contextmanager
def time_limit(seconds: int):
    """SIGALRM-based wall-clock timeout. Only works in a process main thread
    (i.e. the prefork worker) — a no-op elsewhere (e.g. gevent), where the Celery
    task hard time_limit is the backstop."""
    def _handler(signum, frame):
        raise AnalyzerTimeout(f"timed out after {seconds}s")

    try:
        old = signal.signal(signal.SIGALRM, _handler)
    except (ValueError, AttributeError):
        # Not the main thread / no SIGALRM — rely on the Celery task time_limit.
        yield
        return
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


@contextmanager
def suppress_gevent_fork_warnings():
    """
    Suppress gevent fork warnings around subprocess/exec operations.
    
    When using Celery with --pool=gevent, subprocess and exec operations
    can trigger gevent threading warnings that are harmless but noisy.
    This context manager suppresses those specific warnings.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*after_fork_in_child.*") 
        warnings.filterwarnings("ignore", message=".*ForkHooks.*")
        warnings.filterwarnings("ignore", message=".*assert not thread.is_alive.*")
        warnings.filterwarnings("ignore", message=".*AssertionError.*")
        yield

# Import sunpy components for execution analysis
try:
    from sunpy.net import Fido, attrs as a
    from sunpy.net.dataretriever.client import QueryResponse
    from sunpy.net.fido_factory import UnifiedResponse
    SUNPY_AVAILABLE = True
except ImportError:
    SUNPY_AVAILABLE = False


@DatasetUsageAnalyzerRegistry.register("QuerySyntax", data_sources=["vso", "cdaweb"])
class QuerySyntaxAnalyzer(BaseDatasetUsageAnalyzer):
    """Analyzes syntax validity of individual query snippets for all data sources."""
    
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        results = {
            'is_valid': False,
            'syntax_error': '',
            'analyzer_name': 'QuerySyntaxAnalyzer'
        }
        
        if not snippet or not snippet.strip():
            results['syntax_error'] = 'Empty snippet'
            return results
        
        try:
            # Add required imports for parsing
            full_code = "from sunpy.net import Fido, attrs as a\n" + snippet
            ast.parse(full_code)
            results['is_valid'] = True
        except SyntaxError as e:
            results['syntax_error'] = f"Syntax error: {str(e)}"
        except Exception as e:
            results['syntax_error'] = f"Parse error: {str(e)}"
        
        return results


@DatasetUsageAnalyzerRegistry.register("QuerySecurity", data_sources=["vso", "cdaweb"])
class QuerySecurityAnalyzer(BaseDatasetUsageAnalyzer):
    """Analyzes security issues in individual query snippets using bandit for all data sources."""
    
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        results = {
            'is_safe': False,
            'security_issues': [],
            'analyzer_name': 'QuerySecurityAnalyzer'
        }
        
        if not snippet or not snippet.strip():
            results['security_issues'] = ['Empty snippet']
            return results
        
        try:
            # Add required imports for analysis
            full_code = "from sunpy.net import Fido, attrs as a\n" + snippet
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode='w') as temp:
                temp.write(full_code)
                temp.flush()
                
                # Run Bandit (suppress gevent warnings from subprocess)
                try:
                    with suppress_gevent_fork_warnings():
                        process = subprocess.run(
                            ["bandit", temp.name, "-f", "json"],
                            capture_output=True,
                            text=True,
                            timeout=BANDIT_TIMEOUT_SECONDS,
                        )
                except subprocess.TimeoutExpired:
                    os.remove(temp.name)
                    # Fail closed: a bandit hang blocks execution (treated unsafe).
                    results['is_safe'] = False
                    results['security_issues'] = [
                        f"Bandit timed out after {BANDIT_TIMEOUT_SECONDS}s"]
                    return results

                # Clean up
                os.remove(temp.name)

                if process.returncode == 0:
                    results['is_safe'] = True
                else:
                    try:
                        import json
                        bandit_output = json.loads(process.stdout)
                        for result in bandit_output.get('results', []):
                            results['security_issues'].append({
                                'test_id': result.get('test_id'),
                                'test_name': result.get('test_name'),
                                'issue_severity': result.get('issue_severity'),
                                'issue_text': result.get('issue_text')
                            })
                    except (json.JSONDecodeError, KeyError):
                        results['security_issues'] = [f"Bandit failed: {process.stderr}"]
                
        except Exception as e:
            results['security_issues'] = [f"Security analysis failed: {str(e)}"]
        
        return results


@DatasetUsageAnalyzerRegistry.register("QueryExecution", data_sources=["vso"])
class QueryExecutionAnalyzer(BaseDatasetUsageAnalyzer):
    """Executes individual VSO query snippets and captures results ONLY if security checks pass."""
    
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        results = {
            'execution_successful': False,
            'execution_error': '',
            'total_results_found': 0,
            'query_response_summary': {},
            'analyzer_name': 'QueryExecutionAnalyzer'
        }
        
        if not SUNPY_AVAILABLE:
            results['execution_error'] = 'SunPy not available for execution'
            return results
        
        if not snippet or not snippet.strip():
            results['execution_error'] = 'Empty snippet'
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
            # Execute the complete self-contained snippet (no global context needed)
            exec_globals = {'__builtins__': __builtins__}
            exec_locals = {}

            # Suppress gevent warnings from exec operations; hard-cap the live Fido
            # network query so a hung request can't wedge the worker.
            with suppress_gevent_fork_warnings(), time_limit(EXEC_TIMEOUT_SECONDS):
                exec(snippet, exec_globals, exec_locals)

            # Find the query result variable (should be query* pattern)
            query_result = None
            for var_name, var_value in exec_locals.items():
                if var_name.startswith('query') and isinstance(var_value, (QueryResponse, UnifiedResponse)):
                    query_result = var_value
                    break
            
            if query_result is not None:
                results['execution_successful'] = True
                results['total_results_found'] = len(query_result)
                
                # Extract detailed response information using the same approach as RealFidoExecutionAnalyzer
                self._extract_response_info('query_result', query_result, results)
                
            else:
                results['execution_error'] = 'No query result found in executed snippet'
                
        except Exception as e:
            results['execution_error'] = f"Execution failed: {str(e)}"
            results['execution_traceback'] = traceback.format_exc()
        
        return results
    
    def _extract_response_info(self, var_name, value, results):
        """Extract information from a UnifiedResponse object and add to results"""
        # Initialize search_results list if it doesn't exist
        if 'search_results' not in results:
            results['search_results'] = []
            results['total_results'] = 0
        
        # For empty results, create basic info
        if value.file_num == 0:
            response_info = {
                'variable': var_name,
                'num_results': 0,
                'providers': [],
                'all_columns': [],
                'path_format_keys': []
            }
            results['search_results'].append(response_info)
            return

        # For each UnifiedResponse, get detailed info about all results
        response_info = {
            'variable': var_name,
            'num_results': value.file_num,
            'providers': [],
            'all_columns': list(value.all_colnames),
            'path_format_keys': list(value.path_format_keys())
        }

        # Handle each data source's results
        for key in value.keys():
            source_response = value[key]
            # Handle both QueryResponse and VSOQueryResponseTable
            if hasattr(source_response, 'colnames') and hasattr(source_response, '__len__'):
                # Get time range if available
                time_info = {}
                if hasattr(source_response, 'time_range'):
                    try:
                        time_range = source_response.time_range()
                        time_info = {
                            'start': str(time_range.start),
                            'end': str(time_range.end),
                            'duration_seconds': time_range.seconds.value
                        }
                    except Exception:
                        pass
                
                source_info = {
                    'source': key,
                    'num_results': len(source_response),
                    'time_range': time_info,
                    'available_columns': list(source_response.colnames),
                }

                # Extract various metadata from columns if available
                self._extract_column_data(source_response, source_info)
                response_info['providers'].append(source_info)

        results['search_results'].append(response_info)
        results['total_results'] = response_info['num_results']

    def _extract_column_data(self, source_response, source_info):
        """Extract various metadata from QueryResponse columns"""
        columns_to_extract = {
            'Instrument': 'instruments',
            'Provider': 'providers',
            'Resolution': 'resolutions',
            'Physobs': 'physobs',
            'Source': 'telescopes',
            'Wavelength': 'wavelengths',
            'Detector': 'detectors'
        }

        for column, target in columns_to_extract.items():
            if column in source_response.colnames:
                try:
                    source_info[target] = list(set(str(item) for item in source_response[column]))
                except Exception:
                    pass
    
    def _run_security_check(self, snippet: str) -> Dict[str, Any]:
        """Run security analysis before execution"""
        security_analyzer = QuerySecurityAnalyzer()
        return security_analyzer.analyze_snippet(None, snippet)  # dataset_usage not needed for security check
    
    def _run_syntax_check(self, snippet: str) -> Dict[str, Any]:
        """Run syntax validation before execution"""
        syntax_analyzer = QuerySyntaxAnalyzer()
        return syntax_analyzer.analyze_snippet(None, snippet)  # dataset_usage not needed for syntax check


@DatasetUsageAnalyzerRegistry.register("TimeRangeValidation", data_sources=["vso", "cdaweb"])
class TimeRangeValidationAnalyzer(BaseDatasetUsageAnalyzer):
    """Validates time ranges in query snippets for reasonableness for all data sources."""
    
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        results = {
            'time_range_valid': False,
            'time_range_issues': [],
            'time_range_duration_days': 0,
            'analyzer_name': 'TimeRangeValidationAnalyzer'
        }
        
        try:
            # Extract time range from dataset_usage
            if dataset_usage.observation_window:
                start_time = dataset_usage.observation_window.lower
                end_time = dataset_usage.observation_window.upper
                
                if start_time and end_time:
                    duration = end_time - start_time
                    duration_days = duration.total_seconds() / 86400  # Convert to days
                    results['time_range_duration_days'] = round(duration_days, 2)
                    
                    # Validate time range
                    if duration_days <= 0:
                        results['time_range_issues'].append('Invalid time range: end time before start time')
                    elif duration_days > 365 * 10:  # More than 10 years
                        results['time_range_issues'].append(f'Very long time range: {duration_days:.1f} days')
                    elif duration_days < 1/24:  # Less than 1 hour
                        results['time_range_issues'].append(f'Very short time range: {duration_days*24:.2f} hours')
                    else:
                        results['time_range_valid'] = True
                else:
                    results['time_range_issues'].append('Missing start or end time')
            else:
                results['time_range_issues'].append('No observation window found')
                
        except Exception as e:
            results['time_range_issues'].append(f"Time range validation failed: {str(e)}")
        
        return results


@DatasetUsageAnalyzerRegistry.register("InstrumentValidation", data_sources=["vso", "cdaweb"])
class InstrumentValidationAnalyzer(BaseDatasetUsageAnalyzer):
    """Validates instrument parameters in query snippets for all data sources."""
    
    def analyze_snippet(self, dataset_usage, snippet: str) -> Dict[str, Any]:
        results = {
            'instrument_valid': False,
            'instrument_issues': [],
            'extracted_params': {},
            'analyzer_name': 'InstrumentValidationAnalyzer'
        }
        
        try:
            # Extract instrument information from dataset_usage
            instrument = dataset_usage.instrument
            observatory = instrument.observatory if instrument else None
            
            results['extracted_params'] = {
                'instrument_name': instrument.short_name if instrument else None,
                'observatory_name': observatory.short_name if observatory else None,
                'data_source': instrument.observatory.datasource.slug if instrument and instrument.observatory and instrument.observatory.datasource else None
            }
            
            # Basic validation
            if not instrument:
                results['instrument_issues'].append('No instrument found')
            elif not instrument.short_name:
                results['instrument_issues'].append('Instrument missing short_name')
            else:
                # Check if snippet contains expected instrument parameters
                snippet_lower = snippet.lower()
                instrument_name_lower = instrument.short_name.lower()
                
                if f"'{instrument_name_lower}'" in snippet_lower or f'"{instrument_name_lower}"' in snippet_lower:
                    results['instrument_valid'] = True
                else:
                    results['instrument_issues'].append(f'Snippet does not contain expected instrument: {instrument.short_name}')
                
                # Check observatory if available
                if observatory and observatory.short_name:
                    observatory_slug_lower = observatory.short_name.lower()
                    if f"'{observatory_slug_lower}'" not in snippet_lower and f'"{observatory_slug_lower}"' not in snippet_lower:
                        results['instrument_issues'].append(f'Snippet may be missing observatory: {observatory.short_name}')
                        
        except Exception as e:
            results['instrument_issues'].append(f"Instrument validation failed: {str(e)}")
        
        return results