"""GET /builder/version/ — public, unauthenticated version report."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_version_endpoint_is_public_and_reports_package_version(client, monkeypatch):
    import paper_data_linking

    monkeypatch.setenv("GIT_SHA", "abc1234")
    response = client.get(reverse("version"))
    assert response.status_code == 200
    assert response.data["version"] == paper_data_linking.__version__
    assert response.data["git_sha"] == "abc1234"


@pytest.mark.django_db
def test_version_endpoint_git_sha_is_null_when_unset(client, monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    response = client.get(reverse("version"))
    assert response.status_code == 200
    assert response.data["git_sha"] is None
