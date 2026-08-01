from __future__ import annotations

from pathlib import Path

from sophyane.harness_workspace import (
    is_new_project_request,
    select_workspace,
)
from sophyane.multifile_artifact_extractor import extract_files


FASTAPI_TASK = (
    "Implement a fully functional FastAPI TODO application with secure "
    "authentication, SQLite persistence, automated tests, Dockerfile, "
    "GitHub Actions and complete documentation."
)


def test_semantically_rewritten_fastapi_task_is_isolated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    assert is_new_project_request(FASTAPI_TASK)

    repository = tmp_path / "sophyane-repo"
    repository.mkdir()

    selected = select_workspace(FASTAPI_TASK, repository)

    assert selected != repository.resolve()
    assert selected == (
        tmp_path
        / ".sophyane"
        / "generated-projects"
        / "fastapi-project-todo-application"
    ).resolve()


def test_extractor_rejects_command_as_filename() -> None:
    raw = (
        "\n### `pip install -r requirements.txt`\n\n"
        + '```'
        + "bash\n"
        + "pip install -r requirements.txt\n"
        + '```'
        + "\n\n### `app/main.py`\n\n"
        + '```'
        + "python\n"
        + 'print("ok")\n'
        + '```'
        + "\n"
    )

    paths = [artifact.path for artifact in extract_files(raw)]

    assert "app/main.py" in paths
    assert "pip install -r requirements.txt" not in paths


def test_extractor_rejects_numbered_readme_label() -> None:
    raw = (
        "\n### I. README.md\n\n"
        + '```'
        + "markdown\n"
        + "# Wrong\n"
        + '```'
        + "\n\n### `README.md`\n\n"
        + '```'
        + "markdown\n"
        + "# Correct\n"
        + '```'
        + "\n"
    )

    paths = [artifact.path for artifact in extract_files(raw)]

    assert paths == ["README.md"]
