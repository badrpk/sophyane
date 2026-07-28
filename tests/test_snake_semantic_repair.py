from sophyane import adaptive_execution, game_validation
from sophyane.runtime_snake_semantic_repair import install_snake_semantic_repair


def test_vector_component_sum_reverse_guard_is_accepted():
    install_snake_semantic_repair()
    source = """
    function setDirection(nextDir) {
      if (nextDir.x + direction.x === 0 && nextDir.y + direction.y === 0) return;
      pendingDirection = nextDir;
    }
    """
    assert game_validation._snake_has_reverse_guard(source) is True


def test_semantic_problem_requests_full_rewrite_not_continuation():
    install_snake_semantic_repair()
    html = (
        "<!doctype html><html><body><canvas></canvas><script>"
        "let direction={x:1,y:0};function setDirection(d){direction=d;}"
        "</script></body></html>"
    )
    prompt = adaptive_execution._html_continuation_prompt(
        html,
        "snake controls allow unstable 180-degree reversal",
    )
    assert "REPAIR A COMPLETE SELF-CONTAINED HTML PRODUCT" in prompt
    assert "Return ONE full replacement index.html only" in prompt
    assert html in prompt


def test_structural_truncation_still_uses_continuation_prompt():
    install_snake_semantic_repair()
    partial = "<!doctype html><html><body><script>function tick(){"
    prompt = adaptive_execution._html_continuation_prompt(
        partial,
        "document has no closing </html>",
    )
    assert "Continue the unfinished index.html" in prompt
