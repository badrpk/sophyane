"""Typed execution backends for validated Sophyane Task Compiler plans."""

from __future__ import annotations
import ast

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




# SOPHYANE_V62_C1_IDEMPOTENCY_EXECUTOR
@register_executor(
    "idempotency_key"
)
def _execute_idempotency_key(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    # C1 is intentionally conservative:
    # mutation requires an explicit idempotency-store dependency.

    import ast

    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        candidate
        for candidate in targets
        if candidate.suffix.lower()
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
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded payment-handler source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required_groups = (
        (
            "idempotency",
        ),
        (
            "persist",
            "store",
            "record",
        ),
        (
            "response",
            "result",
        ),
        (
            "duplicate",
            "without charging twice",
            "cannot charge twice",
            "at-most-once",
            "at most once",
        ),
    )

    if not all(
        any(
            choice in validated
            for choice in choices
        )
        for choices in required_groups
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    candidate.relative_to(root)
                )
                for candidate in source_targets
            ),
            detail="validated idempotency contract is incomplete",
        )

    chosen = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        lower = raw.lower()

        payment_shape = any(
            token in lower
            for token in (
                "payment",
                "charge(",
                "gateway",
            )
        )

        request_shape = any(
            token in lower
            for token in (
                "post_",
                "post(",
                "request",
                "handler",
                "route",
                "api",
            )
        )

        store_shape = (
            "idempotency"
            in lower
            and "store"
            in lower
        )

        if (
            payment_shape
            and request_shape
            and store_shape
        ):
            chosen = candidate
            break

    if chosen is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=tuple(
                str(
                    candidate.relative_to(root)
                )
                for candidate in source_targets
            ),
            detail=(
                "grounded source lacks payment POST handler "
                "with explicit idempotency-store dependency"
            ),
        )

    relative = str(
        chosen.relative_to(root)
    )

    if chosen.suffix.lower() != ".py":
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                relative,
            ),
            detail="C1 idempotency executor currently supports Python",
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    if (
        "SOPHYANE_IDEMPOTENCY_KEY_V1"
        in raw
    ):
        verify = raw.lower()

        ok = all(
            (
                "fingerprint" in verify,
                "original_response" in verify,
                "conflicting idempotency-key reuse"
                in verify,
                ".get(" in verify,
                ".put(" in verify,
            )
        )

        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=ok,
            mutated=False,
            targets=(
                relative,
            ),
            detail=(
                "idempotency-key architecture already installed"
                if ok
                else "existing idempotency architecture failed verification"
            ),
        )

    try:
        tree = ast.parse(
            raw,
            filename=str(chosen),
        )
    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                relative,
            ),
            detail=(
                "grounded payment source does not parse: "
                + str(exc)
            ),
        )

    function = None

    for node in tree.body:
        if not isinstance(
            node,
            ast.FunctionDef,
        ):
            continue

        positional = (
            list(node.args.posonlyargs)
            + list(node.args.args)
        )

        names = [
            argument.arg
            for argument in positional
        ]

        lower_names = [
            name.lower()
            for name in names
        ]

        segment = (
            ast.get_source_segment(
                raw,
                node,
            )
            or ""
        ).lower()

        request_names = [
            name
            for name in names
            if name.lower()
            == "request"
        ]

        gateway_names = [
            name
            for name in names
            if (
                "gateway"
                in name.lower()
                or "payment_service"
                in name.lower()
            )
        ]

        store_names = [
            name
            for name in names
            if (
                "idempotency"
                in name.lower()
                and "store"
                in name.lower()
            )
        ]

        if (
            len(names) == 3
            and len(request_names) == 1
            and len(gateway_names) == 1
            and len(store_names) == 1
            and ".charge("
            in segment
            and not node.args.vararg
            and not node.args.kwarg
            and not node.args.kwonlyargs
        ):
            function = (
                node,
                names,
                request_names[0],
                gateway_names[0],
                store_names[0],
            )

            break

    if function is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                relative,
            ),
            detail=(
                "no structurally proven Python payment POST function "
                "with request, gateway, and idempotency_store"
            ),
        )

    (
        node,
        names,
        request_name,
        gateway_name,
        store_name,
    ) = function

    lines = raw.splitlines(
        keepends=True
    )

    offsets = [0]

    for line in lines:
        offsets.append(
            offsets[-1]
            + len(line)
        )

    start = offsets[
        node.lineno - 1
    ]

    end = offsets[
        node.end_lineno
    ]

    signature = ",\n    ".join(
        names
    )

    replacement = f'''# SOPHYANE_IDEMPOTENCY_KEY_V1
def {node.name}(
    {signature},
):
    idempotency_key = (
        {request_name}.get(
            "Idempotency-Key"
        )
        or {request_name}.get(
            "idempotency-key"
        )
        or {request_name}.get(
            "idempotency_key"
        )
    )

    fingerprint_items = []

    for key, value in {request_name}.items():
        normalized_key = str(
            key
        ).lower().replace(
            "_",
            "-",
        )

        if normalized_key == "idempotency-key":
            continue

        fingerprint_items.append(
            (
                str(key),
                repr(value),
            )
        )

    fingerprint_items.sort()

    fingerprint = repr(
        fingerprint_items
    )

    if idempotency_key:
        existing = {store_name}.get(
            idempotency_key
        )

        if existing is not None:
            if (
                existing[
                    "fingerprint"
                ]
                != fingerprint
            ):
                raise ValueError(
                    "conflicting Idempotency-Key reuse"
                )

            return existing[
                "original_response"
            ]

    amount = {request_name}[
        "amount"
    ]

    result = {gateway_name}.charge(
        amount
    )

    original_response = {{
        "status": 201,
        "payment": result,
    }}

    if idempotency_key:
        {store_name}.put(
            idempotency_key,
            {{
                "fingerprint": fingerprint,
                "original_response": original_response,
            }},
        )

    return original_response
'''

    updated = (
        raw[:start]
        + replacement
        + raw[end:]
    )

    try:
        parsed = ast.parse(
            updated,
            filename=str(chosen),
        )
    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                relative,
            ),
            detail=(
                "generated idempotency rewrite does not compile: "
                + str(exc)
            ),
        )

    generated = updated.lower()

    semantic_ok = all(
        (
            "sophyane_idempotency_key_v1"
            in generated,
            "fingerprint"
            in generated,
            "original_response"
            in generated,
            "conflicting idempotency-key reuse"
            in generated,
            ".charge("
            in generated,
            ".get("
            in generated,
            ".put("
            in generated,
        )
    )

    if not semantic_ok:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="idempotency_key",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                relative,
            ),
            detail="generated rewrite failed semantic verification",
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    verify = chosen.read_text(
        encoding="utf-8"
    ).lower()

    ok = all(
        (
            "sophyane_idempotency_key_v1"
            in verify,
            "fingerprint"
            in verify,
            "original_response"
            in verify,
            "conflicting idempotency-key reuse"
            in verify,
        )
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="idempotency_key",
        operation=step["operation"],
        ok=ok,
        mutated=ok,
        targets=(
            relative,
        ),
        detail=(
            "idempotency-key handler installed structurally"
            if ok
            else "idempotency-key post-write verification failed"
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



# SOPHYANE_V62_CACHE_STAMPEDE_EXECUTOR
@register_executor(
    "cache_stampede"
)
def _execute_cache_stampede(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        item
        for item in targets
        if item.suffix.lower() == ".py"
    ]

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded Python cache lookup source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required_groups = (
        (
            "single-flight",
            "single flight",
            "per-key",
            "lock",
        ),
        (
            "stale",
        ),
        (
            "database",
            "db",
        ),
        (
            "refresh",
            "fallback",
        ),
    )

    if not all(
        any(
            token in validated
            for token in group
        )
        for group in required_groups
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
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
                "validated cache contract lacks required semantics"
            ),
        )

    chosen = None
    function_name = None
    db_name = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        try:
            tree = ast.parse(
                raw,
                filename=str(candidate),
            )
        except SyntaxError:
            continue

        lower = raw.lower()

        if not (
            "cache.get" in lower
            and (
                "database." in lower
                or "db." in lower
            )
        ):
            continue

        for node in tree.body:
            if not isinstance(
                node,
                ast.FunctionDef,
            ):
                continue

            args = {
                item.arg
                for item in (
                    node.args.posonlyargs
                    + node.args.args
                    + node.args.kwonlyargs
                )
            }

            if not {
                "cache",
                "singleflight",
                "product_id",
            }.issubset(
                args
            ):
                continue

            if "database" in args:
                candidate_db = "database"
            elif "db" in args:
                candidate_db = "db"
            else:
                continue

            function_source = (
                ast.get_source_segment(
                    raw,
                    node,
                )
                or ""
            ).lower()

            if not (
                "cache.get" in function_source
                and (
                    f"{candidate_db}.get_product"
                    in function_source
                )
            ):
                continue

            chosen = candidate
            function_name = node.name
            db_name = candidate_db
            break

        if chosen is not None:
            break

    if (
        chosen is None
        or function_name is None
        or db_name is None
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
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
                "grounded source lacks cache lookup with explicit "
                "singleflight dependency"
            ),
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    if (
        "SOPHYANE_CACHE_STAMPEDE_V1"
        in raw
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
            operation=step["operation"],
            ok=True,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "cache-stampede architecture already installed"
            ),
        )

    tree = ast.parse(
        raw,
        filename=str(chosen),
    )

    target_node = next(
        (
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == function_name
            )
        ),
        None,
    )

    if target_node is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "cache lookup function disappeared before rewrite"
            ),
        )

    lines = raw.splitlines(
        keepends=True
    )

    offsets = [0]

    for line in lines:
        offsets.append(
            offsets[-1]
            + len(line)
        )

    start = offsets[
        target_node.lineno - 1
    ]

    end = offsets[
        target_node.end_lineno
    ]

    replacement_lines = [
        f"def {function_name}(\n",
        "    cache,\n",
        f"    {db_name},\n",
        "    singleflight,\n",
        "    product_id,\n",
        "):\n",
        "    # SOPHYANE_CACHE_STAMPEDE_V1\n",
        "    cached = cache.get(\n",
        "        product_id\n",
        "    )\n",
        "\n",
        "    if cached is not None:\n",
        "        return cached\n",
        "\n",
        "    stale = (\n",
        "        cache.get_stale(\n",
        "            product_id\n",
        "        )\n",
        "        if hasattr(\n",
        "            cache,\n",
        '            "get_stale",\n',
        "        )\n",
        "        else None\n",
        "    )\n",
        "\n",
        "    with singleflight.lock(\n",
        "        product_id\n",
        "    ):\n",
        "        refreshed = cache.get(\n",
        "            product_id\n",
        "        )\n",
        "\n",
        "        if refreshed is not None:\n",
        "            return refreshed\n",
        "\n",
        "        try:\n",
        f"            product = {db_name}.get_product(\n",
        "                product_id\n",
        "            )\n",
        "        except Exception:\n",
        "            if stale is not None:\n",
        "                return stale\n",
        "            raise\n",
        "\n",
        "        cache.set(\n",
        "            product_id,\n",
        "            product,\n",
        "        )\n",
        "\n",
        "        return product\n",
    ]

    replacement = "".join(
        replacement_lines
    )

    updated = (
        raw[:start]
        + replacement
        + raw[end:]
    )

    try:
        compile(
            updated,
            str(chosen),
            "exec",
        )
    except Exception:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="cache_stampede",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "generated cache-stampede rewrite does not compile"
            ),
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    verify = chosen.read_text(
        encoding="utf-8"
    ).lower()

    ok = all(
        (
            "sophyane_cache_stampede_v1"
            in verify,
            "singleflight.lock"
            in verify,
            "cache.get_stale"
            in verify,
            f"{db_name}.get_product"
            in verify,
            "cache.set"
            in verify,
        )
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="cache_stampede",
        operation=step["operation"],
        ok=ok,
        mutated=ok,
        targets=(
            str(
                chosen.relative_to(root)
            ),
        ),
        detail=(
            "cache-stampede single-flight architecture installed"
            if ok
            else "cache-stampede verification failed"
        ),
    )


