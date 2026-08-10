from __future__ import annotations

from pathlib import Path

from sophyane.full_stack_scenarios import (
    discover_api_scenarios,
    scenario_summary,
)


def _scenario(
    root: Path,
):
    values = discover_api_scenarios(
        root
    )

    assert len(values) == 1
    return values[0]


def test_one_response_can_ground_multiple_symbols(
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
        {"title": "x"},
    )

    task_id = created["id"]
    owner_id = created["owner_id"]

    client.request(
        "PUT",
        f"/api/tasks/{task_id}/owners/{owner_id}",
        {"done": True},
    )
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    create = scenario.steps[0]
    update = scenario.steps[1]

    assert [
        (
            item.name,
            item.field,
        )
        for item in create.bindings
    ] == [
        (
            "task_id",
            "id",
        ),
        (
            "owner_id",
            "owner_id",
        ),
    ]

    assert (
        update.path
        == "/api/tasks/{task_id}/owners/{owner_id}"
    )


def test_backward_single_bind_property_still_works(
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

    scenario = _scenario(
        tmp_path
    )

    assert scenario.steps[0].bind is not None
    assert scenario.steps[0].bind.name == "task_id"


def test_multiple_bindings_make_single_bind_view_none(
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
        {"title": "x"},
    )

    task_id = created["id"]
    owner_id = created["owner_id"]
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    scenario = _scenario(
        tmp_path
    )

    assert len(
        scenario.steps[0].bindings
    ) == 2

    assert (
        scenario.steps[0].bind
        is None
    )


def test_plain_reassignment_invalidates_grounded_symbol(
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
        {"title": "x"},
    )

    task_id = created["id"]
    task_id = 999

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

    assert scenario.steps[0].method == "POST"


def test_reassignment_from_new_grounded_response_transfers_provenance(
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

    task_id = first["id"]

    second = client.request(
        "POST",
        "/api/tasks",
        {"title": "second"},
    )

    task_id = second["id"]

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

    assert scenario.steps[0].bindings == ()

    assert len(
        scenario.steps[1].bindings
    ) == 1

    assert (
        scenario.steps[1].bindings[0].name
        == "task_id"
    )

    assert (
        scenario.steps[1].bindings[0].field
        == "id"
    )


def test_shadowing_one_symbol_does_not_invalidate_other_binding(
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
        {"title": "x"},
    )

    task_id = created["id"]
    owner_id = created["owner_id"]

    task_id = 7

    client.request(
        "GET",
        f"/api/owners/{owner_id}",
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
    ) == 2

    assert (
        scenario.steps[1].path
        == "/api/owners/{owner_id}"
    )


def test_summary_lists_every_response_binding(
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
        {"title": "x"},
    )

    task_id = created["id"]
    owner_id = created["owner_id"]
'''.strip()
        + "\n",
        encoding="utf-8",
    )

    summary = scenario_summary(
        _scenario(
            tmp_path
        )
    )

    assert (
        "bindings="
        "task_id<-response.id,"
        "owner_id<-response.owner_id"
        in summary
    )


def test_shadowing_contract_is_explicit_in_source() -> None:
    source = Path(
        "src/sophyane/full_stack_scenarios.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_GROUNDED_MULTI_BINDING_SHADOWING_V1"
        in source
    )

    assert (
        "bindings.pop("
        in source
    )

    assert (
        "pending_bindings_for_step"
        in source
    )
