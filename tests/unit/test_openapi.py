"""The OpenAPI schema is public and describes only the public endpoints."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_schema_is_public_and_lists_only_public_paths(client):
    response = client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    schema = response.json()
    paths = set(schema["paths"])
    assert "/builder/public/papers/{bibcode}/validated-usages/" in paths
    assert "/builder/public/papers/validated/" in paths
    assert "/builder/public/papers/csv/" in paths
    assert "/builder/version/" in paths
    assert not any(p.startswith("/builder/papers/") for p in paths), "authenticated routes must not be published"
    assert not any(p.startswith("/builder/validation-campaigns/") for p in paths)
    assert "/builder/public/papers/{bibcode}/pdf/" not in paths, "the PDF endpoint requires auth and is not public"
    import paper_data_linking
    assert schema["info"]["version"] == paper_data_linking.__version__


@pytest.mark.django_db
def test_swagger_ui_is_public(client):
    response = client.get(reverse("schema-swagger"))
    assert response.status_code == 200
