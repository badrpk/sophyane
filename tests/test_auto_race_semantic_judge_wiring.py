from __future__ import annotations

from types import SimpleNamespace

import sophyane.race_execution as race_execution
import sophyane.v13_cli as v13_cli


REQUEST = (
    "Parse incoming raw payload examples, derive strict JSON schemas "
    "or OpenAPI specifications, and generate functional backend "
    "mocking stubs or test client scripts."
)


def test_auto_execution_wires_configured_semantic_judge(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}

    sentinel_judge = object()

    def fake_run_race_apply_verify(
        request,
        *,
        workspace,
        config,
        progress=None,
        max_rounds=None,
        race_timeout=180.0,
        semantic_judge=None,
        **kwargs,
    ):
        captured["request"] = request
        captured["workspace"] = workspace
        captured["config"] = config
        captured["max_rounds"] = max_rounds
        captured["race_timeout"] = race_timeout
        captured["semantic_judge"] = semantic_judge

        return SimpleNamespace(
            ok=True,
            winner="cloud",
            attempts=1,
            applied=[],
            verifications=[],
            error="",
        )

    monkeypatch.setattr(
        race_execution,
        "run_race_apply_verify",
        fake_run_race_apply_verify,
    )

    monkeypatch.setattr(
        race_execution,
        "_semantic_completion_judgement",
        sentinel_judge,
    )

    monkeypatch.setattr(
        v13_cli,
        "_auto_request_requires_execution",
        lambda request: True,
    )

    result = v13_cli._run_adaptive_race_request(
        REQUEST,
        workspace=tmp_path,
        config={
            "provider": "existing-config",
        },
        progress=None,
        timeout=123.0,
    )

    assert result["ok"] is True
    assert result["mode"] == "execution"

    assert captured["request"] == REQUEST
    assert captured["workspace"] == tmp_path
    assert captured["config"] == {
        "provider": "existing-config",
    }

    assert captured["max_rounds"] == 3
    assert captured["race_timeout"] == 123.0

    # Critical production contract:
    assert (
        captured["semantic_judge"]
        is sentinel_judge
    )


def test_direct_race_api_still_defaults_to_no_semantic_judge():
    import inspect

    parameter = inspect.signature(
        race_execution.run_race_apply_verify
    ).parameters[
        "semantic_judge"
    ]

    assert parameter.default is None
