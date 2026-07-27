from typing import Dict, List, Any, Optional
import json
from datetime import datetime


class VSOValidator:
    def __init__(self, vso_data: List[Dict[str, Any]]):
        """
        Initialize validator with VSO data from JSONLines file.

        Args:
            vso_data: List of dictionaries containing VSO parameter combinations
        """
        self.vso_data = vso_data
        # Index data by source and instrument for faster lookups
        self.source_instrument_map = {}
        for entry in vso_data:
            source = entry['source']
            instrument = entry['instrument']
            if source not in self.source_instrument_map:
                self.source_instrument_map[source] = {}
            if instrument not in self.source_instrument_map[source]:
                self.source_instrument_map[source][instrument] = []
            self.source_instrument_map[source][instrument].append(entry)

    def validate_search_call(self, search_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a single Fido search call against known VSO parameter combinations.

        Args:
            search_call: Dictionary containing search parameters

        Returns:
            Dictionary with validation results
        """
        result = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }

        # Extract source from other_attrs if present
        source = None
        for attr in search_call.get('other_attrs', []):
            if 'Source' in attr:
                if 'Source(' in attr:
                    # Handle format: Source(SOHO: Solar...)
                    source = attr.split('(')[1].split(':')[0]
                else:
                    # Handle format: Source: STEREO_A
                    source = attr.split(':')[1].split()[0].strip()
                break

        # Basic parameter presence checks
        if not search_call.get('instruments'):
            result['errors'].append('No instrument specified')
            result['is_valid'] = False
            return result

        if not source:
            result['errors'].append('No source specified')
            result['is_valid'] = False
            return result

        # Get instrument and check source-instrument combination
        instrument = search_call['instruments'][0]
        if not self._validate_source_instrument(source, instrument):
            result['errors'].append(f'Invalid source-instrument combination: {source}-{instrument}')
            result['is_valid'] = False
            return result

        # Get matching VSO entries for this source-instrument combination
        vso_entries = self.source_instrument_map.get(source, {}).get(instrument, [])
        if not vso_entries:
            result['errors'].append(f'No VSO data found for {source}-{instrument}')
            result['is_valid'] = False
            return result

        # Validate time ranges
        time_validation = self._validate_time_ranges(search_call.get('time_ranges', []), vso_entries)
        if time_validation.get('errors'):
            result['errors'].extend(time_validation['errors'])
            result['is_valid'] = False
        if time_validation.get('warnings'):
            result['warnings'].extend(time_validation['warnings'])

        # Validate wavelengths if present
        if search_call.get('wavelengths'):
            wavelength_validation = self._validate_wavelengths(search_call['wavelengths'], vso_entries)
            if wavelength_validation.get('errors'):
                result['errors'].extend(wavelength_validation['errors'])
                result['is_valid'] = False
            if wavelength_validation.get('warnings'):
                result['warnings'].extend(wavelength_validation['warnings'])

        return result

    def _validate_source_instrument(self, source: str, instrument: str) -> bool:
        """Check if source-instrument combination exists in VSO data."""
        return source in self.source_instrument_map and instrument in self.source_instrument_map[source]

    def _validate_time_ranges(self, time_ranges: List[Dict[str, str]],
                              vso_entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Validate time ranges against VSO data."""
        result = {'errors': [], 'warnings': []}

        if not time_ranges:
            result['warnings'].append('No time ranges specified')
            return result

        for time_range in time_ranges:
            start_time = datetime.fromisoformat(time_range['start'].replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(time_range['end'].replace('Z', '+00:00'))

            # Check against each VSO entry's time range
            valid_for_any = False
            for entry in vso_entries:
                # Convert millisecond timestamps to datetime
                vso_start = datetime.fromtimestamp(entry['start_date'] / 1000)
                vso_end = (datetime.fromtimestamp(entry['end_date'] / 1000)
                           if entry['end_date'] != 'continuing'
                           else datetime.now())

                if start_time >= vso_start and end_time <= vso_end:
                    valid_for_any = True
                    break

            if not valid_for_any:
                result['errors'].append(
                    f'Time range {time_range["start"]} to {time_range["end"]} '
                    f'not valid for {vso_entries[0]["source"]}-{vso_entries[0]["instrument"]}'
                )

        return result

    def _validate_wavelengths(self, wavelengths: List[Dict[str, Any]],
                              vso_entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Validate wavelength ranges against VSO data."""
        result = {'errors': [], 'warnings': []}

        if not wavelengths:
            return result

        for wavelength in wavelengths:
            valid_for_any = False
            for entry in vso_entries:
                vso_spectral_ranges = entry.get('spectral_range', [])
                if not vso_spectral_ranges:
                    continue

                # Handle different spectral range formats in VSO data
                for spectral_range in vso_spectral_ranges:
                    if isinstance(spectral_range, list):
                        # Range specified as [min, max]
                        if wavelength['min'] >= spectral_range[0] and wavelength['max'] <= spectral_range[1]:
                            valid_for_any = True
                            break
                    else:
                        # Single wavelength value
                        if wavelength['min'] <= spectral_range <= wavelength['max']:
                            valid_for_any = True
                            break

            if not valid_for_any:
                result['errors'].append(
                    f'Wavelength range {wavelength} not valid for '
                    f'{vso_entries[0]["source"]}-{vso_entries[0]["instrument"]}'
                )

        return result

    def validate_multiple_search_calls(self, search_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate multiple search calls and return results for each."""
        return [self.validate_search_call(call) for call in search_calls]


# Example usage:
def load_vso_data(jsonl_file_path: str) -> List[Dict[str, Any]]:
    """Load VSO data from JSONLines file."""
    vso_data = []
    with open(jsonl_file_path, 'r') as f:
        for line in f:
            vso_data.append(json.loads(line))
    return vso_data


def create_validator(jsonl_file_path: str) -> VSOValidator:
    """Create a VSO validator from a JSONLines file."""
    vso_data = load_vso_data(jsonl_file_path)
    return VSOValidator(vso_data)
