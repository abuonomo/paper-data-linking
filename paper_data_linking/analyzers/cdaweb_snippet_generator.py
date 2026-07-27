"""CDAWeb-specific snippet generator for DatasetUsage records."""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from .snippet_generator_base import BaseDatasetUsageSnippetGenerator
from .snippet_generator_registry import DataSourceSnippetGeneratorRegistry

logger = logging.getLogger(__name__)


@DataSourceSnippetGeneratorRegistry.register("cdaweb", version="2.0", data_sources=["cdaweb"])
class CDAWebDatasetUsageSnippetGenerator(BaseDatasetUsageSnippetGenerator):
    """
    Generates SunPy Fido.search snippets for CDAWeb-based DatasetUsage records.

    Internally uses HDPWS to discover matching CDAWeb datasets, then generates
    clean SunPy scripts for each discovered dataset. Users see only the SunPy
    scripts, not the HDPWS discovery logic.
    """

    def generate_snippet(self, dataset_usage, query_name: Optional[str] = None, include_imports: bool = True) -> str:
        """
        Generate SunPy Fido.search snippet(s) for a CDAWeb DatasetUsage.

        Runs HDPWS internally to discover matching datasets, extracts their
        CDAWeb ProductKeys, and generates corresponding SunPy scripts.

        Args:
            dataset_usage: DatasetUsage model instance
            query_name: Unused, kept for interface compatibility
            include_imports: Whether to include SunPy imports (default: True)

        Returns:
            Python code snippet as string containing SunPy Fido.search calls
        """
        # Validate this is a CDAWeb dataset usage
        if dataset_usage.instrument.observatory.datasource.slug != 'cdaweb':
            return f"# Unsupported datasource: {dataset_usage.instrument.observatory.datasource.slug}"

        # Extract parameters from dataset usage
        params = self._extract_parameters(dataset_usage)

        # Run HDPWS internally to discover matching datasets
        discovered_datasets = self._discover_datasets_via_hdpws(params)

        if not discovered_datasets:
            return self._build_no_datasets_found_snippet(params)

        # Generate SunPy scripts for each discovered dataset
        snippet = self._build_sunpy_scripts(discovered_datasets, params)

        if include_imports:
            imports = self._get_imports()
            return imports + "\n\n" + snippet
        else:
            return snippet

    def _get_imports(self) -> str:
        """Get necessary imports for SunPy scripts."""
        return "from sunpy.net import Fido, attrs as a"

    def _extract_parameters(self, usage) -> dict:
        """Extract and process parameters from DatasetUsage for script generation."""
        instrument_id = usage.instrument.short_name
        observatory_name = usage.instrument.observatory.short_name if usage.instrument.observatory else "Unknown"

        # Format dates for SunPy (YYYY/MM/DD format)
        start = usage.observation_window.lower.strftime('%Y/%m/%d')
        end = usage.observation_window.upper.strftime('%Y/%m/%d')

        # For HDPWS filtering, we need ISO format dates
        start_iso = usage.observation_window.lower.strftime('%Y-%m-%d')
        end_iso = usage.observation_window.upper.strftime('%Y-%m-%d')

        # HDPWS requires a time range with duration > 0
        if start_iso == end_iso:
            end_date = usage.observation_window.upper + timedelta(days=1)
            end_iso = end_date.strftime('%Y-%m-%d')
            end = end_date.strftime('%Y/%m/%d')

        # Handle nested normalized structure for cadences
        cadence_data = usage.extra_params.get('cadence', {}) if usage.extra_params else {}
        identified_cadences = cadence_data.get('cadences') if isinstance(cadence_data, dict) else None

        return {
            'instrument_id': instrument_id,
            'observatory_name': observatory_name,
            'start_date': start,
            'end_date': end,
            'start_date_iso': start_iso,
            'end_date_iso': end_iso,
            'cadences': identified_cadences
        }

    def _discover_datasets_via_hdpws(self, params: dict) -> List[Dict[str, Any]]:
        """
        Run HDPWS query internally to discover matching CDAWeb datasets.

        Args:
            params: Dictionary with instrument_id, start_date_iso, end_date_iso, cadences

        Returns:
            List of dicts with dataset info: {product_key, name, cadence, resource_id}
        """
        try:
            from hdpws.hdpws import HdpWs
            from hdpws.resourcetype import ResourceType as rt
            from hdpws import NAMESPACES as NS
        except ImportError as e:
            logger.warning(f"HDPWS not available for dataset discovery: {e}")
            return []

        try:
            hdp = HdpWs()

            types = [rt.NUMERICAL_DATA]
            query_params = {'InstrumentID': params['instrument_id']}

            response = hdp.get_spase_data(types, query_params)

            if response.get('HttpStatus') != 200 or response.get('Result') is None:
                logger.warning(f"HDPWS query failed or returned no results for {params['instrument_id']}")
                return []

            xml_result = response['Result']
            spase_datasets = xml_result.findall('.//Spase', namespaces=NS)

            # Filter for datasets that match our specific instrument ID
            matching_datasets = []
            for dataset in spase_datasets:
                instruments = dataset.findall('.//InstrumentID', namespaces=NS)
                for instr in instruments:
                    if instr.text and instr.text.strip() == params['instrument_id']:
                        matching_datasets.append(dataset)
                        break

            # Filter by time range
            start_dt = datetime.fromisoformat(params['start_date_iso'])
            end_dt = datetime.fromisoformat(params['end_date_iso'])

            time_filtered_datasets = []
            for dataset in matching_datasets:
                start_elem = dataset.find('.//TemporalDescription/TimeSpan/StartDate', namespaces=NS)
                stop_elem = dataset.find('.//TemporalDescription/TimeSpan/StopDate', namespaces=NS)

                if start_elem is not None and stop_elem is not None:
                    try:
                        dataset_start = datetime.fromisoformat(start_elem.text.replace('Z', '+00:00'))
                        dataset_stop = datetime.fromisoformat(stop_elem.text.replace('Z', '+00:00'))

                        # Check if dataset time range overlaps with our requested range
                        if dataset_start.replace(tzinfo=None) <= end_dt and dataset_stop.replace(tzinfo=None) >= start_dt:
                            time_filtered_datasets.append(dataset)
                    except Exception:
                        # If date parsing fails, include the dataset anyway
                        time_filtered_datasets.append(dataset)
                else:
                    # If no time info, include the dataset
                    time_filtered_datasets.append(dataset)

            # Filter by cadence if specified
            if params['cadences']:
                cadence_filtered = []
                for dataset in time_filtered_datasets:
                    cadence_elem = dataset.find('.//Cadence', namespaces=NS)
                    if cadence_elem is not None and cadence_elem.text in params['cadences']:
                        cadence_filtered.append(dataset)
                time_filtered_datasets = cadence_filtered if cadence_filtered else time_filtered_datasets

            # Extract ProductKey and metadata from each dataset
            discovered = []
            for dataset in time_filtered_datasets:
                dataset_info = self._extract_dataset_info(dataset, NS)
                if dataset_info and dataset_info.get('product_key'):
                    discovered.append(dataset_info)

            logger.info(f"Discovered {len(discovered)} CDAWeb datasets for {params['instrument_id']}")
            return discovered

        except Exception as e:
            logger.error(f"Error during HDPWS dataset discovery: {e}")
            return []

    def _extract_dataset_info(self, dataset_element, namespaces: dict) -> Optional[Dict[str, Any]]:
        """
        Extract CDAWeb ProductKey and metadata from a SPASE dataset element.

        Looks for AccessURL with Name containing 'CDAWeb' and extracts the ProductKey.
        """
        try:
            info = {}

            # Extract basic metadata
            name_elem = dataset_element.find('.//ResourceHeader/ResourceName', namespaces=namespaces)
            if name_elem is not None:
                info['name'] = name_elem.text

            id_elem = dataset_element.find('.//ResourceID', namespaces=namespaces)
            if id_elem is not None:
                info['resource_id'] = id_elem.text

            cadence_elem = dataset_element.find('.//Cadence', namespaces=namespaces)
            if cadence_elem is not None:
                info['cadence'] = cadence_elem.text

            # Find CDAWeb AccessURL and extract ProductKey
            access_urls = dataset_element.findall('.//AccessURL', namespaces=namespaces)
            for access_url in access_urls:
                name_elem = access_url.find('Name', namespaces=namespaces)
                if name_elem is not None and 'CDAWeb' in (name_elem.text or ''):
                    product_key_elem = access_url.find('ProductKey', namespaces=namespaces)
                    if product_key_elem is not None and product_key_elem.text:
                        info['product_key'] = product_key_elem.text.strip()
                        break

            # Fallback: try to find ProductKey anywhere in AccessInformation
            if 'product_key' not in info:
                product_keys = dataset_element.findall('.//ProductKey', namespaces=namespaces)
                for pk in product_keys:
                    if pk.text:
                        info['product_key'] = pk.text.strip()
                        break

            return info if info.get('product_key') else None

        except Exception as e:
            logger.debug(f"Failed to extract dataset info: {e}")
            return None

    def _build_sunpy_scripts(self, datasets: List[Dict[str, Any]], params: dict) -> str:
        """
        Build SunPy Fido.search scripts for discovered datasets.

        Args:
            datasets: List of dataset info dicts with product_key, name, etc.
            params: Original query parameters (start_date, end_date, etc.)
            query_name: Base name for result variables

        Returns:
            Python code string with SunPy Fido.search calls
        """
        lines = [
            f"# CDAWeb datasets for {params['instrument_id']} on {params['observatory_name']}",
            f"# Time range: {params['start_date']} to {params['end_date']}",
            "",
            f"trange = a.Time('{params['start_date']}', '{params['end_date']}')",
        ]

        for i, dataset in enumerate(datasets, 1):
            product_key = dataset['product_key']
            name = dataset.get('name', 'Unknown Dataset')

            lines.extend([
                "",
                f"# {name}",
                f"dataset_{i} = Fido.search(trange, a.cdaweb.Dataset('{product_key}'))",
            ])

        script = "\n".join(lines) + "\n"

        return script

    def _build_no_datasets_found_snippet(self, params: dict) -> str:
        """Generate a helpful snippet when no datasets are found via HDPWS."""
        return f"""# No CDAWeb datasets found for {params['instrument_id']} on {params['observatory_name']}
# Time range: {params['start_date']} to {params['end_date']}
#
# - CDAWeb, does not provide a dataset that covers the observatory, instrument pair in the time range.  
#
# Try searching manually at: https://cdaweb.gsfc.nasa.gov/
"""
