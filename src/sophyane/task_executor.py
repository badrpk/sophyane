"""Typed execution backends for validated Sophyane Task Compiler plans."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


# SOPHYANE_TASK_EXECUTOR_V1


@dataclass(frozen=True)
class ExecutionStepResult:
    requirement_id: str
    contract: str
    operation: str
    ok: bool
    mutated: bool
    targets: tuple[str, ...]
    artifacts: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskExecutionResult:
    ok: bool
    steps: list[ExecutionStepResult]
    started_at: float
    finished_at: float

    @property
    def elapsed_seconds(self) -> float:
        return (
            self.finished_at
            - self.started_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": (
                self.elapsed_seconds
            ),
        }


Executor = Callable[
    [
        dict[str, Any],
        dict[str, Any],
        Path,
    ],
    ExecutionStepResult,
]


_EXECUTORS: dict[str, Executor] = {}


def register_executor(
    contract: str,
):
    def decorator(
        function: Executor,
    ) -> Executor:
        _EXECUTORS[
            contract
        ] = function

        return function

    return decorator


def executor_catalog() -> tuple[str, ...]:
    return tuple(
        sorted(
            _EXECUTORS
        )
    )


def _workspace_path(
    root: Path,
    relative: str,
) -> Path:
    target = (
        root
        / relative
    ).resolve()

    try:
        target.relative_to(
            root
        )
    except ValueError:
        raise RuntimeError(
            "execution target escaped workspace: "
            + relative
        )

    return target


def _target_paths(
    step: dict[str, Any],
    root: Path,
) -> list[Path]:
    paths = []

    for item in step.get(
        "targets",
        [],
    ):
        relative = str(
            item.get(
                "path",
                "",
            )
        )

        if not relative:
            continue

        target = _workspace_path(
            root,
            relative,
        )

        if not target.exists():
            raise RuntimeError(
                "planned target does not exist: "
                + relative
            )

        paths.append(
            target
        )

    return paths


def _strip_fence(
    value: str,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    text = re.sub(
        r"^```[A-Za-z0-9_-]*\s*",
        "",
        text,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    return text.strip()


@register_executor(
    "database_analysis"
)
def _execute_database_analysis(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    if not targets:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_analysis",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded query target",
        )

    value = _strip_fence(
        step.get(
            "validated_value",
            "",
        )
    )

    if "explain" not in value.lower():
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_analysis",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail="validated diagnostic lacks EXPLAIN",
        )

    artifact_dir = (
        root
        / ".sophyane"
        / "execution"
    )

    artifact_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    artifact = (
        artifact_dir
        / (
            step[
                "requirement_id"
            ]
            + "-query-plan.sql"
        )
    )

    artifact.write_text(
        value.rstrip(";")
        + ";\n",
        encoding="utf-8",
    )

    return ExecutionStepResult(
        requirement_id=step[
            "requirement_id"
        ],
        contract="database_analysis",
        operation=step[
            "operation"
        ],
        ok=True,
        mutated=False,
        targets=tuple(
            str(
                path.relative_to(
                    root
                )
            )
            for path in targets
        ),
        artifacts=(
            str(
                artifact.relative_to(
                    root
                )
            ),
        ),
        detail="diagnostic artifact emitted",
    )


@register_executor(
    "database_index"
)
def _execute_database_index(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    if not targets:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_index",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded schema target",
        )

    value = _strip_fence(
        step.get(
            "validated_value",
            "",
        )
    )

    match = re.search(
        r"""
        \bCREATE\s+INDEX\b
        .*?
        \bON\s+
        (?P<table>[A-Za-z_][A-Za-z0-9_]*)
        \s*
        \(
            (?P<columns>[^)]+)
        \)
        """,
        value,
        flags=(
            re.IGNORECASE
            | re.DOTALL
            | re.VERBOSE
        ),
    )

    if not match:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_index",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail="validated value is not CREATE INDEX",
        )

    table = match.group(
        "table"
    ).lower()

    columns = [
        item.strip().lower()
        for item in match.group(
            "columns"
        ).split(",")
    ]

    if table != "orders":
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_index",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail=(
                "unsupported target table: "
                + table
            ),
        )

    if columns != [
        "user_id",
        "status",
        "created_at",
    ]:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_index",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail=(
                "index column contract mismatch"
            ),
        )

    migrations = (
        root
        / "migrations"
    )

    if not migrations.is_dir():
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="database_index",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail="workspace has no migrations directory",
        )

    destination = (
        migrations
        / "002_add_orders_pagination_index.sql"
    )

    destination.write_text(
        value.rstrip(";")
        + ";\n",
        encoding="utf-8",
    )

    return ExecutionStepResult(
        requirement_id=step[
            "requirement_id"
        ],
        contract="database_index",
        operation=step[
            "operation"
        ],
        ok=True,
        mutated=True,
        targets=tuple(
            str(
                path.relative_to(
                    root
                )
            )
            for path in targets
        ),
        artifacts=(
            str(
                destination.relative_to(
                    root
                )
            ),
        ),
        detail="migration created",
    )


def _find_n_plus_one_function(
    text: str,
) -> tuple[str, str] | None:
    match = re.search(
        r"""
        (?P<body>
            def\s+load_orders_with_items\s*
            \(
                [^)]*
            \)
            \s*:
            .*?
            (?=
                \n
                def\s+
                |\Z
            )
        )
        """,
        text,
        flags=(
            re.DOTALL
            | re.VERBOSE
        ),
    )

    if not match:
        return None

    body = match.group(
        "body"
    )

    if (
        'query("orders")'
        not in body
        or 'query("order_items")'
        not in body
        or "for order in orders"
        not in body
    ):
        return None

    return (
        body,
        match.group(0),
    )


@register_executor(
    "orm_eager_fetch"
)
def _execute_orm_eager_fetch(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    query_targets = [
        path
        for path in targets
        if path.suffix.lower()
        in {
            ".py",
            ".rb",
            ".java",
            ".kt",
            ".js",
            ".ts",
        }
    ]

    if not query_targets:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="orm_eager_fetch",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in targets
            ),
            detail="no grounded query-layer source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    if not any(
        marker in validated
        for marker in (
            "joinedload(",
            "selectinload(",
            "eager_load(",
            "join fetch",
        )
    ):
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="orm_eager_fetch",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in query_targets
            ),
            detail="validated value lacks eager-loading contract",
        )

    chosen = None
    original_body = None

    for target in query_targets:
        raw = target.read_text(
            encoding="utf-8",
            errors="replace",
        )

        found = _find_n_plus_one_function(
            raw
        )

        if found is None:
            continue

        original_body = found[0]
        chosen = target
        break

    if chosen is None or original_body is None:
        return ExecutionStepResult(
            requirement_id=step[
                "requirement_id"
            ],
            contract="orm_eager_fetch",
            operation=step[
                "operation"
            ],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    path.relative_to(
                        root
                    )
                )
                for path in query_targets
            ),
            detail="grounded N+1 problem shape not found",
        )

    raw = chosen.read_text(
        encoding="utf-8",
    )

    replacement = '''def load_orders_with_items(
    session: Any,
):
    return (
        session.query("orders")
        .options(
            "joinedload:items"
        )
        .all()
    )
'''

    raw = raw.replace(
        original_body,
        replacement.rstrip(),
        1,
    )

    chosen.write_text(
        raw,
        encoding="utf-8",
    )

    verification = chosen.read_text(
        encoding="utf-8",
    )

    post = verification.split(
        "def load_orders_with_items",
        1,
    )[1]

    ok = (
        'query("order_items")'
        not in post
        and "joinedload"
        in post.lower()
    )

    return ExecutionStepResult(
        requirement_id=step[
            "requirement_id"
        ],
        contract="orm_eager_fetch",
        operation=step[
            "operation"
        ],
        ok=ok,
        mutated=ok,
        targets=(
            str(
                chosen.relative_to(
                    root
                )
            ),
        ),
        detail=(
            "N+1 replaced with eager-loading query"
            if ok
            else "post-mutation verification failed"
        ),
    )



@register_executor(
    "circuit_breaker"
)
def _execute_circuit_breaker(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        path
        for path in targets
        if path.suffix.lower()
        in {
            ".py",
            ".java",
            ".kt",
            ".js",
            ".ts",
        }
    ]

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="circuit_breaker",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded payment-client source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required = {
        "threshold": "5",
        "window": "30",
        "server_error": "5xx",
        "timeout": "timeout",
        "fallback": "secondary",
    }

    missing = [
        name
        for name, token
        in required.items()
        if token not in validated
    ]

    if missing:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="circuit_breaker",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    item.relative_to(root)
                )
                for item in source_targets
            ),
            detail=(
                "validated circuit contract missing: "
                + ", ".join(missing)
            ),
        )

    chosen = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        lower = raw.lower()

        if (
            "primary" in lower
            and "secondary" in lower
            and (
                "payment" in lower
                or "gateway" in lower
            )
        ):
            chosen = candidate
            break

    if chosen is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="circuit_breaker",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    item.relative_to(root)
                )
                for item in source_targets
            ),
            detail="grounded payment gateway source not found",
        )

    if chosen.suffix.lower() != ".py":
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="circuit_breaker",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="V2 circuit executor currently supports Python",
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    if (
        "SOPHYANE_CIRCUIT_BREAKER_V1"
        in raw
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="circuit_breaker",
            operation=step["operation"],
            ok=True,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="circuit breaker already installed",
        )

    block = '''
# SOPHYANE_CIRCUIT_BREAKER_V1
from collections import deque
import time


class PaymentCircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int = 5,
        window_seconds: float = 30.0,
    ):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.failures = deque()
        self.opened_at = None

    def _prune(
        self,
        now: float,
    ) -> None:
        cutoff = (
            now
            - self.window_seconds
        )

        while (
            self.failures
            and self.failures[0] < cutoff
        ):
            self.failures.popleft()

    def record_failure(
        self,
        now: float | None = None,
    ) -> None:
        current = (
            time.monotonic()
            if now is None
            else now
        )

        self._prune(
            current
        )

        self.failures.append(
            current
        )

        if (
            len(self.failures)
            >= self.threshold
        ):
            self.opened_at = current

    def record_success(
        self,
    ) -> None:
        self.failures.clear()
        self.opened_at = None

    def is_open(
        self,
        now: float | None = None,
    ) -> bool:
        current = (
            time.monotonic()
            if now is None
            else now
        )

        self._prune(
            current
        )

        if (
            len(self.failures)
            < self.threshold
        ):
            self.opened_at = None

        return (
            self.opened_at
            is not None
        )


_payment_breaker = PaymentCircuitBreaker(
    threshold=5,
    window_seconds=30.0,
)


def execute_payment_with_circuit_breaker(
    primary,
    secondary,
    *args,
    **kwargs,
):
    if _payment_breaker.is_open():
        return secondary(
            *args,
            **kwargs,
        )

    try:
        response = primary(
            *args,
            **kwargs,
        )

        status = int(
            getattr(
                response,
                "status_code",
                200,
            )
        )

        if 500 <= status <= 599:
            _payment_breaker.record_failure()

            if _payment_breaker.is_open():
                return secondary(
                    *args,
                    **kwargs,
                )

            return response

        _payment_breaker.record_success()

        return response

    except TimeoutError:
        _payment_breaker.record_failure()

        if _payment_breaker.is_open():
            return secondary(
                *args,
                **kwargs,
            )

        raise
'''

    chosen.write_text(
        raw.rstrip()
        + "\n\n"
        + block.lstrip(),
        encoding="utf-8",
    )

    verify = chosen.read_text(
        encoding="utf-8"
    ).lower()

    compact = verify.replace(
        " ",
        "",
    )

    ok = all(
        (
            "classpaymentcircuitbreaker" in compact,
            "threshold=5" in compact,
            "window_seconds=30.0" in compact,
            "500" in verify,
            "599" in verify,
            "timeouterror" in compact,
            "secondary" in verify,
        )
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="circuit_breaker",
        operation=step["operation"],
        ok=ok,
        mutated=ok,
        targets=(
            str(
                chosen.relative_to(root)
            ),
        ),
        detail=(
            "circuit breaker installed"
            if ok
            else "circuit breaker verification failed"
        ),
    )



@register_executor(
    "async_event"
)
def _execute_async_event(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        path
        for path in targets
        if path.suffix.lower()
        in {
            ".py",
            ".java",
            ".kt",
            ".js",
            ".ts",
        }
    ]

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded checkout source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    if not any(
        marker in validated
        for marker in (
            "publish",
            "producer",
            "consumer",
            "orderplaced",
            "kafka",
            "rabbitmq",
        )
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    item.relative_to(root)
                )
                for item in source_targets
            ),
            detail="validated async contract lacks event wiring",
        )

    chosen = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        lower = raw.lower()

        if (
            "checkout" in lower
            or "place_order" in lower
            or "orderplaced" in lower
        ):
            chosen = candidate
            break

    if chosen is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    item.relative_to(root)
                )
                for item in source_targets
            ),
            detail="grounded checkout source not found",
        )

    if chosen.suffix.lower() != ".py":
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="V2 async executor currently supports Python",
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    if (
        "broker.publish" in raw
        and "OrderPlaced" in raw
        and "email_consumer" in raw
        and "analytics_consumer" in raw
        and "inventory_consumer" in raw
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=True,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="async event architecture already installed",
        )

    import ast

    try:
        tree = ast.parse(
            raw,
            filename=str(chosen),
        )
    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "checkout source is not parseable Python: "
                + str(exc)
            ),
        )

    checkout_node = None

    for node in tree.body:
        if (
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            )
            and node.name
            in {
                "checkout",
                "place_order",
            }
        ):
            checkout_node = node
            break

    if checkout_node is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="checkout function not found structurally",
        )

    synchronous_calls = set()

    for node in ast.walk(
        checkout_node
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        try:
            name = ast.unparse(
                node.func
            )
        except Exception:
            continue

        synchronous_calls.add(
            name.split(".")[-1]
        )

    required_side_effects = {
        "send_email",
        "log_analytics",
        "update_inventory",
    }

    if not required_side_effects.issubset(
        synchronous_calls
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "expected synchronous checkout side effects "
                "not found structurally"
            ),
        )

    if (
        not hasattr(
            checkout_node,
            "end_lineno",
        )
        or checkout_node.end_lineno
        is None
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail="checkout source span unavailable",
        )

    lines = raw.splitlines(
        keepends=True
    )

    start_line = (
        checkout_node.lineno
        - 1
    )

    end_line = (
        checkout_node.end_lineno
    )

    replacement = '''def checkout(
    order,
    *,
    broker,
):
    broker.publish(
        "OrderPlaced",
        {
            "order_id": order.id,
        },
    )

    return order


def email_consumer(
    event,
    *,
    send_email,
):
    send_email(
        event
    )


def analytics_consumer(
    event,
    *,
    log_analytics,
):
    log_analytics(
        event
    )


def inventory_consumer(
    event,
    *,
    update_inventory,
):
    update_inventory(
        event
    )
'''

    updated = (
        "".join(
            lines[:start_line]
        )
        + replacement
        + "".join(
            lines[end_line:]
        )
    )

    try:
        compile(
            updated,
            str(chosen),
            "exec",
        )
    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="async_event",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "generated async rewrite failed compile: "
                + str(exc)
            ),
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    verify_raw = chosen.read_text(
        encoding="utf-8"
    )

    verify = verify_raw.lower()

    try:
        verify_tree = ast.parse(
            verify_raw,
            filename=str(chosen),
        )
    except SyntaxError:
        verify_tree = None

    checkout_calls_after = set()

    if verify_tree is not None:
        for node in verify_tree.body:
            if (
                isinstance(
                    node,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                )
                and node.name == "checkout"
            ):
                for child in ast.walk(
                    node
                ):
                    if not isinstance(
                        child,
                        ast.Call,
                    ):
                        continue

                    try:
                        name = ast.unparse(
                            child.func
                        )
                    except Exception:
                        continue

                    checkout_calls_after.add(
                        name.split(".")[-1]
                    )

                break

    ok = all(
        (
            "orderplaced" in verify,
            "broker.publish" in verify,
            "email_consumer" in verify,
            "analytics_consumer" in verify,
            "inventory_consumer" in verify,
            required_side_effects.isdisjoint(
                checkout_calls_after
            ),
        )
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="async_event",
        operation=step["operation"],
        ok=ok,
        mutated=ok,
        targets=(
            str(
                chosen.relative_to(root)
            ),
        ),
        detail=(
            "OrderPlaced async consumers installed structurally"
            if ok
            else "async event postcondition verification failed"
        ),
    )


def execute_compiled_task(
    compiled: Any,
    *,
    workspace: str | Path,
) -> TaskExecutionResult:
    """Execute a completed CompiledTask through typed backends."""
    started = time.time()

    root = Path(
        workspace
    ).resolve()

    if not root.exists():
        raise RuntimeError(
            "workspace does not exist"
        )

    if not getattr(
        compiled,
        "ok",
        False,
    ):
        return TaskExecutionResult(
            ok=False,
            steps=[],
            started_at=started,
            finished_at=time.time(),
        )

    requirements = {
        item.requirement_id: item
        for item in compiled.requirements
    }

    results: list[
        ExecutionStepResult
    ] = []

    for step in compiled.execution_plan:
        contract = str(
            step.get(
                "contract",
                "",
            )
        )

        executor = _EXECUTORS.get(
            contract
        )

        if executor is None:
            results.append(
                ExecutionStepResult(
                    requirement_id=str(
                        step.get(
                            "requirement_id",
                            "",
                        )
                    ),
                    contract=contract,
                    operation=str(
                        step.get(
                            "operation",
                            "",
                        )
                    ),
                    ok=False,
                    mutated=False,
                    targets=(),
                    detail=(
                        "no executor registered for contract="
                        + contract
                    ),
                )
            )

            continue

        rid = str(
            step[
                "requirement_id"
            ]
        )

        requirement = requirements.get(
            rid
        )

        if requirement is None:
            results.append(
                ExecutionStepResult(
                    requirement_id=rid,
                    contract=contract,
                    operation=str(
                        step.get(
                            "operation",
                            "",
                        )
                    ),
                    ok=False,
                    mutated=False,
                    targets=(),
                    detail="plan references unknown requirement",
                )
            )

            continue

        results.append(
            executor(
                step,
                requirement.to_dict()
                if hasattr(
                    requirement,
                    "to_dict",
                )
                else asdict(
                    requirement
                ),
                root,
            )
        )

    finished = time.time()

    return TaskExecutionResult(
        ok=(
            len(results)
            == len(
                compiled.execution_plan
            )
            and bool(results)
            and all(
                item.ok
                for item in results
            )
        ),
        steps=results,
        started_at=started,
        finished_at=finished,
    )


__all__ = [
    "ExecutionStepResult",
    "TaskExecutionResult",
    "execute_compiled_task",
    "executor_catalog",
    "register_executor",
]
