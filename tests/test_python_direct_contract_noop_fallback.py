from __future__ import annotations

from pathlib import Path

import sophyane.local_coding_capability as coding


def _request() -> str:
    return (
        "Create records_tool.py. "
        "Define function choose_best(items). "
        "items is a list of dictionaries containing id and score. "
        "Ignore records missing id or score. "
        "If an id appears multiple times, keep the record "
        "with the highest numeric score. "
        "Return a list sorted by score descending, "
        "then id ascending. "
        "Do not modify the input."
    )


def _bad_source() -> str:
    return """def choose_best(items):
    return sorted(
        [
            item
            for item in items
            if item["id"] and item["score"]
        ],
        key=lambda item: (
            -item["score"],
            item["id"],
        ),
    )
"""


def test_ast_identical_model_repair_uses_contract_candidate(
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

        response = (
            "```python\n"
            + _bad_source()
            + "\n```"
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

    result = coding._small_model_direct_contract_generation(
        request=_request(),
        filename="records_tool.py",
        function_name="choose_best",
        test_source=contract["test_source"],
        workspace=tmp_path,
    )

    assert result is not None
    assert result.handled
    assert result.ok

    #
    # Model remains first candidate + one bounded repair.
    #
    assert len(calls) == 2

    target = (
        tmp_path
        / "records_tool.py"
    )

    assert target.is_file()

    namespace = {}

    exec(
        target.read_text(
            encoding="utf-8"
        ),
        namespace,
    )

    choose_best = namespace[
        "choose_best"
    ]

    records = [
        {
            "id": "b",
            "score": 2,
        },
        {
            "id": "a",
            "score": 5,
        },
        {
            "id": "b",
            "score": 8,
        },
        {
            "id": "ignored",
        },
        {
            "score": 100,
        },
    ]

    before = [
        dict(item)
        for item in records
    ]

    assert choose_best(
        records
    ) == [
        {
            "id": "b",
            "score": 8,
        },
        {
            "id": "a",
            "score": 5,
        },
    ]

    assert records == before


def test_unrelated_contract_has_no_deterministic_fallback() -> None:
    source = (
        coding._explicit_record_contract_implementation(
            filename="hello.py",
            request=(
                "Create hello.py. "
                "Define function greet(name). "
                "Return hello and the name."
            ),
        )
    )

    assert source is None
