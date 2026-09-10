from pathlib import Path


class _FakeCDP:
    def __init__(self):
        self.expressions = []

    def evaluate(self, expression):
        self.expressions.append(expression)
        return True


def _source():
    path = Path(
        "src/sophyane/providers/nifdu_cdp_bridge.py"
    )
    return path.read_text(encoding="utf-8")


def test_populate_prompt_preserves_native_textarea_setter():
    from sophyane.providers.nifdu_cdp_bridge import (
        populate_prompt,
    )

    cdp = _FakeCDP()

    populate_prompt(
        cdp,
        "hello",
    )

    assert len(cdp.expressions) == 1

    expression = cdp.expressions[0]

    assert "HTMLTextAreaElement.prototype" in expression
    assert "HTMLInputElement.prototype" in expression
    assert "setter.call(e, value)" in expression


def test_contenteditable_population_avoids_execcommand():
    from sophyane.providers.nifdu_cdp_bridge import (
        populate_prompt,
    )

    cdp = _FakeCDP()

    populate_prompt(
        cdp,
        "NS_LIGHTWEIGHT_PROMPT_TEST",
    )

    expression = cdp.expressions[0]

    assert "document.execCommand" not in expression
    assert "replaceChildren" in expression
    assert "document.createTextNode(value)" in expression


def test_contenteditable_input_event_does_not_duplicate_full_prompt():
    from sophyane.providers.nifdu_cdp_bridge import (
        populate_prompt,
    )

    cdp = _FakeCDP()

    populate_prompt(
        cdp,
        "X" * 10000,
    )

    expression = cdp.expressions[0]

    # The prompt is embedded once as:
    #
    #   const value = "...";
    #
    # It must not then be copied into InputEvent.data as well.
    assert "data: value" not in expression
    assert "data: null" in expression


def test_populate_prompt_still_raises_when_composer_missing():
    source = _source()

    assert "Unable to populate ChatGPT prompt." in source
