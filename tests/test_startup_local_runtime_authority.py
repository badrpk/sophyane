from __future__ import annotations

import json
from pathlib import Path

import sophyane.startup_policy as policy


def test_valid_runtime_model_overrides_stale_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = (
        tmp_path
        / "home"
    )

    runtime_dir = (
        home
        / ".local/state/sophyane"
    )

    runtime_dir.mkdir(
        parents=True,
    )

    model = (
        tmp_path
        / "qwen2.5-7b-instruct-q4_k_m.gguf"
    )

    model.write_bytes(
        b"GGUF"
        + b"x" * 1024
    )

    (
        runtime_dir
        / "gguf_runtime.json"
    ).write_text(
        json.dumps(
            {
                "provider": "local_gguf",
                "model": (
                    "qwen2.5-7b-instruct-q4_k_m"
                ),
                "gguf_path": str(model),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        policy.Path,
        "home",
        classmethod(
            lambda cls: home
        ),
    )

    candidate = policy._local_candidate(
        {
            "provider": "local_gguf",
            "model": (
                "qwen2.5-1.5b-instruct-q4_k_m"
            ),
        },
        {
            "providers": {
                "local_gguf": {
                    "enabled": True,
                    "model": (
                        "qwen2.5-1.5b-instruct-q4_k_m"
                    ),
                }
            }
        },
    )

    assert candidate == (
        "local_gguf",
        "qwen2.5-7b-instruct-q4_k_m",
    )


def test_missing_runtime_falls_back_to_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = (
        tmp_path
        / "home"
    )

    home.mkdir()

    monkeypatch.setattr(
        policy.Path,
        "home",
        classmethod(
            lambda cls: home
        ),
    )

    candidate = policy._local_candidate(
        {
            "provider": "local_gguf",
            "model": "saved-model",
        },
        {},
    )

    assert candidate == (
        "local_gguf",
        "saved-model",
    )


def test_runtime_with_missing_gguf_is_not_authoritative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = (
        tmp_path
        / "home"
    )

    runtime_dir = (
        home
        / ".local/state/sophyane"
    )

    runtime_dir.mkdir(
        parents=True,
    )

    (
        runtime_dir
        / "gguf_runtime.json"
    ).write_text(
        json.dumps(
            {
                "model": "missing-7b",
                "gguf_path": (
                    str(
                        tmp_path
                        / "missing.gguf"
                    )
                ),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        policy.Path,
        "home",
        classmethod(
            lambda cls: home
        ),
    )

    candidate = policy._local_candidate(
        {
            "provider": "local_gguf",
            "model": "fallback-model",
        },
        {},
    )

    assert candidate == (
        "local_gguf",
        "fallback-model",
    )
