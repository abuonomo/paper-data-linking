"""Tests for the validation-campaign claim grouping helper."""
from datetime import datetime

import pytest
import pytz
from psycopg2.extras import DateTimeTZRange

from vso_query_builder.campaign_claims import (
    campaign_usages_queryset,
    get_paper_claims,
    resolve_claim,
)

WINDOW_START = datetime(2003, 1, 1, tzinfo=pytz.UTC)
WINDOW_END = datetime(2003, 1, 2, tzinfo=pytz.UTC)
OTHER_END = datetime(2004, 6, 1, tzinfo=pytz.UTC)


@pytest.fixture
def test_campaign():
    """A campaign definition injected into the settings registry."""
    from paper_data_linking.config.settings import VALIDATION_CAMPAIGNS, ValidationCampaign

    campaign = ValidationCampaign(
        slug="testcamp",
        configs=["cfg-a", "cfg-b"],
        set_tag="test_set_camp",
        tag_prefix="testcamp:",
        reviewers=["testuser", "otheruser"],
        overlap_tag="testcamp:overlap",
        calibration_tag="testcamp:calibration",
        calibration_size=3,
    )
    VALIDATION_CAMPAIGNS["testcamp"] = campaign
    yield campaign
    del VALIDATION_CAMPAIGNS["testcamp"]


@pytest.fixture
def campaign_data(test_campaign, paper_factory, observatory_factory, instrument_factory,
                  paper_analysis_factory):
    """One campaign paper with DUs from both configs (shared + divergent claims)."""
    from vso_query_builder.models import DatasetUsage

    paper = paper_factory(tags=["test_set_camp"])
    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    inst2 = instrument_factory(obs, "EIT")
    pa_a = paper_analysis_factory(paper=paper, configuration_name="cfg-a")
    pa_b = paper_analysis_factory(paper=paper, configuration_name="cfg-b")

    def du(analysis, instrument, window):
        return DatasetUsage.objects.create(
            paper=paper,
            paper_analysis=analysis,
            instrument=instrument,
            observation_window=window,
        )

    shared_window = DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)")
    data = {
        "paper": paper, "obs": obs, "inst": inst, "inst2": inst2,
        "pa_a": pa_a, "pa_b": pa_b,
        # Same claim from both configs (identical window)
        "du_a_shared": du(pa_a, inst, shared_window),
        "du_b_shared": du(pa_b, inst, shared_window),
        # Window-divergent: same instrument, cfg-b stretches the window
        "du_a_div": du(pa_a, inst2, DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)")),
        "du_b_div": du(pa_b, inst2, DateTimeTZRange(WINDOW_START, OTHER_END, bounds="[)")),
    }
    return data


