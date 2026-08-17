"""Tests for the validation-campaign API views (blinding, propagation, progress)."""
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz
from django.urls import reverse
from psycopg2.extras import DateTimeTZRange

WINDOW_START = datetime(2003, 1, 1, tzinfo=pytz.UTC)
WINDOW_END = datetime(2003, 1, 2, tzinfo=pytz.UTC)

APPROVE_PAYLOAD = {
    "validation_status": "approved",
    "mission_correct": True,
    "instrument_correct": True,
    "window_correct": True,
}


@pytest.fixture
def test_campaign():
    from paper_data_linking.config.settings import VALIDATION_CAMPAIGNS, ValidationCampaign

    campaign = ValidationCampaign(
        slug="testcamp",
        configs=["cfg-a", "cfg-b"],
        set_tag="test_set_camp",
        tag_prefix="testcamp:",
        reviewers=["testuser", "otheruser"],
        overlap_tag="testcamp:overlap",
        calibration_tag="testcamp:calibration",
        calibration_size=1,
    )
    VALIDATION_CAMPAIGNS["testcamp"] = campaign
    yield campaign
    del VALIDATION_CAMPAIGNS["testcamp"]


@pytest.fixture
def campaign_data(test_campaign, paper_factory, observatory_factory, instrument_factory,
                  paper_analysis_factory, api_client):
    from vso_query_builder.models import DatasetUsage, SupportQuote

    paper = paper_factory(tags=["test_set_camp", "testcamp:testuser"])
    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    pa_a = paper_analysis_factory(paper=paper, configuration_name="cfg-a")
    pa_b = paper_analysis_factory(paper=paper, configuration_name="cfg-b")

    window = DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)")
    du_a = DatasetUsage.objects.create(
        paper=paper, paper_analysis=pa_a, instrument=inst, observation_window=window)
    du_b = DatasetUsage.objects.create(
        paper=paper, paper_analysis=pa_b, instrument=inst, observation_window=window)

    # Same quote text found by both configs — must dedupe in the claim payload.
    for analysis, du in ((pa_a, du_a), (pa_b, du_b)):
        quote = SupportQuote.objects.create(
            paper_analysis=analysis, quote="Observed with LASCO on Jan 1",
            instrument="LASCO", parameter="Period 1:time", page_number=1, y_coord=100.0,
        )
        du.supporting_quotes.add(quote)

    return {"paper": paper, "obs": obs, "inst": inst, "du_a": du_a, "du_b": du_b,
            "pa_a": pa_a, "pa_b": pa_b}


def _other_client(username="stranger"):
    from rest_framework.test import APIClient
    from django.contrib.auth.models import User
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    user = User.objects.create_user(username=username, password="x")
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    client._test_user = user
    return client


@pytest.mark.django_db
class TestCampaignAccess:

    def test_unknown_campaign_404(self, api_client, campaign_data):
        url = reverse("campaign-overview", kwargs={"slug": "nope"})
        assert api_client.get(url).status_code == 404

    def test_non_reviewer_403(self, campaign_data):
        client = _other_client()
        url = reverse("campaign-overview", kwargs={"slug": "testcamp"})
        assert client.get(url).status_code == 403

    def test_unauthenticated_401(self, client, campaign_data):
        url = reverse("campaign-overview", kwargs={"slug": "testcamp"})
        assert client.get(url).status_code == 401


