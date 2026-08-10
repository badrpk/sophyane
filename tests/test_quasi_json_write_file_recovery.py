from pathlib import Path

from sophyane.execution_runtime import (
    _normalize_action,
    _recover_quasi_json_file_action,
    extract_plan,
)


def test_recovers_triple_double_quoted_write_file() -> None:
    raw = '''{
  "action": "write_file",
  "path": "backend/app.py",
  "content": """
print("hello")
"""
}'''

    recovered = (
        _recover_quasi_json_file_action(
            raw
        )
    )

    assert recovered == {
        "action": "write_file",
        "path": "backend/app.py",
        "content": '\nprint("hello")\n',
    }

    plan = extract_plan(
        raw
    )

    assert plan == recovered

    normalized = _normalize_action(
        plan
    )

    assert normalized == {
        "path": "backend/app.py",
        "content": '\nprint("hello")\n',
        "type": "write_file",
    }


def test_recovers_triple_single_quoted_append_file() -> None:
    raw = """{
  "action": "append_file",
  "path": "backend/app.py",
  "content": '''
print("more")
'''
}"""

    plan = extract_plan(
        raw
    )

    assert plan is not None

    assert (
        plan["action"]
        == "append_file"
    )

    assert (
        plan["path"]
        == "backend/app.py"
    )

    assert (
        'print("more")'
        in plan["content"]
    )


def test_recovery_rejects_non_file_actions() -> None:
    raw = '''{
  "action": "run_command",
  "path": "backend/app.py",
  "content": """rm -rf something"""
}'''

    assert (
        _recover_quasi_json_file_action(
            raw
        )
        is None
    )


def test_recovery_does_not_replace_normal_json_parser() -> None:
    raw = (
        '{"action":"write_file",'
        '"path":"x.py",'
        '"content":"print(1)"}'
    )

    plan = extract_plan(
        raw
    )

    assert plan == {
        "action": "write_file",
        "path": "x.py",
        "content": "print(1)",
    }


def test_exact_live_local_gguf_output_is_recovered() -> None:
    path = (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "local-gguf-real-coding-output-20260811-010654.txt"
    )

    if not path.is_file():
        return

    raw = path.read_text(
        encoding="utf-8",
    )

    plan = extract_plan(
        raw
    )

    assert plan is not None

    normalized = _normalize_action(
        plan
    )

    assert normalized is not None

    assert (
        normalized["type"]
        == "write_file"
    )

    assert (
        normalized["path"]
        == "backend/app.py"
    )

    content = normalized[
        "content"
    ]

    assert len(
        content
    ) > 4000

    assert (
        "sqlite3"
        in content
    )

    assert (
        "ThreadingHTTPServer"
        in content
    )

    assert (
        "BaseHTTPRequestHandler"
        in content
    )
