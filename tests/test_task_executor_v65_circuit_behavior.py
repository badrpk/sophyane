from __future__ import annotations

import importlib.util
from pathlib import Path

from sophyane.task_compiler import (
    compile_task,
)

from sophyane.task_executor import (
    execute_compiled_task,
)


PROMPT = (
    "Integrate a circuit breaker around the primary payment gateway "
    "HTTP client. Open after 5 consecutive 5xx errors or timeouts "
    "within a 30s window and fall back to the secondary processor."
)


SUPPORTED = r'''
from __future__ import annotations


class Response:
    def __init__(
        self,
        status_code: int,
        processor: str,
    ):
        self.status_code = status_code
        self.processor = processor


class PrimaryGateway:
    def __init__(self):
        self.responses = []
        self.calls = 0

    def post(
        self,
        request,
    ):
        self.calls += 1

        if not self.responses:
            return Response(
                200,
                "primary",
            )

        result = self.responses.pop(
            0
        )

        if result == "timeout":
            raise TimeoutError(
                "primary timeout"
            )

        return Response(
            int(result),
            "primary",
        )


class SecondaryProcessor:
    def __init__(self):
        self.calls = 0

    def post(
        self,
        request,
    ):
        self.calls += 1

        return Response(
            200,
            "secondary",
        )


primary_gateway = PrimaryGateway()
secondary_processor = SecondaryProcessor()


def process_payment(
    request,
):
    try:
        return primary_gateway.post(
            request
        )
    except TimeoutError:
        return secondary_processor.post(
            request
        )
'''.lstrip()


def _write_supported(
    root: Path,
) -> Path:
    app = (
        root
        / "app"
    )

    app.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        app
        / "payments.py"
    )

    path.write_text(
        SUPPORTED,
        encoding="utf-8",
    )

    return path


def _compile(
    root: Path,
):
    compiled = compile_task(
        PROMPT,
        workspace=root,
    )

    assert compiled.handled
    assert compiled.ok
    assert compiled.unresolved == []

    assert len(
        compiled.execution_plan
    ) == 1

    assert (
        compiled.execution_plan[0][
            "contract"
        ]
        == "circuit_breaker"
    )

    return compiled


def _install(
    root: Path,
):
    compiled = _compile(
        root
    )

    result = execute_compiled_task(
        compiled,
        workspace=root,
    )

    assert result.ok
    assert result.steps

    return result


