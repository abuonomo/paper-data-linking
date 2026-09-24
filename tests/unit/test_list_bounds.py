"""Whole-table list endpoints are paginated and never inline paper full text."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["list_papers", "my_papers"])
def test_paper_lists_are_paginated_without_full_text(api_client, paper_factory, route):
    for i in range(30):
        paper_factory(bibcode=f"2020TEST..{i:03d}..1X", user=api_client._test_user)
    r = api_client.get(reverse(route))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"count", "next", "previous", "results"}
    assert len(body["results"]) == 25
    assert all("full_text" not in row for row in body["results"])


@pytest.mark.django_db
def test_page_size_is_capped(api_client, paper_factory):
    for i in range(3):
        paper_factory(bibcode=f"2020TEST..{i:03d}..2X")
    r = api_client.get(reverse("list_papers"), {"page_size": 100000})
    assert r.status_code == 200
    from vso_query_builder.views import BoundedPageNumberPagination
    assert BoundedPageNumberPagination.max_page_size == 200
    assert len(r.json()["results"]) == 3


@pytest.mark.django_db
def test_paper_analyses_paginated(api_client, paper_analysis_factory):
    for _ in range(3):
        paper_analysis_factory()
    r = api_client.get(reverse("paper-analyses"), {"page_size": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3 and len(body["results"]) == 2 and body["next"]


@pytest.mark.django_db
def test_paper_detail_still_has_full_text(api_client, paper_factory):
    p = paper_factory()
    r = api_client.get(reverse("paper_detail", kwargs={"pk": p.id}))
    assert "full_text" in r.json()
