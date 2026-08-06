from sophyane.tui_v2 import (
    _simple_chat_reply,
)


def test_secret_request_is_intercepted_before_sli() -> None:
    result = _simple_chat_reply(
        "what is my gmail app password?"
    )

    assert result is not None
    assert "cannot be displayed" in result
    assert "Secret disclosed: False" in result


def test_dialogue_question_is_answered_privately() -> None:
    result = _simple_chat_reply(
        "why you close dialog box"
    )

    assert result is not None
    assert "private connector" in result.casefold()
    assert "Success: True" in result
