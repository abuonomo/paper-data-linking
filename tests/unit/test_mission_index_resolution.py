"""Deterministic tests for #170: mission-index off-by-one correction.

`mission_identification` asks the model for `ShortCode(index)` pairs; the model
reliably names the mission but occasionally writes a 1-based index off by ±1.
`InstrumentGrounder._resolve_mission_index` trusts the token to validate/correct
the index. These tests are pure logic — no LLM, no DB.
"""
from types import SimpleNamespace
import pytest


def _missions(*names_and_codes):
    return [SimpleNamespace(mission_name=n, mission_code=c) for n, c in names_and_codes]


@pytest.fixture
def grounder():
    # _resolve_mission_index / _norm_token don't touch self state, so a bare instance
    # via __new__ is enough (avoids constructing finder/llm deps).
    from paper_data_linking.linkers.general.instrument_grounder import InstrumentGrounder
    return InstrumentGrounder.__new__(InstrumentGrounder)


# A slice mimicking the real adjacency that triggered the bug.
SORTED = _missions(
    ("Park Site Geophysical Observatory", "spase://SMWG/Observatory/PARK"),
    ("Parker Solar Probe", "spase://SMWG/Observatory/ParkerSolarProbe"),     # idx 1
    ("Pello Geophysical Observatory", "spase://SMWG/Observatory/PELLO"),     # idx 2
    ("Petersburg Geophysical Observatory", "spase://SMWG/Observatory/PET"),
)


class TestResolveMissionIndex:

    def test_index_correct_kept(self, grounder):
        # token names Parker, index points at Parker -> unchanged
        assert grounder._resolve_mission_index("Parker Solar Probe", 1, SORTED) == 1

    def test_off_by_plus_one_corrected(self, grounder):
        # the real bug: token Parker, but index points at the next mission (Pello)
        assert grounder._resolve_mission_index("Parker Solar Probe", 2, SORTED) == 1

    def test_off_by_minus_one_corrected(self, grounder):
        # token Pello, index points one before (Parker) -> corrected to Pello
        assert grounder._resolve_mission_index("Pello Geophysical Observatory", 1, SORTED) == 2

    def test_uppercased_despaced_token_matches(self, grounder):
        # the model sometimes writes PARKERSOLARPROBE
        assert grounder._resolve_mission_index("PARKERSOLARPROBE", 2, SORTED) == 1

    def test_code_segment_abbreviation_matches(self, grounder):
        ms = _missions(
            ("Solar and Heliospheric Observatory", "spase://SMWG/Observatory/SOHO"),
            ("Wind", "spase://SMWG/Observatory/Wind"),
        )
        # token 'SOHO' matches by mission_code last segment even though the name differs;
        # index wrong (points at Wind) -> corrected to SOHO
        assert grounder._resolve_mission_index("SOHO", 1, ms) == 0

    def test_unrelated_token_keeps_index(self, grounder):
        # token matches neither the index nor its neighbours -> keep index (no worse than before)
        assert grounder._resolve_mission_index("Zorblax", 1, SORTED) == 1

    def test_out_of_range_index_resolved_by_token(self, grounder):
        # index wildly wrong/out of range -> find the named mission anywhere
        assert grounder._resolve_mission_index("Parker Solar Probe", 999, SORTED) == 1

    def test_out_of_range_unknown_token_returns_none(self, grounder):
        assert grounder._resolve_mission_index("Zorblax", 999, SORTED) is None
