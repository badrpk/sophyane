from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sophyane import web_grounding


def test_extract_public_url_accepts_bare_domain() -> None:
    assert (
        web_grounding.extract_public_url("latest news on www.dawn.com")
        == "https://www.dawn.com"
    )


def test_recent_fetch_phrase_uses_latest_scrape(tmp_path: Path) -> None:
    older = tmp_path / "100_a.json"
    newer = tmp_path / "200_b.json"
    older.write_text(
        json.dumps(
            {
                "ok": True,
                "url": "https://old.example",
                "title": "Old",
                "text": "old page text",
            }
        ),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            {
                "ok": True,
                "url": "https://www.dawn.com",
                "title": "Home - DAWN.COM",
                "text": "Headline A\nHeadline B",
            }
        ),
        encoding="utf-8",
    )

    data = web_grounding.latest_scrape(scrape_dir=tmp_path)
    assert data is not None
    assert data["url"] == "https://www.dawn.com"


def test_explicit_url_fetch_builds_bounded_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        web_grounding,
        "fetch_url",
        lambda url: SimpleNamespace(
            ok=True,
            text="Headline A\nHeadline B",
            to_dict=lambda: {
                "ok": True,
                "url": url,
                "title": "Home - DAWN.COM",
                "text": "Headline A\nHeadline B",
            },
        ),
    )

    context = web_grounding.build_web_grounding(
        "what is latest news item on www.dawn.com",
        max_chars=500,
    )

    assert "LIVE WEB PAGE EVIDENCE" in context
    assert "https://www.dawn.com" in context
    assert "Headline A" in context
    assert len(context) <= 500


def test_generic_search_is_secondary_fallback(monkeypatch) -> None:
    monkeypatch.setattr(web_grounding, "needs_web_research", lambda message: True)
    monkeypatch.setattr(
        web_grounding,
        "web_search",
        lambda query, limit=5: {
            "ok": True,
            "results": [
                {
                    "title": "Current item",
                    "snippet": "Current facts",
                    "url": "https://example.com/news",
                }
            ],
        },
    )

    context = web_grounding.build_web_grounding("latest Pakistan news")
    assert "LIVE INTERNET RESEARCH" in context
    assert "Current facts" in context
