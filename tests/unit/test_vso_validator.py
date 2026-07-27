import unittest
from paper_data_linking.linkers.vso_validator import VSOValidator


class TestVSOValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create test VSO data
        cls.vso_data = [
            {
                "provider": "SDAC",
                "source": "SOHO",
                "instrument": "LASCO",
                "detector": ["C2"],
                "physobs": "intensity",
                "spectral_range": [[4000.0, 7000.0]],
                "time_range": None,
                "data_layout": ["image"],
                "observed_region": "CORONA",
                "spectral_range_unit": "Angstrom",
                "start_date": 820454400000,  # 1996-01-01
                "end_date": "continuing"
            },
            {
                "provider": "SSC",
                "source": "STEREO_A",
                "instrument": "SECCHI",
                "detector": ["COR2"],
                "physobs": "intensity",
                "spectral_range": [[6500.0, 7500.0]],
                "time_range": None,
                "data_layout": ["image"],
                "observed_region": "CORONA",
                "spectral_range_unit": "Angstrom",
                "start_date": 1162857600000,  # 2006-11-07
                "end_date": "continuing"
            }
        ]
        cls.validator = VSOValidator(cls.vso_data)

    def test_valid_soho_lasco(self):
        """Test a valid SOHO/LASCO search call."""
        search_call = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
            'wavelengths': [{'min': 4500.0, 'max': 6000.0}]
        }
        result = self.validator.validate_search_call(search_call)
        self.assertTrue(result['is_valid'])
        self.assertEqual(len(result['errors']), 0)

    def test_missing_instrument(self):
        """Test validation when instrument is missing."""
        search_call = {
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('No instrument specified' in error for error in result['errors']))

    def test_missing_source(self):
        """Test validation when source is missing."""
        search_call = {
            'instruments': ['LASCO'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('No source specified' in error for error in result['errors']))

    def test_invalid_source_instrument_combination(self):
        """Test validation with invalid source-instrument combination."""
        search_call = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source: STEREO_A object>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('Invalid source-instrument combination' in error for error in result['errors']))

    def test_time_range_before_instrument_start(self):
        """Test validation with time range before instrument start date."""
        search_call = {
            'instruments': ['SECCHI'],
            'other_attrs': ['<sunpy.net.attrs.Source: STEREO_A object>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('Time range' in error for error in result['errors']))

    def test_invalid_wavelength(self):
        """Test validation with wavelength outside instrument range."""
        search_call = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
            'wavelengths': [{'min': 1.0, 'max': 2.0}]  # Outside LASCO range
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('Wavelength range' in error for error in result['errors']))

    def test_multiple_time_ranges(self):
        """Test validation with multiple time ranges."""
        search_call = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'time_ranges': [
                {'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'},
                {'start': '1995-01-01T00:00:00.000', 'end': '1995-12-31T00:00:00.000'}  # Before LASCO
            ],
        }
        result = self.validator.validate_search_call(search_call)
        self.assertFalse(result['is_valid'])
        self.assertTrue(any('Time range' in error for error in result['errors']))

    def test_no_time_ranges(self):
        """Test validation when no time ranges are specified."""
        search_call = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'wavelengths': [{'min': 4500.0, 'max': 6000.0}]
        }
        result = self.validator.validate_search_call(search_call)
        self.assertTrue(result['is_valid'])  # Should be valid but with warning
        self.assertTrue(any('No time ranges specified' in warning for warning in result['warnings']))

    def test_different_source_formats(self):
        """Test validation with different source string formats."""
        # Test SOHO format
        search_call1 = {
            'instruments': ['LASCO'],
            'other_attrs': ['<sunpy.net.attrs.Source(SOHO: Solar and Heliospheric Observatory)>'],
            'time_ranges': [{'start': '2000-01-01T00:00:00.000', 'end': '2000-12-31T00:00:00.000'}],
        }
        result1 = self.validator.validate_search_call(search_call1)
        self.assertTrue(result1['is_valid'])

        # Test STEREO format
        search_call2 = {
            'instruments': ['SECCHI'],
            'other_attrs': ['<sunpy.net.attrs.Source: STEREO_A object>'],
            'time_ranges': [{'start': '2010-01-01T00:00:00.000', 'end': '2010-12-31T00:00:00.000'}],
        }
        result2 = self.validator.validate_search_call(search_call2)
        self.assertTrue(result2['is_valid'])


if __name__ == '__main__':
    unittest.main()