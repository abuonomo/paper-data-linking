"""Tests for public monitoring endpoints using mocks only."""

from unittest.mock import patch

from django.test import RequestFactory

from vso_query_builder.views import AvailableConfigurationsView, MonitoringDashboardView


class TestPublicMonitoringDashboardView:
    """Monitoring dashboard should be reachable without authentication."""

    @patch("vso_query_builder.views.cache")
    def test_dashboard_returns_cached_payload_without_auth(self, mock_cache):
        cached_payload = {
            "counts": {
                "total_papers": 10,
                "total_observatories": 2,
                "total_instruments": 3,
                "total_dataset_usages": 12,
                "validated_papers": 4,
                "needs_review_total": 1,
            },
            "overall_precision": {
                "approved": 3,
                "rejected": 1,
                "needs_review": 1,
                "total_validated": 4,
                "precision": 0.75,
                "ci_low": 0.3,
                "ci_high": 0.95,
            },
            "per_instrument": [],
        }
        mock_cache.get.return_value = cached_payload

        request = RequestFactory().get("/builder/monitoring/dashboard/")
        response = MonitoringDashboardView.as_view()(request)

        assert response.status_code == 200
        assert response.data == cached_payload


class TestPublicAvailableConfigurationsView:
    """Configuration list should be reachable without authentication."""

    @patch("paper_data_linking.config.settings.list_available_configurations")
    def test_configurations_returns_list_without_auth(self, mock_list_available_configurations):
        mock_list_available_configurations.return_value = ["standard", "budget"]

        request = RequestFactory().get("/builder/configurations/")
        response = AvailableConfigurationsView.as_view()(request)

        assert response.status_code == 200
        assert response.data == ["standard", "budget"]
