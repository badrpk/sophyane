from pathlib import Path


def test_adaptive_execution_delegates_full_stack_runtime_verification() -> None:
    source = Path(
        "src/sophyane/adaptive_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "verify_full_stack_application"
        in source
    )

    assert (
        "def _verify_full_stack_service_fabric("
        not in source
    )

    assert (
        "http.client.HTTPConnection"
        not in source
    )

    assert (
        "ServiceSupervisor("
        not in source
    )


def test_dedicated_verification_module_owns_service_fabric_runtime() -> None:
    source = Path(
        "src/sophyane/full_stack_verification.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "def verify_full_stack_application("
        in source
    )

    assert (
        "discover_service_manifest"
        in source
    )

    assert (
        "ServiceSupervisor"
        in source
    )

    assert (
        "supervisor.start_manifest("
        in source
    )

    assert (
        "supervisor.status()"
        in source
    )

    assert (
        "supervisor.stop_all()"
        in source
    )


def test_verification_module_does_not_spawn_processes_directly() -> None:
    source = Path(
        "src/sophyane/full_stack_verification.py"
    ).read_text(
        encoding="utf-8",
    )

    forbidden = (
        "subprocess.Popen",
        "os.system(",
        ".sophyane-full-stack-server",
        "curl ",
        "127.0.0.1:8080",
    )

    for marker in forbidden:
        assert marker not in source


def test_verification_module_does_not_fabricate_mutation_requests() -> None:
    source = Path(
        "src/sophyane/full_stack_verification.py"
    ).read_text(
        encoding="utf-8",
    )

    # The transport is intentionally generic now because grounded scenarios
    # may execute POST/PUT/PATCH/DELETE. Safety therefore cannot be proved by
    # requiring the transport itself to be GET-only.
    assert (
        "connection.request("
        in source
    )

    assert (
        "discover_api_scenarios("
        in source
    )

    assert (
        "for scenario in scenarios:"
        in source
    )

    assert (
        "for step in scenario.steps:"
        in source
    )

    assert (
        "step.method"
        in source
    )

    assert (
        "step.path"
        in source
    )

    # Mutation endpoints discovered from server source are evidence only.
    # They must not themselves drive requests.
    assert (
        "mutation_contracts_unexecuted="
        in source
    )

    assert (
        "no grounded static request scenario"
        in source
    )


def test_runtime_verifier_is_small_adaptive_surface() -> None:
    source = Path(
        "src/sophyane/adaptive_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        'elif deterministic_verification_stage == '
        '"full_stack_fabric":'
    )

    assert marker in source

    start = source.index(
        marker
    )

    window = source[
        start:
        start + 2400
    ]

    assert (
        "verify_full_stack_application("
        in window
    )

    assert (
        "discover_service_manifest("
        not in window
    )

    assert (
        "ServiceSupervisor("
        not in window
    )