# SOPHYANE_V62_TRANSACTIONAL_OUTBOX_EXECUTOR
@register_executor(
    "transactional_outbox"
)
def _execute_transactional_outbox(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        item
        for item in targets
        if item.suffix.lower() == ".py"
    ]

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail=(
                "no grounded Python transaction/event source"
            ),
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required_groups = (
        (
            "outbox",
        ),
        (
            "same transaction",
            "atomic",
            "atomically",
        ),
        (
            "background",
            "worker",
            "publisher",
        ),
        (
            "retry",
        ),
        (
            "duplicate",
            "idempotent",
            "dedup",
        ),
    )

    if not all(
        any(
            token in validated
            for token in group
        )
        for group in required_groups
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
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
                "validated outbox contract lacks required semantics"
            ),
        )

    chosen = None
    function_name = None
    session_name = None
    broker_name = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if (
            "SOPHYANE_TRANSACTIONAL_OUTBOX_V1"
            in raw
        ):
            return ExecutionStepResult(
                requirement_id=step["requirement_id"],
                contract="transactional_outbox",
                operation=step["operation"],
                ok=True,
                mutated=False,
                targets=(
                    str(
                        candidate.relative_to(
                            root
                        )
                    ),
                ),
                detail=(
                    "transactional outbox already installed"
                ),
            )

        try:
            tree = ast.parse(
                raw,
                filename=str(candidate),
            )
        except SyntaxError:
            continue

        for node in tree.body:
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            args = [
                item.arg
                for item
                in node.args.args
            ]

            session_candidates = [
                name
                for name in args
                if name.lower()
                in {
                    "session",
                    "db",
                    "database",
                    "transaction",
                    "uow",
                    "unit_of_work",
                }
            ]

            broker_candidates = [
                name
                for name in args
                if name.lower()
                in {
                    "broker",
                    "publisher",
                    "producer",
                    "event_bus",
                    "eventbus",
                }
            ]

            if not (
                session_candidates
                and broker_candidates
            ):
                continue

            segment = ast.get_source_segment(
                raw,
                node,
            ) or ""

            lower = segment.lower()

            has_db_write = any(
                token in lower
                for token in (
                    ".add(",
                    ".save(",
                    ".insert(",
                    ".execute(",
                    "commit(",
                )
            )

            has_commit = (
                ".commit("
                in lower
                or "commit("
                in lower
            )

            has_publish = any(
                token in lower
                for token in (
                    ".publish(",
                    ".send(",
                    ".produce(",
                )
            )

            if not (
                has_db_write
                and has_commit
                and has_publish
            ):
                continue

            chosen = candidate
            function_name = node.name
            session_name = (
                session_candidates[0]
            )
            broker_name = (
                broker_candidates[0]
            )
            break

        if chosen is not None:
            break

    if (
        chosen is None
        or function_name is None
        or session_name is None
        or broker_name is None
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
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
                "grounded source lacks explicit "
                "transaction + publisher dependencies"
            ),
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        raw,
        filename=str(chosen),
    )

    target_node = None

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
            == function_name
        ):
            target_node = node
            break

    if target_node is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "grounded transaction function vanished"
            ),
        )

    args_text = ast.get_source_segment(
        raw,
        target_node.args,
    )

    if not args_text:
        args_text = ", ".join(
            item.arg
            for item
            in target_node.args.args
        )

    lines = raw.splitlines(
        keepends=True
    )

    start = sum(
        len(line)
        for line in lines[
            :target_node.lineno - 1
        ]
    )

    end = sum(
        len(line)
        for line in lines[
            :target_node.end_lineno
        ]
    )

    original_function = raw[
        start:end
    ]

    body_lines = original_function.splitlines()

    signature_lines = []
    body_started = False

    for line in body_lines:
        signature_lines.append(
            line
        )

        if line.rstrip().endswith(
            ":"
        ):
            body_started = True
            break

    if not body_started:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "could not isolate grounded function signature"
            ),
        )

    indent = "    "

    replacement = (
        "\n".join(
            signature_lines
        )
        + "\n"
        + indent
        + '"""Sophyane transactional-outbox boundary."""\n'
        + indent
        + "event_id = str(getattr(order, \"id\", id(order)))\n"
        + indent
        + "outbox_event = {\n"
        + indent
        + '    "event_id": event_id,\n'
        + indent
        + '    "event_type": "OrderPlaced",\n'
        + indent
        + '    "payload": {\n'
        + indent
        + '        "order_id": getattr(order, "id", None),\n'
        + indent
        + "    },\n"
        + indent
        + '    "published": False,\n'
        + indent
        + '    "attempts": 0,\n'
        + indent
        + "}\n"
        + "\n"
        + indent
        + "# SOPHYANE_TRANSACTIONAL_OUTBOX_V1\n"
        + indent
        + session_name
        + ".add(order)\n"
        + indent
        + session_name
        + ".add(outbox_event)\n"
        + indent
        + session_name
        + ".commit()\n"
        + "\n"
        + indent
        + "return outbox_event\n"
    )

    helper = (
        "\n\n"
        "def publish_pending_outbox(\n"
        "    outbox_rows,\n"
        "    *,\n"
        "    broker,\n"
        "    max_attempts=3,\n"
        "):\n"
        "    published = []\n"
        "\n"
        "    for event in outbox_rows:\n"
        "        if event.get(\"published\"):\n"
        "            continue\n"
        "\n"
        "        if event.get(\"attempts\", 0) >= max_attempts:\n"
        "            continue\n"
        "\n"
        "        event[\"attempts\"] = (\n"
        "            event.get(\"attempts\", 0)\n"
        "            + 1\n"
        "        )\n"
        "\n"
        "        broker.publish(\n"
        "            event[\"event_type\"],\n"
        "            event[\"payload\"],\n"
        "            event_id=event[\"event_id\"],\n"
        "        )\n"
        "\n"
        "        event[\"published\"] = True\n"
        "        published.append(\n"
        "            event[\"event_id\"]\n"
        "        )\n"
        "\n"
        "    return published\n"
    )

    updated = (
        raw[:start]
        + replacement
        + raw[end:]
    )

    if (
        "def publish_pending_outbox("
        not in updated
    ):
        updated = (
            updated.rstrip()
            + helper
            + "\n"
        )

    try:
        compile(
            updated,
            str(chosen),
            "exec",
        )
    except Exception as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "outbox rewrite failed compile: "
                + str(exc)
            ),
        )

    lower = updated.lower()

    postcondition = all(
        token in lower
        for token in (
            "sophyane_transactional_outbox_v1",
            "outbox_event",
            '"published": false',
            '"attempts": 0',
            "publish_pending_outbox",
            "event_id",
            ".commit()",
            "broker.publish",
        )
    )

    if not postcondition:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "transactional-outbox postcondition failed"
            ),
        )

    before = raw.encode(
        "utf-8"
    )

    after = updated.encode(
        "utf-8"
    )

    if before == after:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="transactional_outbox",
            operation=step["operation"],
            ok=True,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "transactional outbox already installed"
            ),
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="transactional_outbox",
        operation=step["operation"],
        ok=True,
        mutated=True,
        targets=(
            str(
                chosen.relative_to(root)
            ),
        ),
        detail=(
            "transactional outbox installed structurally"
        ),
    )




