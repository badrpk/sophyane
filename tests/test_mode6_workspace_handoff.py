from pathlib import Path

import pytest

import sophyane.human_conversation_cli as cli


@pytest.mark.parametrize(
    "request_template",
    [
        """Work in {workspace}.

Inspect the existing files.
Do not modify anything.""",

        """Continue the existing task in this exact directory:
{workspace}

Inspect the existing files.
Do not modify anything.""",

        """Inspect the explicitly supplied repository {workspace}
read-only and report what files are present.
Do not modify anything.""",
    ],
)
def test_mode6_explicit_workspace_wording_resolves_exact_repository(
    tmp_path,
    request_template,
):
    workspace = (tmp_path / "requested-repository").resolve()
    workspace.mkdir()

    request = request_template.format(workspace=workspace)

    resolved = cli._requested_execution_workspace(request)

    assert resolved is not None
    assert Path(resolved).resolve() == workspace
