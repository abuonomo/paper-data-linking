"""Tests for `InstrumentGrounder._build_context_for_llm` quote-field rendering.

These tests document the contract: when an `instrument_entry` has populated
`general_quotes` / `time_quotes` / `wavelength_quotes` / `physobs_quotes`
fields, the rendered context string must include their content so the
grounding LLM can see discriminating identifiers (e.g., "MMS2", "LET1") that
often live only in the supporting quotes captured by the markdown parser.

Tests that fail BEFORE the rendering fix and pass AFTER are the regression
bar for the fix. Tests covering existing behavior (raw field rendering)
ensure the fix doesn't drop anything previously working.

The end-to-end chain test at the bottom proves the parser → context builder
pipeline preserves discriminators end-to-end after both fixes are applied.
"""

import os
import sys
from pathlib import Path

import pytest

# Setup Django before importing instrument_grounder (required by its dependencies).
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "api"))
sys.path.insert(0, str(project_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paper_analyzer_app.settings")
os.environ.setdefault("RUNNING_LOCALLY", "true")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

try:
    import django

    django.setup()
except (RuntimeError, ImportError):
    pass

from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
from paper_data_linking.linkers.general.paper_analysis_output_parser import (
    parse_instrument_markdown,
)


REAL_PROD_DIR = Path(__file__).parent.parent / "data" / "parser_test_data" / "real_prod"


def _render(entry: dict) -> str:
    """Call `_build_context_for_llm` without instantiating InstrumentGrounder.

    The function only uses `self` for method binding; it doesn't read any
    grounder state. Calling as an unbound method sidesteps the need for a
    fully-mocked grounder fixture and isolates the rendering logic.
    """
    return InstrumentGrounder._build_context_for_llm(None, entry)


class TestBuildContextForLLMRendering:
    """Cover quote-field and existing-field rendering in `_build_context_for_llm`."""

    def test_minimal_entry_does_not_crash(self):
        """Bare-minimum instrument_entry — only `name` set."""
        ctx = _render({"name": "Test Only"})
        assert "Test Only" in ctx

    def test_existing_field_rendering_preserved(self):
        """Regression check: the original 6 fields must still render after any quote-rendering fix."""
        entry = {
            "name": "Test Instrument",
            "general_comments": "general blurb",
            "data_collection_periods": [
                {
                    "time_range": "2020 to 2024",
                    "wavelengths": "171 Å",
                    "physical_observable": "EUV",
                    "additional_comments": "extra",
                }
            ],
        }
        ctx = _render(entry)
        assert "Test Instrument" in ctx
        assert "general blurb" in ctx
        assert "2020 to 2024" in ctx
        assert "171 Å" in ctx
        assert "EUV" in ctx
        assert "extra" in ctx

    def test_general_quotes_rendered(self):
        """Suite-level `general_quotes` must reach the LLM context.

        Models the MMS2 case: the discriminator lives only in a suite-level quote
        because stage-1 generalized the section title to drop the variant suffix.
        """
        entry = {
            "name": "FGM on board MMS",  # name lacks the variant suffix
            "general_comments": "Magnetic field instrument",
            "general_quotes": [
                "The presented magnetic fields are measured by the FGM onboard MMS2."
            ],
            "data_collection_periods": [],
        }
        ctx = _render(entry)
        assert "MMS2" in ctx, (
            "Suite-level general_quotes content (containing the spacecraft variant "
            f"discriminator) is not reaching the rendered context. Got: {ctx!r}"
        )

    def test_period_time_quotes_rendered(self):
        """Period-level `time_quotes` must reach the LLM context."""
        entry = {
            "name": "Test Instrument",
            "general_comments": "general",
            "data_collection_periods": [
                {
                    "time_range": "2018 event",
                    "wavelengths": "EUV",
                    "physical_observable": "intensity",
                    "time_quotes": ["Observed during the 2018-04 event SPECIFIC_TIME_TOKEN"],
                }
            ],
        }
        ctx = _render(entry)
        assert "SPECIFIC_TIME_TOKEN" in ctx

    def test_period_physobs_quotes_rendered(self):
        """Period-level `physobs_quotes` must reach the LLM context.

        Models the LET1 case: the paper attributes a specific sub-instrument
        inside a physobs supporting quote (and cites the literal CDF dataset name).
        """
        entry = {
            "name": "Integrated Science Investigation of the Sun (IS⊙IS)",
            "general_comments": "Energetic particles",
            "data_collection_periods": [
                {
                    "time_range": "2018-11-16 to 2018-11-22",
                    "wavelengths": "1.00-5.66 MeV",
                    "physical_observable": "Proton fluxes",
                    "physobs_quotes": [
                        "EPI-Hi fluxes are from LET1 (psp_isois-epihi_l2-let1-rates3600)."
                    ],
                }
            ],
        }
        ctx = _render(entry)
        assert "LET1" in ctx, (
            "Period-level physobs_quotes content (containing the sub-instrument "
            f"discriminator) is not reaching the rendered context. Got: {ctx!r}"
        )
        assert "psp_isois-epihi_l2-let1-rates3600" in ctx, (
            "Literal dataset filename should reach the LLM context"
        )

    def test_period_wavelength_quotes_rendered(self):
        entry = {
            "name": "X",
            "general_comments": "",
            "data_collection_periods": [
                {
                    "time_range": "T",
                    "wavelengths": "171 Å",
                    "physical_observable": "EUV",
                    "wavelength_quotes": ["Wavelength quote with WL_TOKEN_42"],
                }
            ],
        }
        ctx = _render(entry)
        assert "WL_TOKEN_42" in ctx

    def test_all_four_quote_categories_rendered(self):
        """A single period populating all 4 quote categories — every one must reach the context."""
        entry = {
            "name": "Multi-Quote Test",
            "general_comments": "general",
            "general_quotes": ["SUITE_LEVEL_TOKEN"],
            "data_collection_periods": [
                {
                    "time_range": "T",
                    "wavelengths": "W",
                    "physical_observable": "P",
                    "additional_comments": "A",
                    "time_quotes": ["TIME_TOKEN"],
                    "wavelength_quotes": ["WAVE_TOKEN"],
                    "physobs_quotes": ["PHYSOBS_TOKEN"],
                    "general_quotes": ["GENERAL_TOKEN"],
                }
            ],
        }
        ctx = _render(entry)
        for tok in (
            "SUITE_LEVEL_TOKEN",
            "TIME_TOKEN",
            "WAVE_TOKEN",
            "PHYSOBS_TOKEN",
            "GENERAL_TOKEN",
        ):
            assert tok in ctx, f"Token {tok!r} missing from rendered context: {ctx!r}"

    def test_multiple_periods_quotes_attributed_correctly(self):
        """Multiple periods, each with distinct quote tokens — no cross-contamination."""
        entry = {
            "name": "Multi-Period",
            "general_comments": "g",
            "data_collection_periods": [
                {
                    "time_range": "T1",
                    "wavelengths": "W1",
                    "physical_observable": "P1",
                    "physobs_quotes": ["PERIOD1_PHYSOBS_TOKEN"],
                },
                {
                    "time_range": "T2",
                    "wavelengths": "W2",
                    "physical_observable": "P2",
                    "time_quotes": ["PERIOD2_TIME_TOKEN"],
                },
                {
                    "time_range": "T3",
                    "wavelengths": "W3",
                    "physical_observable": "P3",
                    "general_quotes": ["PERIOD3_GENERAL_TOKEN"],
                },
            ],
        }
        ctx = _render(entry)
        assert "PERIOD1_PHYSOBS_TOKEN" in ctx
        assert "PERIOD2_TIME_TOKEN" in ctx
        assert "PERIOD3_GENERAL_TOKEN" in ctx

    def test_empty_quote_arrays_render_cleanly(self):
        """Empty quote arrays must not produce ugly artifacts (`[]`, raw repr, dangling labels).

        Helps ensure the rendering fix degrades gracefully when the parser
        legitimately captured no quotes.
        """
        entry = {
            "name": "Empty",
            "general_comments": "g",
            "general_quotes": [],
            "data_collection_periods": [
                {
                    "time_range": "T",
                    "wavelengths": "W",
                    "physical_observable": "P",
                    "time_quotes": [],
                    "wavelength_quotes": [],
                    "physobs_quotes": [],
                    "general_quotes": [],
                }
            ],
        }
        ctx = _render(entry)
        assert "[]" not in ctx
        assert "Supporting Quote: \n" not in ctx

    def test_missing_quote_fields_treated_as_empty(self):
        """When the quote fields are absent entirely (legacy data), behavior matches empty list."""
        entry = {
            "name": "Legacy",
            "general_comments": "g",
            "data_collection_periods": [
                {
                    "time_range": "T",
                    "wavelengths": "W",
                    "physical_observable": "P",
                }
            ],
        }
        ctx = _render(entry)
        assert "Legacy" in ctx
        assert "[]" not in ctx

    def test_quote_with_markdown_formatting_preserved(self):
        """Quote text containing markdown bold/italic survives unchanged into context."""
        entry = {
            "name": "Md-quote test",
            "general_comments": "g",
            "general_quotes": ["Field at **17:22 UT** observed by *LASCO C2*"],
            "data_collection_periods": [],
        }
        ctx = _render(entry)
        assert "**17:22 UT**" in ctx
        assert "*LASCO C2*" in ctx


class TestParserToContextBuilderChain:
    """Integration: parser output → context builder rendering."""

    def test_bedrock_let1_chain_preserves_let1(self):
        """Full chain: load bedrock_let1.md → parse → render context for IS⊙IS instrument.

        After both fixes (parser + context builder) are in place, "LET1" should
        appear in the final rendered context string. Until then, this test fails.
        """
        fixture_path = REAL_PROD_DIR / "bedrock_let1.md"
        md = fixture_path.read_text()

        result = parse_instrument_markdown(md)
        assert len(result.instruments) >= 1, "No instruments parsed from bedrock_let1.md"

        # The IS⊙IS instrument is the one with EPI-Hi and LET1 references.
        target_instr = result.instruments[0]
        instr_dict = target_instr.model_dump()

        ctx = _render(instr_dict)
        assert "LET1" in ctx, (
            "End-to-end parser→context chain dropped the LET1 discriminator. "
            "This is the test that should pass after both the parser regex fix and the "
            "_build_context_for_llm quote-rendering fix are applied. "
            f"Rendered context (first 800 chars): {ctx[:800]!r}"
        )
