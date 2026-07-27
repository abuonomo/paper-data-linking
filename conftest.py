"""Root conftest.py for pytest-django integration.

Provides signal disconnection (prevents OpenAI API calls during tests),
DB connection keep-alive (prevents @close_db_connection from breaking tests),
and model factory fixtures for batch task testing.
"""
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _disconnect_embedding_signals():
    """Disconnect post_save signals that call OpenAI for embeddings.

    SupportQuote and Instrument post_save signals generate embeddings
    via the OpenAI API. We disconnect them for all tests to avoid
    external calls and reconnect after each test.
    """
    from django.db.models.signals import post_save
    from vso_query_builder.signals import create_embedding, update_instrument_embedding
    from vso_query_builder.models import SupportQuote, Instrument

    post_save.disconnect(create_embedding, sender=SupportQuote)
    post_save.disconnect(update_instrument_embedding, sender=Instrument)
    yield
    post_save.connect(create_embedding, sender=SupportQuote)
    post_save.connect(update_instrument_embedding, sender=Instrument)


@pytest.fixture(autouse=True)
def _keep_db_connection_open():
    """Prevent @close_db_connection decorator from closing the test DB connection.

    Celery tasks use @close_db_connection which calls connection.close() after
    execution. In tests, tasks run eagerly in the same thread, so closing the
    connection breaks the test transaction. We patch it to a no-op.
    """
    with patch("django.db.connection.close"):
        yield


# ---------------------------------------------------------------------------
# Model factory fixtures (require @pytest.mark.django_db on the test)
# ---------------------------------------------------------------------------

@pytest.fixture
def paper_factory(db):
    """Factory that creates Paper instances with sensible defaults."""
    from vso_query_builder.models import Paper

    _counter = [0]

    def _create(bibcode=None, full_text="Solar wind observations from AIA...", **kwargs):
        _counter[0] += 1
        if bibcode is None:
            bibcode = f"2024ApJ...test{_counter[0]:03d}"
        return Paper.objects.create(bibcode=bibcode, full_text=full_text, **kwargs)

    return _create


@pytest.fixture
def batch_job_factory(db):
    """Factory that creates BatchJob instances with sensible defaults."""
    from vso_query_builder.models import BatchJob

    def _create(**kwargs):
        defaults = {
            "batch_id": "batch_test_123",
            "input_file_id": "file-input-test",
            "status": "submitted",
            "provider": "openai",
            "configuration_name": "standard",
            "paper_mapping": {},
            "total_requests": 0,
        }
        defaults.update(kwargs)
        return BatchJob.objects.create(**defaults)

    return _create


@pytest.fixture
def vso_datasource(db):
    """Create a VSO DataSource."""
    from vso_query_builder.models import DataSource
    return DataSource.objects.create(slug="vso", name="Virtual Solar Observatory")


@pytest.fixture
def observatory_factory(db, vso_datasource):
    """Factory that creates Observatory instances."""
    from vso_query_builder.models import Observatory

    def _create(short_name, name=None, datasource=None):
        return Observatory.objects.create(
            datasource=datasource or vso_datasource,
            short_name=short_name,
            name=name or short_name,
        )

    return _create


@pytest.fixture
def instrument_factory(db):
    """Factory that creates Instrument instances."""
    from vso_query_builder.models import Instrument

    def _create(observatory, short_name, full_name=None, **kwargs):
        return Instrument.objects.create(
            observatory=observatory,
            short_name=short_name,
            full_name=full_name or short_name,
            **kwargs,
        )

    return _create


@pytest.fixture
def paper_analysis_factory(db, paper_factory):
    """Factory that creates PaperAnalysis instances."""
    from vso_query_builder.models import PaperAnalysis

    def _create(paper=None, configuration_name="standard", **kwargs):
        if paper is None:
            paper = paper_factory()
        defaults = {
            "status": "completed",
            "configuration_name": configuration_name,
            "instruments_details": "# Instruments\n## LASCO\n...",
            "context": [],
            "token_usage": {},
        }
        defaults.update(kwargs)
        return PaperAnalysis.objects.create(paper=paper, **defaults)

    return _create


@pytest.fixture
def api_client(db):
    """Authenticated DRF APIClient with JWT token."""
    from rest_framework.test import APIClient
    from django.contrib.auth.models import User
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    user = User.objects.create_user(username="testuser", password="testpass")
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    client._test_user = user
    return client