@pytest.mark.django_db
class TestCampaignOverview:

    def test_progress_counts_only_my_votes(self, api_client, campaign_data):
        from vso_query_builder.models import DatasetUsageValidation
        from django.contrib.auth.models import User

        other = User.objects.create_user(username="otheruser", password="x")
        # The co-reviewer votes; my progress must stay 0.
        DatasetUsageValidation.objects.create(
            dataset_usage=campaign_data["du_a"], user=other, validation_status="approved")
        # An anonymous vote must not count either.
        DatasetUsageValidation.objects.create(
            dataset_usage=campaign_data["du_a"], user=None,
            anonymous_id="11111111-1111-1111-1111-111111111111",
            validation_status="approved")

        url = reverse("campaign-overview", kwargs={"slug": "testcamp"})
        data = api_client.get(url).json()
        assert data["stats"]["judged_claims"] == 0
        paper_row = data["papers"][0]
        assert paper_row["total_claims"] == 1
        assert paper_row["my_judged_claims"] == 0
        assert paper_row["resume_usage_id"] is not None

    def test_resume_pointer_and_progress_after_vote(self, api_client, campaign_data):
        url = reverse("campaign-claim-validate",
                      kwargs={"slug": "testcamp", "usage_id": campaign_data["du_a"].id})
        assert api_client.post(url, APPROVE_PAYLOAD, format="json").status_code == 200

        data = api_client.get(reverse("campaign-overview", kwargs={"slug": "testcamp"})).json()
        assert data["stats"]["judged_claims"] == 1
        assert data["papers"][0]["my_judged_claims"] == 1
        assert data["papers"][0]["resume_usage_id"] is None
        assert data["resume"] is None  # everything judged

    def test_calibration_gate(self, api_client, campaign_data, test_campaign):
        rep_id = str(min(campaign_data["du_a"].id, campaign_data["du_b"].id, key=str))
        test_campaign.calibration_usage_ids = [rep_id]
        try:
            url = reverse("campaign-overview", kwargs={"slug": "testcamp"})
            data = api_client.get(url).json()
            assert data["campaign"]["calibration_complete"] is False
            assert data["calibration"]["total"] == 1
            # Resume points at the calibration claim first
            assert data["resume"]["usage_id"] == rep_id

            validate_url = reverse("campaign-claim-validate",
                                   kwargs={"slug": "testcamp", "usage_id": rep_id})
            api_client.post(validate_url, APPROVE_PAYLOAD, format="json")
            data = api_client.get(url).json()
            assert data["campaign"]["calibration_complete"] is True
        finally:
            test_campaign.calibration_usage_ids = []

    def test_zero_claim_papers_excluded(self, api_client, campaign_data, paper_factory):
        """A campaign paper with no DUs from either config has nothing to
        review and must not appear as a 0/0 row in the queue."""
        paper_factory(tags=["test_set_camp", "testcamp:testuser"])
        data = api_client.get(reverse("campaign-overview", kwargs={"slug": "testcamp"})).json()
        assert len(data["papers"]) == 1  # only the paper with claims

    def test_overlap_section_label(self, api_client, campaign_data):
        paper = campaign_data["paper"]
        paper.tags = paper.tags + ["testcamp:overlap"]
        paper.save(update_fields=["tags"])
        data = api_client.get(reverse("campaign-overview", kwargs={"slug": "testcamp"})).json()
        assert data["papers"][0]["section"] == "overlap"