def _load(
    path: Path,
):
    spec = (
        importlib.util
        .spec_from_file_location(
            "v65_payment_fixture",
            path,
        )
    )

    assert spec is not None
    assert spec.loader is not None

    module = (
        importlib.util
        .module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def test_v65_executor_installs_requested_contract(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    before = path.read_bytes()

    result = _install(
        tmp_path
    )

    after = path.read_bytes()

    assert result.steps[0].mutated
    assert before != after

    lower = after.decode(
        "utf-8"
    ).lower()

    # Durable source-shape proof only.
    #
    # HTTP-5xx qualification is proven behaviorally below;
    # do not depend on one literal textual spelling.
    for token in (
        "5",
        "30",
        "timeout",
        "open",
        "secondary",
    ):
        assert token in lower

    assert (
        "execute_payment_with_circuit_breaker"
        in lower
    )


def test_v65_four_5xx_failures_do_not_open_breaker(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    _install(
        tmp_path
    )

    module = _load(
        path
    )

    primary = module.PrimaryGateway()
    secondary = module.SecondaryProcessor()

    primary.responses = [
        500,
        501,
        502,
        503,
    ]

    for _ in range(
        4
    ):
        response = (
            module
            .execute_payment_with_circuit_breaker(
                primary.post,
                secondary.post,
                object(),
            )
        )

        assert (
            500
            <= response.status_code
            <= 599
        )

        assert secondary.calls == 0


def test_v65_fifth_5xx_opens_and_falls_back(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    _install(
        tmp_path
    )

    module = _load(
        path
    )

    primary = module.PrimaryGateway()
    secondary = module.SecondaryProcessor()

    primary.responses = [
        500,
        500,
        500,
        500,
        500,
    ]

    for _ in range(
        4
    ):
        response = (
            module
            .execute_payment_with_circuit_breaker(
                primary.post,
                secondary.post,
                object(),
            )
        )

        assert response.status_code >= 500
        assert secondary.calls == 0

    response = (
        module
        .execute_payment_with_circuit_breaker(
            primary.post,
            secondary.post,
            object(),
        )
    )

    assert response.status_code == 200
    assert secondary.calls == 1

    # OPEN means primary is bypassed.
    primary.responses = [
        200
    ]

    response = (
        module
        .execute_payment_with_circuit_breaker(
            primary.post,
            secondary.post,
            object(),
        )
    )

    assert response.status_code == 200
    assert secondary.calls == 2

    # The queued primary success was never consumed.
    assert primary.responses == [
        200
    ]


def test_v65_timeout_is_a_qualifying_failure(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    _install(
        tmp_path
    )

    module = _load(
        path
    )

    primary = module.PrimaryGateway()
    secondary = module.SecondaryProcessor()

    primary.responses = [
        "timeout",
        "timeout",
        "timeout",
        "timeout",
        "timeout",
    ]

    for _ in range(
        4
    ):
        try:
            (
                module
                .execute_payment_with_circuit_breaker(
                    primary.post,
                    secondary.post,
                    object(),
                )
            )
        except TimeoutError:
            pass
        else:
            raise AssertionError(
                "breaker must not fallback "
                "before threshold"
            )

        assert secondary.calls == 0

    response = (
        module
        .execute_payment_with_circuit_breaker(
            primary.post,
            secondary.post,
            object(),
        )
    )

    assert response.status_code == 200
    assert secondary.calls == 1


def test_v65_success_resets_consecutive_failure_state(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    _install(
        tmp_path
    )

    module = _load(
        path
    )

    primary = module.PrimaryGateway()
    secondary = module.SecondaryProcessor()

    primary.responses = [
        500,
        500,
        200,
        500,
        500,
        500,
        500,
    ]

    for _ in range(
        7
    ):
        (
            module
            .execute_payment_with_circuit_breaker(
                primary.post,
                secondary.post,
                object(),
            )
        )

    # Only four consecutive failures occurred after
    # the success, so the breaker remains CLOSED.
    assert secondary.calls == 0


def test_v65_failures_outside_30_second_window_are_pruned(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    _install(
        tmp_path
    )

    module = _load(
        path
    )

    breaker = (
        module
        .PaymentCircuitBreaker(
            threshold=5,
            window_seconds=30.0,
        )
    )

    breaker.record_failure(
        now=0.0
    )
    breaker.record_failure(
        now=1.0
    )
    breaker.record_failure(
        now=2.0
    )
    breaker.record_failure(
        now=3.0
    )

    assert not breaker.is_open(
        now=3.0
    )

    # Failures before t=4 are older than the
    # 30-second window at t=34.
    breaker.record_failure(
        now=34.0
    )

    assert not breaker.is_open(
        now=34.0
    )


def test_v65_second_sophyane_execution_is_zero_byte(
    tmp_path: Path,
):
    path = _write_supported(
        tmp_path
    )

    first = _install(
        tmp_path
    )

    assert first.steps[0].mutated

    before = path.read_bytes()

    second = _install(
        tmp_path
    )

    after = path.read_bytes()

    assert second.ok
    assert second.steps
    assert not second.steps[0].mutated

    assert before == after


def test_v65_unsupported_payment_shape_fails_closed(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "payments.py"
    )

    path.write_text(
        """
def charge(request):
    return request
""".lstrip(),
        encoding="utf-8",
    )

    before = path.read_bytes()

    compiled = compile_task(
        PROMPT,
        workspace=tmp_path,
    )

    assert compiled.handled
    assert not compiled.ok
    assert compiled.unresolved
    assert compiled.execution_plan == []

    assert path.read_bytes() == before
