from pathlib import Path

from sophyane.browser_partial_recovery import _extraction_diagnostic, _save_raw


class AdaptiveStub:
    @staticmethod
    def _extract_html(text: str):
        return text if "<html" in text.lower() and "</html>" in text.lower() else None


def test_save_raw_response(tmp_path: Path) -> None:
    path = _save_raw(tmp_path, 2, "provider output")
    assert path.name == ".sophyane-provider-response-2.txt"
    assert path.read_text(encoding="utf-8") == "provider output"


def test_empty_response_diagnostic() -> None:
    assert _extraction_diagnostic(AdaptiveStub, "") == "provider response was empty"


def test_structured_response_without_html_diagnostic() -> None:
    text = '{"action":{"content":"not html"}}'
    assert "structured artifact" in _extraction_diagnostic(AdaptiveStub, text)


def test_truncated_html_diagnostic() -> None:
    assert "closing </html>" in _extraction_diagnostic(AdaptiveStub, "<html><body>")


def test_complete_html_diagnostic() -> None:
    text = "prefix <html><body>ok</body></html> suffix"
    assert _extraction_diagnostic(AdaptiveStub, text) == "HTML was extracted but failed later validation"
