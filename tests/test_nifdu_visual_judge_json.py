from sophyane.browser_partial_recovery import _json_object


PAYLOAD = {
    "accepted": False,
    "score": 81,
    "critical_issues": 0,
    "unmet_requirements": 1,
    "summary": "Needs stronger hierarchy.",
    "problems": ["Hero CTA lacks emphasis."],
    "repair_instruction": "Strengthen hero hierarchy.",
}


def test_plain_json():
    import json
    assert _json_object(json.dumps(PAYLOAD)) == PAYLOAD


def test_markdown_json_fence():
    import json
    raw = "```json\n" + json.dumps(PAYLOAD) + "\n```"
    assert _json_object(raw) == PAYLOAD


def test_prose_around_json():
    import json
    raw = "Here is the evaluation:\n" + json.dumps(PAYLOAD) + "\nDone."
    assert _json_object(raw) == PAYLOAD


def test_braces_inside_json_string():
    import json
    payload = dict(PAYLOAD)
    payload["summary"] = 'Layout uses "{cards}" effectively.'
    raw = "Result:\n```json\n" + json.dumps(payload) + "\n```"
    assert _json_object(raw) == payload


def test_array_is_not_accepted_as_object():
    assert _json_object('[{"score": 99}]') is None


def test_python_literal_is_not_accepted():
    assert _json_object("{'score': 99, 'accepted': True}") is None


def test_garbage_is_not_accepted():
    assert _json_object("evaluation unavailable") is None