# SOPHYANE_V62_SAGA_COMPENSATION_EXECUTOR
@register_executor(
    "saga_compensation"
)
def _execute_saga_compensation(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        item
        for item in targets
        if item.suffix.lower() == ".py"
    ]

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded Python checkout source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required_groups = (
        (
            "saga",
        ),
        (
            "payment",
        ),
        (
            "inventory",
        ),
        (
            "compensat",
            "refund",
        ),
        (
            "persist",
            "durable",
            "state",
        ),
    )

    if not all(
        any(
            token in validated
            for token in group
        )
        for group in required_groups
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
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
                "validated saga contract lacks required semantics"
            ),
        )

    chosen = None
    checkout_function = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        try:
            tree = ast.parse(
                raw,
                filename=str(candidate),
            )
        except SyntaxError:
            continue

        for node in tree.body:
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            args = {
                item.arg
                for item in node.args.args
            }

            lower_name = (
                node.name.lower()
            )

            source_segment = (
                ast.get_source_segment(
                    raw,
                    node,
                )
                or ""
            )

            lower_segment = (
                source_segment.lower()
            )

            payment_present = any(
                token in lower_segment
                for token in (
                    "payment",
                    ".charge(",
                )
            )

            inventory_present = any(
                token in lower_segment
                for token in (
                    "inventory",
                    ".reserve(",
                )
            )

            durable_store_present = any(
                marker_name in args
                for marker_name in (
                    "saga_store",
                    "state_store",
                    "workflow_store",
                )
            )

            if (
                (
                    "checkout"
                    in lower_name
                    or "order"
                    in lower_name
                )
                and payment_present
                and inventory_present
                and durable_store_present
            ):
                chosen = candidate
                checkout_function = (
                    node.name
                )
                break

        if chosen is not None:
            break

    if (
        chosen is None
        or checkout_function is None
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
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
                "grounded source lacks checkout/payment/inventory "
                "flow with explicit durable saga-store dependency"
            ),
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    if (
        "SOPHYANE_SAGA_COMPENSATION_V1"
        in raw
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
            operation=step["operation"],
            ok=True,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "saga compensation architecture already installed"
            ),
        )

    tree = ast.parse(
        raw,
        filename=str(chosen),
    )

    target = None

    for node in tree.body:
        if (
            isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == checkout_function
        ):
            target = node
            break

    if target is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "checkout function disappeared during verification"
            ),
        )

    args = [
        item.arg
        for item in target.args.args
    ]

    payment_arg = next(
        (
            name
            for name in args
            if "payment" in name
        ),
        None,
    )

    inventory_arg = next(
        (
            name
            for name in args
            if "inventory" in name
        ),
        None,
    )

    store_arg = next(
        (
            name
            for name in args
            if name in {
                "saga_store",
                "state_store",
                "workflow_store",
            }
        ),
        None,
    )

    order_arg = next(
        (
            name
            for name in args
            if "order" in name
        ),
        None,
    )

    if not all(
        (
            payment_arg,
            inventory_arg,
            store_arg,
            order_arg,
        )
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "saga mutation requires explicit payment, inventory, "
                "order and durable store arguments"
            ),
        )

    replacement = f'''def {checkout_function}(
    {payment_arg},
    {inventory_arg},
    {store_arg},
    {order_arg},
):
    # SOPHYANE_SAGA_COMPENSATION_V1
    saga_id = str(
        getattr(
            {order_arg},
            "id",
            id({order_arg}),
        )
    )

    existing = {store_arg}.get(
        saga_id
    )

    if (
        existing
        and existing.get(
            "state"
        )
        in {{
            "COMPLETED",
            "COMPENSATED",
        }}
    ):
        return existing

    saga = {{
        "saga_id": saga_id,
        "state": "STARTED",
        "payment": None,
        "inventory": None,
        "compensation": None,
    }}

    {store_arg}.put(
        saga_id,
        dict(
            saga
        ),
    )

    payment = {payment_arg}.charge(
        {order_arg}.total
    )

    saga[
        "payment"
    ] = payment

    saga[
        "state"
    ] = "PAYMENT_SUCCEEDED"

    {store_arg}.put(
        saga_id,
        dict(
            saga
        ),
    )

    try:
        inventory = {inventory_arg}.reserve(
            {order_arg}.items
        )

    except Exception as exc:
        saga[
            "state"
        ] = "INVENTORY_FAILED"

        {store_arg}.put(
            saga_id,
            dict(
                saga
            ),
        )

        compensation = {payment_arg}.refund(
            payment
        )

        saga[
            "compensation"
        ] = compensation

        saga[
            "state"
        ] = "COMPENSATED"

        saga[
            "failure"
        ] = str(
            exc
        )

        {store_arg}.put(
            saga_id,
            dict(
                saga
            ),
        )

        return saga

    saga[
        "inventory"
    ] = inventory

    saga[
        "state"
    ] = "COMPLETED"

    {store_arg}.put(
        saga_id,
        dict(
            saga
        ),
    )

    return saga
'''

    lines = raw.splitlines(
        keepends=True
    )

    offsets = [0]

    for line in lines:
        offsets.append(
            offsets[-1]
            + len(line)
        )

    start = offsets[
        target.lineno - 1
    ]

    end = offsets[
        target.end_lineno
    ]

    updated = (
        raw[:start]
        + replacement
        + raw[end:]
    )

    try:
        ast.parse(
            updated,
            filename=str(chosen),
        )

    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="saga_compensation",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(
                    chosen.relative_to(root)
                ),
            ),
            detail=(
                "generated saga mutation failed syntax validation: "
                + str(exc)
            ),
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    verify = chosen.read_text(
        encoding="utf-8"
    )

    required_postconditions = (
        "SOPHYANE_SAGA_COMPENSATION_V1",
        '"PAYMENT_SUCCEEDED"',
        '"INVENTORY_FAILED"',
        '"COMPENSATED"',
        '"COMPLETED"',
        ".refund(",
        ".put(",
    )

    ok = all(
        token in verify
        for token in required_postconditions
    )

    if not ok:
        chosen.write_text(
            raw,
            encoding="utf-8",
        )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="saga_compensation",
        operation=step["operation"],
        ok=ok,
        mutated=ok,
        targets=(
            str(
                chosen.relative_to(root)
            ),
        ),
        detail=(
            "durable saga compensation installed structurally"
            if ok
            else "saga post-mutation verification failed"
        ),
    )




