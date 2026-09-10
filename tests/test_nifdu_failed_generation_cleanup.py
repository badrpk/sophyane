import inspect

import sophyane.providers.nifdu_cdp_bridge as bridge


class _FakeCDP:
    pass


def test_failed_generation_cleanup_is_noop_before_submission(
    monkeypatch,
):
    calls = []

    def fake_prepare(cdp, **kwargs):
        calls.append((cdp, kwargs))

    monkeypatch.setattr(
        bridge,
        "prepare_for_new_generation",
        fake_prepare,
    )

    cdp = _FakeCDP()

    result = bridge.cleanup_failed_generation(
        cdp,
        generation_submitted=False,
    )

    assert result is None
    assert calls == []


def test_failed_generation_cleanup_runs_after_submission(
    monkeypatch,
):
    calls = []

    def fake_prepare(cdp, **kwargs):
        calls.append((cdp, kwargs))

    monkeypatch.setattr(
        bridge,
        "prepare_for_new_generation",
        fake_prepare,
    )

    cdp = _FakeCDP()

    result = bridge.cleanup_failed_generation(
        cdp,
        generation_submitted=True,
    )

    assert result is None
    assert len(calls) == 1
    assert calls[0][0] is cdp


def test_failed_generation_cleanup_returns_cleanup_error_without_raising(
    monkeypatch,
):
    cleanup_error = RuntimeError(
        "cleanup did not settle"
    )

    def fake_prepare(cdp, **kwargs):
        raise cleanup_error

    monkeypatch.setattr(
        bridge,
        "prepare_for_new_generation",
        fake_prepare,
    )

    result = bridge.cleanup_failed_generation(
        _FakeCDP(),
        generation_submitted=True,
    )

    assert result is cleanup_error


def test_ask_tracks_submission_after_click_and_cleans_failure():
    source = inspect.getsource(
        bridge.ask
    )

    initial = source.index(
        "generation_submitted = False"
    )

    send = source.index(
        "click_send(cdp)"
    )

    submitted = source.index(
        "generation_submitted = True"
    )

    cleanup = source.index(
        "cleanup_failed_generation("
    )

    final_close = source.index(
        "cdp.close()"
    )

    assert initial < submitted
    assert submitted < send
    assert send < cleanup
    assert cleanup < final_close

    assert "except Exception as exc:" in source

    # The original provider exception must be re-raised rather
    # than replaced by a cleanup exception.
    assert "\n        raise\n\n    finally:" in source


def test_success_path_has_no_unconditional_cleanup_before_return():
    source = inspect.getsource(
        bridge.ask
    )

    cleanup = source.index(
        "cleanup_failed_generation("
    )

    first_success_return = source.index(
        "return settle_completed_assistant_text("
    )

    # Failure cleanup belongs in the exception path, after
    # ordinary successful-return logic.
    assert first_success_return < cleanup
