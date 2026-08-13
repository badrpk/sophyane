from __future__ import annotations

import os
from pathlib import Path


def test_five_mode_menu_contract_is_present():
    path = Path("src/sophyane/startup_policy.py")
    text = path.read_text(encoding="utf-8")

    assert "Select [1-5, default 1]:" in text

    assert (
        'if answer in {"", "1"}:' in text
        and 'os.environ["SOPHYANE_SESSION_MODE"] = "race"' in text
    )

    assert (
        'if answer == "2":' in text
        and 'os.environ["SOPHYANE_SESSION_MODE"] = "sli_graph"' in text
    )

    assert (
        'if answer == "3":' in text
        and 'os.environ["SOPHYANE_SESSION_MODE"] = "local_llm"' in text
    )

    assert (
        'if answer == "4":' in text
        and 'os.environ["SOPHYANE_SESSION_MODE"] = "cloud_llm"' in text
    )

    assert (
        'if answer == "5":' in text
        and 'os.environ["SOPHYANE_SLI_CONTINUOUS"] = "1"' in text
        and 'os.environ["SOPHYANE_TOPIC_LEARNING"] = "1"' in text
    )


def test_auto_mode_clears_strict_mode_flags():
    path = Path("src/sophyane/startup_policy.py")
    text = path.read_text(encoding="utf-8")

    required = (
        'os.environ.pop("SOPHYANE_SLI_ONLY", None)',
        'os.environ.pop("SOPHYANE_LOCAL_ONLY", None)',
        'os.environ.pop("SOPHYANE_DISABLE_CLOUD_FALLBACK", None)',
        'os.environ.pop("SOPHYANE_SLI_CONTINUOUS", None)',
        'os.environ.pop("SOPHYANE_TOPIC_LEARNING", None)',
    )

    for item in required:
        assert item in text
