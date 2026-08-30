from __future__ import annotations

import json
import pytest
from pathlib import Path

import sophyane.local_coding_capability as coding


def _request() -> str:
    return (
        "Create records_tool.py. "
        "Define function choose_best(items). "
        "items is a list of dictionaries containing id and score. "
        "Ignore records missing id or score. "
        "If an id appears multiple times, keep the record with "
        "the highest numeric score. "
        "Return a list sorted by score descending, then id ascending."
    )


def _implementation() -> str:
    return """def choose_best(items):
    best = {}

    for item in items:
        if "id" not in item or "score" not in item:
            continue

        current = best.get(item["id"])

        if (
            current is None
            or item["score"] > current["score"]
        ):
            best[item["id"]] = dict(item)

    return sorted(
        best.values(),
        key=lambda item: (
            -item["score"],
            item["id"],
        ),
    )
"""


def test_direct_contract_decodes_source_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    contract = coding._explicit_record_function_contract(
        filename="records_tool.py",
        request=_request(),
    )

    assert contract is not None

    calls = []

    def fake_model(
        prompt: str,
        *,
        temperature: float = 0.0,
        return_metadata: bool = False,
    ):
        calls.append(prompt)

        response = json.dumps(
            {
                "source":
                    _implementation(),
            }
        )

        if return_metadata:
            return (
                response,
                {},
            )

        return response

    monkeypatch.setattr(
        coding,
        "_ask_local_coding_model",
        fake_model,
    )

    result = (
        coding._small_model_direct_contract_generation(
            request=_request(),
            filename="records_tool.py",
            function_name="choose_best",
            test_source=contract["test_source"],
            workspace=tmp_path,
        )
    )

    assert result is not None
    assert result.handled
    assert result.ok
    assert result.capability == (
        "development."
        "python_direct_contract_green"
    )

    target = (
        tmp_path
        / "records_tool.py"
    )

    assert target.is_file()

    assert (
        "def choose_best(items)"
        in target.read_text(
            encoding="utf-8"
        )
    )

    assert len(calls) == 1


def test_direct_contract_accepts_fenced_python_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    contract = coding._explicit_record_function_contract(
        filename="records_tool.py",
        request=_request(),
    )

    assert contract is not None

    response = (
        "```python\n"
        + _implementation()
        + "```"
    )

    def fake_model(
        prompt: str,
        *,
        temperature: float = 0.0,
        return_metadata: bool = False,
    ):
        if return_metadata:
            return (
                response,
                {},
            )

        return response

    monkeypatch.setattr(
        coding,
        "_ask_local_coding_model",
        fake_model,
    )

    result = (
        coding._small_model_direct_contract_generation(
            request=_request(),
            filename="records_tool.py",
            function_name="choose_best",
            test_source=contract["test_source"],
            workspace=tmp_path,
        )
    )

    assert result is not None
    assert result.handled
    assert result.ok

    target = (
        tmp_path
        / "records_tool.py"
    )

    assert target.is_file()

    generated = target.read_text(
        encoding="utf-8"
    )

    assert "```" not in generated
    assert "def choose_best" in generated



def test_global_adaptive_json_decoder_rejects_fenced_python() -> None:
    raw = """```python
def choose_best(items):
    return []
```"""

    with pytest.raises(
        ValueError,
        match="no canonical JSON object",
    ):
        coding._coding_json_object(
            raw
        )
