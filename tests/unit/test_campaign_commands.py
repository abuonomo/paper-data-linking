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


W1 = DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)")
W2 = DateTimeTZRange(WINDOW_START, datetime(2003, 6, 1, tzinfo=pytz.UTC), bounds="[)")


@pytest.fixture
def window_campaigns():
    """A reference campaign (existing verdicts) + a claim-scoped comparison campaign."""
    from paper_data_linking.config.settings import VALIDATION_CAMPAIGNS, ValidationCampaign

    reference = ValidationCampaign(
        slug="refcamp", configs=["ref-a", "ref-b"], set_tag="test_set_camp",
        tag_prefix="refcamp:", reviewers=["alice"], overlap_tag="refcamp:overlap",
        calibration_tag="refcamp:calibration",
    )
    window = ValidationCampaign(
        slug="wincamp", configs=["cfg-a", "cfg-b"], set_tag="wincamp:set",
        tag_prefix="wincamp:", reviewers=["alice"], overlap_tag="wincamp:overlap",
        calibration_tag="wincamp:calibration", calibration_size=0, claim_scoped=True,
    )
    VALIDATION_CAMPAIGNS["refcamp"] = reference
    VALIDATION_CAMPAIGNS["wincamp"] = window
    yield reference, window
    del VALIDATION_CAMPAIGNS["refcamp"]
    del VALIDATION_CAMPAIGNS["wincamp"]


@pytest.fixture
def window_universe(window_campaigns, paper_factory, observatory_factory, instrument_factory,
                    paper_analysis_factory):
    """Per paper: X window-divergent across configs, Y cfg-a only, Z shared.

    Paper 0's cfg-a X/W1 claim also exists in the reference campaign with a
    reviewer verdict, so it must be skipped. Every paper also has a quote-less
    cfg-a Q claim (never drawable), and paper 1's cfg-b asserts Y/W1 without
    quotes, which still makes cfg-a's Y/W1 a shared claim there.
    """
    from django.contrib.auth.models import User
    from vso_query_builder.models import DatasetUsage, DatasetUsageValidation, SupportQuote

    obs = observatory_factory("SOHO")
    inst = {name: instrument_factory(obs, name) for name in ("X", "Y", "Z", "Q")}
    alice = User.objects.create_user(username="alice", password="x")
    ids = {"shared": set(), "judged": set(), "window": set(), "pair": set(), "unquoted": set()}
    papers = []
    for i in range(6):
        paper = paper_factory(tags=["test_set_camp"])
        papers.append(paper)
        pa = {cfg: paper_analysis_factory(paper=paper, configuration_name=cfg)
              for cfg in ("cfg-a", "cfg-b", "ref-a")}

        def du(cfg, name, window, quoted=True):
            usage = DatasetUsage.objects.create(
                paper=paper, paper_analysis=pa[cfg], instrument=inst[name], observation_window=window)
            if quoted:
                usage.supporting_quotes.add(SupportQuote.objects.create(
                    paper_analysis=pa[cfg], quote=f"{name} in paper {i}", instrument=name,
                    parameter="Period 1:time", page_number=1, y_coord=10.0))
            return usage

        x_a, x_b = du("cfg-a", "X", W1), du("cfg-b", "X", W2)
        (ids["judged"] if i == 0 else ids["window"]).add(str(x_a.id))
        ids["window"].add(str(x_b.id))
        y_a = str(du("cfg-a", "Y", W1).id)
        if i == 1:
            ids["shared"].update({y_a, str(du("cfg-b", "Y", W1, quoted=False).id)})
        else:
            ids["pair"].add(y_a)
        ids["unquoted"].add(str(du("cfg-a", "Q", W1, quoted=False).id))
        ids["shared"].update({str(du("cfg-a", "Z", W1).id), str(du("cfg-b", "Z", W1).id)})
        if i == 0:
            ref = du("ref-a", "X", W1)
            DatasetUsageValidation.objects.create(dataset_usage=ref, user=alice, validation_status="approved")
    return papers, ids


@pytest.mark.django_db
class TestSampleWindowClaims:

    def _run(self, **kwargs):
        out, err = StringIO(), StringIO()
        opts = dict(campaign="wincamp", reference_campaign="refcamp", seed=7, per_config=4,
                    window_share=0.5, max_per_paper=3, dry_run=True, stdout=out, stderr=err)
        opts.update(kwargs)
        call_command("sample_window_claims", **opts)
        return json.loads(out.getvalue())

    def test_only_disagreement_claims_never_judged_or_shared(self, window_universe):
        _, ids = window_universe
        data = self._run(per_config=50)
        sampled = set(data["claim_usage_ids"])
        assert sampled == ids["window"] | ids["pair"]
        assert not sampled & (ids["shared"] | ids["judged"] | ids["unquoted"])

    def test_strata_and_configs_labeled(self, window_universe):
        _, ids = window_universe
        data = self._run(per_config=50)
        for claim in data["key"]:
            expected = "window_divergent" if claim["usage_id"] in ids["window"] else "pair_unique"
            assert claim["stratum"] == expected
        assert {c["config"] for c in data["key"]} == {"cfg-a", "cfg-b"}

    def test_targets_per_config_with_backfill(self, window_universe):
        data = self._run(per_config=4, window_share=0.5)
        by_cfg = {}
        for claim in data["key"]:
            by_cfg.setdefault(claim["config"], []).append(claim["stratum"])
        assert sorted(by_cfg["cfg-a"]) == ["pair_unique"] * 2 + ["window_divergent"] * 2
        # cfg-b has no pair_unique claims: its shortfall backfills from window_divergent.
        assert by_cfg["cfg-b"] == ["window_divergent"] * 4

    def test_per_paper_cap(self, window_universe):
        data = self._run(per_config=50, max_per_paper=1)
        per = {}
        for claim in data["key"]:
            per[(claim["config"], claim["paper_id"])] = per.get((claim["config"], claim["paper_id"]), 0) + 1
        assert max(per.values()) == 1

    def test_seed_determinism(self, window_universe):
        assert self._run() == self._run()
        assert self._run()["claim_usage_ids"] != self._run(seed=8)["claim_usage_ids"]

    def test_tagging_applied_without_dry_run(self, window_universe):
        from vso_query_builder.models import Paper

        data = self._run(dry_run=False)
        tagged = {str(p.id) for p in Paper.objects.filter(tags__contains=["wincamp:set", "wincamp:alice"])}
        assert tagged == {c["paper_id"] for c in data["key"]}

    def test_dry_run_tags_nothing(self, window_universe):
        from vso_query_builder.models import Paper

        self._run()
        assert not Paper.objects.filter(tags__contains=["wincamp:set"]).exists()

    def test_refuses_unscoped_campaign(self, window_universe, test_campaign):
        with pytest.raises(CommandError, match="not claim-scoped"):
            self._run(campaign="testcamp")
