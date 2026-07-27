"""Inner (defense-in-depth) timeouts for the hang-prone analyzer steps."""

import subprocess
import time
import pytest
from unittest.mock import patch

from paper_data_linking.analyzers.implementations import (
    time_limit, AnalyzerTimeout, QuerySecurityAnalyzer)


def test_time_limit_raises_on_overrun():
    with pytest.raises(AnalyzerTimeout):
        with time_limit(1):
            time.sleep(3)


def test_time_limit_noop_when_under():
    with time_limit(5):
        pass  # completes well under the limit; no raise


def test_bandit_timeout_fails_closed():
    """A hung bandit subprocess must be killed and treated as UNSAFE (block exec)."""
    analyzer = QuerySecurityAnalyzer()
    snippet = "query = Fido.search(a.Time('2020-01-01', '2020-01-02'))"
    with patch("paper_data_linking.analyzers.implementations.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="bandit", timeout=30)):
        result = analyzer.analyze_snippet(None, snippet)
    assert result["is_safe"] is False
    assert any("timed out" in str(x).lower() for x in result["security_issues"])


def test_extract_text_skips_ocr_when_disabled():
    """allow_ocr=False: a junk/scanned PDF returns ('', False) and never OCRs."""
    from unittest.mock import MagicMock
    from paper_data_linking.processing import text_extractor as te
    ext = te.PDFTextExtractor()
    with patch.object(ext, '_load_doc', return_value=([], b'data')), \
         patch.object(te, 'is_junk_pdf', return_value=True), \
         patch.object(ext, '_get_text_ocr') as ocr:
        txt, used = ext.extract_text(b'x', allow_ocr=False)
    assert txt == "" and used is False
    ocr.assert_not_called()
