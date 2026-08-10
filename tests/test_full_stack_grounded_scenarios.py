from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_scenarios import (
    discover_api_scenarios,
)


def _pairs(
    root: Path,
):
    scenarios = discover_api_scenarios(
        root
    )

    return [
        (
            step.method,
            step.path,
            step.body,
            step.expected_status,
        )
        for scenario in scenarios
        for step in scenario.steps
    ]


def test_discovers_literal_post_payload(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_create(client):
    status, payload = client.request(
        "POST",
        "/api/tasks",
        {
            "title": "Write tests",
            "done": False,
        },
    )
    assert status == 201
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    rows = _pairs(
        tmp_path
    )

    assert (
        "POST",
        "/api/tasks",
        {
            "title": "Write tests",
            "done": False,
        },
        (
            201,
        ),
    ) in rows


def test_discovers_literal_put_and_delete(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_crud(client):
    response = client.request(
        "PUT",
        "/api/tasks/7",
        {"done": True},
    )
    assert response == 200

    response = client.request(
        "DELETE",
        "/api/tasks/7",
    )
    assert response == 204
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    rows = _pairs(
        tmp_path
    )

    assert (
        "PUT",
        "/api/tasks/7",
        {
            "done": True,
        },
        (
            200,
        ),
    ) in rows

    assert (
        "DELETE",
        "/api/tasks/7",
        None,
        (
            204,
        ),
    ) in rows


def test_dynamic_path_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_update(client):
    item_id = 7
    client.request(
        "PUT",
        f"/api/tasks/{item_id}",
        {"done": True},
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == []


def test_dynamic_payload_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_create(client):
    payload = make_payload()

    client.request(
        "POST",
        "/api/tasks",
        payload,
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == []


def test_non_api_request_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    (tests / "test_external.py").write_text(
        '''
def test_external(client):
    client.request(
        "POST",
        "/oauth/token",
        {"secret": "do-not-send"},
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert _pairs(
        tmp_path
    ) == []


def test_scenario_source_is_generated_test_file(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"

    tests.mkdir()

    target = (
        tests
        / "test_tasks.py"
    )

    target.write_text(
        '''
def test_create(client):
    client.request(
        "POST",
        "/api/tasks",
        {"title": "one"},
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenarios = discover_api_scenarios(
        tmp_path
    )

    assert len(
        scenarios
    ) == 1

    assert (
        scenarios[
            0
        ].source
        == "tests/test_tasks.py"
    )
