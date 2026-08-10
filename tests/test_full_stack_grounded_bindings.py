from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_scenarios import (
    discover_api_scenarios,
)


def _scenario(
    root: Path,
):
    values = discover_api_scenarios(
        root
    )

    assert len(values) == 1

    return values[0]


def test_response_id_binding_drives_later_path_template(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_crud.py").write_text(
        '''
def test_crud(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "hello"},
    )
    assert created == 201

    task_id = created["id"]

    updated = client.request(
        "PUT",
        f"/api/tasks/{task_id}",
        {"done": True},
    )
    assert updated == 200
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    assert len(
        scenario.steps
    ) == 2

    create = scenario.steps[0]
    update = scenario.steps[1]

    assert create.bind is not None
    assert create.bind.name == "task_id"
    assert create.bind.field == "id"

    assert (
        update.path
        == "/api/tasks/{task_id}"
    )


def test_unbound_fstring_remains_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_dynamic.py").write_text(
        '''
def test_update(client):
    task_id = 7

    client.request(
        "PUT",
        f"/api/tasks/{task_id}",
        {"done": True},
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


def test_binding_from_non_response_variable_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_bad.py").write_text(
        '''
def test_update(client):
    payload = {"id": 9}
    task_id = payload["id"]

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


def test_attribute_binding_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_bad.py").write_text(
        '''
def test_update(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = created.id

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
    ) == 1

    assert (
        scenario.steps[0].bind
        is None
    )


def test_computed_binding_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_bad.py").write_text(
        '''
def test_update(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = int(created["id"])

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
    ) == 1


def test_nested_response_lookup_is_rejected(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_bad.py").write_text(
        '''
def test_update(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
    )

    task_id = created["task"]["id"]

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
    ) == 1


def test_binding_summary_is_explicit(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "test_crud.py").write_text(
        '''
def test_crud(client):
    created = client.request(
        "POST",
        "/api/tasks",
        {"title": "x"},
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

    from sophyane.full_stack_scenarios import (
        scenario_summary,
    )

    scenario = _scenario(
        tmp_path
    )

    summary = scenario_summary(
        scenario
    )

    assert (
        "bindings=task_id<-response.id"
        in summary
    )

    assert (
        "DELETE /api/tasks/{task_id}"
        in summary
    )
