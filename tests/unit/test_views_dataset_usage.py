"""Tests for DatasetUsage-related views."""
import pytest
from datetime import datetime
from django.urls import reverse
from psycopg2.extras import DateTimeTZRange
import pytz


@pytest.fixture
def dataset_usage_data(vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    """Create a complete set of test data for dataset usage views."""
    from vso_query_builder.models import DatasetUsage, SupportQuote

    obs = observatory_factory("SOHO")
    inst = instrument_factory(obs, "LASCO")
    pa = paper_analysis_factory()

    start = datetime(2003, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2003, 1, 2, tzinfo=pytz.UTC)
    du = DatasetUsage.objects.create(
        paper=pa.paper,
        instrument=inst,
        paper_analysis=pa,
        observation_window=DateTimeTZRange(start, end, bounds="[]"),
        validation_status="pending",
    )

    quote = SupportQuote.objects.create(
        paper_analysis=pa,
        quote="Observed with LASCO on Jan 1",
        instrument="LASCO",
        parameter="Period 1:time",
        page_number=1,
        y_coord=100.0,
    )
    du.supporting_quotes.add(quote)

    return {
        "observatory": obs,
        "instrument": inst,
        "paper_analysis": pa,
        "paper": pa.paper,
        "dataset_usage": du,
        "quote": quote,
    }


@pytest.mark.django_db
class TestDatasetUsageListView:

    def test_returns_200_with_auth(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = api_client.get(url)
        assert response.status_code == 200

    def test_returns_401_without_auth(self, client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = client.get(url)
        assert response.status_code == 401

    def test_filters_by_instrument(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = api_client.get(url, {"instrument": "LASCO"})
        assert response.status_code == 200
        results = response.data["results"] if "results" in response.data else response.data
        assert len(results) >= 1

    def test_filters_by_observatory(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = api_client.get(url, {"observatory": "soho"})
        assert response.status_code == 200

    def test_filters_by_paper_bibcode(self, api_client, dataset_usage_data):
        bibcode = dataset_usage_data["paper"].bibcode
        url = reverse("dataset-usage-list")
        response = api_client.get(url, {"paper": bibcode})
        assert response.status_code == 200

    def test_filters_by_date_range(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = api_client.get(url, {
            "start_date": "2003-01-01",
            "end_date": "2003-01-03",
        })
        assert response.status_code == 200

    def test_no_results_for_nonmatching_filter(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-list")
        response = api_client.get(url, {"instrument": "NONEXISTENT"})
        assert response.status_code == 200
        results = response.data["results"] if "results" in response.data else response.data
        assert len(results) == 0


@pytest.mark.django_db
class TestDatasetUsageDetailView:

    def test_returns_detail(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-detail", kwargs={"id": du.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["id"] == str(du.id)

    def test_404_for_nonexistent(self, api_client, dataset_usage_data):
        import uuid
        url = reverse("dataset-usage-detail", kwargs={"id": uuid.uuid4()})
        response = api_client.get(url)
        assert response.status_code == 404


@pytest.mark.django_db
class TestDatasetUsageStatsView:

    def test_returns_stats(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-stats")
        response = api_client.get(url)
        assert response.status_code == 200
        assert "total_count" in response.data
        assert response.data["total_count"] >= 1

    def test_stats_with_instrument_filter(self, api_client, dataset_usage_data):
        url = reverse("dataset-usage-stats")
        response = api_client.get(url, {"instrument": "LASCO"})
        assert response.status_code == 200
        assert response.data["total_count"] >= 1


@pytest.mark.django_db
class TestDatasetUsageValidationView:

    def test_approve_usage(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = api_client.post(url, {"validation_status": "approved"})
        assert response.status_code == 200
        assert response.data["validation_status"] == "approved"

    def test_reject_with_notes(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = api_client.post(url, {
            "validation_status": "rejected",
            "validation_notes": "Incorrect instrument",
        })
        assert response.status_code == 200
        assert response.data["validation_status"] == "rejected"

    def test_invalid_status_returns_400(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = api_client.post(url, {"validation_status": "invalid_status"})
        assert response.status_code == 400

    def test_anon_without_header_returns_400(self, client, dataset_usage_data):
        """Anonymous POST without X-Anonymous-ID header returns 400, not 401."""
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = client.post(
            url,
            data={"validation_status": "approved"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_anon_with_valid_header_returns_200(self, client, dataset_usage_data):
        """Anonymous POST with a valid X-Anonymous-ID header is accepted."""
        import uuid
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = client.post(
            url,
            data={"validation_status": "approved"},
            content_type="application/json",
            HTTP_X_ANONYMOUS_ID=str(uuid.uuid4()),
        )
        assert response.status_code == 200
        assert response.data["validation_status"] == "approved"

    def test_anon_with_invalid_uuid_returns_400(self, client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        response = client.post(
            url,
            data={"validation_status": "approved"},
            content_type="application/json",
            HTTP_X_ANONYMOUS_ID="not-a-uuid",
        )
        assert response.status_code == 400

    def test_404_for_nonexistent_usage(self, api_client):
        import uuid
        url = reverse("dataset-usage-validate", kwargs={"usage_id": uuid.uuid4()})
        response = api_client.post(url, {"validation_status": "approved"})
        assert response.status_code == 404

    def test_creates_dataset_usage_validation_record(self, api_client, dataset_usage_data):
        """Each POST creates a DatasetUsageValidation record."""
        from vso_query_builder.models import DatasetUsageValidation
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        api_client.post(url, {"validation_status": "approved"})
        assert DatasetUsageValidation.objects.filter(dataset_usage=du).count() == 1

    def test_second_post_upserts_existing_record(self, api_client, dataset_usage_data):
        """A second POST from the same authenticated user updates the existing record."""
        from vso_query_builder.models import DatasetUsageValidation
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        api_client.post(url, {"validation_status": "approved"})
        api_client.post(url, {"validation_status": "rejected"})
        assert DatasetUsageValidation.objects.filter(dataset_usage=du).count() == 1
        record = DatasetUsageValidation.objects.get(dataset_usage=du)
        assert record.validation_status == "rejected"

    def test_consensus_single_vote(self, api_client, dataset_usage_data):
        """A single approved vote makes consensus 'approved'."""
        from vso_query_builder.models import DatasetUsage
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        api_client.post(url, {"validation_status": "approved"})
        du.refresh_from_db()
        assert du.validation_status == "approved"

    def test_consensus_majority_wins(self, api_client, dataset_usage_data, db):
        """Two approved vs one rejected → consensus is 'approved'."""
        import uuid
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        from vso_query_builder.models import DatasetUsage

        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})

        # First voter: approved
        api_client.post(url, {"validation_status": "approved"})

        # Second voter: approved
        user2 = User.objects.create_user(username="voter2", password="pass")
        client2 = APIClient()
        client2.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user2).access_token}")
        client2.post(url, {"validation_status": "approved"})

        # Third voter: rejected
        user3 = User.objects.create_user(username="voter3", password="pass")
        client3 = APIClient()
        client3.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user3).access_token}")
        client3.post(url, {"validation_status": "rejected"})

        du.refresh_from_db()
        assert du.validation_status == "approved"

    def test_consensus_tie_becomes_needs_review(self, api_client, dataset_usage_data, db):
        """One approved vs one rejected → tie → 'needs_review'."""
        import uuid
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        from vso_query_builder.models import DatasetUsage

        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})

        api_client.post(url, {"validation_status": "approved"})

        user2 = User.objects.create_user(username="voter2b", password="pass")
        client2 = APIClient()
        client2.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user2).access_token}")
        client2.post(url, {"validation_status": "rejected"})

        du.refresh_from_db()
        assert du.validation_status == "needs_review"

    def test_anon_vote_deduped_by_uuid(self, client, dataset_usage_data):
        """Two POSTs from the same anonymous UUID only create one record."""
        import uuid
        from vso_query_builder.models import DatasetUsageValidation

        anon_id = str(uuid.uuid4())
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})

        client.post(
            url,
            data={"validation_status": "approved"},
            content_type="application/json",
            HTTP_X_ANONYMOUS_ID=anon_id,
        )
        client.post(
            url,
            data={"validation_status": "rejected"},
            content_type="application/json",
            HTTP_X_ANONYMOUS_ID=anon_id,
        )

        records = DatasetUsageValidation.objects.filter(dataset_usage=du, user__isnull=True)
        assert records.count() == 1
        assert records.first().validation_status == "rejected"


@pytest.mark.django_db
class TestDatasetUsageValidationsListView:

    def test_returns_empty_list_initially(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validations-list", kwargs={"usage_id": du.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["total"] == 0
        assert response.data["validations"] == []

    def test_returns_validation_after_vote(self, api_client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        validate_url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})
        api_client.post(validate_url, {"validation_status": "approved"})

        list_url = reverse("dataset-usage-validations-list", kwargs={"usage_id": du.id})
        response = api_client.get(list_url)
        assert response.status_code == 200
        assert response.data["total"] == 1
        assert response.data["approved"] == 1
        assert response.data["rejected"] == 0
        assert response.data["needs_review"] == 0

    def test_requires_auth(self, client, dataset_usage_data):
        du = dataset_usage_data["dataset_usage"]
        url = reverse("dataset-usage-validations-list", kwargs={"usage_id": du.id})
        response = client.get(url)
        assert response.status_code == 401

    def test_404_for_nonexistent(self, api_client):
        import uuid
        url = reverse("dataset-usage-validations-list", kwargs={"usage_id": uuid.uuid4()})
        response = api_client.get(url)
        assert response.status_code == 404

    def test_summary_counts_multiple_voters(self, api_client, dataset_usage_data, db):
        import uuid
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        du = dataset_usage_data["dataset_usage"]
        validate_url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})

        api_client.post(validate_url, {"validation_status": "approved"})

        user2 = User.objects.create_user(username="lv_voter2", password="pass")
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user2).access_token}")
        c2.post(validate_url, {"validation_status": "rejected"})

        list_url = reverse("dataset-usage-validations-list", kwargs={"usage_id": du.id})
        response = api_client.get(list_url)
        assert response.data["total"] == 2
        assert response.data["approved"] == 1
        assert response.data["rejected"] == 1


