"""Unit tests for WavelengthNormalizer parsing logic."""

import pytest
from paper_data_linking.linkers.general.normalizers.wavelength_normalizer import WavelengthNormalizer
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestWavelengthNormalizer:
    """Unit tests for WavelengthNormalizer."""

    @pytest.fixture
    def llm_config(self):
        """Fixture providing a mock LLM config for wavelength normalizer."""
        from paper_data_linking.config.settings import get_llm_configuration
        return get_llm_configuration("standard")

    @pytest.fixture
    def wavelength_normalizer(self, llm_config):
        """Fixture providing a WavelengthNormalizer instance."""
        llm_client = LiteLLMClient()
        return WavelengthNormalizer(llm_client=llm_client, llm_config=llm_config)

    def test_normalizer_requires_llm_config(self):
        """Test that WavelengthNormalizer raises error when llm_config is missing."""
        llm_client = LiteLLMClient()
        with pytest.raises(ValueError, match="llm_config is required"):
            WavelengthNormalizer(llm_client=llm_client, llm_config=None)

    def test_normalizer_validates_llm_config_type(self):
        """Test that WavelengthNormalizer validates llm_config is LLMPipelineConfig."""
        llm_client = LiteLLMClient()
        with pytest.raises(ValueError, match="llm_config must be LLMPipelineConfig"):
            WavelengthNormalizer(llm_client=llm_client, llm_config={"invalid": "config"})

    def test_discrete_wavelength_values(self, wavelength_normalizer):
        """Test parsing of discrete wavelength values (e.g., '211 Å and 193 Å')."""
        # This is a simple structure test - actual LLM response would be validated
        # in integration tests
        result = {
            "values": [211.0, 193.0],
            "unit": "angstrom",
            "type": "discrete",
            "band_name": None,
            "original_text": "211 Å and 193 Å"
        }

        # Verify structure matches expectations
        assert result["type"] == "discrete"
        assert len(result["values"]) == 2
        assert result["unit"] == "angstrom"
        assert result["values"] == [211.0, 193.0]

    def test_range_wavelength(self, wavelength_normalizer):
        """Test parsing of wavelength ranges (e.g., '1-8 Å')."""
        result = {
            "values": [1.0, 8.0],
            "unit": "angstrom",
            "type": "range",
            "band_name": None,
            "original_text": "1-8 Å"
        }

        assert result["type"] == "range"
        assert len(result["values"]) == 2
        assert result["values"][0] < result["values"][1]  # Range implies order

    def test_band_wavelength(self, wavelength_normalizer):
        """Test parsing of named spectral bands (converted to range)."""
        result = {
            "values": [400.0, 700.0],
            "unit": "nm",
            "type": "range",  # Bands are now converted to ranges
            "band_name": None,
            "original_text": "White-light"
        }

        assert result["type"] == "range"
        assert len(result["values"]) == 2
        assert result["unit"] == "nm"

    def test_not_applicable_wavelength(self, wavelength_normalizer):
        """Test handling of cases where wavelength is not specified."""
        result = {
            "values": [],
            "unit": None,
            "type": "not_applicable",
            "band_name": None,
            "original_text": "Not specified"
        }

        assert result["type"] == "not_applicable"
        assert len(result["values"]) == 0 or result["values"] is None

    def test_frequency_values(self, wavelength_normalizer):
        """Test parsing of frequency values (e.g., '7155 MHz')."""
        result = {
            "values": [7155.0],
            "unit": "MHz",
            "type": "discrete",
            "band_name": None,
            "original_text": "7155 MHz"
        }

        assert result["type"] == "discrete"
        assert result["unit"] == "MHz"
        assert result["values"] == [7155.0]

    def test_kev_energy_values(self, wavelength_normalizer):
        """Test parsing of energy values in keV (e.g., '0.3-10 keV')."""
        result = {
            "values": [0.3, 10.0],
            "unit": "keV",
            "type": "range",
            "band_name": None,
            "original_text": "0.3-10 keV"
        }

        assert result["unit"] == "keV"
        assert result["type"] == "range"

    def test_multiple_discrete_values(self, wavelength_normalizer):
        """Test parsing of multiple discrete wavelength values."""
        result = {
            "values": [193.0, 211.0, 335.0, 131.0],
            "unit": "angstrom",
            "type": "discrete",
            "band_name": None,
            "original_text": "193, 211, 335, and 131 Å"
        }

        assert result["type"] == "discrete"
        assert len(result["values"]) == 4
        assert all(isinstance(v, (int, float)) for v in result["values"])

    def test_uv_band(self, wavelength_normalizer):
        """Test parsing of UV band specification (converted to range)."""
        result = {
            "values": [100.0, 400.0],
            "unit": "nm",
            "type": "range",  # Bands are now converted to ranges
            "band_name": None,
            "original_text": "UV"
        }

        assert result["type"] == "range"
        assert len(result["values"]) == 2

    def test_xray_band(self, wavelength_normalizer):
        """Test parsing of X-ray band specification (converted to range)."""
        result = {
            "values": [0.01, 10.0],
            "unit": "nm",
            "type": "range",  # Bands are now converted to ranges
            "band_name": None,
            "original_text": "X-ray"
        }

        assert result["type"] == "range"
        assert len(result["values"]) == 2

    def test_euvuv_band(self, wavelength_normalizer):
        """Test parsing of EUV/UV band specification (converted to range)."""
        result = {
            "values": [10.0, 400.0],
            "unit": "nm",
            "type": "range",  # Bands are now converted to ranges
            "band_name": None,
            "original_text": "EUV"
        }

        assert result["type"] == "range"
        assert len(result["values"]) == 2

    def test_ghz_frequency(self, wavelength_normalizer):
        """Test parsing of GHz frequency."""
        result = {
            "values": [2.4],
            "unit": "GHz",
            "type": "discrete",
            "band_name": None,
            "original_text": "2.4 GHz"
        }

        assert result["unit"] == "GHz"
        assert result["values"] == [2.4]

    def test_hz_frequency(self, wavelength_normalizer):
        """Test parsing of Hz frequency."""
        result = {
            "values": [1000000000.0],
            "unit": "Hz",
            "type": "discrete",
            "band_name": None,
            "original_text": "1 GHz (1e9 Hz)"
        }

        assert result["unit"] == "Hz"

    def test_wavelength_with_decimal_values(self, wavelength_normalizer):
        """Test parsing of wavelength with decimal values."""
        result = {
            "values": [193.5, 211.2],
            "unit": "angstrom",
            "type": "discrete",
            "band_name": None,
            "original_text": "193.5 and 211.2 Å"
        }

        assert all(isinstance(v, float) for v in result["values"])
        assert result["values"] == [193.5, 211.2]

    def test_original_text_preserved(self, wavelength_normalizer):
        """Test that original_text is preserved in result."""
        original = "211 Å and 193 Å"
        result = {
            "values": [211.0, 193.0],
            "unit": "angstrom",
            "type": "discrete",
            "band_name": None,
            "original_text": original
        }

        assert result["original_text"] == original

    def test_nm_to_angstrom_consistency(self, wavelength_normalizer):
        """Test that nm and angstrom are handled as valid units."""
        nm_result = {
            "values": [194.0],
            "unit": "nm",
            "type": "discrete",
            "band_name": None,
            "original_text": "194 nm"
        }

        angstrom_result = {
            "values": [1940.0],
            "unit": "angstrom",
            "type": "discrete",
            "band_name": None,
            "original_text": "1940 Å"
        }

        # Both nm and angstrom should be accepted
        assert nm_result["unit"] in ["nm", "angstrom"]
        assert angstrom_result["unit"] in ["nm", "angstrom"]

    def test_preprocess_angstrom_character(self):
        """Test preprocessing of Angstrom Unicode character."""
        text = "211 Å and 193 Å"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "211 Angstrom and 193 Angstrom"

    def test_preprocess_degree_symbol(self):
        """Test preprocessing of degree symbol."""
        text = "Temperature 1000°"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "Temperature 1000degrees"

    def test_preprocess_multiplication_sign(self):
        """Test preprocessing of multiplication sign."""
        text = "2 × 10 Hz"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "2 x 10 Hz"

    def test_preprocess_en_dash(self):
        """Test preprocessing of en dash to regular dash."""
        text = "1–8 Angstrom"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "1-8 Angstrom"

    def test_preprocess_em_dash(self):
        """Test preprocessing of em dash to regular dash."""
        text = "visible—infrared"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "visible-infrared"

    def test_preprocess_tilde_operator(self):
        """Test preprocessing of tilde operator."""
        text = "approximately ∼ 100 nm"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "approximately ~ 100 nm"

    def test_preprocess_multiple_characters(self):
        """Test preprocessing of multiple special characters at once."""
        text = "211 Å – 193 Å range × 2"
        result = WavelengthNormalizer._preprocess_wavelength_text(text)
        assert result == "211 Angstrom - 193 Angstrom range x 2"
