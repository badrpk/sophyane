import json

from sophyane.game_validation import _const_is_reassigned, _snake_problem
from sophyane.workspace_attachment import extract_embedded_html, extract_embedded_partial_html


HTML = "<!doctype html><html><body><canvas></canvas><script>const leftBtn=document.querySelector('#left');const keyPressed=event.keyCode;if(keyPressed===37){leftBtn.addEventListener('click',()=>{});}let snake=[];snake.unshift({x:1,y:1});setInterval(()=>{},100);document.addEventListener('keydown',()=>{});</script></body></html>"


def test_const_comparisons_and_method_calls_are_not_reassignment() -> None:
    source = "const keyPressed=event.keyCode;if(keyPressed===37){};const leftBtn=x;leftBtn.addEventListener('click',f);"
    assert not _const_is_reassigned(source[source.find(';') + 1:], "keyPressed")
    assert not _const_is_reassigned(source[source.rfind(';const') + 1:], "leftBtn")


def test_real_const_writes_are_detected() -> None:
    assert _const_is_reassigned("score = 2", "score")
    assert _const_is_reassigned("score += 2", "score")
    assert _const_is_reassigned("score++", "score")
    assert _const_is_reassigned("++score", "score")


def test_valid_snake_does_not_report_false_const_reassignment() -> None:
    assert _snake_problem(HTML, "make snake game") == ""


def test_complete_embedded_html_is_preferred_over_json_envelope() -> None:
    raw = json.dumps({"objective": "build", "action": {"content": HTML}, "candidates": [{"content": HTML}]})
    assert extract_embedded_html(raw) == HTML
    partial = extract_embedded_partial_html(raw)
    assert partial == HTML
    assert not partial.lstrip().startswith("{")
