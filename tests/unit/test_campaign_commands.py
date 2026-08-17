"""Tests for the campaign tagging and calibration-sampling commands."""
import json
from datetime import datetime
from io import StringIO

import pytest
import pytz
from django.core.management import call_command
from django.core.management.base import CommandError
from psycopg2.extras import DateTimeTZRange

WINDOW_START = datetime(2003, 1, 1, tzinfo=pytz.UTC)
WINDOW_END = datetime(2003, 1, 2, tzinfo=pytz.UTC)


@pytest.fixture
def test_campaign():
    from paper_data_linking.config.settings import VALIDATION_CAMPAIGNS, ValidationCampaign

    campaign = ValidationCampaign(
        slug="testcamp",
        configs=["cfg-a", "cfg-b"],
        set_tag="test_set_camp",
        tag_prefix="testcamp:",
        reviewers=["alice", "bob"],
        overlap_tag="testcamp:overlap",
        calibration_tag="testcamp:calibration",
        calibration_size=3,
    )
    VALIDATION_CAMPAIGNS["testcamp"] = campaign
    yield campaign
    del VALIDATION_CAMPAIGNS["testcamp"]


@pytest.fixture
def campaign_papers(test_campaign, paper_factory):
    return [paper_factory(tags=["test_set_camp"]) for _ in range(12)]


def _assignments(papers):
    """Map paper id -> campaign tags after refresh."""
    result = {}
    for paper in papers:
        paper.refresh_from_db()
        result[paper.id] = sorted(t for t in paper.tags if t.startswith("testcamp:"))
    return result


@pytest.mark.django_db
class TestTagValidationCampaign:

    def _run(self, **kwargs):
        out, err = StringIO(), StringIO()
        opts = dict(campaign="testcamp", seed=42, overlap_count=3, stdout=out, stderr=err)
        opts.update(kwargs)
        call_command("tag_validation_campaign", **opts)
        return out.getvalue()

    def test_split_covers_all_papers_disjointly(self, campaign_papers):
        self._run()
        assignments = _assignments(campaign_papers)
        overlap = [p for p, tags in assignments.items() if tags == ["testcamp:overlap"]]
        alice = [p for p, tags in assignments.items() if tags == ["testcamp:alice"]]
        bob = [p for p, tags in assignments.items() if tags == ["testcamp:bob"]]
        assert len(overlap) == 3
        assert len(alice) + len(bob) == len(campaign_papers) - 3
        assert abs(len(alice) - len(bob)) <= 1
        # Every paper got exactly one campaign tag
        assert all(len(tags) == 1 for tags in assignments.values())

    def test_seed_determinism(self, campaign_papers):
        self._run()
        first = _assignments(campaign_papers)
        self._run(force=True)
        assert _assignments(campaign_papers) == first

    def test_different_seed_changes_split(self, campaign_papers):
        self._run()
        first = _assignments(campaign_papers)
        self._run(force=True, seed=43)
        # Extremely unlikely to be identical for 12 papers; treat equality as failure.
        assert _assignments(campaign_papers) != first

    def test_idempotency_guard(self, campaign_papers):
        self._run()
        with pytest.raises(CommandError, match="--force"):
            self._run()

    def test_dry_run_applies_nothing(self, campaign_papers):
        self._run(dry_run=True)
        assert all(tags == [] for tags in _assignments(campaign_papers).values())


@pytest.fixture
def claim_universe(test_campaign, paper_factory, observatory_factory, instrument_factory,
                   paper_analysis_factory):
    """A small claim universe spanning several strata."""
    from vso_query_builder.models import DatasetUsage, SupportQuote

    obs_soho = observatory_factory("SOHO")
    obs_omni = observatory_factory("OMNI")
    obs_goes = observatory_factory("GOES-15")
    instruments = {
        "lasco": instrument_factory(obs_soho, "LASCO"),
        "omni": instrument_factory(obs_omni, "OMNI-merged"),
        "xrs": instrument_factory(obs_goes, "XRS"),
        "suite": instrument_factory(obs_soho, "SECCHI/EUVI"),
    }

    window = DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)")
    papers = []
    for i in range(4):
        paper = paper_factory(tags=["test_set_camp"])
        papers.append(paper)
        pa_a = paper_analysis_factory(paper=paper, configuration_name="cfg-a")
        pa_b = paper_analysis_factory(paper=paper, configuration_name="cfg-b")
        for name, inst in instruments.items():
            du_a = DatasetUsage.objects.create(
                paper=paper, paper_analysis=pa_a, instrument=inst, observation_window=window)
            quote_a = SupportQuote.objects.create(
                paper_analysis=pa_a, quote=f"Quote one about {name} in paper {i}",
                instrument=name, parameter="Period 1:time", page_number=1, y_coord=10.0)
            quote_a2 = SupportQuote.objects.create(
                paper_analysis=pa_a, quote=f"Quote two about {name} in paper {i}",
                instrument=name, parameter="Period 1:time", page_number=2, y_coord=20.0)
            du_a.supporting_quotes.add(quote_a, quote_a2)
            if name != "lasco" or i % 2 == 0:
                # lasco in odd papers stays cfg-a-only
                du_b = DatasetUsage.objects.create(
                    paper=paper, paper_analysis=pa_b, instrument=inst, observation_window=window)
                du_b.supporting_quotes.add(quote_a, quote_a2)
    return papers


@pytest.mark.django_db
class TestSampleCalibrationClaims:

    def _run(self, **kwargs):
        out, err = StringIO(), StringIO()
        opts = dict(campaign="testcamp", seed=7, dry_run=True, stdout=out, stderr=err)
        opts.update(kwargs)
        call_command("sample_calibration_claims", **opts)
        return out.getvalue(), err.getvalue()

    def test_stdout_is_pure_json(self, claim_universe):
        out, _ = self._run()
        data = json.loads(out)  # raises if the report leaked into stdout
        assert data["campaign"] == "testcamp"
        assert data["seed"] == 7
        assert data["n_claims"] == len(data["claims"]) > 0

    def test_no_duplicate_claims_and_strata_labeled(self, claim_universe):
        out, _ = self._run()
        data = json.loads(out)
        ids = [c["usage_id"] for c in data["claims"]]
        assert len(ids) == len(set(ids))
        assert all(c["stratum"] for c in data["claims"])
        strata = {c["stratum"] for c in data["claims"]}
        assert "config_a_only" in strata     # the lasco odd-paper claims
        assert "omni_composite" in strata

    def test_seed_determinism(self, claim_universe):
        out1, _ = self._run()
        out2, _ = self._run()
        assert json.loads(out1) == json.loads(out2)

    def test_tagging_applied_without_dry_run(self, claim_universe, test_campaign):
        out, _ = self._run(dry_run=False)
        data = json.loads(out)
        from vso_query_builder.models import Paper

        tagged = set(
            str(pid) for pid in Paper.objects.filter(
                tags__contains=[test_campaign.calibration_tag]
            ).values_list("id", flat=True)
        )
        assert tagged == {c["paper_id"] for c in data["claims"]}
