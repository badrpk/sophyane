import copy

import sophyane.startup_policy as policy


BASE_CONFIG = {
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "company": "Google",
}

BASE_LLM = {
    "active_provider": "gemini",
    "fallback_order": ["gemini"],
    "providers": {},
}


def _prepare(
    monkeypatch,
    mode,
):
    config = copy.deepcopy(BASE_CONFIG)
    llm = copy.deepcopy(BASE_LLM)

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        mode,
    )

    # Register every startup-policy environment flag with
    # MonkeyPatch before production code can mutate it.  Some startup
    # branches write these keys directly through os.environ; recording
    # their initial absence here ensures pytest removes those writes at
    # teardown instead of leaking session state into later tests.
    for key in (
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    ):
        monkeypatch.setenv(
            key,
            "__sophyane_test_unset__",
        )
        monkeypatch.delenv(
            key,
            raising=False,
        )

    monkeypatch.setattr(
        policy.sys.stdin,
        "isatty",
        lambda: False,
    )

    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: copy.deepcopy(config),
    )

    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: llm,
    )

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: (
            "local_gguf",
            "qwen-test",
        ),
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [
            (
                "gemini",
                "Google Gemini",
            )
        ],
    )

    monkeypatch.setattr(
        policy,
        "_cloud_model",
        lambda provider_id, config, llm:
            "gemini-test",
    )

    return llm


def test_noninteractive_sli_graph(
    monkeypatch,
):
    _prepare(
        monkeypatch,
        "sli_graph",
    )

    result = (
        policy.choose_startup_provider()
    )

    assert result["company"] == "SLI"

    assert (
        policy.os.environ[
            "SOPHYANE_SESSION_MODE"
        ]
        == "sli_graph"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_SLI_GRAPH"
        ]
        == "1"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_SLI_ONLY"
        ]
        == "1"
    )


def test_noninteractive_local_llm(
    monkeypatch,
):
    llm = _prepare(
        monkeypatch,
        "local_llm",
    )

    result = (
        policy.choose_startup_provider()
    )

    assert (
        result["provider"]
        == "local_gguf"
    )

    assert (
        result["model"]
        == "qwen-test"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_LOCAL_ONLY"
        ]
        == "1"
    )

    assert (
        policy.os.environ[
            "SOPHYANE_DISABLE_CLOUD_FALLBACK"
        ]
        == "1"
    )

    assert (
        llm["fallback_order"]
        == ["local_gguf"]
    )

    assert (
        llm[
            "allow_quality_escalation"
        ]
        is False
    )


def test_noninteractive_cloud_llm(
    monkeypatch,
):
    llm = _prepare(
        monkeypatch,
        "cloud_llm",
    )

    result = (
        policy.choose_startup_provider()
    )

    assert (
        result["provider"]
        == "gemini"
    )

    assert (
        result["model"]
        == "gemini-test"
    )

    assert (
        llm["active_provider"]
        == "gemini"
    )


def test_noninteractive_unspecified_preserves_config(
    monkeypatch,
):
    # Own all flags production may write in the noninteractive default branch.
    for key in (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SLI_GRAPH",
        "SOPHYANE_SLI_ONLY",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    ):
        monkeypatch.setenv(key, "__sophyane_test_unset__")
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(
        policy.sys.stdin,
        "isatty",
        lambda: False,
    )

    monkeypatch.setattr(
        policy,
        "load_config",
        lambda: copy.deepcopy(
            BASE_CONFIG
        ),
    )

    monkeypatch.setattr(
        policy,
        "_load_llm",
        lambda: copy.deepcopy(
            BASE_LLM
        ),
    )

    monkeypatch.setattr(
        policy,
        "_local_candidate",
        lambda config, llm: None,
    )

    monkeypatch.setattr(
        policy,
        "_configured_clouds",
        lambda: [],
    )

    result = (
        policy.choose_startup_provider()
    )

    assert (
        result["provider"]
        == "gemini"
    )
