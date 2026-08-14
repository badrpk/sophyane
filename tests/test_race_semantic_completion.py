from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.race_execution as race_execution

from sophyane.race_adapters import ProgressProposal


REQUEST = (
    "Parse incoming raw payload examples or rough functional descriptions, "
    "derive strict JSON schemas or OpenAPI specifications, and generate "
    "functional backend mocking stubs or test client scripts."
)


def _proposal(action):
    return SimpleNamespace(
        winner=SimpleNamespace(
            worker="cloud",
            value=ProgressProposal(
                engine="cloud",
                payload={
                    "action": action,
                },
                kind="action",
                confidence=0.95,
                evidence=("fixture",),
                requires_write=False,
            ),
        )
    )


def _green_verifier(workspace):
    return []


def test_semantically_incomplete_material_artifact_is_not_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    def runner(*args, **kwargs):
        nonlocal calls
        calls += 1

        return _proposal(
            {
                "type": "write_file",
                "path": "payload_parser.py",
                "content": (
                    "import json\n"
                    "def parse_payload(value):\n"
                    "    return json.loads(value)\n"
                ),
            }
        )

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        _green_verifier,
    )

    monkeypatch.setattr(
        race_execution,
        "_semantic_completion_judgement",
        lambda **kwargs: {
            "available": True,
            "complete": False,
            "reason": (
                "Only payload parsing exists; schema/OpenAPI generation "
                "and mocking/client functionality are missing."
            ),
            "missing": [
                "schema derivation",
                "OpenAPI generation",
                "backend mock or test client",
            ],
        },
    )

    result = race_execution.run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=runner,
        verifier=_green_verifier,
        semantic_judge=(
            race_execution._semantic_completion_judgement
        ),
    )

    assert calls == 1
    assert result.ok is False
    assert result.error == "maximum adaptive repair rounds exhausted"


def test_semantically_complete_material_artifact_can_succeed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def runner(*args, **kwargs):
        return _proposal(
            {
                "type": "write_file",
                "path": "api_harness.py",
                "content": (
                    "def infer_schema(payload):\n"
                    "    return {'type': 'object'}\n\n"
                    "def generate_openapi(schema):\n"
                    "    return {'openapi': '3.1.0'}\n\n"
                    "def mock_backend():\n"
                    "    return None\n"
                ),
            }
        )

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        _green_verifier,
    )

    monkeypatch.setattr(
        race_execution,
        "_semantic_completion_judgement",
        lambda **kwargs: {
            "available": True,
            "complete": True,
            "reason": "Requested functional capabilities are represented.",
            "missing": [],
        },
    )

    result = race_execution.run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        max_rounds=1,
        race_runner=runner,
        verifier=_green_verifier,
        semantic_judge=(
            race_execution._semantic_completion_judgement
        ),
    )

    assert result.ok is True
