"""Tests for NormalizationContext, specifically mission-only match support."""
import pytest

from paper_data_linking.linkers.general.normalizers.normalization_context import (
    GroundingResult,
    NormalizationContext,
)
from paper_data_linking.linkers.general.normalizers.normalization_models import (
    InternalDataCollectionPeriod,
)


def _make_grounding_result(**overrides):
    defaults = dict(
        matched_instrument_code=None,
        matched_mission_code="MLSO",
        matched_instrument_name=None,
        matched_mission_name="Mauna Loa Solar Observatory",
        data_system="VSO",
        reasoning="",
    )
    defaults.update(overrides)
    return GroundingResult(**defaults)


def _make_context(**overrides):
    defaults = dict(
        period_data=InternalDataCollectionPeriod(period_name="general"),
        instrument_code=None,
        instrument_name="MLSO",
        data_system="VSO",
        period_name="general",
        grounding_result=_make_grounding_result(),
    )
    defaults.update(overrides)
    return NormalizationContext(**defaults)


class TestMissionOnlyNormalizationContext:
    """Regression tests for mission-only matches where instrument_code is None."""

    def test_none_instrument_code_accepted(self):
        """NormalizationContext should accept instrument_code=None for mission-only matches."""
        ctx = _make_context(instrument_code=None)
        assert ctx.instrument_code is None

    def test_string_instrument_code_still_works(self):
        """Normal case: string instrument_code should still work."""
        ctx = _make_context(instrument_code="eit")
        assert ctx.instrument_code == "eit"

    def test_instrument_code_defaults_to_none(self):
        """instrument_code should default to None when omitted."""
        ctx = NormalizationContext(
            period_data=InternalDataCollectionPeriod(period_name="general"),
            instrument_name="MLSO",
            data_system="VSO",
            period_name="general",
            grounding_result=_make_grounding_result(),
        )
        assert ctx.instrument_code is None
