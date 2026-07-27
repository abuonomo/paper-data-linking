import pytest
from unittest.mock import Mock
from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.catalogue_models import CatalogueEntry
from paper_data_linking.clients.litellm_client import LiteLLMClient

class TestInstrumentGrounderIntegration:
    
    @pytest.fixture
    def grounder(self, llm_pipeline_config):
        """Create an InstrumentGrounder with a real LLM client but mocked finder."""
        finder_mock = Mock()
        client = LiteLLMClient()
        return InstrumentGrounder(finder=finder_mock, llm_client=client, llm_config=llm_pipeline_config)

    @pytest.mark.integration
    @pytest.mark.parametrize("instrument_entry,catalogue_entry,expected_valid", [
        (
            # Case 1: Valid Match - LASCO C2 on SOHO
            {
                "name": "LASCO C2",
                "general_comments": "White-light coronagraph images",
                "data_collection_periods": [{"time_range": "1996-2010", "physical_observable": "intensity"}]
            },
            CatalogueEntry(
                instrument_code="LASCO",
                instrument_name="Large Angle and Spectrometric Coronagraph",
                mission_code="SOHO",
                mission_name="Solar and Heliospheric Observatory",
                data_system="vso",
                description="The Large Angle and Spectrometric Coronagraph (LASCO) is a set of three coronagraphs..."
            ),
            True
        ),
        (
            # Case 2: Invalid Match - EIT vs LASCO (Instrument Mismatch)
            {
                "name": "EIT",
                "general_comments": "EUV images at 195 Angstroms",
                "data_collection_periods": [{"wavelengths": "195"}]
            },
            CatalogueEntry(
                instrument_code="LASCO",
                instrument_name="Large Angle and Spectrometric Coronagraph",
                mission_code="SOHO",
                mission_name="Solar and Heliospheric Observatory",
                data_system="vso",
                description="The Large Angle and Spectrometric Coronagraph (LASCO)..."
            ),
            False
        ),
        (
            # Case 3: Invalid Match - AIA vs EIT (Mission Mismatch / Instrument Mismatch)
            {
                "name": "AIA",
                "general_comments": "Atmospheric Imaging Assembly on SDO",
                "data_collection_periods": [{"time_range": "2011-2012"}]
            },
            CatalogueEntry(
                instrument_code="EIT",
                instrument_name="Extreme ultraviolet Imaging Telescope",
                mission_code="SOHO",
                mission_name="Solar and Heliospheric Observatory",
                data_system="vso",
                description="The Extreme ultraviolet Imaging Telescope (EIT)..."
            ),
            False
        ),
        (
            # Case 4: Ambiguous/Unclear but likely Valid if context matches (testing robustness)
            # "EUVI" typically implies STEREO. If we check against STEREO-A, it should likely pass or be ambiguous.
            # But here we just test strict validation. If the catalogue says STEREO-A and input says EUVI, it should pass.
            {
                "name": "EUVI",
                "general_comments": "STEREO Ahead EUVI data",
                "data_collection_periods": []
            },
            CatalogueEntry(
                instrument_code="EUVI",
                instrument_name="Extreme Ultraviolet Imager",
                mission_code="STEREO A",
                mission_name="Solar Terrestrial Relations Observatory A",
                data_system="vso",
                description="The Extreme Ultraviolet Imager (EUVI)..."
            ),
            True
        ),
        (
            # Case 5: Invalid Match - MWO magnetograms vs 60-ft SHG (capability mismatch)
            # Paper describes magnetograms but 60-ft SHG is a spectroheliograph producing Ca II K images.
            # With the instrument description in the prompt, the LLM should reject this.
            {
                "name": "MWO synoptic magnetograms",
                "general_comments": "Mount Wilson Observatory synoptic magnetogram data used for solar magnetic field analysis",
                "data_collection_periods": [
                    {
                        "time_range": "1970-2009",
                        "physical_observable": "magnetic field",
                        "wavelengths": None,
                    }
                ]
            },
            CatalogueEntry(
                instrument_code="60-ft_SHG",
                instrument_name="60-ft SHG",
                mission_code="MtWilson",
                mission_name="MtWilson",
                data_system="vso",
                description="Mt Wilson 60-foot tower spectroheliograph producing Ca II K intensity images"
            ),
            False
        )
    ])
    def test_validate_single_catalogue_entry_integration(self, grounder, instrument_entry, catalogue_entry, expected_valid):
        """
        Integration test for _validate_single_catalogue_entry using real LLM calls.
        Verifies that the LLM correctly validates or rejects instrument-catalogue pairs.
        """
        print(f"\nTesting validation for: Input='{instrument_entry['name']}' vs Catalogue='{catalogue_entry.instrument_code}/{catalogue_entry.mission_code}'")
        
        result = grounder._validate_single_catalogue_entry(instrument_entry, catalogue_entry)
        
        print(f"Result: {result}, Expected: {expected_valid}")
        assert result is expected_valid, \
            f"Validation failed. Input: {instrument_entry['name']}, Catalogue: {catalogue_entry.instrument_code}. Expected {expected_valid}, got {result}"

if __name__ == "__main__":
    # Run integration tests 
    pytest.main([__file__, "-v", "-m", "integration", "-s"])
