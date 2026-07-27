"""Tests for the deterministic markdown structure parser."""

import json
from pathlib import Path

import pytest

from paper_data_linking.linkers.general.paper_analysis_output_parser import (
    _extract_period_name,
    _extract_quote,
    _is_sub_bullet,
    _match_field_label,
    parse_instrument_markdown,
)

DATA_DIR = Path(__file__).parent.parent / "data" / "parser_test_data"
REAL_PROD_DIR = DATA_DIR / "real_prod"


@pytest.fixture
def simple_markdown():
    return (DATA_DIR / "simple_single_instrument.md").read_text()


@pytest.fixture
def complex_markdown():
    return (DATA_DIR / "multi_instrument_complex.md").read_text()


@pytest.fixture
def expected_simple():
    return json.loads((DATA_DIR / "expected_simple.json").read_text())


@pytest.fixture
def expected_multi():
    return json.loads((DATA_DIR / "expected_multi.json").read_text())


def _all_quotes_for_period(period) -> list:
    """Helper: concatenate every quote field of a DataCollectionPeriod into a single list."""
    return list(period.time_quotes) + list(period.wavelength_quotes) + list(period.physobs_quotes) + list(period.general_quotes)


def _all_quotes_for_instrument(instrument) -> list:
    """Helper: every quote anywhere in an Instrument (top-level + per-period)."""
    out = list(instrument.general_quotes)
    for p in instrument.data_collection_periods:
        out.extend(_all_quotes_for_period(p))
    return out


class TestParseInstrumentMarkdown:
    def test_simple_single_instrument(self, simple_markdown, expected_simple):
        result = parse_instrument_markdown(simple_markdown)
        assert len(result.instruments) == expected_simple["instruments"].__len__()
        assert len(result.instruments) == 1
        inst = result.instruments[0]
        assert len(inst.data_collection_periods) == 2

    def test_multi_instrument_complex(self, complex_markdown, expected_multi):
        result = parse_instrument_markdown(complex_markdown)
        assert len(result.instruments) == 8
        total_periods = sum(
            len(inst.data_collection_periods) for inst in result.instruments
        )
        assert total_periods == 16

    def test_empty_markdown(self):
        result = parse_instrument_markdown("")
        assert len(result.instruments) == 0
        assert result.paper_summary == ""

    def test_no_instruments_section(self):
        md = "## Summary of the Paper\n- **Content Summary**: Just a summary.\n"
        result = parse_instrument_markdown(md)
        assert len(result.instruments) == 0
        assert result.paper_summary == "Just a summary."

    def test_paper_summary_extraction(self, simple_markdown):
        result = parse_instrument_markdown(simple_markdown)
        assert len(result.paper_summary) > 0
        assert isinstance(result.paper_summary, str)

    def test_period_fields_populated(self, simple_markdown):
        result = parse_instrument_markdown(simple_markdown)
        period = result.instruments[0].data_collection_periods[0]
        assert period.time_range
        assert period.physical_observable
        assert period.period_name

    def test_instrument_names_preserved(self, complex_markdown, expected_multi):
        result = parse_instrument_markdown(complex_markdown)
        result_names = [inst.name for inst in result.instruments]
        expected_names = [inst["name"] for inst in expected_multi["instruments"]]
        assert result_names == expected_names

    def test_quotes_collected(self, simple_markdown):
        result = parse_instrument_markdown(simple_markdown)
        period = result.instruments[0].data_collection_periods[0]
        # Should have at least some quotes
        has_quotes = (
            len(period.time_quotes) > 0
            or len(period.wavelength_quotes) > 0
            or len(period.physobs_quotes) > 0
            or len(period.general_quotes) > 0
        )
        assert has_quotes

    def test_output_is_valid_pydantic(self, simple_markdown):
        result = parse_instrument_markdown(simple_markdown)
        # Should serialize without error
        d = result.model_dump()
        assert "paper_summary" in d
        assert "instruments" in d

    def test_minimal_instrument(self):
        md = (
            "## Instrumentation Details\n"
            "### My Instrument\n"
            "#### Data Collection Period 1: First\n"
            "- **Time Range**: 2020-01-01 to 2020-12-31\n"
            "- **Physical Observable**: Temperature\n"
        )
        result = parse_instrument_markdown(md)
        assert len(result.instruments) == 1
        assert result.instruments[0].name == "My Instrument"
        assert len(result.instruments[0].data_collection_periods) == 1
        p = result.instruments[0].data_collection_periods[0]
        assert p.period_name == "First"
        assert "2020" in p.time_range
        assert p.physical_observable == "Temperature"


