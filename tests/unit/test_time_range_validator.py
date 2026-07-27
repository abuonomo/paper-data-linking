"""Tests for TimeRangeDateValidator detect() and fix()."""

import json
from unittest.mock import Mock

import pytest

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    DataCollectionPeriod,
    Instrument,
    StructuredInstrumentDetails,
)
from paper_data_linking.linkers.general.validators.time_range_validator import (
    TimeRangeDateValidator,
)


def _period(time_range="", **kw):
    defaults = dict(
        period_name="P1",
        time_range=time_range,
        time_quotes=[],
        wavelengths=None,
        wavelength_quotes=[],
        physical_observable="obs",
        physobs_quotes=[],
        general_quotes=[],
        additional_comments=None,
    )
    defaults.update(kw)
    return DataCollectionPeriod(**defaults)


def _instrument(periods, name="Inst"):
    return Instrument(
        name=name,
        general_comments="",
        general_quotes=[],
        data_collection_periods=periods,
    )


def _structured(instruments):
    return StructuredInstrumentDetails(
        paper_summary="test",
        instruments=instruments,
    )


@pytest.fixture
def validator():
    return TimeRangeDateValidator(llm_client=None, llm_config=None)


class TestDetect:
    def test_all_dates_present(self, validator):
        s = _structured([
            _instrument([
                _period("2020-01-01 to 2020-06-30"),
                _period("2019-03-15T10:00 UT"),
            ])
        ])
        issues = validator.detect(s, "")
        assert len(issues) == 0

    def test_missing_date_flagged(self, validator):
        s = _structured([
            _instrument([_period("Not specified in the paper")])
        ])
        issues = validator.detect(s, "")
        assert len(issues) == 1
        assert "missing_date" in issues[0].issue_type

    def test_descriptive_text_flagged(self, validator):
        s = _structured([
            _instrument([_period("see TRACE periods above")])
        ])
        issues = validator.detect(s, "")
        assert len(issues) == 1

    def test_empty_time_range_skipped(self, validator):
        s = _structured([_instrument([_period("")])])
        issues = validator.detect(s, "")
        assert len(issues) == 0

    def test_none_time_range_skipped(self, validator):
        p = _period("")
        p.time_range = None
        s = _structured([_instrument([p])])
        issues = validator.detect(s, "")
        assert len(issues) == 0

    def test_mixed_periods(self, validator):
        s = _structured([
            _instrument([
                _period("2020-01-01 to 2020-12-31"),
                _period("Not specified"),
                _period("1999-03-15"),
            ])
        ])
        issues = validator.detect(s, "")
        assert len(issues) == 1
        assert "data_collection_periods[1]" in issues[0].field_path

    def test_year_pattern_various(self, validator):
        """Various formats that contain a year should not be flagged."""
        for tr in [
            "2011-09-13T22:00",
            "circa 2005",
            "1999–2003",
            "November 2016 to May 2021",
            "The year 1990 observation",
        ]:
            s = _structured([_instrument([_period(tr)])])
            issues = validator.detect(s, "")
            assert len(issues) == 0, f"'{tr}' should not be flagged"

    def test_field_path_format(self, validator):
        s = _structured([
            _instrument([_period("2020-01-01")], name="A"),
            _instrument([
                _period("ok date 2020"),
                _period("no date here"),
            ], name="B"),
        ])
        issues = validator.detect(s, "")
        assert len(issues) == 1
        assert issues[0].field_path == "instruments[1].data_collection_periods[1].time_range"


class TestFix:
    def test_fix_no_llm_client_raises(self):
        v = TimeRangeDateValidator(llm_client=None, llm_config=Mock())
        s = _structured([_instrument([_period("no date")])])
        issues = v.detect(s, "")
        with pytest.raises(AttributeError):
            v.fix(s, issues, "markdown")

    def test_fix_applies_patches(self):
        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(
                    content=json.dumps({
                        "patches": [
                            {
                                "field_path": "instruments[0].data_collection_periods[0].time_range",
                                "new_value": "2020-01-15 to 2020-02-15",
                                "reasoning": "Inferred from context",
                            }
                        ],
                        "unfixable_paths": [],
                    })
                )
            )
        ]
        mock_client = Mock()
        mock_client.completion.return_value = mock_response

        mock_sv_config = Mock()
        mock_sv_config.model = "test-model"
        mock_sv_config.to_kwargs.return_value = {}

        mock_config = Mock()
        mock_config.structure_validation = mock_sv_config

        v = TimeRangeDateValidator(llm_client=mock_client, llm_config=mock_config)
        s = _structured([_instrument([_period("see above")])])
        issues = v.detect(s, "")

        result = v.fix(s, issues, "original markdown")
        assert (
            result.instruments[0].data_collection_periods[0].time_range
            == "2020-01-15 to 2020-02-15"
        )
        mock_client.completion.assert_called_once()

    def test_fix_unfixable(self):
        mock_response = Mock()
        mock_response.choices = [
            Mock(
                message=Mock(
                    content=json.dumps({
                        "patches": [],
                        "unfixable_paths": [
                            "instruments[0].data_collection_periods[0].time_range"
                        ],
                    })
                )
            )
        ]
        mock_client = Mock()
        mock_client.completion.return_value = mock_response

        mock_sv_config = Mock()
        mock_sv_config.model = "test-model"
        mock_sv_config.to_kwargs.return_value = {}

        mock_config = Mock()
        mock_config.structure_validation = mock_sv_config

        v = TimeRangeDateValidator(llm_client=mock_client, llm_config=mock_config)
        s = _structured([_instrument([_period("lab measurement")])])
        issues = v.detect(s, "")

        result = v.fix(s, issues, "markdown")
        # Unchanged
        assert (
            result.instruments[0].data_collection_periods[0].time_range
            == "lab measurement"
        )

    def test_fix_llm_parse_error(self):
        mock_response = Mock()
        mock_response.choices = [
            Mock(message=Mock(content="not valid json at all"))
        ]
        mock_client = Mock()
        mock_client.completion.return_value = mock_response

        mock_sv_config = Mock()
        mock_sv_config.model = "test-model"
        mock_sv_config.to_kwargs.return_value = {}

        mock_config = Mock()
        mock_config.structure_validation = mock_sv_config

        v = TimeRangeDateValidator(llm_client=mock_client, llm_config=mock_config)
        s = _structured([_instrument([_period("no date")])])
        issues = v.detect(s, "")

        result = v.fix(s, issues, "markdown")
        # Should return original on parse failure
        assert result.instruments[0].data_collection_periods[0].time_range == "no date"

    def test_fix_empty_issues(self):
        v = TimeRangeDateValidator(llm_client=Mock(), llm_config=Mock())
        s = _structured([_instrument([_period("2020-01-01")])])
        result = v.fix(s, [], "markdown")
        # No-op
        assert result is s
