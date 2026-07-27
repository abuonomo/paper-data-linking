"""Unit tests for VSO snippet generator."""

import pytest
from unittest.mock import Mock
from datetime import datetime
from psycopg2.extras import DateTimeTZRange

from paper_data_linking.analyzers.vso_snippet_generator import VSO_DatasetUsageSnippetGenerator


class TestVSOSnippetGenerator:
    """Unit tests for VSO_DatasetUsageSnippetGenerator."""

    @pytest.fixture
    def generator(self):
        """Create a VSO snippet generator instance."""
        return VSO_DatasetUsageSnippetGenerator()

    def test_format_wavelength_attr_single_discrete(self, generator):
        """Test formatting a single discrete wavelength."""
        ranges = [{"min": 193.0, "max": 193.0, "unit": "angstrom"}]
        result = generator._format_wavelength_attr(ranges)
        assert result == "a.Wavelength(193.0*u.angstrom)"

    def test_format_wavelength_attr_multiple_discrete(self, generator):
        """Test formatting multiple discrete wavelengths."""
        ranges = [
            {"min": 193.0, "max": 193.0, "unit": "angstrom"},
            {"min": 211.0, "max": 211.0, "unit": "angstrom"},
            {"min": 335.0, "max": 335.0, "unit": "angstrom"}
        ]
        result = generator._format_wavelength_attr(ranges)
        assert result == "a.AttrOr([a.Wavelength(193.0*u.angstrom), a.Wavelength(211.0*u.angstrom), a.Wavelength(335.0*u.angstrom)])"

    def test_format_wavelength_attr_single_range(self, generator):
        """Test formatting a single wavelength range."""
        ranges = [{"min": 1.0, "max": 8.0, "unit": "angstrom"}]
        result = generator._format_wavelength_attr(ranges)
        assert result == "a.Wavelength(1.0*u.angstrom, 8.0*u.angstrom)"

    def test_format_wavelength_attr_multiple_ranges(self, generator):
        """Test formatting multiple wavelength ranges."""
        ranges = [
            {"min": 5.0, "max": 10.0, "unit": "keV"},
            {"min": 25.0, "max": 50.0, "unit": "keV"}
        ]
        result = generator._format_wavelength_attr(ranges)
        assert result == "a.AttrOr([a.Wavelength(5.0*u.keV, 10.0*u.keV), a.Wavelength(25.0*u.keV, 50.0*u.keV)])"

    def test_format_wavelength_attr_mixed_units(self, generator):
        """Test formatting wavelengths with mixed units."""
        ranges = [
            {"min": 1.0, "max": 8.0, "unit": "angstrom"},
            {"min": 0.1, "max": 1.0, "unit": "keV"}
        ]
        result = generator._format_wavelength_attr(ranges)
        assert result == "a.AttrOr([a.Wavelength(1.0*u.angstrom, 8.0*u.angstrom), a.Wavelength(0.1*u.keV, 1.0*u.keV)])"

    def test_format_wavelength_attr_empty_ranges(self, generator):
        """Test formatting with empty ranges list."""
        ranges = []
        result = generator._format_wavelength_attr(ranges)
        assert result is None

    def test_format_wavelength_attr_none_ranges(self, generator):
        """Test formatting with None ranges."""
        result = generator._format_wavelength_attr(None)
        assert result is None

    def test_format_wavelength_attr_unsupported_unit(self, generator):
        """Test formatting with unsupported unit - should be skipped."""
        ranges = [{"min": 100.0, "max": 200.0, "unit": "unsupported"}]
        result = generator._format_wavelength_attr(ranges)
        assert result is None

    def test_format_wavelength_attr_missing_min_max(self, generator):
        """Test formatting with missing min/max values."""
        ranges = [{"unit": "angstrom"}]
        result = generator._format_wavelength_attr(ranges)
        assert result is None

    def test_format_wavelength_attr_various_units(self, generator):
        """Test formatting with various supported units."""
        test_cases = [
            ({"min": 100.0, "max": 100.0, "unit": "nm"}, "a.Wavelength(100.0*u.nm)"),
            ({"min": 10.0, "max": 10.0, "unit": "keV"}, "a.Wavelength(10.0*u.keV)"),
            ({"min": 7155.0, "max": 7155.0, "unit": "MHz"}, "a.Wavelength(7155.0*u.MHz)"),
            ({"min": 1.0, "max": 1.0, "unit": "GHz"}, "a.Wavelength(1.0*u.GHz)"),
            ({"min": 100.0, "max": 100.0, "unit": "kHz"}, "a.Wavelength(100.0*u.kHz)"),
            ({"min": 1000.0, "max": 1000.0, "unit": "Hz"}, "a.Wavelength(1000.0*u.Hz)"),
        ]

        for wavelength_range, expected in test_cases:
            result = generator._format_wavelength_attr([wavelength_range])
            assert result == expected, f"Failed for {wavelength_range}"

    def test_generate_snippet_no_wavelength(self, generator):
        """Test script generation without wavelength data."""
        # Create mock DatasetUsage
        usage = Mock()
        usage.instrument.short_name = "AIA"
        usage.instrument.observatory.short_name = "SDO"
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(
            datetime(2023, 1, 1),
            datetime(2023, 1, 2)
        )
        usage.extra_params = {}

        snippet = generator.generate_snippet(usage, include_imports=False)

        assert "a.Instrument('AIA')" in snippet
        assert "a.Source('SDO')" in snippet
        assert "a.Time('2023-01-01 00:00:00', '2023-01-02 00:00:00')" in snippet
        assert "a.Wavelength" not in snippet

    def test_generate_snippet_with_single_wavelength(self, generator):
        """Test script generation with single wavelength."""
        usage = Mock()
        usage.instrument.short_name = "AIA"
        usage.instrument.observatory.short_name = "SDO"
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(
            datetime(2023, 1, 1),
            datetime(2023, 1, 2)
        )
        usage.extra_params = {
            "wavelengths": {
                "ranges": [{"min": 193.0, "max": 193.0, "unit": "angstrom"}],
                "original_text": "193 Å"
            }
        }

        snippet = generator.generate_snippet(usage, include_imports=False)

        assert "a.Wavelength(193.0*u.angstrom)" in snippet
        assert "a.Instrument('AIA')" in snippet

    def test_generate_snippet_with_multiple_wavelengths(self, generator):
        """Test script generation with multiple wavelengths."""
        usage = Mock()
        usage.instrument.short_name = "AIA"
        usage.instrument.observatory.short_name = "SDO"
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(
            datetime(2023, 1, 1),
            datetime(2023, 1, 2)
        )
        usage.extra_params = {
            "wavelengths": {
                "ranges": [
                    {"min": 193.0, "max": 193.0, "unit": "angstrom"},
                    {"min": 211.0, "max": 211.0, "unit": "angstrom"}
                ],
                "original_text": "193 Å and 211 Å"
            }
        }

        snippet = generator.generate_snippet(usage, include_imports=False)

        assert "a.AttrOr" in snippet
        assert "a.Wavelength(193.0*u.angstrom)" in snippet
        assert "a.Wavelength(211.0*u.angstrom)" in snippet

    def test_generate_snippet_with_all_params(self, generator):
        """Test script generation with wavelength, detector, and physobs."""
        usage = Mock()
        usage.instrument.short_name = "SECCHI"
        usage.instrument.observatory.short_name = "STEREO_A"
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(
            datetime(2023, 1, 1),
            datetime(2023, 1, 2)
        )
        usage.extra_params = {
            "wavelengths": {
                "ranges": [{"min": 195.0, "max": 195.0, "unit": "angstrom"}],
                "original_text": "195 Å"
            },
            "detector": {
                "detector": "EUVI"
            },
            "physical_observable": {
                "physical_observable": "intensity"
            }
        }

        snippet = generator.generate_snippet(usage, include_imports=False)

        assert "a.Wavelength(195.0*u.angstrom)" in snippet
        assert "a.Detector('EUVI')" in snippet
        assert "a.Physobs('intensity')" in snippet
        # Verify order: Time, Wavelength, Physobs
        time_idx = snippet.index("a.Time")
        wave_idx = snippet.index("a.Wavelength")
        physobs_idx = snippet.index("a.Physobs")
        assert time_idx < wave_idx < physobs_idx

    def test_generate_snippet_with_imports(self, generator):
        """Test that imports are included when requested."""
        usage = Mock()
        usage.instrument.short_name = "AIA"
        usage.instrument.observatory.short_name = "SDO"
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(
            datetime(2023, 1, 1),
            datetime(2023, 1, 2)
        )
        usage.extra_params = {}

        snippet = generator.generate_snippet(usage, include_imports=True)

        assert "from sunpy.net import Fido, attrs as a" in snippet
        assert "import astropy.units as u" in snippet
