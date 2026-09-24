"""GET /builder/public/papers/<bibcode>/similar/ — nearest papers by quote embeddings."""
from datetime import datetime

import numpy as np
import pytz
import pytest
from django.core.cache import cache
from django.urls import reverse
from psycopg2.extras import DateTimeTZRange

DIM = 1536
WINDOW = DateTimeTZRange(datetime(2003, 1, 1, tzinfo=pytz.UTC), datetime(2003, 1, 2, tzinfo=pytz.UTC), bounds="[]")


def _vec(*head):
    """A unit-ish vector whose first components are `head` (rest zero)."""
    v = np.zeros(DIM)
    v[: len(head)] = head
    return v.tolist()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def corpus(paper_factory, paper_analysis_factory, observatory_factory, instrument_factory):
    from vso_query_builder.models import DatasetUsage, SupportQuote

    soho = observatory_factory("SOHO")
    lasco = instrument_factory(soho, "LASCO")
    ace = instrument_factory(observatory_factory("ACE"), "SWEPAM")

    def make(bibcode, embeddings, status="approved", instrument=lasco, title=None):
        paper = paper_factory(bibcode=bibcode, title=title or f"Title {bibcode}",
                              authors=["A", "B", "C", "D"], year=2020,
                              full_text="x" * 50_000)
        pa = paper_analysis_factory(paper=paper)
        for i, emb in enumerate(embeddings):
            SupportQuote.objects.create(paper_analysis=pa, quote=f"q{i}", instrument="LASCO",
                                        parameter="p", page_number=1, y_coord=1.0, embedding=emb)
        if status:
            DatasetUsage.objects.create(paper=paper, instrument=instrument, paper_analysis=pa,
                                        validation_status=status, observation_window=WINDOW)
        return paper

    query = make("Q", [_vec(1, 0), _vec(1, 0.2)])
    make("NEAR", [_vec(1, 0.15), _vec(0, 1)])              # best quote very close
    make("MID", [_vec(1, 1)], instrument=ace)               # 45 degrees
    make("FAR", [_vec(0, 1)])                               # orthogonal
    make("PENDING", [_vec(1, 0.1)], status="pending")       # = query average, but unvalidated
    make("NOUSAGE", [_vec(1, 0.1)], status=None)            # = query average, no usage at all
    make("NOEMB", [])                                       # approved, no quotes
    return query


def _get(client, bibcode, **params):
    return client.get(reverse("public-similar-papers", kwargs={"bibcode": bibcode}), params)


@pytest.mark.django_db
def test_ranks_approved_papers_by_best_quote(client, corpus):
    r = _get(client, "Q")
    assert r.status_code == 200
    rows = r.json()
    assert [row["bibcode"] for row in rows] == ["NEAR", "MID", "FAR"]
    assert rows[0]["score"] > rows[1]["score"] > rows[2]["score"]
    assert rows[0]["title"] == "Title NEAR"
    assert rows[0]["authors"] == ["A", "B", "C"]
    assert str(rows[0]["year"]) == "2020"
    assert rows[0]["missions"] == ["SOHO"]
    assert rows[1]["missions"] == ["ACE"]
    assert "full_text" not in rows[0]


@pytest.mark.django_db
def test_include_unvalidated_adds_pending(client, corpus):
    rows = _get(client, "Q", include_unvalidated="true").json()
    assert rows[0]["bibcode"] == "PENDING"
    assert "NOUSAGE" not in [r["bibcode"] for r in rows]


@pytest.mark.django_db
def test_excludes_self_and_caps_at_ten(client, corpus, paper_factory, paper_analysis_factory):
    from vso_query_builder.models import DatasetUsage, Instrument, SupportQuote
    inst = Instrument.objects.get(short_name="LASCO")
    for i in range(15):
        p = paper_factory(bibcode=f"EXTRA{i:02d}")
        pa = paper_analysis_factory(paper=p)
        for j in range(3):  # several quotes per paper: must still count once
            SupportQuote.objects.create(paper_analysis=pa, quote="q", instrument="LASCO", parameter="p",
                                        page_number=1, y_coord=1.0, embedding=_vec(1, 0.05 * (i + j)))
        DatasetUsage.objects.create(paper=p, instrument=inst, paper_analysis=pa, validation_status="approved", observation_window=WINDOW)
    bibs = [r["bibcode"] for r in _get(client, "Q").json()]
    assert len(bibs) == 10 == len(set(bibs))
    assert "Q" not in bibs


@pytest.mark.django_db
def test_paper_without_embeddings_returns_empty(client, corpus):
    assert _get(client, "NOEMB").json() == []


@pytest.mark.django_db
def test_unknown_bibcode_404(client, corpus):
    assert _get(client, "NOPE").status_code == 404


@pytest.mark.django_db
def test_cached(client, corpus, django_assert_num_queries):
    first = _get(client, "Q").json()
    with django_assert_num_queries(0):
        assert _get(client, "Q").json() == first
