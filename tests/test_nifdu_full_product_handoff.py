from pathlib import Path


def test_nifdu_browser_product_uses_full_cycle_not_one_shot(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import adaptive_execution as adaptive
    from sophyane import execution_runtime as runtime
    from sophyane import nifdu_product_supervisor as supervisor

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    nifdu_workspace = tmp_path / "nifdu-workspaces/product-1"
    nifdu_product = nifdu_workspace / "product/index.html"
    nifdu_product.parent.mkdir(parents=True)

    nifdu_product.write_text(
        "<!doctype html><html><body>"
        "<canvas id='game'></canvas>"
        "<script>console.log('nifdu')</script>"
        "</body></html>"
        + (" " * 300),
        encoding="utf-8",
    )

    cycle_calls = []

    def fake_cycle(requirement):
        cycle_calls.append(requirement)
        return {
            "accepted": True,
            "score": 97,
            "iterations": 3,
            "final_file": nifdu_product,
            "workspace": nifdu_workspace,
            "report_file": nifdu_workspace / "final-report.json",
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "summary": "accepted",
        }

    monkeypatch.setattr(
        supervisor,
        "run_nifdu_product_cycle",
        fake_cycle,
    )

    # NIFDU full-cycle ownership means the legacy Sophyane
    # browser generator/wrapper chain must never be entered.
    monkeypatch.setattr(
        adaptive,
        "_one_shot_browser_artifact",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "legacy one-shot browser generator was called"
            )
        ),
    )

    opened = []

    def fake_execute(action, workspace, progress):
        opened.append(
            (
                action,
                Path(workspace),
                (Path(workspace) / "index.html").read_text(
                    encoding="utf-8"
                ),
            )
        )
        return True, "NIFDU target: final-preview"

    monkeypatch.setattr(
        runtime,
        "execute_action",
        fake_execute,
    )

    ask_calls = []

    def ask(prompt):
        ask_calls.append(prompt)
        raise AssertionError(
            "adaptive loop made an extra provider request"
        )

    result = adaptive.run_adaptive_loop(
        initial_text="Provider already handled the user's first turn.",
        original_request="make snake game",
        ask=ask,
        workspace=tmp_path / "active-project",
        max_steps=16,
        progress=lambda _message: None,
    )

    assert cycle_calls == ["make snake game"]

    # No second Sophyane provider-generation call.
    assert ask_calls == []

    adopted = tmp_path / "active-project/index.html"
    assert adopted.is_file()
    assert adopted.read_text(
        encoding="utf-8"
    ) == nifdu_product.read_text(
        encoding="utf-8"
    )

    assert len(opened) == 1
    action, opened_workspace, opened_html = opened[0]

    assert action == {"type": "open_browser"}
    assert opened_workspace == (
        tmp_path / "active-project"
    ).resolve()
    assert "console.log('nifdu')" in opened_html

    assert "97" in result
    assert "3" in result
    assert "final-preview" in result


def test_nifdu_unaccepted_product_is_not_adopted(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import adaptive_execution as adaptive
    from sophyane import execution_runtime as runtime
    from sophyane import nifdu_product_supervisor as supervisor

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    active = tmp_path / "active-project"
    active.mkdir()

    original = active / "index.html"
    original.write_text(
        "<!doctype html><html><body>"
        "existing-good-project"
        "</body></html>"
        + (" " * 300),
        encoding="utf-8",
    )

    failed_product = (
        tmp_path
        / "nifdu-workspaces/product-failed/product/index.html"
    )
    failed_product.parent.mkdir(parents=True)

    failed_product.write_text(
        "<!doctype html><html><body>"
        "unaccepted"
        "</body></html>"
        + (" " * 300),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        supervisor,
        "run_nifdu_product_cycle",
        lambda requirement: {
            "accepted": False,
            "score": 88,
            "iterations": 10,
            "final_file": failed_product,
            "summary": "quality threshold not reached",
            "returncode": 1,
            "stdout": "",
            "stderr": "",
        },
    )

    monkeypatch.setattr(
        adaptive,
        "_one_shot_browser_artifact",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "legacy one-shot fallback must not run "
                "after a completed NIFDU quality cycle"
            )
        ),
    )

    monkeypatch.setattr(
        runtime,
        "execute_action",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError(
                "unaccepted NIFDU product must not open"
            )
        ),
    )

    result = adaptive.run_adaptive_loop(
        initial_text="Provider first turn complete.",
        original_request="make snake game",
        ask=lambda prompt: (_ for _ in ()).throw(
            AssertionError(
                "no extra provider call expected"
            )
        ),
        workspace=active,
        max_steps=16,
        progress=lambda _message: None,
    )

    assert original.read_text(
        encoding="utf-8"
    ).find("existing-good-project") >= 0

    assert "88" in result
    assert "10" in result
    assert "not accepted" in result.lower()


def test_non_nifdu_browser_request_keeps_existing_pipeline(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import adaptive_execution as adaptive
    from sophyane import nifdu_product_supervisor as supervisor

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )

    monkeypatch.setattr(
        supervisor,
        "run_nifdu_product_cycle",
        lambda requirement: (_ for _ in ()).throw(
            AssertionError(
                "NIFDU product supervisor used outside nifdu_llm"
            )
        ),
    )

    calls = []

    monkeypatch.setattr(
        adaptive,
        "_one_shot_browser_artifact",
        lambda **kwargs: (
            calls.append(kwargs["original_request"])
            or "legacy-browser-result"
        ),
    )

    result = adaptive.run_adaptive_loop(
        initial_text="",
        original_request="make snake game",
        ask=lambda prompt: "unused",
        workspace=tmp_path,
        max_steps=4,
        progress=lambda _message: None,
    )

    assert calls == ["make snake game"]
    assert result == "legacy-browser-result"
