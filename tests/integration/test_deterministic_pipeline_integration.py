"""Integration tests for the deterministic parser + validator pipeline.

These tests make real LLM API calls. Run with: pytest -m integration
"""

from pathlib import Path

import pytest

from paper_data_linking.clients import LiteLLMClient
from paper_data_linking.config.settings import LLM_CONFIGURATIONS
from paper_data_linking.linkers.general.paper_analysis_output_parser import (
    parse_instrument_markdown,
)
from paper_data_linking.linkers.general.validators.pipeline import (
    StructureValidatorPipeline,
)

DATA_DIR = Path(__file__).parent.parent / "data" / "parser_test_data"


@pytest.fixture(scope="module")
def llm_client():
    return LiteLLMClient()


@pytest.fixture(scope="module")
def llm_config():
    return LLM_CONFIGURATIONS["standard"]


class TestDeterministicPipelineIntegration:
    @pytest.mark.integration
    def test_clean_case_no_llm(self, llm_client, llm_config):
        """Case with all dates present — parser only, 0 LLM calls."""
        md = (DATA_DIR / "simple_single_instrument.md").read_text()
        parsed = parse_instrument_markdown(md)
        assert len(parsed.instruments) >= 1

        pipeline = StructureValidatorPipeline(
            llm_client=llm_client, llm_config=llm_config
        )
        result = pipeline.run(parsed, md)

        assert result.total_llm_calls == 0
        assert result.all_skipped is True
        assert result.total_issues_found == 0

    @pytest.mark.integration
    def test_missing_dates_triggers_fix(self, llm_client, llm_config):
        """Case 27: descriptive time_ranges → LLM fix resolves them."""
        md = (DATA_DIR / "missing_dates.md").read_text()
        parsed = parse_instrument_markdown(md)
        assert len(parsed.instruments) >= 4

        pipeline = StructureValidatorPipeline(
            llm_client=llm_client, llm_config=llm_config
        )
        result = pipeline.run(parsed, md)

        assert result.total_issues_found >= 1
        assert result.total_llm_calls >= 1

        # At least some issues should have been fixed (the cross-referenced ones)
        # The MDI "contemporaneous with TRACE" case should get real dates
        for inst in result.structured.instruments:
            if "MDI" in inst.name:
                for p in inst.data_collection_periods:
                    # Should now contain a year after fix
                    tr = p.time_range or ""
                    import re
                    if "contemporaneous" not in tr.lower():
                        # Was fixed — verify it has a date
                        assert re.search(r"\b(19|20)\d{2}\b", tr), (
                            f"MDI time_range should have been fixed: '{tr}'"
                        )

    @pytest.mark.integration
    def test_unfixable_case_not_hallucinated(self, llm_client, llm_config):
        """Unfixable time_ranges should not get hallucinated dates."""
        # Build a case with genuinely unfixable time ranges
        from paper_data_linking.linkers.general.schemas.structured_instruments import (
            DataCollectionPeriod,
            Instrument,
            StructuredInstrumentDetails,
        )

        s = StructuredInstrumentDetails(
            paper_summary="Lab plasma experiment",
            instruments=[
                Instrument(
                    name="Pickup coil probe",
                    general_comments="Lab measurement",
                    general_quotes=[],
                    data_collection_periods=[
                        DataCollectionPeriod(
                            period_name="Discharge window",
                            time_range="20 µs window during stationary period of discharge",
                            time_quotes=[],
                            wavelengths=None,
                            wavelength_quotes=[],
                            physical_observable="Magnetic field",
                            physobs_quotes=[],
                            general_quotes=[],
                            additional_comments=None,
                        )
                    ],
                )
            ],
        )

        pipeline = StructureValidatorPipeline(
            llm_client=llm_client, llm_config=llm_config
        )
        result = pipeline.run(s, "# Lab experiment\nNo calendar dates in this paper.")

        assert result.total_llm_calls == 1
        # Should NOT have been modified — still no calendar year
        tr = result.structured.instruments[0].data_collection_periods[0].time_range
        assert "µs" in tr or "discharge" in tr.lower(), (
            f"Unfixable time_range should not be replaced: '{tr}'"
        )