class TestHelperFunctions:
    def test_extract_period_name_standard(self):
        assert (
            _extract_period_name("#### Data Collection Period 1: Solar Flare Obs")
            == "Solar Flare Obs"
        )

    def test_extract_period_name_numbered(self):
        assert (
            _extract_period_name("#### Data Collection Period 42: Long Name Here")
            == "Long Name Here"
        )

    def test_extract_period_name_no_pattern(self):
        assert _extract_period_name("#### Some Other Heading") == "Some Other Heading"

    def test_match_field_label_time_range(self):
        result = _match_field_label("- **Time Range**: 2020-01-01 to 2020-12-31")
        assert result == ("time_range", "2020-01-01 to 2020-12-31")

    def test_match_field_label_wavelengths(self):
        result = _match_field_label("- **Wavelength(s)**: 171 Å, 304 Å")
        assert result == ("wavelengths", "171 Å, 304 Å")

    def test_match_field_label_physical_observable(self):
        result = _match_field_label("- **Physical Observable**: EUV emission")
        assert result == ("physical_observable", "EUV emission")

    def test_match_field_label_additional_comments(self):
        result = _match_field_label("- **Additional Comments**: Some notes")
        assert result == ("additional_comments", "Some notes")

    def test_match_field_label_general_comments(self):
        result = _match_field_label("- **General Comments**: Overview text")
        assert result == ("general_comments", "Overview text")

    def test_match_field_label_no_match(self):
        assert _match_field_label("Just some regular text") is None

    def test_match_field_label_plain_bold(self):
        result = _match_field_label("- Time Range: 2020-01-01")
        assert result == ("time_range", "2020-01-01")

    def test_extract_quote_standard(self):
        line = '- Supporting Quote: "This is the quote text"'
        assert _extract_quote(line) == "This is the quote text"

    def test_extract_quote_curly(self):
        line = "- Supporting Quote: \u201cCurly quoted text\u201d"
        assert _extract_quote(line) == "Curly quoted text"

    def test_extract_quote_bold_label(self):
        line = '- **Supporting Quote**: "Bold label quote"'
        assert _extract_quote(line) == "Bold label quote"

    def test_extract_quote_no_quote(self):
        assert _extract_quote("- Time Range: 2020-01-01") is None
        assert _extract_quote("Just regular text") is None

    def test_is_sub_bullet_true(self):
        assert _is_sub_bullet("    - sub item") is True
        assert _is_sub_bullet("      - deep sub item") is True

    def test_is_sub_bullet_false(self):
        assert _is_sub_bullet("- top level") is False
        assert _is_sub_bullet("regular text") is False
        assert _is_sub_bullet(" - only one space") is False


# ---------------------------------------------------------------------------
# Parametrized format-variation coverage for _extract_quote.
#
# Each case mirrors a distinct way Supporting Quote lines have been observed
# to appear in real LLM output. The test is the regression bar for the
# extractor — adding a format variation here is the way to declare it
# supported (or explicitly unsupported, via expected=None).
# ---------------------------------------------------------------------------

