"""Unit tests for PublicValidatedPapersCSVView - using mocks, no database access."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from urllib.parse import quote
from django.test import RequestFactory
from vso_query_builder.views import PublicValidatedPapersCSVView


class TestPublicValidatedPapersCSVView:
    """Test suite for CSV export endpoint - all tests use mocking, no database."""

    @pytest.fixture
    def mock_queryset(self):
        """Create a mock queryset that returns test bibcodes."""
        mock_qs = MagicMock()

        # Mock the iterator to return test bibcodes
        test_bibcodes = [
            '2019A&A...624A.106A',
            '2020ApJ...891..160S',
            '2021SoPh..296...36B'
        ]
        mock_qs.iterator.return_value = iter(test_bibcodes)

        return mock_qs

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_basic_response(self, mock_settings, mock_paper_objects, mock_queryset):
        """Test basic CSV export returns correct format."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        # Mock the entire query chain
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_queryset

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)

        # Check response properties
        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'
        assert 'attachment' in response['Content-Disposition']
        assert 'validated_papers.csv' in response['Content-Disposition']

        # Parse CSV content
        content = b''.join(response.streaming_content).decode('utf-8')
        lines = [line.strip() for line in content.strip().split('\n')]

        # Validate header
        assert lines[0] == 'Bibcode,URL'

        # Validate data rows (3 bibcodes from mock)
        assert len(lines) == 4  # header + 3 data rows

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_bibcode_encoding(self, mock_settings, mock_paper_objects):
        """Test that bibcodes are properly URL-encoded."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        # Mock queryset with bibcode containing special characters
        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter(['2019A&A...624A.106A'])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)
        content = b''.join(response.streaming_content).decode('utf-8')

        # Check that ampersand is encoded
        assert '%26' in content, "Ampersand should be URL-encoded"

        # Verify the exact encoded bibcode
        expected_encoded = quote('2019A&A...624A.106A', safe='')
        assert expected_encoded in content

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_url_format(self, mock_settings, mock_paper_objects):
        """Test that URLs are in the correct format."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter(['2019A&A...624A.106A'])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)
        content = b''.join(response.streaming_content).decode('utf-8')
        lines = content.strip().split('\n')

        # Check URL format - should use settings.BASE_URL
        for line in lines[1:]:  # Skip header
            parts = line.split(',')
            if len(parts) == 2:
                url = parts[1].strip()
                assert url.startswith('http://localhost:8000/public/p/'), f"URL should start with http://localhost:8000/public/p/, got: {url}"

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_empty_results(self, mock_settings, mock_paper_objects):
        """Test CSV export with no matching papers."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        # Mock empty queryset
        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter([])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/?q=NONEXISTENT_BIBCODE_12345')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)
        content = b''.join(response.streaming_content).decode('utf-8')
        lines = content.strip().split('\n')

        # Should only have header row when no results match
        assert len(lines) == 1
        assert lines[0] == 'Bibcode,URL'

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_no_auth_required(self, mock_settings, mock_paper_objects):
        """Test that CSV endpoint is accessible without authentication."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter([])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')
        # Don't set any authentication headers

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)

        # Should return 200, not 401 or 403
        assert response.status_code == 200

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_url_uses_base_url_setting(self, mock_settings, mock_paper_objects):
        """Test that URLs use settings.BASE_URL (environment-aware)."""
        # Set production BASE_URL
        mock_settings.BASE_URL = 'https://paper-data.example.com'

        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter(['2019A&A...624A.106A'])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)
        content = b''.join(response.streaming_content).decode('utf-8')

        # URLs should use the BASE_URL from settings (production URL in this test)
        assert 'https://paper-data.example.com/public/p/' in content

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_multiple_rows(self, mock_settings, mock_paper_objects):
        """Test CSV with multiple papers returns correct number of rows."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        # Mock queryset with 5 bibcodes
        test_bibcodes = [f'2020ApJ...{i}..100A' for i in range(100, 105)]
        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter(test_bibcodes)
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)
        content = b''.join(response.streaming_content).decode('utf-8')
        lines = [line.strip() for line in content.strip().split('\n')]

        # Should have header + 5 data rows
        assert len(lines) == 6
        assert lines[0] == 'Bibcode,URL'

    @patch('vso_query_builder.views.Paper.objects')
    @patch('vso_query_builder.views.settings')
    def test_csv_streaming_response(self, mock_settings, mock_paper_objects):
        """Test that response uses streaming for memory efficiency."""
        mock_settings.BASE_URL = 'http://localhost:8000'

        mock_qs = MagicMock()
        mock_qs.iterator.return_value = iter(['2020ApJ...100..1A'])
        mock_paper_objects.filter.return_value.values_list.return_value.distinct.return_value.order_by.return_value = mock_qs

        factory = RequestFactory()
        request = factory.get('/builder/public/papers/csv/')

        view = PublicValidatedPapersCSVView.as_view()
        response = view(request)

        # Verify it's a streaming response
        assert hasattr(response, 'streaming_content')
        assert response.streaming
