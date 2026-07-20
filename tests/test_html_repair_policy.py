from sophyane.game_validation import _snake_advances
from sophyane.html_repair_policy import install_html_repair_policy, is_structural_problem


def test_snake_movement_accepts_non_snake_variable_names():
    assert _snake_advances("segments.unshift(head); segments.pop();")
    assert _snake_advances("body=[head,...body.slice(0,-1)]")
    assert _snake_advances("advanceSnake(head)")


def test_snake_movement_rejects_static_body():
    assert not _snake_advances("drawSnake(); score.textContent=0")


def test_problem_classification():
    assert is_structural_problem("HTML body tag is not closed")
    assert is_structural_problem("JavaScript has 2 unclosed bracket(s)")
    assert not is_structural_problem("snake game does not advance the snake body")


def test_prepare_removes_both_document_closers(monkeypatch):
    from sophyane import adaptive_execution as adaptive

    original = adaptive._prepare_for_continuation
    try:
        install_html_repair_policy()
        prepared = adaptive._prepare_for_continuation("<html><body><script>x()</script></body></html>")
        assert prepared.endswith("</script>")
        assert "</body>" not in prepared
        assert "</html>" not in prepared
    finally:
        adaptive._prepare_for_continuation = original


def test_semantic_repair_requests_complete_rewrite(monkeypatch):
    from sophyane import adaptive_execution as adaptive

    original_prepare = adaptive._prepare_for_continuation
    original_prompt = adaptive._html_continuation_prompt
    original_join = adaptive._join_html_continuation
    try:
        install_html_repair_policy()
        prompt = adaptive._html_continuation_prompt(
            "<!doctype html><html><body></body></html>",
            "snake game does not advance the snake body",
        )
        assert "Rewrite the following complete index.html" in prompt
        assert "Do not append a fragment" in prompt
    finally:
        adaptive._prepare_for_continuation = original_prepare
        adaptive._html_continuation_prompt = original_prompt
        adaptive._join_html_continuation = original_join