EXTRACT_QUOTE_CASES = [
    # (id, input_line, expected_output)
    # ASCII straight double quotes (existing behavior)
    ("ascii_quoted", '- Supporting Quote: "Hello"', "Hello"),
    # Curly Unicode double quotes (existing behavior)
    ("curly_quoted", "- Supporting Quote: “Hello”", "Hello"),
    # Bold label, ASCII quoted (existing behavior)
    ("bold_label_ascii_quoted", '- **Supporting Quote**: "Hello"', "Hello"),
    # Bedrock unquoted bare-text format — the failing case we want supported
    (
        "bold_label_unquoted_plain",
        "- **Supporting Quote**: This text has no surrounding quotes.",
        "This text has no surrounding quotes.",
    ),
    # Plain label (no bold), unquoted plain text
    (
        "plain_label_unquoted_plain",
        "- Supporting Quote: bare text",
        "bare text",
    ),
    # Mixed quote chars: ASCII open, curly close. NOTE: the parser captures
    # content greedily back to the LAST closing quote character, so an
    # ill-formed `"mixed"”` (ASCII close followed by curly close) yields
    # `mixed"` — documented quirk, not a target for fixing.
    (
        "mixed_open_ascii_close_curly_documented_quirk",
        '- **Supporting Quote**: "mixed"”',
        'mixed"',
    ),
    # Mixed quote chars: curly open, ASCII close
    (
        "mixed_open_curly_close_ascii",
        '- **Supporting Quote**: “mixed"',
        "mixed",
    ),
    # Quote contains embedded markdown bold
    (
        "embedded_markdown_bold",
        '- **Supporting Quote**: "field at **17:22 UT**"',
        "field at **17:22 UT**",
    ),
    # Quote with trailing whitespace
    (
        "trailing_whitespace",
        '- **Supporting Quote**: "Hello"   ',
        "Hello",
    ),
    # Unquoted with parenthetical citation
    (
        "unquoted_with_citation",
        "- **Supporting Quote**: bare text (Author et al., 2020)",
        "bare text (Author et al., 2020)",
    ),
    # Unquoted starting with capital letter (bedrock common case)
    (
        "unquoted_capital_start",
        "- **Supporting Quote**: The presented magnetic fields are measured by the FGM onboard MMS2.",
        "The presented magnetic fields are measured by the FGM onboard MMS2.",
    ),
    # Unquoted starting with ellipsis-style "..."
    (
        "unquoted_ellipsis_start",
        "- **Supporting Quote**: ... continuation of an elided quote.",
        "... continuation of an elided quote.",
    ),
    # Open quote with no closing on same line (multi-line continuation; existing behavior)
    (
        "open_quote_no_close",
        '- **Supporting Quote**: "Multi-line quote continues',
        "Multi-line quote continues",
    ),
    # Indented sub-bullet (Supporting Quote inside a deeper context)
    (
        "indented_sub_bullet_quoted",
        '  - **Supporting Quote**: "indented quote"',
        "indented quote",
    ),
    # Indented sub-bullet, unquoted
    (
        "indented_sub_bullet_unquoted",
        "  - **Supporting Quote**: indented bare text",
        "indented bare text",
    ),
    # Negative cases — should return None
    ("non_quote_field_label", "- Time Range: 2020-01-01", None),
    ("non_supporting_quote_text", "Just regular paragraph text", None),
]


