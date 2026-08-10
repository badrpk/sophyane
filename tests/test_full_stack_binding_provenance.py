from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_scenarios import (
    discover_api_scenarios,
)


def _scenario(
    root: Path,
):
    scenarios = discover_api_scenarios(
        root
    )

    assert len(
        scenarios
    ) == 1

    return scenarios[0]


def test_binding_attaches_to_originating_response_not_latest_request(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_flow(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "one"},
    )

    listed = client.request(
        "GET",
        "/api/tasks",
    )

    task_id = created["id"]

    client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    assert len(
        scenario.steps
    ) == 3

    created = scenario.steps[0]
    listed = scenario.steps[1]
    deleted = scenario.steps[2]

    assert created.method == "POST"

    assert created.bind is not None
    assert created.bind.name == "task_id"
    assert created.bind.field == "id"

    assert listed.method == "GET"
    assert listed.bind is None

    assert (
        deleted.path
        == "/api/tasks/{task_id}"
    )


def test_binding_can_attach_to_non_immediately_previous_response(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_flow(client):
    first = client.request(
        "POST",
        "/api/tasks",
        {"title": "first"},
    )

    second = client.request(
        "POST",
        "/api/tasks",
        {"title": "second"},
    )

    first_id = first["id"]

    client.request(
        "DELETE",
        f"/api/tasks/{first_id}",
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    assert (
        scenario.steps[0].bind
        is not None
    )

    assert (
        scenario.steps[0].bind.name
        == "first_id"
    )

    assert (
        scenario.steps[1].bind
        is None
    )


def test_get_response_can_ground_later_identifier(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_flow(client):
    selected = client.request(
        "GET",
        "/api/selected",
    )

    task_id = selected["id"]

    client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    assert (
        scenario.steps[0].method
        == "GET"
    )

    assert (
        scenario.steps[0].bind
        is not None
    )

    assert (
        scenario.steps[0].bind.name
        == "task_id"
    )

    assert (
        scenario.steps[1].path
        == "/api/tasks/{task_id}"
    )


def test_unknown_response_variable_still_cannot_create_binding(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_api.py").write_text(
        '''
def test_flow(client):
    task_id = invented["id"]

    client.request(
        "DELETE",
        f"/api/tasks/{task_id}",
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    assert (
        discover_api_scenarios(
            tmp_path
        )
        == ()
    )


def test_response_provenance_is_not_based_on_latest_step(
    tmp_path: Path,
) -> None:
    source = Path(
        "src/sophyane/full_stack_scenarios.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_GROUNDED_RESPONSE_PROVENANCE_V1"
        in source
    )

    assert (
        "response_steps"
        in source
    )

    assert (
        "response_steps.get("
        in source
    )

    assert (
        "pending_bindings_for_step"
        in source
    )

    assert (
        "origin_step"
        in source
    )

    # Multi-binding storage replaced the old single-binding structure.
    assert (
        "pending_binding_for_step"
        not in source
    )

    # The unsafe previous adjacency shortcut must remain gone.
    assert (
        "len(steps) - 1"
        not in source[
            source.index(
                "binding_result = _binding_assignment("
            ):
            source.index(
                "call: ast.Call | None = None",
                source.index(
                    "binding_result = _binding_assignment("
                ),
            )
        ]
    )
