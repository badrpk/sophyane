from __future__ import annotations

import ast
from pathlib import Path


CLI = Path("src/sophyane/cli_entry.py")
RACE = Path("src/sophyane/race_orchestrator.py")


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return node

    raise AssertionError(f"{name} missing")


def test_mode1_real_workers_do_not_register_sli():
    node = _function(
        RACE,
        "build_real_workers",
    )

    source = ast.get_source_segment(
        RACE.read_text(encoding="utf-8"),
        node,
    )

    assert source is not None
    assert "make_sli_producer" not in source
    assert "run_sli_graph" not in source


def test_cli_sli_runtime_installation_is_mode2_guarded():
    text = CLI.read_text(encoding="utf-8")

    marker = "SOPHYANE_MODE2_RUNTIME_ISOLATION_V1"

    assert text.count(marker) == 1

    before, after = text.split(
        marker,
        1,
    )

    for installer in (
        "install_sli_brain()",
        "install_sli_builder()",
        "install_sli_capability_planner()",
        "install_sli_intent_routing()",
        "install_sli_mission_os()",
        "install_sli_onset_feedback()",
    ):
        assert installer not in before
        assert installer in after


def test_mode2_guard_is_explicit_sli_graph_session():
    text = CLI.read_text(encoding="utf-8")

    marker = "SOPHYANE_MODE2_RUNTIME_ISOLATION_V1"
    tail = text.split(marker, 1)[1][:2200]

    assert 'SOPHYANE_SESSION_MODE' in tail
    assert '"sli_graph"' in tail


def test_fresh_preview_is_not_installed_globally():
    text = CLI.read_text(encoding="utf-8")

    marker = "SOPHYANE_FRESH_PREVIEW_INSTALL_V1"
    tail = text.split(marker, 1)[1][:1200]

    assert "SOPHYANE_SESSION_MODE" in tail
    assert '"sli_graph"' in tail


def test_mode1_worker_registry_is_initialized_without_sli():
    text = RACE.read_text(encoding="utf-8")
    node = _function(
        RACE,
        "build_real_workers",
    )

    source = ast.get_source_segment(
        text,
        node,
    ) or ""

    assert "workers = {}" in source

    assert (
        '"sli"'
        not in source
    )

    assert "make_sli_producer" not in source
    assert "run_sli_graph" not in source


def test_mode1_has_no_legacy_prefer_sli_only_contract():
    execution = Path(
        "src/sophyane/race_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    orchestrator = RACE.read_text(
        encoding="utf-8",
    )

    assert "prefer_sli_only" not in execution

    node = _function(
        RACE,
        "build_real_workers",
    )

    source = ast.get_source_segment(
        orchestrator,
        node,
    ) or ""

    assert "prefer_sli_only" not in source