@pytest.mark.parametrize(
    "case_id,line,expected",
    EXTRACT_QUOTE_CASES,
    ids=[case[0] for case in EXTRACT_QUOTE_CASES],
)
def test_extract_quote_format_variations(case_id, line, expected):
    """Single source of truth for every Supporting Quote format variation we support.

    Add a row to EXTRACT_QUOTE_CASES (above) to declare a new variation supported.
    """
    assert _extract_quote(line) == expected, (
        f"Case '{case_id}' failed: got {_extract_quote(line)!r}, expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Synthetic-fixture coverage for parse_instrument_markdown.
#
# These fixtures isolate one parser failure mode each (unquoted format,
# bullet-style period headers, multi-line quote, etc.) and make assertions
# directly on the structured representation the parser produces.
# ---------------------------------------------------------------------------


@pytest.fixture
def unquoted_quotes_markdown():
    return (DATA_DIR / "unquoted_supporting_quotes.md").read_text()


@pytest.fixture
def mixed_quotes_markdown():
    return (DATA_DIR / "mixed_quoted_unquoted.md").read_text()


@pytest.fixture
def bullet_period_markdown():
    return (DATA_DIR / "bullet_period_headers.md").read_text()


@pytest.fixture
def multiline_quote_markdown():
    return (DATA_DIR / "multiline_supporting_quote.md").read_text()


@pytest.fixture
def dataset_name_quote_markdown():
    return (DATA_DIR / "quote_with_dataset_name.md").read_text()


class TestSyntheticFixtures:
    """Per-format parser variation fixtures."""

    def test_unquoted_supporting_quotes_capture_all_categories(self, unquoted_quotes_markdown):
        """Bedrock's unquoted format must populate every quote category, not silently drop them."""
        result = parse_instrument_markdown(unquoted_quotes_markdown)
        assert len(result.instruments) == 1
        instr = result.instruments[0]
        assert len(instr.data_collection_periods) == 1
        period = instr.data_collection_periods[0]

        # Suite-level quote captured
        assert len(instr.general_quotes) >= 1, (
            f"Expected suite-level general_quotes populated; got {instr.general_quotes!r}"
        )

        # Each period-level quote category captured
        assert len(period.time_quotes) >= 1, "time_quotes empty"
        assert len(period.wavelength_quotes) >= 1, "wavelength_quotes empty"
        assert len(period.physobs_quotes) >= 1, "physobs_quotes empty"
        # general_quotes is filled when a Supporting Quote follows additional_comments
        assert len(period.general_quotes) >= 1, "general_quotes empty"

        # Discriminating tokens survive
        all_quotes = _all_quotes_for_instrument(instr)
        joined = " ".join(all_quotes)
        assert "TOKEN_PHYSOBS_42" in joined, (
            f"Expected TOKEN_PHYSOBS_42 in captured quotes; got {all_quotes!r}"
        )
        assert "TOKEN_GENERAL_99" in joined, (
            f"Expected TOKEN_GENERAL_99 in captured quotes; got {all_quotes!r}"
        )

    def test_mixed_quoted_unquoted_both_captured(self, mixed_quotes_markdown):
        """Same instrument may use both quoted and unquoted Supporting Quote formats; both must capture."""
        result = parse_instrument_markdown(mixed_quotes_markdown)
        assert len(result.instruments) == 1
        instr = result.instruments[0]
        period = instr.data_collection_periods[0]

        all_quotes = " ".join(_all_quotes_for_instrument(instr))
        assert "ASCII double quotes" in all_quotes, "ASCII-quoted suite quote missing"
        assert "TOKEN_CURLY" in all_quotes, "Curly-quoted physobs quote missing"
        assert "TOKEN_UNQUOTED" in all_quotes, "Unquoted general quote missing"
        assert "Wavelength quote uses bare unquoted text" in all_quotes, "Unquoted wavelength quote missing"

    def test_bullet_period_headers_extracted(self, bullet_period_markdown):
        """`- **Data Collection Period N: ...**` (bullet form) must produce DataCollectionPeriod entries.

        Without this, multi-event papers using the bullet form silently produce 0 periods.
        Currently expected to FAIL until the parser is updated to accept this form.
        """
        result = parse_instrument_markdown(bullet_period_markdown)
        assert len(result.instruments) == 1
        instr = result.instruments[0]
        # Two bulleted periods declared in the fixture
        assert len(instr.data_collection_periods) == 2, (
            f"Expected 2 periods (bullet form); got {len(instr.data_collection_periods)}"
        )
        period_names = [p.period_name for p in instr.data_collection_periods]
        assert any("First event" in n for n in period_names)
        assert any("Second event" in n for n in period_names)

    def test_multiline_supporting_quote_captured(self, multiline_quote_markdown):
        """Multi-line Supporting Quote (open quote on label line, content continues onto sub-lines)."""
        result = parse_instrument_markdown(multiline_quote_markdown)
        assert len(result.instruments) == 1
        period = result.instruments[0].data_collection_periods[0]
        all_quotes = " ".join(_all_quotes_for_period(period))
        # Either the parser captures the whole multi-line block or just the first line — at minimum
        # the discriminating token from the first line should appear.
        assert "TOKEN_MULTILINE_77" in all_quotes or "starts on the same line" in all_quotes, (
            f"Multi-line quote not captured at all; got {all_quotes!r}"
        )
        # The unquoted physobs quote must always be captured
        assert "TOKEN_BARE_88" in all_quotes, "Bare unquoted physobs quote missing"

    def test_quote_with_dataset_name_preserved(self, dataset_name_quote_markdown):
        """Supporting Quote containing a literal dataset filename and spacecraft variant identifier
        must survive into the structured representation. This is the LET1/MMS2 test case.
        """
        result = parse_instrument_markdown(dataset_name_quote_markdown)
        assert len(result.instruments) == 1
        instr = result.instruments[0]
        all_quotes_text = " ".join(_all_quotes_for_instrument(instr))

        # The discriminators that grounding needs to see
        assert "MMS2" in all_quotes_text, (
            f"MMS2 (spacecraft variant identifier) not preserved in any quote field; got {all_quotes_text!r}"
        )
        assert "LET1" in all_quotes_text, (
            f"LET1 (sub-instrument identifier) not preserved in any quote field; got {all_quotes_text!r}"
        )
        assert "psp_isois-epihi_l2-let1-rates3600" in all_quotes_text, (
            "Literal CDF dataset filename should survive into the structured quotes"
        )


# ---------------------------------------------------------------------------
# Real-production fixture coverage.
#
# These fixtures are stage-1 instruments_details pulled directly from
# completed PaperAnalysis rows in production. They double as integration
# tests against the actual format variations bedrock and standard emit.
# ---------------------------------------------------------------------------


@pytest.fixture
def bedrock_let1_md():
    return (REAL_PROD_DIR / "bedrock_let1.md").read_text()


@pytest.fixture
def bedrock_mms2_md():
    return (REAL_PROD_DIR / "bedrock_mms2.md").read_text()


@pytest.fixture
def bedrock_mostl_md():
    return (REAL_PROD_DIR / "bedrock_mostl.md").read_text()


@pytest.fixture
def bedrock_cme_23instruments_md():
    return (REAL_PROD_DIR / "bedrock_cme_23instruments.md").read_text()


@pytest.fixture
def bedrock_quoted_success_md():
    return (REAL_PROD_DIR / "bedrock_quoted_success.md").read_text()


@pytest.fixture
def standard_let1_md():
    return (REAL_PROD_DIR / "standard_let1.md").read_text()


class TestRealProdFixtures:
    """Regression tests against actual bedrock and standard stage-1 outputs.

    Each test asserts the discriminating identifier from the paper survives into
    the structured representation. `bedrock_*` cases that use unquoted Supporting
    Quote format are the failing ones until the parser is updated.
    """

    def test_bedrock_let1_preserves_let1(self, bedrock_let1_md):
        """2021A&A...650A..24S (PSP SIR) — LET1 must survive as a quote token."""
        result = parse_instrument_markdown(bedrock_let1_md)
        # IS⊙IS instrument is the first
        assert len(result.instruments) >= 1
        all_quotes_text = " ".join(_all_quotes_for_instrument(result.instruments[0]))
        assert "LET1" in all_quotes_text, (
            "LET1 (the specific EPI-Hi sub-telescope used) was dropped during structuring; "
            f"got quote text: {all_quotes_text[:500]!r}"
        )

    def test_bedrock_mms2_preserves_mms2(self, bedrock_mms2_md):
        """2024GeoRL..5108894C (Alfvén wings) — MMS2 must survive in some quote."""
        result = parse_instrument_markdown(bedrock_mms2_md)
        assert len(result.instruments) >= 1
        # Aggregate across all instruments — MMS2 should appear somewhere
        all_quotes_text = " ".join(
            q for instr in result.instruments for q in _all_quotes_for_instrument(instr)
        )
        assert "MMS2" in all_quotes_text, (
            "MMS2 (the specific spacecraft used) was dropped during structuring; "
            f"got quote text (first 500 chars): {all_quotes_text[:500]!r}"
        )

    def test_bedrock_mostl_captures_quotes(self, bedrock_mostl_md):
        """2008AnGeo..26.3139M — bedrock unquoted format on multi-instrument paper.

        Asserts the parser recovers at least one supporting quote per instrument
        (a baseline sanity check; before the fix, all quote arrays are empty).
        """
        result = parse_instrument_markdown(bedrock_mostl_md)
        assert len(result.instruments) >= 1
        instruments_with_some_quote = sum(
            1 for instr in result.instruments if _all_quotes_for_instrument(instr)
        )
        assert instruments_with_some_quote == len(result.instruments), (
            f"Only {instruments_with_some_quote}/{len(result.instruments)} instruments have any "
            "quotes captured. Bedrock's unquoted format is likely silently dropping them."
        )

    def test_bedrock_cme_23instruments_periods_extracted(self, bedrock_cme_23instruments_md):
        """2010SoPh..265...49B — 23-instrument CME study uses bullet-form period headers.

        Before parser fix: 0 periods extracted across all instruments.
        After parser fix: at least one period per instrument.
        """
        result = parse_instrument_markdown(bedrock_cme_23instruments_md)
        assert len(result.instruments) >= 20, (
            f"Expected ~23 instruments; got {len(result.instruments)}"
        )
        instruments_with_periods = sum(
            1 for instr in result.instruments if instr.data_collection_periods
        )
        assert instruments_with_periods >= len(result.instruments) // 2, (
            f"Only {instruments_with_periods}/{len(result.instruments)} instruments have any "
            "data_collection_periods extracted — bullet-form period headers may be unrecognized."
        )

    def test_bedrock_quoted_success_control(self, bedrock_quoted_success_md):
        """2018AnGeo..36..945J — bedrock paper that emits curly-quoted format.

        Control case: should pass both before and after parser changes.
        """
        result = parse_instrument_markdown(bedrock_quoted_success_md)
        assert len(result.instruments) >= 3
        # Most periods should have at least one quote
        periods_with_quotes = sum(
            1
            for instr in result.instruments
            for p in instr.data_collection_periods
            if _all_quotes_for_period(p)
        )
        total_periods = sum(
            len(instr.data_collection_periods) for instr in result.instruments
        )
        assert total_periods > 0, "No periods extracted at all"
        assert periods_with_quotes / total_periods >= 0.5, (
            f"Only {periods_with_quotes}/{total_periods} periods have quotes; expected most "
            "to be populated for curly-quoted format."
        )

    def test_standard_let1_control(self, standard_let1_md):
        """2021A&A...650A..24S in standard config — uses ASCII-quoted format.

        Control case: standard reliably emits quoted format and should always parse cleanly.
        """
        result = parse_instrument_markdown(standard_let1_md)
        assert len(result.instruments) >= 1
        # Standard tends to split IS⊙IS into EPI-Hi and EPI-Lo entries
        all_quotes_text = " ".join(
            q for instr in result.instruments for q in _all_quotes_for_instrument(instr)
        )
        # Standard preserves LET1 in its quotes too
        assert "LET1" in all_quotes_text, (
            f"Standard config should preserve LET1 in quotes; got: {all_quotes_text[:500]!r}"
        )
