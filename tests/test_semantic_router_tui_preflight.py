from sophyane.tui_v2 import (
    _simple_chat_reply,
)


def test_personal_question_never_reaches_public_acquisition(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.MEMORY_FILE",
        tmp_path / "memory.json",
    )

    reply = _simple_chat_reply(
        "what is name of my USA company?"
    )

    assert reply is not None
    assert (
        "personal factual question"
        in reply.casefold()
    )
    assert "public internet" in reply.casefold()
    assert "WhatsMyName" not in reply
    assert "index.html" not in reply
