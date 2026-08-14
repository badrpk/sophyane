from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sophyane.race_execution import (
    _workspace_environment,
)


def test_workspace_prepended_to_pythonpath(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv(
        "PYTHONPATH",
        "/existing/path",
    )

    environment = _workspace_environment(
        tmp_path
    )

    parts = environment[
        "PYTHONPATH"
    ].split(
        os.pathsep
    )

    assert parts[0] == str(
        tmp_path.resolve()
    )


def test_workspace_importable(
    tmp_path: Path,
):
    (
        tmp_path
        / "score_window.py"
    ).write_text(
        "VALUE = 42\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import score_window; "
                "print(score_window.VALUE)"
            ),
        ],
        cwd=tmp_path,
        env=_workspace_environment(
            tmp_path
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "42"
