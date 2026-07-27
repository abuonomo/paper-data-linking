"""Tests for CDAWeb analyzer implementations."""
import pytest
from unittest.mock import MagicMock, patch
from paper_data_linking.analyzers.cdaweb_analyzers import CDAWebQueryExecutionAnalyzer
from paper_data_linking.analyzers.registry import DatasetUsageAnalyzerRegistry


class TestCDAWebQueryExecutionAnalyzerRegistration:

    def test_registered_in_registry(self):
        info = DatasetUsageAnalyzerRegistry.get_analyzer_info("QueryExecution.cdaweb")
        assert info is not None
        assert info.class_ref is CDAWebQueryExecutionAnalyzer

    def test_data_sources(self):
        info = DatasetUsageAnalyzerRegistry.get_analyzer_info("QueryExecution.cdaweb")
        assert "cdaweb" in info.data_sources


class TestCDAWebQueryExecutionAnalyzerSnippet:

    @pytest.fixture
    def analyzer(self):
        return CDAWebQueryExecutionAnalyzer()

    def test_empty_snippet_returns_error(self, analyzer):
        result = analyzer.analyze_snippet(None, "")
        assert result["execution_successful"] is False
        assert "Empty snippet" in result["execution_error"]

    def test_none_snippet_returns_error(self, analyzer):
        result = analyzer.analyze_snippet(None, None)
        assert result["execution_successful"] is False

    def test_whitespace_snippet_returns_error(self, analyzer):
        result = analyzer.analyze_snippet(None, "   ")
        assert result["execution_successful"] is False
        assert "Empty snippet" in result["execution_error"]

    def test_no_datasets_found_snippet(self, analyzer):
        snippet = "# No CDAWeb datasets found for MAG on ACE\n# ..."
        result = analyzer.analyze_snippet(None, snippet)
        assert result["execution_successful"] is False
        assert "No datasets were discovered" in result["execution_error"]

    @patch("paper_data_linking.analyzers.cdaweb_analyzers.CDAWebQueryExecutionAnalyzer._run_security_check")
    def test_security_check_blocks_unsafe_code(self, mock_security, analyzer):
        mock_security.return_value = {
            "is_safe": False,
            "security_issues": ["dangerous import detected"],
        }
        result = analyzer.analyze_snippet(None, "import os; os.system('rm -rf /')")
        assert result["execution_successful"] is False
        assert "Security check failed" in result["execution_error"]

    @patch("paper_data_linking.analyzers.cdaweb_analyzers.CDAWebQueryExecutionAnalyzer._run_syntax_check")
    @patch("paper_data_linking.analyzers.cdaweb_analyzers.CDAWebQueryExecutionAnalyzer._run_security_check")
    def test_syntax_check_blocks_invalid_code(self, mock_security, mock_syntax, analyzer):
        mock_security.return_value = {"is_safe": True}
        mock_syntax.return_value = {
            "is_valid": False,
            "syntax_error": "invalid syntax on line 1",
        }
        result = analyzer.analyze_snippet(None, "def (broken")
        assert result["execution_successful"] is False
        assert "Syntax check failed" in result["execution_error"]

    def test_sunpy_import_unavailable(self, analyzer):
        with patch.dict("sys.modules", {"sunpy": None, "sunpy.net": None}):
            # Force re-import to fail
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args: (_ for _ in ()).throw(ImportError("no sunpy"))
                if "sunpy" in name else __import__(name, *args),
            ):
                result = analyzer.analyze_snippet(None, "x = 1")
                assert result["execution_successful"] is False
                assert "SunPy not available" in result["execution_error"]

    def test_result_structure(self, analyzer):
        result = analyzer.analyze_snippet(None, "")
        assert "execution_successful" in result
        assert "execution_error" in result
        assert "total_datasets_found" in result
        assert "total_records_found" in result
        assert "query_response_summary" in result
        assert "analyzer_name" in result
        assert result["analyzer_name"] == "CDAWebQueryExecutionAnalyzer"


class TestExtractFidoResponseInfo:

    @pytest.fixture
    def analyzer(self):
        return CDAWebQueryExecutionAnalyzer()

    def test_empty_response(self, analyzer):
        mock_response = MagicMock()
        mock_response.__len__ = MagicMock(return_value=0)
        mock_response.__iter__ = MagicMock(return_value=iter([]))
        result = analyzer._extract_fido_response_info(mock_response, "result_1")
        assert result["variable"] == "result_1"
        assert result["record_count"] == 0

    def test_response_with_error(self, analyzer):
        # An object that raises on attribute access
        mock_response = MagicMock()
        mock_response.__len__ = MagicMock(side_effect=Exception("bad response"))
        result = analyzer._extract_fido_response_info(mock_response, "result_1")
        assert "error" in result or result["record_count"] == 0
