from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.race_execution as race_execution

from sophyane.race_adapters import ProgressProposal


REQUEST = (
    "Parse incoming raw payload examples or rough functional "
    "descriptions, derive strict JSON schemas or OpenAPI "
    "specifications, and generate functional backend mocking "
    "stubs or test client scripts."
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
        ),
    )


def test_semantic_repair_receives_existing_material_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requests: list[str] = []

    def runner(request, **kwargs):
        requests.append(request)

        if len(requests) == 1:
            return _proposal(
                {
                    "type": "write_file",
                    "path": "payload_parser.py",
                    "content": (
                        "import json\\n\\n"
                        "def parse_payload(payload):\\n"
                        "    return json.loads(payload)\\n"
                    ),
                }
            )

        # Stop after observing the repair request.
        return SimpleNamespace(
            winner=None,
        )

    monkeypatch.setattr(
        race_execution,
        "verify_workspace",
        lambda workspace: [],
    )

    def semantic_judge(**kwargs):
        return {
            "available": True,
            "complete": False,
            "reason": (
                "Schema/OpenAPI and mock/client functionality "
                "are missing."
            ),
            "missing": [
                "schema derivation",
                "OpenAPI generation",
                "backend mock or test client",
            ],
        }

    result = race_execution.run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        max_rounds=2,
        race_runner=runner,
        verifier=lambda workspace: [],
        semantic_judge=semantic_judge,
    )

    assert result.ok is False
    assert len(requests) == 2

    repair = requests[1]

    assert (
        "SEMANTIC COMPLETION VALIDATION FAILED."
        in repair
    )

    assert "CURRENT MATERIAL ARTIFACT STATE:" in repair
    assert "FILE: payload_parser.py" in repair
    assert "def parse_payload(payload):" in repair

    assert "schema derivation" in repair
    assert "OpenAPI generation" in repair
    assert "backend mock or test client" in repair
