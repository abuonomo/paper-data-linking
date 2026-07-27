"""Integration tests for VSO snippet generator with realistic scenarios."""

import pytest
import ast
from unittest.mock import Mock
from datetime import datetime
from psycopg2.extras import DateTimeTZRange

from paper_data_linking.analyzers.vso_snippet_generator import VSO_DatasetUsageSnippetGenerator


class TestVSOSnippetGeneratorIntegration:
    """Integration tests for VSO_DatasetUsageSnippetGenerator with realistic data."""

    @pytest.fixture
    def generator(self):
        """Create a VSO snippet generator instance."""
        return VSO_DatasetUsageSnippetGenerator()

    def _create_mock_usage(self, instrument, observatory, start_dt, end_dt, extra_params=None):
        """Helper to create mock DatasetUsage objects."""
        usage = Mock()
        usage.instrument.short_name = instrument
        usage.instrument.observatory.short_name = observatory
        usage.instrument.observatory.datasource.slug = "vso"
        usage.observation_window = DateTimeTZRange(start_dt, end_dt)
        usage.extra_params = extra_params or {}
        return usage

    @pytest.mark.integration
    def test_aia_multi_wavelength_generation(self, generator):
        """Test realistic AIA query with multiple wavelengths."""
        usage = self._create_mock_usage(
            instrument="AIA",
            observatory="SDO",
            start_dt=datetime(2023, 6, 1, 12, 0, 0),
            end_dt=datetime(2023, 6, 1, 13, 0, 0),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 193.0, "max": 193.0, "unit": "angstrom"},
                        {"min": 211.0, "max": 211.0, "unit": "angstrom"},
                        {"min": 335.0, "max": 335.0, "unit": "angstrom"}
                    ],
                    "original_text": "193 Å, 211 Å, and 335 Å"
                },
                "physical_observable": {
                    "physical_observable": "intensity"
                }
            }
        )

        snippet = generator.generate_snippet(usage, query_name="aia_query", include_imports=True)

        # Verify imports
        assert "from sunpy.net import Fido, attrs as a" in snippet
        assert "import astropy.units as u" in snippet

        # Verify all components present
        assert "aia_query = Fido.search(" in snippet
        assert "a.Source('SDO')" in snippet
        assert "a.Instrument('AIA')" in snippet
        assert "a.Time('2023-06-01 12:00:00', '2023-06-01 13:00:00')" in snippet

        # Verify wavelengths with AttrOr
        assert "a.AttrOr" in snippet
        assert "a.Wavelength(193.0*u.angstrom)" in snippet
        assert "a.Wavelength(211.0*u.angstrom)" in snippet
        assert "a.Wavelength(335.0*u.angstrom)" in snippet
        assert "a.Physobs('intensity')" in snippet

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_secchi_with_detector_and_wavelength(self, generator):
        """Test SECCHI query with detector and wavelength range."""
        usage = self._create_mock_usage(
            instrument="SECCHI",
            observatory="STEREO_A",
            start_dt=datetime(2020, 1, 1, 0, 0, 0),
            end_dt=datetime(2020, 1, 2, 0, 0, 0),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 195.0, "max": 195.0, "unit": "angstrom"}
                    ],
                    "original_text": "195 Å"
                },
                "detector": {
                    "detector": "EUVI"
                }
            }
        )

        snippet = generator.generate_snippet(usage, include_imports=False)

        # Verify detector in comment
        assert "# Query for SECCHI on STEREO_A (detector: EUVI)" in snippet

        # Verify all components
        assert "a.Detector('EUVI')" in snippet
        assert "a.Wavelength(195.0*u.angstrom)" in snippet
        assert "a.Instrument('SECCHI')" in snippet

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_instrument_without_wavelength(self, generator):
        """Test instrument without wavelength data (should work gracefully)."""
        usage = self._create_mock_usage(
            instrument="LASCO",
            observatory="SOHO",
            start_dt=datetime(2019, 9, 1, 0, 0, 0),
            end_dt=datetime(2019, 9, 30, 23, 59, 59),
            extra_params={}  # No wavelength data
        )

        snippet = generator.generate_snippet(usage, include_imports=True)

        # Verify query works without wavelength
        assert "a.Instrument('LASCO')" in snippet
        assert "a.Source('SOHO')" in snippet
        assert "a.Time('2019-09-01 00:00:00', '2019-09-30 23:59:59')" in snippet
        assert "a.Wavelength" not in snippet  # Should not include wavelength

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_wavelength_range_not_discrete(self, generator):
        """Test wavelength range (not discrete values)."""
        usage = self._create_mock_usage(
            instrument="EIT",
            observatory="SOHO",
            start_dt=datetime(2010, 1, 1, 0, 0, 0),
            end_dt=datetime(2010, 1, 1, 1, 0, 0),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 10.0, "max": 1200.0, "unit": "angstrom"}
                    ],
                    "original_text": "10 to 1200 angstroms"
                }
            }
        )

        snippet = generator.generate_snippet(usage, include_imports=False)

        # Verify range format (both min and max specified)
        assert "a.Wavelength(10.0*u.angstrom, 1200.0*u.angstrom)" in snippet

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_mixed_unit_wavelengths(self, generator):
        """Test wavelengths with different units."""
        usage = self._create_mock_usage(
            instrument="XRT",
            observatory="Hinode",
            start_dt=datetime(2015, 1, 1, 0, 0, 0),
            end_dt=datetime(2015, 1, 31, 23, 59, 59),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 1.0, "max": 8.0, "unit": "angstrom"},
                        {"min": 0.3, "max": 10.0, "unit": "keV"}
                    ],
                    "original_text": "1-8 Å, 0.3-10 keV"
                }
            }
        )

        snippet = generator.generate_snippet(usage, include_imports=False)

        # Verify both units present
        assert "a.Wavelength(1.0*u.angstrom, 8.0*u.angstrom)" in snippet
        assert "a.Wavelength(0.3*u.keV, 10.0*u.keV)" in snippet
        assert "a.AttrOr" in snippet

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_complete_query_with_all_parameters(self, generator):
        """Test comprehensive query with all supported parameters."""
        usage = self._create_mock_usage(
            instrument="SECCHI",
            observatory="STEREO_B",
            start_dt=datetime(2014, 6, 15, 10, 30, 0),
            end_dt=datetime(2014, 6, 15, 11, 30, 0),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 171.0, "max": 171.0, "unit": "angstrom"},
                        {"min": 195.0, "max": 195.0, "unit": "angstrom"}
                    ],
                    "original_text": "171 Å and 195 Å"
                },
                "detector": {
                    "detector": "EUVI"
                },
                "physical_observable": {
                    "physical_observable": "intensity"
                }
            }
        )

        snippet = generator.generate_snippet(usage, query_name="comprehensive_query", include_imports=True)

        # Verify all parameters present
        assert "from sunpy.net import Fido, attrs as a" in snippet
        assert "import astropy.units as u" in snippet
        assert "comprehensive_query = Fido.search(" in snippet
        assert "a.Source('STEREO_B')" in snippet
        assert "a.Instrument('SECCHI')" in snippet
        assert "a.Detector('EUVI')" in snippet
        assert "a.Time('2014-06-15 10:30:00', '2014-06-15 11:30:00')" in snippet
        assert "a.AttrOr([a.Wavelength(171.0*u.angstrom), a.Wavelength(195.0*u.angstrom)])" in snippet
        assert "a.Physobs('intensity')" in snippet

        # Verify order: Instrument, Detector, Time, Wavelength, Physobs
        inst_idx = snippet.index("a.Instrument")
        det_idx = snippet.index("a.Detector")
        time_idx = snippet.index("a.Time")
        wave_idx = snippet.index("a.Wavelength")
        physobs_idx = snippet.index("a.Physobs")
        assert inst_idx < det_idx < time_idx < wave_idx < physobs_idx

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")

    @pytest.mark.integration
    def test_frequency_units(self, generator):
        """Test wavelengths specified in frequency units."""
        usage = self._create_mock_usage(
            instrument="WAVES",
            observatory="Wind",
            start_dt=datetime(2018, 3, 1, 0, 0, 0),
            end_dt=datetime(2018, 3, 31, 23, 59, 59),
            extra_params={
                "wavelengths": {
                    "ranges": [
                        {"min": 7155.0, "max": 7155.0, "unit": "MHz"}
                    ],
                    "original_text": "7155 MHz"
                }
            }
        )

        snippet = generator.generate_snippet(usage, include_imports=False)

        # Verify frequency unit
        assert "a.Wavelength(7155.0*u.MHz)" in snippet

        # Verify valid Python syntax
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Generated script has invalid Python syntax: {e}")
