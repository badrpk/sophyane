from __future__ import annotations

from sophyane.sli_capability_engine import (
    is_build_request,
)
from sophyane.sli_semantic_intelligence import (
    build_semantic_plan,
)


LIVE = (
    "Provide a terminal-access agent with explicit safety guardrails "
    "to monitor long-running background processes or daemon crash logs, "
    "dynamically diagnose out-of-memory or port-binding conflicts, "
    "and execute safe corrective shell scripts."
)


def test_provide_software_is_constructive() -> None:
    assert is_build_request(LIVE)


def test_operational_agent_semantic_plan_has_runtime_capabilities() -> None:
    plan = build_semantic_plan(LIVE)

    names = set(plan.required_names)

    assert "process_supervision" in names
    assert "log_diagnostics" in names
    assert "resource_diagnostics" in names
    assert "network_port_diagnostics" in names
    assert "safe_command_execution" in names


def test_operational_plan_keeps_generic_safety_capabilities() -> None:
    plan = build_semantic_plan(LIVE)

    names = set(plan.required_names)

    assert "error_handling" in names
    assert "rules_and_validation" in names


def test_informational_daemon_request_does_not_become_build() -> None:
    assert not is_build_request(
        "Explain how daemon process monitoring works."
    )