@pytest.mark.django_db
class TestCampaignClaims:

    def test_claims_deduped_and_blinded(self, api_client, campaign_data):
        url = reverse("campaign-paper-claims",
                      kwargs={"slug": "testcamp", "paper_id": campaign_data["paper"].id})
        claims = api_client.get(url).json()
        assert len(claims) == 1  # two DUs, one claim
        claim = claims[0]

        # Blinding regression: nothing config- or consensus-related may appear.
        forbidden = {"configuration_name", "paper_analysis", "analysis",
                     "validation_status", "validated_by", "validated_by_username",
                     "member_usage_ids", "member_count", "validations"}
        assert not (set(claim.keys()) & forbidden), claim.keys()
        serialized = str(claim)
        assert "cfg-a" not in serialized and "cfg-b" not in serialized

        # Quote union deduped by (text, page)
        assert len(claim["supporting_quotes"]) == 1
        assert claim["my_validation_status"] is None
        assert claim["instrument_name"] == "LASCO"

    def test_quoteless_claims_included(self, api_client, campaign_data, instrument_factory):
        from vso_query_builder.models import DatasetUsage

        inst2 = instrument_factory(campaign_data["obs"], "EIT")
        DatasetUsage.objects.create(
            paper=campaign_data["paper"], paper_analysis=campaign_data["pa_a"],
            instrument=inst2,
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        url = reverse("campaign-paper-claims",
                      kwargs={"slug": "testcamp", "paper_id": campaign_data["paper"].id})
        claims = api_client.get(url).json()
        assert len(claims) == 2

    def test_paper_outside_campaign_400(self, api_client, campaign_data, paper_factory):
        outsider = paper_factory(tags=[])
        url = reverse("campaign-paper-claims",
                      kwargs={"slug": "testcamp", "paper_id": outsider.id})
        assert api_client.get(url).status_code == 400


@pytest.mark.django_db
class TestCampaignValidate:

    def _url(self, usage_id):
        return reverse("campaign-claim-validate",
                       kwargs={"slug": "testcamp", "usage_id": usage_id})

    def test_approve_requires_all_checks(self, api_client, campaign_data):
        payload = dict(APPROVE_PAYLOAD, window_correct=False)
        response = api_client.post(self._url(campaign_data["du_a"].id), payload, format="json")
        assert response.status_code == 400

    def test_checks_must_be_booleans_for_verdicts(self, api_client, campaign_data):
        payload = {"validation_status": "approved", "mission_correct": True,
                   "instrument_correct": True}  # window missing
        response = api_client.post(self._url(campaign_data["du_a"].id), payload, format="json")
        assert response.status_code == 400

    def test_reject_requires_notes(self, api_client, campaign_data):
        payload = {"validation_status": "rejected", "mission_correct": True,
                   "instrument_correct": True, "window_correct": False}
        response = api_client.post(self._url(campaign_data["du_a"].id), payload, format="json")
        assert response.status_code == 400

        payload["validation_notes"] = "window over-extends past the studied event"
        response = api_client.post(self._url(campaign_data["du_a"].id), payload, format="json")
        assert response.status_code == 200

    def test_unsure_allows_missing_checks(self, api_client, campaign_data):
        response = api_client.post(
            self._url(campaign_data["du_a"].id),
            {"validation_status": "needs_review"}, format="json")
        assert response.status_code == 200

    def test_propagates_to_all_members_and_recomputes_consensus(self, api_client, campaign_data):
        from vso_query_builder.models import DatasetUsage, DatasetUsageValidation

        response = api_client.post(self._url(campaign_data["du_a"].id), APPROVE_PAYLOAD, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["propagated_to"] == 2
        assert "consensus_status" not in body  # blinding

        rows = DatasetUsageValidation.objects.filter(user__username="testuser")
        assert rows.count() == 2
        assert {r.dataset_usage_id for r in rows} == {campaign_data["du_a"].id, campaign_data["du_b"].id}
        assert all(r.mission_correct and r.instrument_correct and r.window_correct for r in rows)
        # Consensus recomputed on every member DU
        for du in (campaign_data["du_a"], campaign_data["du_b"]):
            du.refresh_from_db()
            assert du.validation_status == "approved"

    def test_atomicity_on_midway_failure(self, api_client, campaign_data):
        from vso_query_builder.models import DatasetUsageValidation

        # The test client re-raises unhandled view exceptions (which would be a
        # 500 in production) — either way, the transaction must roll back fully.
        with patch("vso_query_builder.campaign_views.recompute_consensus",
                   side_effect=[None, RuntimeError("boom")]):
            with pytest.raises(RuntimeError):
                api_client.post(
                    self._url(campaign_data["du_a"].id), APPROVE_PAYLOAD, format="json")
        assert DatasetUsageValidation.objects.filter(user__username="testuser").count() == 0

    def test_revote_upserts_all_members(self, api_client, campaign_data):
        from vso_query_builder.models import DatasetUsageValidation

        api_client.post(self._url(campaign_data["du_a"].id), APPROVE_PAYLOAD, format="json")
        reject = {"validation_status": "rejected", "mission_correct": True,
                  "instrument_correct": False, "window_correct": True,
                  "validation_notes": "wrong instrument suite"}
        api_client.post(self._url(campaign_data["du_b"].id), reject, format="json")

        rows = DatasetUsageValidation.objects.filter(user__username="testuser")
        assert rows.count() == 2  # upserted, not duplicated
        assert all(r.validation_status == "rejected" for r in rows)
        assert all(r.instrument_correct is False for r in rows)

    def test_non_campaign_du_404_and_untouched(self, api_client, campaign_data,
                                               paper_analysis_factory):
        from vso_query_builder.models import DatasetUsage, DatasetUsageValidation

        pa_c = paper_analysis_factory(paper=campaign_data["paper"], configuration_name="cfg-c")
        du_c = DatasetUsage.objects.create(
            paper=campaign_data["paper"], paper_analysis=pa_c,
            instrument=campaign_data["inst"],
            observation_window=DateTimeTZRange(WINDOW_START, WINDOW_END, bounds="[)"),
        )
        # Direct vote on the third-config DU is rejected...
        assert api_client.post(self._url(du_c.id), APPROVE_PAYLOAD, format="json").status_code == 404
        # ...and a campaign vote on the shared claim never touches it.
        api_client.post(self._url(campaign_data["du_a"].id), APPROVE_PAYLOAD, format="json")
        assert not DatasetUsageValidation.objects.filter(dataset_usage=du_c).exists()

    def test_legacy_endpoint_still_accepts_fieldless_payload(self, api_client, campaign_data):
        url = reverse("dataset-usage-validate", kwargs={"usage_id": campaign_data["du_a"].id})
        response = api_client.post(url, {"validation_status": "approved"}, format="json")
        assert response.status_code in (200, 201)