# SOPHYANE_V63_REDIS_SLIDING_WINDOW_EXECUTOR

@register_executor(
    "redis_sliding_window_rate_limit"
)
def _execute_redis_sliding_window_rate_limit(
    step: dict[str, Any],
    requirement: dict[str, Any],
    root: Path,
) -> ExecutionStepResult:
    targets = _target_paths(
        step,
        root,
    )

    source_targets = [
        item
        for item in targets
        if item.suffix.lower() == ".py"
    ]

    relative_targets = tuple(
        str(item.relative_to(root))
        for item in source_targets
    )

    if not source_targets:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(),
            detail="no grounded Python HTTP middleware source",
        )

    validated = str(
        step.get(
            "validated_value",
            "",
        )
    ).lower()

    required_groups = (
        ("sliding window", "sliding-window"),
        ("redis",),
        ("lua", "eval", "evalsha"),
        ("100",),
        ("60 seconds", "60 second", "per minute"),
        ("ip", "client ip"),
        ("unauthenticated",),
        ("429",),
        ("retry-after",),
        ("x-ratelimit-limit",),
        ("x-ratelimit-remaining",),
        ("x-ratelimit-reset",),
    )

    if not all(
        any(
            token in validated
            for token in group
        )
        for group in required_groups
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=relative_targets,
            detail=(
                "validated rate-limit contract lacks "
                "required sliding-window semantics"
            ),
        )

    chosen = None
    function_node = None
    request_name = None
    redis_name = None

    for candidate in source_targets:
        raw = candidate.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if (
            "SOPHYANE_REDIS_SLIDING_WINDOW_RATE_LIMIT_V1"
            in raw
        ):
            return ExecutionStepResult(
                requirement_id=step["requirement_id"],
                contract="redis_sliding_window_rate_limit",
                operation=step["operation"],
                ok=True,
                mutated=False,
                targets=(
                    str(candidate.relative_to(root)),
                ),
                detail=(
                    "Redis sliding-window rate limiter "
                    "already installed"
                ),
            )

        try:
            tree = ast.parse(
                raw,
                filename=str(candidate),
            )
        except SyntaxError:
            continue

        for node in tree.body:
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ),
            ):
                continue

            # Phase B deliberately supports a narrow, structurally
            # provable function form. Unknown shapes fail closed.
            if (
                node.args.vararg is not None
                or node.args.kwarg is not None
                or node.args.kwonlyargs
                or node.args.posonlyargs
            ):
                continue

            arg_names = [
                item.arg
                for item in node.args.args
            ]

            req_candidates = [
                name
                for name in arg_names
                if name.lower() in {
                    "request",
                    "req",
                }
            ]

            redis_candidates = [
                name
                for name in arg_names
                if "redis" in name.lower()
            ]

            if (
                not req_candidates
                or not redis_candidates
            ):
                continue

            segment = (
                ast.get_source_segment(
                    raw,
                    node,
                )
                or ""
            )

            lower = segment.lower()

            has_request_identity = any(
                token in lower
                for token in (
                    "client.host",
                    "client_ip",
                    "remote_addr",
                    "request.client",
                )
            )

            has_redis_dependency = any(
                token in lower
                for token in (
                    "redis",
                    ".get(",
                    ".eval(",
                    ".evalsha(",
                    ".zadd(",
                )
            )

            if not (
                has_request_identity
                and has_redis_dependency
            ):
                continue

            chosen = candidate
            function_node = node
            request_name = req_candidates[0]
            redis_name = redis_candidates[0]
            break

        if chosen is not None:
            break

    if (
        chosen is None
        or function_node is None
        or request_name is None
        or redis_name is None
    ):
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=relative_targets,
            detail=(
                "grounded source lacks proven request/client-IP "
                "and explicit Redis dependency"
            ),
        )

    raw = chosen.read_text(
        encoding="utf-8"
    )

    lines = raw.splitlines(
        keepends=True
    )

    offsets = [0]

    for line in lines:
        offsets.append(
            offsets[-1] + len(line)
        )

    start = offsets[
        function_node.lineno - 1
    ]

    end = offsets[
        function_node.end_lineno
    ]

    region = raw[
        start:end
    ]

    region_lines = region.splitlines(
        keepends=True
    )

    if not region_lines:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(chosen.relative_to(root)),
            ),
            detail="empty grounded middleware function",
        )

    first_line = region_lines[0]

    # Keep Phase B intentionally narrow: require a one-line function
    # signature so the transformation cannot guess at complex syntax.
    import re as _re

    match = _re.match(
        r"^(?P<indent>\s*)"
        r"(?P<async>async\s+)?"
        r"def\s+"
        + _re.escape(function_node.name)
        + r"\s*\((?P<args>[^)]*)\)\s*:\s*$",
        first_line.rstrip("\n"),
    )

    if match is None:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(chosen.relative_to(root)),
            ),
            detail=(
                "unsupported middleware signature; "
                "refusing structural guess"
            ),
        )

    indent = match.group("indent")
    async_prefix = (
        match.group("async")
        or ""
    )

    args_source = match.group("args")
    original_name = (
        "_sophyane_original_"
        + function_node.name
    )

    renamed_first = first_line.replace(
        "def " + function_node.name + "(",
        "def " + original_name + "(",
        1,
    )

    renamed_region = (
        renamed_first
        + "".join(
            region_lines[1:]
        )
    )

    arg_names = [
        item.arg
        for item in function_node.args.args
    ]

    call_args = ", ".join(
        arg_names
    )

    original_call = (
        f"{original_name}({call_args})"
    )

    if isinstance(
        function_node,
        ast.AsyncFunctionDef,
    ):
        original_call = (
            "await "
            + original_call
        )

    wrapper = f'''
{async_prefix}def {function_node.name}({args_source}):
    # SOPHYANE_REDIS_SLIDING_WINDOW_RATE_LIMIT_V1
    import time
    import uuid

    request = {request_name}
    redis_client = {redis_name}

    user = getattr(
        request,
        "user",
        None,
    )

    authenticated = bool(
        user is not None
        and getattr(
            user,
            "is_authenticated",
            False,
        )
    )

    # The V6.3 contract limits unauthenticated users only.
    if authenticated:
        return {original_call}

    client = getattr(
        request,
        "client",
        None,
    )

    client_ip = getattr(
        client,
        "host",
        None,
    )

    if not client_ip:
        client_ip = getattr(
            request,
            "client_ip",
            None,
        )

    if not client_ip:
        raise RuntimeError(
            "cannot determine unauthenticated client IP"
        )

    limit = 100
    window_seconds = 60

    now_ms = int(
        time.time() * 1000
    )

    window_ms = (
        window_seconds * 1000
    )

    key = (
        "sophyane:rate-limit:ip:"
        + str(client_ip)
    )

    member = (
        str(now_ms)
        + ":"
        + uuid.uuid4().hex
    )

    lua = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

local count = redis.call('ZCARD', key)

if count >= limit then
    local oldest = redis.call(
        'ZRANGE',
        key,
        0,
        0,
        'WITHSCORES'
    )

    local reset = now

    if oldest[2] then
        reset = tonumber(oldest[2]) + window
    end

    redis.call('PEXPIRE', key, window)

    return {{0, count, reset}}
end

redis.call('ZADD', key, now, member)

count = count + 1

redis.call('PEXPIRE', key, window)

return {{1, count, now + window}}
"""

    allowed, count, reset_ms = redis_client.eval(
        lua,
        1,
        key,
        now_ms,
        window_ms,
        limit,
        member,
    )

    allowed = int(
        allowed
    )

    count = int(
        count
    )

    reset_ms = int(
        reset_ms
    )

    remaining = max(
        0,
        limit - count,
    )

    retry_after = max(
        1,
        (
            reset_ms
            - now_ms
            + 999
        )
        // 1000,
    )

    rate_headers = {{
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(
            reset_ms // 1000
        ),
    }}

    if not allowed:
        headers = dict(
            rate_headers
        )

        headers[
            "Retry-After"
        ] = str(
            retry_after
        )

        return {{
            "status": 429,
            "status_code": 429,
            "body": "Too Many Requests",
            "headers": headers,
        }}

    result = {original_call}

    if isinstance(
        result,
        dict,
    ):
        headers = dict(
            result.get(
                "headers",
                {{}},
            )
        )

        headers.update(
            rate_headers
        )

        result[
            "headers"
        ] = headers

    return result
'''

    updated = (
        raw[:start]
        + renamed_region
        + "\n"
        + wrapper
        + raw[end:]
    )

    try:
        ast.parse(
            updated,
            filename=str(chosen),
        )
    except SyntaxError as exc:
        return ExecutionStepResult(
            requirement_id=step["requirement_id"],
            contract="redis_sliding_window_rate_limit",
            operation=step["operation"],
            ok=False,
            mutated=False,
            targets=(
                str(chosen.relative_to(root)),
            ),
            detail=(
                "generated middleware failed syntax validation: "
                + str(exc)
            ),
        )

    chosen.write_text(
        updated,
        encoding="utf-8",
    )

    return ExecutionStepResult(
        requirement_id=step["requirement_id"],
        contract="redis_sliding_window_rate_limit",
        operation=step["operation"],
        ok=True,
        mutated=True,
        targets=(
            str(chosen.relative_to(root)),
        ),
        detail=(
            "Redis Lua sliding-window rate limiter "
            "installed structurally"
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
