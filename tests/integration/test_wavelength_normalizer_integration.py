"""Integration tests for WavelengthNormalizer with real LLM calls."""

import pytest
from paper_data_linking.linkers.general.normalizers.wavelength_normalizer import WavelengthNormalizer
from paper_data_linking.linkers.general.normalizers.normalization_context import NormalizationContext, GroundingResult
from paper_data_linking.linkers.general.normalizers.normalization_models import InternalDataCollectionPeriod
from paper_data_linking.clients.litellm_client import LiteLLMClient


class TestWavelengthNormalizerIntegration:
    """Integration tests that call the LLM with real wavelength data."""

    @pytest.mark.integration
    @pytest.mark.parametrize("raw_wavelength,expected_num_ranges,expected_unit", [
        ("211 Å and 193 Å", 2, "angstrom"),  # Two discrete values
        ("1-8 Å", 1, "angstrom"),  # Single range
        ("White-light", 0, None),  # Qualitative band names without numbers → empty ranges
        ("7155 MHz", 1, "MHz"),  # Single discrete value
        ("0.3-10 keV", 1, "keV"),  # Single range
    ])
    def test_wavelength_normalization_with_type(
        self, raw_wavelength, expected_num_ranges, expected_unit, llm_pipeline_config
    ):
        """Test wavelength normalization with LLM, verifying ranges and unit parsing.

        Tests:
        1. Discrete wavelength values (e.g., 211 Å and 193 Å) → 2 ranges with min==max
        2. Wavelength ranges (e.g., 1-8 Å) → 1 range with min < max
        3. Named spectral bands (e.g., White-light) → 0 ranges (not_applicable)
        4. Frequency values (e.g., 7155 MHz) → 1 range with min==max
        5. Energy ranges (e.g., 0.3-10 keV) → 1 range with min < max
        """
        period = InternalDataCollectionPeriod(
            period_name="Test period",
            wavelengths=raw_wavelength,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="AIA",
            matched_instrument_name="Atmospheric Imaging Assembly",
            matched_mission_name="SDO",
            data_system="vso",
            reasoning="Test wavelength"
        )

        context = NormalizationContext(
            instrument_code="AIA",
            instrument_name="Atmospheric Imaging Assembly",
            data_system="vso",
            period_name="Test period",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = WavelengthNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting wavelength: {raw_wavelength}")

        # Call the normalizer (will actually call LLM)
        result = normalizer.normalize(context)

        print(f"Wavelength normalization result: {result}")

        # Verify result structure
        assert result is not None
        assert "ranges" in result
        assert "original_text" in result

        # Verify number of ranges matches expectation
        assert len(result["ranges"]) == expected_num_ranges, \
            f"Expected {expected_num_ranges} ranges, got {len(result['ranges'])}"

        # Verify each range has proper structure and unit
        for i, r in enumerate(result["ranges"]):
            assert "min" in r, f"Range {i} missing 'min'"
            assert "max" in r, f"Range {i} missing 'max'"
            assert "unit" in r, f"Range {i} missing 'unit'"
            assert isinstance(r["min"], (int, float)), f"Range {i} min should be numeric"
            assert isinstance(r["max"], (int, float)), f"Range {i} max should be numeric"
            assert r["min"] <= r["max"], f"Range {i} min should be <= max"
            if expected_unit:
                assert r["unit"] == expected_unit, \
                    f"Expected unit '{expected_unit}', got '{r['unit']}' in range {i}"

        print(f"✓ Wavelength normalized: {len(result['ranges'])} ranges with unit(s): {[r['unit'] for r in result['ranges']]}")

    @pytest.mark.integration
    def test_wavelength_normalization_discrete_values(self, llm_pipeline_config):
        """Test normalization of discrete wavelength values."""
        raw_wavelength = "193, 211, 335, and 131 Å"

        period = InternalDataCollectionPeriod(
            period_name="AIA wavelengths",
            wavelengths=raw_wavelength,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="AIA",
            matched_instrument_name="Atmospheric Imaging Assembly",
            matched_mission_name="SDO",
            data_system="vso",
            reasoning="AIA multi-wavelength observations"
        )

        context = NormalizationContext(
            instrument_code="AIA",
            instrument_name="Atmospheric Imaging Assembly",
            data_system="vso",
            period_name="AIA wavelengths",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = WavelengthNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting discrete values: {raw_wavelength}")

        result = normalizer.normalize(context)

        print(f"Result: {result}")

        # For discrete values, should have 4 ranges (each with min==max)
        assert len(result["ranges"]) == 4
        values = [r["min"] for r in result["ranges"]]
        assert set(values) == {193.0, 211.0, 335.0, 131.0}
        # Verify all are discrete (min == max)
        for r in result["ranges"]:
            assert r["min"] == r["max"], f"Expected discrete value, got range: {r}"

        print(f"✓ Discrete values correctly parsed: {values}")

    @pytest.mark.integration
    def test_wavelength_normalization_range(self, llm_pipeline_config):
        """Test normalization of wavelength ranges."""
        raw_wavelength = "10 to 1200 angstroms"

        period = InternalDataCollectionPeriod(
            period_name="EUV range",
            wavelengths=raw_wavelength,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="SECCHI",
            matched_instrument_name="Sun Earth Connection Coronal and Heliospheric Investigation",
            matched_mission_name="STEREO",
            data_system="vso",
            reasoning="EUV wavelength range"
        )

        context = NormalizationContext(
            instrument_code="SECCHI",
            instrument_name="Sun Earth Connection Coronal and Heliospheric Investigation",
            data_system="vso",
            period_name="EUV range",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = WavelengthNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting range: {raw_wavelength}")

        result = normalizer.normalize(context)

        print(f"Result: {result}")

        # For ranges, should have exactly 1 range with min < max
        assert len(result["ranges"]) == 1
        r = result["ranges"][0]
        assert r["min"] < r["max"], f"Expected min < max, got {r}"
        assert r["min"] == 10.0
        assert r["max"] == 1200.0

        print(f"✓ Range correctly parsed: {r['min']} to {r['max']} {r['unit']}")

    @pytest.mark.integration
    def test_wavelength_normalization_band(self, llm_pipeline_config):
        """Test normalization of qualitative spectral band names (returns not_applicable)."""
        raw_wavelength = "soft X-ray"

        period = InternalDataCollectionPeriod(
            period_name="Soft X-ray",
            wavelengths=raw_wavelength,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="XRT",
            matched_instrument_name="X-Ray Telescope",
            matched_mission_name="Hinode",
            data_system="vso",
            reasoning="Soft X-ray band"
        )

        context = NormalizationContext(
            instrument_code="XRT",
            instrument_name="X-Ray Telescope",
            data_system="vso",
            period_name="Soft X-ray",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = WavelengthNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting band: {raw_wavelength}")

        result = normalizer.normalize(context)

        print(f"Result: {result}")

        # Qualitative band names without numeric bounds return empty ranges
        assert len(result["ranges"]) == 0

        print(f"✓ Qualitative band name correctly returned empty ranges (not_applicable)")

    @pytest.mark.integration
    def test_wavelength_normalization_not_applicable(self, llm_pipeline_config):
        """Test handling of cases where wavelength is not specified."""
        raw_wavelength = "Not specified in the paper"

        period = InternalDataCollectionPeriod(
            period_name="No wavelength",
            wavelengths=raw_wavelength,
        )

        grounding_result = GroundingResult(
            matched_instrument_code="GENERIC",
            matched_instrument_name="Generic Instrument",
            matched_mission_name="Generic Mission",
            data_system="vso",
            reasoning="Test case"
        )

        context = NormalizationContext(
            instrument_code="GENERIC",
            instrument_name="Generic Instrument",
            data_system="vso",
            period_name="No wavelength",
            period_data=period,
            grounding_result=grounding_result
        )

        llm_client = LiteLLMClient()
        normalizer = WavelengthNormalizer(llm_client=llm_client, llm_config=llm_pipeline_config)

        print(f"\nTesting not applicable: {raw_wavelength}")

        result = normalizer.normalize(context)

        print(f"Result: {result}")

        # For not applicable, should have empty ranges
        assert len(result["ranges"]) == 0

        print(f"✓ Not applicable correctly identified (empty ranges)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration", "-s"])
