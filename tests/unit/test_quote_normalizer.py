"""Tests for QuoteNormalizer."""
import pytest
from unittest.mock import patch, MagicMock


class TestNormalizeQuoteListPdfPathTypes:
    """Verify _normalize_quote_list handles both str paths and bytes PDF content."""

    @pytest.fixture
    def normalizer(self):
        from paper_data_linking.linkers.general.normalizers.quote_normalizer import QuoteNormalizer
        return QuoteNormalizer()

    def test_bytes_pdf_path_does_not_raise(self, normalizer):
        """When pdf_path is bytes (PDF content), it should not raise TypeError."""
        fake_pdf_bytes = b"%PDF-1.4 fake content"
        with patch(
            "paper_data_linking.linkers.general.normalizers.quote_normalizer.PDFTextSearcher"
        ) as mock_searcher_cls:
            mock_searcher = MagicMock()
            mock_searcher.find_quotes_original.return_value = [
                {"quote": "observed on Jan 1", "location": None}
            ]
            mock_searcher_cls.return_value = mock_searcher

            result = normalizer._normalize_quote_list(
                raw_quotes=["observed on Jan 1"],
                category="time",
                instrument_name="LASCO",
                parameter="Period 1:time",
                pdf_path=fake_pdf_bytes,
            )

        assert len(result) == 1
        assert result[0].text == "observed on Jan 1"
        mock_searcher_cls.assert_called_once_with(fake_pdf_bytes)

    def test_none_pdf_path_returns_basic_quotes(self, normalizer):
        """When pdf_path is None, returns quotes without coordinates."""
        result = normalizer._normalize_quote_list(
            raw_quotes=["some quote"],
            category="general",
            instrument_name="LASCO",
            parameter="Period 1:general",
            pdf_path=None,
        )

        assert len(result) == 1
        assert result[0].location is None

    def test_nonexistent_str_path_returns_basic_quotes(self, normalizer):
        """When pdf_path is a string but file doesn't exist, returns quotes without coordinates."""
        result = normalizer._normalize_quote_list(
            raw_quotes=["some quote"],
            category="time",
            instrument_name="LASCO",
            parameter="Period 1:time",
            pdf_path="/nonexistent/path.pdf",
        )

        assert len(result) == 1
        assert result[0].location is None