@pytest.mark.django_db
class TestValidationKappaView:

    def test_returns_200_with_no_data(self, api_client):
        url = reverse("validation-kappa")
        response = api_client.get(url)
        assert response.status_code == 200
        assert "fleiss" in response.data
        assert "pairwise" in response.data

    def test_requires_auth(self, client):
        url = reverse("validation-kappa")
        response = client.get(url)
        assert response.status_code == 401

    def test_returns_kappa_with_multi_voter_data(self, api_client, dataset_usage_data, db):
        """With two raters voting on one item, endpoint returns kappa data."""
        import uuid
        from django.contrib.auth.models import User
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        du = dataset_usage_data["dataset_usage"]
        validate_url = reverse("dataset-usage-validate", kwargs={"usage_id": du.id})

        api_client.post(validate_url, {"validation_status": "approved"})

        user2 = User.objects.create_user(username="kappa_voter2", password="pass")
        c2 = APIClient()
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user2).access_token}")
        c2.post(validate_url, {"validation_status": "approved"})

        url = reverse("validation-kappa")
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["n_total_validations"] == 2

    def test_paper_filter(self, api_client, dataset_usage_data):
        paper = dataset_usage_data["paper"]
        url = reverse("validation-kappa")
        response = api_client.get(url, {"paper": str(paper.id)})
        assert response.status_code == 200


@pytest.mark.django_db
class TestValidationQueueView:

    def test_returns_pending_by_default(self, api_client, dataset_usage_data):
        url = reverse("validation-queue")
        response = api_client.get(url)
        assert response.status_code == 200

    def test_filters_by_status(self, api_client, dataset_usage_data):
        url = reverse("validation-queue")
        response = api_client.get(url, {"validation_status": "all"})
        assert response.status_code == 200


@pytest.mark.django_db
class TestValidationStatsView:

    def test_returns_stats(self, api_client, dataset_usage_data):
        url = reverse("validation-stats")
        response = api_client.get(url)
        assert response.status_code == 200
        assert "total_stats" in response.data
        assert "user_stats" in response.data
