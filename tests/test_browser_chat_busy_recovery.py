from pathlib import Path


APP = Path("src/sophyane/browser/home/app.js")


def _composer_submit_body() -> str:
    text = APP.read_text(encoding="utf-8")
    start = text.index("els.composer.onsubmit = async (e) => {")
    end = text.index("\n  };", start)
    return text[start:end]


def test_chat_submit_captures_auth_identity_before_async_request() -> None:
    body = _composer_submit_body()

    busy_pos = body.index("busy = true;")
    try_pos = body.index("try {", busy_pos)

    prefix = body[:try_pos]

    assert "auth.email" in prefix, (
        "chat submit must capture the signed-in identity before awaiting "
        "mutable auth state"
    )

    catch_pos = body.index("catch (err)", try_pos)
    catch_body = body[catch_pos:]

    assert "auth.email" not in catch_body, (
        "async error handling must not dereference mutable auth after logout"
    )


def test_chat_submit_resets_busy_inside_finally() -> None:
    body = _composer_submit_body()

    catch_pos = body.index("catch (err)")
    cleanup_pos = body.index("busy = false;", catch_pos)

    between = body[catch_pos:cleanup_pos]

    assert "finally" in between, (
        "busy cleanup must be protected by finally so secondary error-path "
        "exceptions cannot leave chat permanently busy"
    )

def test_chat_network_requests_use_abortable_timeout() -> None:
    text = APP.read_text(encoding="utf-8")

    start = text.index("async function fetchWithTimeout(")
    end = text.index("\n  function authHeaders()", start)
    helpers = text[start:end]

    assert "AbortController" in helpers
    assert "setTimeout" in helpers
    assert ".abort()" in helpers
    assert "clearTimeout" in helpers
    assert "finally" in helpers


def test_chat_and_source_fetches_use_timeout_helper() -> None:
    text = APP.read_text(encoding="utf-8")

    jpost_start = text.index("async function jpost(")
    jpost_end = text.index(
        "\n  function authHeaders()",
        jpost_start,
    )
    jpost = text[jpost_start:jpost_end]

    chat_start = text.index("async function chatApi(")
    chat_end = text.index(
        "\n  async function maybeFetchSource(",
        chat_start,
    )
    chat = text[chat_start:chat_end]

    assert "fetchWithTimeout(" in jpost
    assert "fetchWithTimeout(" in chat

