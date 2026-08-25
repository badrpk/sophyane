from __future__ import annotations

from pathlib import Path

from sophyane.browser.launcher import find_chromium, serve_browser_home
from sophyane.self_improve.ledger import (
    chain_tip,
    export_daily_epoch,
    propose_improvement,
    verify_chain,
)
from sophyane.web_intel import fetch_url, scrape_for_improvement
# SOPHYANE_TEST_LIVE_LEDGER_ISOLATION_V1
def _isolate_improvement_ledger(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sophyane.self_improve.ledger as ledger

    state_dir = (
        tmp_path
        / "sophyane-state"
    )

    repo_improvements = (
        tmp_path
        / "repo"
        / "improvements"
    )

    monkeypatch.setattr(
        ledger,
        "STATE_DIR",
        state_dir,
    )

    monkeypatch.setattr(
        ledger,
        "LEDGER_PATH",
        state_dir
        / "improvement_chain.jsonl",
    )

    monkeypatch.setattr(
        ledger,
        "EPOCH_DIR",
        state_dir
        / "improvement_epochs",
    )

    monkeypatch.setattr(
        ledger,
        "REPO_IMPROVEMENTS",
        repo_improvements,
    )




def test_browser_home_exists() -> None:
    home = Path(__file__).resolve().parents[1] / "src" / "sophyane" / "browser" / "home" / "index.html"
    assert home.exists()
    # find_chromium may be None in CI — that's ok
    _ = find_chromium()
    server, port, url = serve_browser_home()
    assert port > 0
    assert url.startswith("http://127.0.0.1:")
    server.shutdown()


def test_fetch_example_com() -> None:
    result = fetch_url("https://example.com", timeout=20)
    assert result.ok is True
    assert "Example" in (result.title or result.text)
    assert result.content_hash


def test_improvement_chain(monkeypatch, tmp_path: Path) -> None:
    _isolate_improvement_ledger(
        monkeypatch,
        tmp_path,
    )

    before = chain_tip()["length"]
    out = propose_improvement("fact", "test-proposal", "body for chain", score=0.2)
    assert out["ok"] is True
    verify = verify_chain()
    assert verify["ok"] is True
    assert chain_tip()["length"] == before + 1
    epoch = export_daily_epoch()
    assert "merkle_root" in epoch
    assert epoch["count"] >= 0


def test_scrape_for_improvement_bundle() -> None:
    bundle = scrape_for_improvement(["https://example.com"])
    assert bundle["fetched"] == 1
