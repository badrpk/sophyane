from pathlib import Path


SOURCE = Path(
    "src/sophyane/agent_supervisor.py"
).read_text(
    encoding="utf-8"
)


def test_postgres_store_is_coordination_dependency():
    assert (
        "PostgresMultiAgentStore"
        in SOURCE
    )


def test_per_agent_progress_fields_exist():
    for token in (
        "progress_percent",
        "current_task",
        "completed_tasks",
        "failed_tasks",
        "queued_tasks",
        "worker_instance",
        "heartbeat_at",
        "blocker",
        "detail",
    ):
        assert token in SOURCE


def test_agent_lifecycle_is_explicit():
    for state in (
        "created",
        "starting",
        "running",
        "waiting",
        "blocked",
        "paused",
        "completed",
        "failed",
        "stopped",
    ):
        assert f'"{state}"' in SOURCE


def test_status_rendering_exists():
    assert "def render_status(" in SOURCE
    assert "AGENT_STATUS:" in SOURCE
    assert "PROGRESS=" in SOURCE
    assert "HEARTBEAT=" in SOURCE


def test_resource_governor_contract_exists():
    for token in (
        "max_concurrent_agents",
        "max_browser_agents",
        "max_local_llm_agents",
        "max_cpu_workers",
    ):
        assert token in SOURCE


def test_approval_gate_is_default_on():
    assert (
        "approval_gate_enabled: bool = True"
        in SOURCE
    )


def test_outreach_is_default_off():
    assert (
        "outreach_enabled: bool = False"
        in SOURCE
    )


def test_configuration_does_not_claim_running():
    assert (
        "MULTI_AGENT_RUNTIME=CONFIGURED_NOT_STARTED"
        in SOURCE
    )
    assert "SUPERVISOR=CONFIGURED" in SOURCE


def test_live_worker_identity_is_visible():
    assert "WORKER=" in SOURCE
    assert "worker_instance" in SOURCE


def test_heartbeat_is_visible():
    assert "HEARTBEAT=" in SOURCE
    assert "def heartbeat(" in SOURCE
