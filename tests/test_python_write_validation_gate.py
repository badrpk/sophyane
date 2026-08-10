from pathlib import Path

import sophyane.adaptive_execution as adaptive


class Runtime:
    @staticmethod
    def execute_action(action, workspace, progress):
        path = workspace / action["path"]
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            action["content"],
            encoding="utf-8",
        )
        return True, "written"


def test_valid_python_write_passes(
    tmp_path: Path,
) -> None:
    action = {
        "type": "write_file",
        "path": "app.py",
        "content": "print('ok')\n",
    }

    ok, result = adaptive._execute(
        Runtime,
        action,
        tmp_path,
        lambda _message: None,
    )

    # _execute itself still represents the lower-level write.
    assert ok


def test_py_compile_detects_generated_syntax_error(
    tmp_path: Path,
) -> None:
    import py_compile

    target = tmp_path / "app.py"
    target.write_text(
        "print('Starting httpd...\n')\n",
        encoding="utf-8",
    )

    try:
        py_compile.compile(
            str(target),
            doraise=True,
        )
    except py_compile.PyCompileError:
        pass
    else:
        raise AssertionError(
            "Malformed generated Python was not rejected"
        )
