from pathlib import Path

from sophyane import adaptive_execution


class RuntimeStub:
    @staticmethod
    def execute_action(
        action,
        workspace,
        progress,
    ):
        kind = action["type"]
        target = workspace / action["path"]

        if kind == "write_file":
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            target.write_text(
                action.get("content", ""),
                encoding="utf-8",
            )
            return True, f"Wrote {target}"

        raise AssertionError(
            f"unexpected action: {action}"
        )


def test_intentional_empty_file_recovery_executes(
    tmp_path: Path,
) -> None:
    action = {
        "type": "write_file",
        "path": "test.py",
        "content": "",
        "replace": True,
        "artifact_source": (
            "simple_empty_file_recovery"
        ),
    }

    ok, result = adaptive_execution._execute(
        RuntimeStub(),
        action,
        tmp_path,
        lambda _message: None,
    )

    assert ok is True, result

    target = tmp_path / "test.py"

    assert target.is_file()
    assert target.read_bytes() == b""


def test_ordinary_empty_write_remains_rejected(
    tmp_path: Path,
) -> None:
    action = {
        "type": "write_file",
        "path": "bad.py",
        "content": "",
    }

    ok, result = adaptive_execution._execute(
        RuntimeStub(),
        action,
        tmp_path,
        lambda _message: None,
    )

    assert ok is False
    assert "empty content" in result.lower()
    assert not (tmp_path / "bad.py").exists()
