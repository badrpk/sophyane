from pathlib import Path


def test_open_browser_uses_second_nifdu_target_for_verified_project(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import execution_runtime as runtime
    from sophyane.browser import launcher

    index = tmp_path / "index.html"
    index.write_text(
        "<!doctype html><html><body>"
        "<canvas id='game'></canvas>"
        "<script>console.log('snake')</script>"
        "</body></html>"
        + (" " * 200),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setattr(
        runtime,
        "_workspace_server",
        lambda workspace: "http://127.0.0.1:8765",
    )

    verified_urls = []

    def fake_verify(candidate, url):
        verified_urls.append((candidate, url))
        return True, "sha256=test-digest"

    monkeypatch.setattr(
        runtime,
        "_verify_served_file",
        fake_verify,
    )

    opened_targets = []

    monkeypatch.setattr(
        launcher,
        "open_nifdu_target",
        lambda url: (
            opened_targets.append(url)
            or {
                "ok": True,
                "target": {
                    "id": "game-preview",
                    "type": "page",
                    "url": url,
                },
            }
        ),
    )

    presented_targets = []

    monkeypatch.setattr(
        launcher,
        "present_nifdu_browser",
        lambda target_id: (
            presented_targets.append(target_id)
            or {
                "ok": True,
                "target_id": target_id,
                "presented": True,
            }
        ),
    )

    # The NIFDU path must not fall through to any generic opener.
    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: (_ for _ in ()).throw(
            AssertionError(
                f"generic opener queried: {name}"
            )
        ),
    )

    monkeypatch.setattr(
        runtime.webbrowser,
        "open",
        lambda url: (_ for _ in ()).throw(
            AssertionError(
                f"default browser opened: {url}"
            )
        ),
    )

    progress_messages = []

    result = runtime._open_browser(
        tmp_path,
        "",
        progress_messages.append,
    )

    assert len(verified_urls) == 1
    assert verified_urls[0][0] == index

    verified_url = verified_urls[0][1]

    assert verified_url.startswith(
        "http://127.0.0.1:8765/index.html?v="
    )

    assert opened_targets == [verified_url]

    assert "game-preview" in result
    assert presented_targets == ["game-preview"]
    assert verified_url in result

    assert any(
        "Verified browser artifact over HTTP"
        in message
        for message in progress_messages
    )


def test_open_browser_non_nifdu_keeps_existing_generic_path(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import execution_runtime as runtime

    index = tmp_path / "index.html"
    index.write_text(
        "<!doctype html><html><body>"
        + ("x" * 200)
        + "</body></html>",
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "cloud_llm",
    )

    monkeypatch.setattr(
        runtime,
        "_workspace_server",
        lambda workspace: "http://127.0.0.1:8765",
    )

    monkeypatch.setattr(
        runtime,
        "_verify_served_file",
        lambda candidate, url: (
            True,
            "sha256=test-digest",
        ),
    )

    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: (
            "/data/data/com.termux/files/usr/bin/termux-open-url"
            if name == "termux-open-url"
            else None
        ),
    )

    commands = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kwargs: (
            commands.append(command)
            or Result()
        ),
    )

    result = runtime._open_browser(
        tmp_path,
        "",
        lambda message: None,
    )

    assert len(commands) == 1
    assert commands[0][0].endswith(
        "termux-open-url"
    )
    assert "Browser command: termux-open-url" in result
