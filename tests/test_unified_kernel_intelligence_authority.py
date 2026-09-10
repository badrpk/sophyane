from pathlib import Path


def _request(
    tmp_path: Path,
):
    from sophyane.unified_execution_kernel import (
        ExecutionRequest,
    )

    return ExecutionRequest(
        text="Reply exactly TRACE_OK",
        workspace=str(tmp_path),
    )


def test_direct_local_handler_is_blocked_in_sli_mode(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as race

    from sophyane.unified_execution_kernel import (
        _direct_local_reasoning_handler,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "sli_graph",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "local provider must not be constructed"
        )

    monkeypatch.setattr(
        race,
        "_single_provider",
        forbidden,
    )

    assert (
        _direct_local_reasoning_handler(
            _request(
                tmp_path
            )
        )
        is None
    )


def test_direct_local_handler_is_blocked_in_codex_mode(
    monkeypatch,
    tmp_path,
):
    import sophyane.race_orchestrator as race

    from sophyane.unified_execution_kernel import (
        _direct_local_reasoning_handler,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "codex_cli",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "codex_cli",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "local provider must not be constructed"
        )

    monkeypatch.setattr(
        race,
        "_single_provider",
        forbidden,
    )

    assert (
        _direct_local_reasoning_handler(
            _request(
                tmp_path
            )
        )
        is None
    )
