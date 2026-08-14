from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sophyane.race_execution import _winner_action


def _winner(payload):
    proposal = SimpleNamespace(
        payload=payload,
    )
    return SimpleNamespace(
        worker="sli",
        value=proposal,
    )


def test_sli_shadow_changed_file_becomes_write_action(
    tmp_path: Path,
):
    shadow = tmp_path / "shadow"
    shadow.mkdir()

    target = shadow / "generated" / "openapi.json"
    target.parent.mkdir()
    target.write_text(
        '{"openapi":"3.1.0"}\n',
        encoding="utf-8",
    )

    winner = _winner(
        {
            "route": "artifact",
            "report": "generated artifact",
            "success": True,
            "promoted": False,
            "shadow_workspace": str(shadow),
            "changed_files": [
                "generated/openapi.json",
            ],
        }
    )

    action = _winner_action(winner)

    assert action is not None
    assert action["type"] == "write_file"
    assert action["path"] == "generated/openapi.json"
    assert action["content"] == '{"openapi":"3.1.0"}\n'


def test_sli_shadow_promotion_rejects_path_escape(
    tmp_path: Path,
):
    shadow = tmp_path / "shadow"
    shadow.mkdir()

    outside = tmp_path / "outside.txt"
    outside.write_text(
        "must not promote\n",
        encoding="utf-8",
    )

    winner = _winner(
        {
            "shadow_workspace": str(shadow),
            "changed_files": [
                "../outside.txt",
            ],
        }
    )

    assert _winner_action(winner) is None


def test_non_sli_proposal_contract_is_unchanged():
    winner = SimpleNamespace(
        worker="local",
        value=SimpleNamespace(
            payload={
                "action": {
                    "type": "mkdir",
                    "path": "generated",
                },
            },
        ),
    )

    assert _winner_action(winner) == {
        "type": "mkdir",
        "path": "generated",
    }
