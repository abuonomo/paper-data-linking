"""VSO-specific snippet generator for DatasetUsage records."""

from typing import Optional

from .snippet_generator_base import BaseDatasetUsageSnippetGenerator
from .snippet_generator_registry import DataSourceSnippetGeneratorRegistry


@DataSourceSnippetGeneratorRegistry.register("vso", version="1.0", data_sources=["vso"])
class VSO_DatasetUsageSnippetGenerator(BaseDatasetUsageSnippetGenerator):
    """
    Generates SunPy/Fido.search Python snippets for VSO-based DatasetUsage records.
    Extracted from the original DatasetUsageSnippetGenerator logic.
    """
    
    def generate_snippet(self, dataset_usage, query_name: Optional[str] = None, include_imports: bool = True) -> str:
        """
        Generate an individual Python snippet for a single VSO DatasetUsage.
        
        Args:
            dataset_usage: DatasetUsage model instance
            query_name: Optional name for the query variable
            include_imports: Whether to include SunPy imports (default: True)
            
        Returns:
            Python code snippet as string
        """
        if not query_name:
            query_name = "query"

        # Validate this is a VSO dataset usage
        if dataset_usage.instrument.observatory.datasource.slug != 'vso':
            return f"# Unsupported datasource: {dataset_usage.instrument.observatory.datasource.slug}"
        
        snippet = self._build_vso_query(dataset_usage, query_name)
        
        if include_imports:
            imports = "from sunpy.net import Fido, attrs as a\nimport astropy.units as u\n\n"
            return imports + snippet
        else:
            return snippet
    
    def _build_vso_query(self, usage, query_name: str) -> str:
        """
        Builds a single Fido.search query for a VSO-based DatasetUsage.
        Reuses logic from original DatasetUsageSnippetGenerator for consistency.
        """
        instrument_attr = usage.instrument.short_name
        source_attr = usage.instrument.observatory.short_name if usage.instrument.observatory else None
        start = usage.observation_window.lower.strftime('%Y-%m-%d %H:%M:%S')
        end = usage.observation_window.upper.strftime('%Y-%m-%d %H:%M:%S')

        # Handle nested normalized structure for physical_observable
        physobs_data = usage.extra_params.get('physical_observable', {}) if usage.extra_params else {}
        physobs_attr = physobs_data.get('physical_observable') if isinstance(physobs_data, dict) else None

        # Handle nested normalized structure for detector
        detector_data = usage.extra_params.get('detector', {}) if usage.extra_params else {}
        detector_attr = detector_data.get('detector') if isinstance(detector_data, dict) else None

        # Handle nested normalized structure for wavelengths (new range-based schema)
        wavelength_data = usage.extra_params.get('wavelengths', {}) if usage.extra_params else {}
        wavelength_ranges = wavelength_data.get('ranges', []) if isinstance(wavelength_data, dict) else []

        detector_info = f" (detector: {detector_attr})" if detector_attr else ""
        comment_line = (
            f"# Query for {usage.instrument.short_name} on {source_attr.upper() if source_attr else 'N/A'}{detector_info}"
        )

        query_parts = [
            f"{query_name} = Fido.search("
        ]

        if source_attr:
            query_parts.append(f"    a.Source('{source_attr}'),")
        query_parts.append(f"    a.Instrument('{instrument_attr}'),")

        # Add detector if available (critical for instruments like SECCHI)
        if detector_attr:
            query_parts.append(f"    a.Detector('{detector_attr}'),")

        query_parts.append(f"    a.Time('{start}', '{end}')")

        # Add wavelength constraints if available
        if wavelength_ranges:
            wavelength_attr = self._format_wavelength_attr(wavelength_ranges)
            if wavelength_attr:
                if query_parts[-1][-1] != ',':
                    query_parts[-1] += ','
                query_parts.append(f"    {wavelength_attr}")

        if physobs_attr:
            if query_parts[-1][-1] != ',':
                query_parts[-1] += ','
            query_parts.append(f"    a.Physobs('{physobs_attr}')")

        query_parts.append(")")

        return comment_line + "\n" + "\n".join(query_parts)

    def _format_wavelength_attr(self, ranges: list) -> Optional[str]:
        """
        Format wavelength ranges into SunPy Wavelength attribute syntax.

        Args:
            ranges: List of wavelength range dicts with min, max, unit fields

        Returns:
            Formatted wavelength attribute string or None if invalid
        """
        if not ranges:
            return None

        # Map units to astropy unit syntax
        unit_map = {
            'angstrom': 'u.angstrom',
            'nm': 'u.nm',
            'kev': 'u.keV',
            'khz': 'u.kHz',
            'mhz': 'u.MHz',
            'ghz': 'u.GHz',
            'hz': 'u.Hz',
        }

        wavelength_attrs = []
        for r in ranges:
            unit = r.get('unit', '').lower()
            astropy_unit = unit_map.get(unit)

            if not astropy_unit:
                continue  # Skip unsupported units

            min_val = r.get('min')
            max_val = r.get('max')

            if min_val is None or max_val is None:
                continue

            # For discrete values (min == max), use single wavelength syntax
            if min_val == max_val:
                wavelength_attrs.append(f"a.Wavelength({min_val}*{astropy_unit})")
            else:
                # For ranges, specify both min and max
                wavelength_attrs.append(f"a.Wavelength({min_val}*{astropy_unit}, {max_val}*{astropy_unit})")

        if not wavelength_attrs:
            return None

        # Single wavelength: return directly
        if len(wavelength_attrs) == 1:
            return wavelength_attrs[0]

        # Multiple wavelengths: use AttrOr
        return f"a.AttrOr([{', '.join(wavelength_attrs)}])"