@pytest.mark.django_db
class TestClaimGrouping:

    def test_identical_windows_collapse_to_one_claim(self, test_campaign, campaign_data):
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        lasco = [c for c in claims if c.representative.instrument.short_name == "LASCO"]
        assert len(lasco) == 1
        assert len(lasco[0].members) == 2

    def test_divergent_windows_stay_separate_claims(self, test_campaign, campaign_data):
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        eit = [c for c in claims if c.representative.instrument.short_name == "EIT"]
        assert len(eit) == 2
        assert all(len(c.members) == 1 for c in eit)

    def test_bound_form_variants_group_together(self, test_campaign, campaign_data):
        """'[]' vs '[)' with the same endpoints must merge (grouping is on
        annotated lower/upper, not the raw range representation)."""
        from vso_query_builder.models import DatasetUsage

        DatasetUsage.objects.create(
            paper=campaign_data["paper"],
            paper_analysis=campaign_data["pa_b"],
            instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[]"),
        )
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        lasco = [c for c in claims if c.representative.instrument.short_name == "LASCO"]
        # Note: psycopg2 passes '[]' through for tstzrange; if Postgres kept
        # distinct upper bounds this would split — the annotated upper is what
        # decides. Either 1 claim (merged) is required here.
        assert len(lasco) == 1
        assert len(lasco[0].members) == 3

    def test_unbounded_upper_windows_group_together(self, test_campaign, campaign_data,
                                                    instrument_factory):
        """Windows with an open upper bound (upper=None) share a claim key."""
        from vso_query_builder.models import DatasetUsage

        inst3 = instrument_factory(campaign_data["obs"], "MDI")
        for analysis in (campaign_data["pa_a"], campaign_data["pa_b"]):
            DatasetUsage.objects.create(
                paper=campaign_data["paper"],
                paper_analysis=analysis,
                instrument=inst3,
                observation_window=DateTimeTZRange(WINDOW_START, None),
            )
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        open_claims = [c for c in claims if c.representative.instrument.short_name == "MDI"]
        assert len(open_claims) == 1
        assert len(open_claims[0].members) == 2

    def test_third_config_and_null_analysis_excluded(self, test_campaign, campaign_data,
                                                     paper_analysis_factory):
        from vso_query_builder.models import DatasetUsage

        pa_c = paper_analysis_factory(paper=campaign_data["paper"], configuration_name="cfg-c")
        DatasetUsage.objects.create(
            paper=campaign_data["paper"], paper_analysis=pa_c,
            instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        DatasetUsage.objects.create(
            paper=campaign_data["paper"], paper_analysis=None,
            instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        lasco = [c for c in claims if c.representative.instrument.short_name == "LASCO"]
        assert len(lasco) == 1
        assert len(lasco[0].members) == 2  # only cfg-a + cfg-b

    def test_paper_outside_set_tag_excluded(self, test_campaign, campaign_data,
                                            paper_factory, paper_analysis_factory):
        from vso_query_builder.models import DatasetUsage

        outsider = paper_factory(tags=[])
        pa = paper_analysis_factory(paper=outsider, configuration_name="cfg-a")
        du = DatasetUsage.objects.create(
            paper=outsider, paper_analysis=pa, instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        assert campaign_usages_queryset(test_campaign).filter(id=du.id).count() == 0
        assert resolve_claim(test_campaign, du.id) is None

    def test_representative_is_min_uuid_and_deterministic(self, test_campaign, campaign_data):
        claims = get_paper_claims(test_campaign, campaign_data["paper"].id)
        lasco = [c for c in claims if c.representative.instrument.short_name == "LASCO"][0]
        expected = min(str(campaign_data["du_a_shared"].id), str(campaign_data["du_b_shared"].id))
        assert str(lasco.usage_id) == expected
        # Re-grouping yields the same representative
        again = get_paper_claims(test_campaign, campaign_data["paper"].id)
        lasco2 = [c for c in again if c.representative.instrument.short_name == "LASCO"][0]
        assert lasco2.usage_id == lasco.usage_id

    def test_same_claim_in_two_papers_stays_separate(self, test_campaign, campaign_data,
                                                     paper_factory, paper_analysis_factory):
        """Regression: grouping across a multi-paper queryset must not merge
        identical instrument+window claims from different papers."""
        from vso_query_builder.campaign_claims import group_claims
        from vso_query_builder.models import DatasetUsage

        other_paper = paper_factory(tags=["test_set_camp"])
        pa = paper_analysis_factory(paper=other_paper, configuration_name="cfg-a")
        DatasetUsage.objects.create(
            paper=other_paper, paper_analysis=pa, instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        claims = group_claims(campaign_usages_queryset(test_campaign))
        lasco = [c for c in claims if c.representative.instrument.short_name == "LASCO"]
        assert len(lasco) == 2
        assert {c.representative.paper_id for c in lasco} == {
            campaign_data["paper"].id, other_paper.id,
        }

    def test_resolve_claim_from_any_member(self, test_campaign, campaign_data):
        for du in (campaign_data["du_a_shared"], campaign_data["du_b_shared"]):
            claim = resolve_claim(test_campaign, du.id)
            assert claim is not None
            assert len(claim.members) == 2
