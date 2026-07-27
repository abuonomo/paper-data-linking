"""Tests for patch_utils: path parsing and model patching."""

import pytest

from paper_data_linking.linkers.general.schemas.structured_instruments import (
    DataCollectionPeriod,
    Instrument,
    StructuredInstrumentDetails,
)
from paper_data_linking.linkers.general.validators.patch_utils import (
    _parse_path,
    _resolve,
    apply_patch,
)


def _make_model(**overrides):
    """Build a minimal StructuredInstrumentDetails for testing."""
    defaults = {
        "paper_summary": "Test summary",
        "instruments": [
            Instrument(
                name="Instrument A",
                general_comments="",
                general_quotes=[],
                data_collection_periods=[
                    DataCollectionPeriod(
                        period_name="Period 1",
                        time_range="descriptive text",
                        time_quotes=[],
                        wavelengths=None,
                        wavelength_quotes=[],
                        physical_observable="obs",
                        physobs_quotes=[],
                        general_quotes=[],
                        additional_comments=None,
                    ),
                    DataCollectionPeriod(
                        period_name="Period 2",
                        time_range="2020-01-01",
                        time_quotes=[],
                        wavelengths="171 Å",
                        wavelength_quotes=[],
                        physical_observable="EUV",
                        physobs_quotes=[],
                        general_quotes=[],
                        additional_comments=None,
                    ),
                ],
            ),
        ],
    }
    defaults.update(overrides)
    return StructuredInstrumentDetails(**defaults)


class TestParsePath:
    def test_simple_attribute(self):
        assert _parse_path("paper_summary") == ["paper_summary"]

    def test_array_index(self):
        assert _parse_path("instruments[0]") == ["instruments", 0]

    def test_nested_path(self):
        path = "instruments[0].data_collection_periods[1].time_range"
        expected = [
            "instruments", 0,
            "data_collection_periods", 1,
            "time_range",
        ]
        assert _parse_path(path) == expected

    def test_multiple_indices(self):
        path = "instruments[2].data_collection_periods[5]"
        expected = ["instruments", 2, "data_collection_periods", 5]
        assert _parse_path(path) == expected


class TestResolve:
    def test_resolve_attribute(self):
        model = _make_model()
        assert _resolve(model, "paper_summary") == "Test summary"

    def test_resolve_index(self):
        items = ["a", "b", "c"]
        assert _resolve(items, 1) == "b"


class TestApplyPatch:
    def test_set_time_range(self):
        model = _make_model()
        apply_patch(
            model,
            "instruments[0].data_collection_periods[0].time_range",
            "2023-06-15 to 2023-06-20",
        )
        assert (
            model.instruments[0].data_collection_periods[0].time_range
            == "2023-06-15 to 2023-06-20"
        )

    def test_set_paper_summary(self):
        model = _make_model()
        apply_patch(model, "paper_summary", "New summary")
        assert model.paper_summary == "New summary"

    def test_set_wavelengths(self):
        model = _make_model()
        apply_patch(
            model,
            "instruments[0].data_collection_periods[0].wavelengths",
            "304 Å",
        )
        assert model.instruments[0].data_collection_periods[0].wavelengths == "304 Å"

    def test_second_period(self):
        model = _make_model()
        apply_patch(
            model,
            "instruments[0].data_collection_periods[1].time_range",
            "patched",
        )
        assert model.instruments[0].data_collection_periods[1].time_range == "patched"
        # First period unchanged
        assert (
            model.instruments[0].data_collection_periods[0].time_range
            == "descriptive text"
        )

    def test_index_out_of_bounds(self):
        model = _make_model()
        with pytest.raises(IndexError):
            apply_patch(
                model,
                "instruments[5].data_collection_periods[0].time_range",
                "value",
            )

    def test_invalid_attribute(self):
        model = _make_model()
        with pytest.raises((AttributeError, ValueError)):
            apply_patch(
                model,
                "instruments[0].nonexistent_field",
                "value",
            )
