from sophyane import adaptive_execution as adaptive
from sophyane import execution_runtime as runtime


def _action(raw: str):
    plan = runtime.extract_plan(raw)

    assert isinstance(plan, dict)

    action = adaptive._selected_action(
        runtime,
        plan,
    )

    assert isinstance(action, dict)

    return action


def test_live_style_nested_write_recovers_unescaped_source_quotes():
    raw = (
        '{"action":{"type":"write_file","path":"app.py","content":"'
        'import json\\n'
        'from datetime import datetime, timezone\\n'
        '\\n'
        'def health():\\n'
        ' body = json.dumps({\\n'
        ' "status": "ok",\\n'
        ' "timestamp": datetime.now(timezone.utc).isoformat(),\\n'
        ' })\\n'
        ' return body\\n'
        '"}}'
    )

    action = _action(raw)

    assert action["type"] == "write_file"
    assert action["path"] == "app.py"
    assert '"status": "ok"' in action["content"]
    assert (
        '"timestamp": datetime.now(timezone.utc).isoformat()'
        in action["content"]
    )


def test_live_style_f_string_and_index_quotes_recover():
    raw = (
        '{"action":{"type":"write_file","path":"test_app.py","content":"'
        'from urllib.request import urlopen\\n'
        '\\n'
        'def test_health(server):\\n'
        ' with urlopen(f"http://127.0.0.1:{server.server_port}/health") '
        'as response:\\n'
        '  data = response.read()\\n'
        '  assert result["status"] == "ok"\\n'
        '"}}'
    )

    action = _action(raw)

    assert action["path"] == "test_app.py"

    assert (
        'f"http://127.0.0.1:{server.server_port}/health"'
        in action["content"]
    )

    assert (
        'result["status"] == "ok"'
        in action["content"]
    )


def test_valid_json_path_is_unchanged():
    raw = (
        '{"action":{"type":"write_file","path":"ok.py",'
        '"content":"print(\\"ok\\")\\n"}}'
    )

    action = _action(raw)

    assert action["type"] == "write_file"
    assert action["path"] == "ok.py"
    assert action["content"] == 'print("ok")\n'


def test_malformed_run_command_is_not_recovered():
    raw = (
        '{"action":{"type":"run_command","command":"'
        'echo "ambiguous"'
        '"}}'
    )

    assert runtime.extract_plan(raw) is None


def test_missing_path_is_not_recovered():
    raw = (
        '{"action":{"type":"write_file","content":"'
        'print("missing")'
        '"}}'
    )

    assert runtime.extract_plan(raw) is None


def test_existing_v3_triple_quote_shape_remains_supported():
    raw = (
        '{"action":"write_file","path":"legacy.py","content":'
        '"""print("legacy")\n"""}'
    )

    action = _action(raw)

    assert action["type"] == "write_file"
    assert action["path"] == "legacy.py"
    assert 'print("legacy")' in action["content"]
