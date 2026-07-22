"""Verified agent harness primitives for Sophyane.

Capabilities:
1. ToolRegistry — named callables with duplicate protection
2. ModelRegistry — priority fallback across backends
3. ContextManager — bounded conversation budget
4. Guardrails — destructive-pattern blocking + dangerous tools
5. AgentHarness — generate / verify / repair loop
6. SandboxRunner — timed shell/python execution with output caps
7. VerificationResult — explicit pass/fail feedback in the trace
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import resource
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class ModelBackend(Protocol):
    def __call__(self, prompt: str, system_prompt: str) -> str: ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable[..., Any]
    description: str = ""
    dangerous: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        function: Callable[..., Any],
        *,
        description: str = "",
        dangerous: bool = False,
    ) -> ToolSpec:
        if not name or not callable(function):
            raise ValueError("tool requires a non-empty name and callable")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        spec = ToolSpec(name, function, description, dangerous)
        self._tools[name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def invoke(self, name: str, /, **kwargs: Any) -> Any:
        return self.get(name).function(**kwargs)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    backend: ModelBackend
    priority: int = 100


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}

    def register(
        self,
        name: str,
        backend: ModelBackend,
        *,
        priority: int = 100,
    ) -> None:
        if not name or not callable(backend):
            raise ValueError("model requires a non-empty name and callable backend")
        self._models[name] = ModelSpec(name, backend, priority)

    def ordered(self) -> list[ModelSpec]:
        return sorted(
            self._models.values(),
            key=lambda item: (item.priority, item.name),
        )

    def generate(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        errors: list[str] = []
        for spec in self.ordered():
            try:
                return spec.name, spec.backend(prompt, system_prompt)
            except Exception as error:  # noqa: BLE001 — intentional fallback
                errors.append(f"{spec.name}: {type(error).__name__}: {error}")
        raise RuntimeError("all models failed: " + "; ".join(errors))


@dataclass
class ContextManager:
    max_chars: int = 12000
    items: list[tuple[str, str]] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        self.items.append((role, content))
        self._trim()

    def _trim(self) -> None:
        while (
            self.items
            and sum(len(role) + len(content) for role, content in self.items)
            > self.max_chars
        ):
            self.items.pop(0)

    def render(self) -> str:
        return "\n".join(f"[{role}] {content}" for role, content in self.items)


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str = ""


class Guardrails:
    BLOCKED_PATTERNS = (
        r"\brm\s+-rf\s+/(?:\s|$)",
        r"\brm\s+-rf\s+~",
        r"\bmkfs\b",
        r"\bdd\s+if=.*\s+of=/dev/",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bchmod\s+-R\s+777\s+/",
        r"\bcurl\b.+\|\s*(ba)?sh\b",
        r"\bwget\b.+\|\s*(ba)?sh\b",
        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",  # fork bomb
        r"\bmkfifo\b.+/tmp/",
        r">\s*/dev/sd[a-z]",
    )

    def check_text(self, text: str) -> GuardrailDecision:
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                return GuardrailDecision(
                    False,
                    f"blocked dangerous pattern: {pattern}",
                )
        return GuardrailDecision(True)

    def check_tool(self, spec: ToolSpec, *, approved: bool = False) -> GuardrailDecision:
        if spec.dangerous and not approved:
            return GuardrailDecision(False, f"tool requires approval: {spec.name}")
        return GuardrailDecision(True)


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    feedback: str = ""


@dataclass
class HarnessResult:
    output: str
    verified: bool
    iterations: int
    model: str
    trace: list[dict[str, Any]]
    duration_ms: float = 0.0


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: float
    command: str


class SandboxRunner:
    """Run shell/python snippets with timeout, output caps, and soft resource limits."""

    def __init__(
        self,
        *,
        max_output_bytes: int = 64_000,
        default_timeout: float = 30.0,
        memory_mb: int = 256,
    ) -> None:
        self.max_output_bytes = max(1024, max_output_bytes)
        self.default_timeout = max(0.1, default_timeout)
        self.memory_mb = max(16, memory_mb)

    def _preexec(self) -> None:
        # Soft limits only; ignore failures on platforms that reject them.
        # Avoid RLIMIT_NPROC — Crostini/user namespaces often cannot fork under
        # aggressive process caps, which breaks even simple shell builtins.
        # Android/Termux processes can abort during startup when RLIMIT_AS is
        # imposed, even for trivial shell commands. Keep the memory ceiling on
        # conventional POSIX hosts, but rely on timeout/output limits on Termux.
        is_android = bool(
            os.environ.get("ANDROID_ROOT")
            or os.environ.get("ANDROID_DATA")
            or os.environ.get("TERMUX_VERSION")
            or "com.termux" in os.environ.get("PREFIX", "")
        )
        if not is_android:
            try:
                limit = self.memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except (ValueError, OSError, AttributeError):
                pass
        try:
            # CPU seconds are a soft ceiling for runaway compute, not wall-clock
            # timeout (subprocess timeout handles wall clock).
            cpu = max(5, int(self.default_timeout) + 5)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        except (ValueError, OSError):
            pass

    def run(
        self,
        command: str | list[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        shell: bool | None = None,
    ) -> SandboxResult:
        started = time.perf_counter()
        timeout_s = self.default_timeout if timeout is None else max(0.1, float(timeout))
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        # Strip secrets from child env by default keys if caller didn't pass env.
        for key in list(process_env):
            if any(token in key.upper() for token in ("API_KEY", "SECRET", "TOKEN", "PASSWORD")):
                # Keep PATH etc.; only drop obvious credential vars unless explicitly provided.
                if env is None or key not in env:
                    process_env.pop(key, None)

        use_shell = shell if shell is not None else isinstance(command, str)
        display = command if isinstance(command, str) else " ".join(command)
        argv: str | list[str]
        if use_shell:
            argv = command if isinstance(command, str) else " ".join(command)
        else:
            argv = command if isinstance(command, list) else command.split()

        try:
            completed = subprocess.run(
                argv,
                shell=use_shell,
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=process_env,
                preexec_fn=self._preexec if os.name == "posix" else None,
            )
            stdout = (completed.stdout or "")[: self.max_output_bytes]
            stderr = (completed.stderr or "")[: self.max_output_bytes]
            duration_ms = (time.perf_counter() - started) * 1000
            return SandboxResult(
                ok=completed.returncode == 0,
                exit_code=int(completed.returncode),
                stdout=stdout,
                stderr=stderr,
                timed_out=False,
                duration_ms=duration_ms,
                command=display,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (error.stdout or "") if isinstance(error.stdout, str) else ""
            stderr = (error.stderr or "") if isinstance(error.stderr, str) else "timeout"
            duration_ms = (time.perf_counter() - started) * 1000
            return SandboxResult(
                ok=False,
                exit_code=124,
                stdout=stdout[: self.max_output_bytes],
                stderr=(stderr or "command timed out")[: self.max_output_bytes],
                timed_out=True,
                duration_ms=duration_ms,
                command=display,
            )
        except OSError as error:
            duration_ms = (time.perf_counter() - started) * 1000
            return SandboxResult(
                ok=False,
                exit_code=127,
                stdout="",
                stderr=str(error),
                timed_out=False,
                duration_ms=duration_ms,
                command=display,
            )

    def run_python(
        self,
        code: str,
        *,
        timeout: float | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> SandboxResult:
        # Avoid shell interpolation; pass code via python -c.
        return self.run(
            ["python3", "-c", code],
            cwd=cwd,
            timeout=timeout,
            shell=False,
        )


class AgentHarness:
    def __init__(
        self,
        models: ModelRegistry,
        tools: ToolRegistry | None = None,
        context: ContextManager | None = None,
        guardrails: Guardrails | None = None,
        max_iterations: int = 4,
        sandbox: SandboxRunner | None = None,
    ) -> None:
        self.models = models
        self.tools = tools or ToolRegistry()
        self.context = context or ContextManager()
        self.guardrails = guardrails or Guardrails()
        self.max_iterations = max(1, max_iterations)
        self.sandbox = sandbox or SandboxRunner()

    def run(
        self,
        task: str,
        verifier: Callable[[str], VerificationResult],
        *,
        system_prompt: str = "",
    ) -> HarnessResult:
        decision = self.guardrails.check_text(task)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        trace: list[dict[str, Any]] = []
        prompt = task
        last_model = ""
        output = ""
        started = time.perf_counter()
        for iteration in range(1, self.max_iterations + 1):
            self.context.add("user", prompt)
            assembled = self.context.render()
            step_started = time.perf_counter()
            last_model, output = self.models.generate(assembled, system_prompt)
            model_ms = (time.perf_counter() - step_started) * 1000
            trace.append(
                {
                    "step": "model",
                    "iteration": iteration,
                    "model": last_model,
                    "duration_ms": model_ms,
                }
            )
            verification = verifier(output)
            trace.append(
                {
                    "step": "verify",
                    "iteration": iteration,
                    "passed": verification.passed,
                    "feedback": verification.feedback,
                }
            )
            self.context.add("assistant", output)
            if verification.passed:
                return HarnessResult(
                    output,
                    True,
                    iteration,
                    last_model,
                    trace,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            prompt = (
                "Repair the previous answer. Verification feedback: "
                f"{verification.feedback}"
            )
        return HarnessResult(
            output,
            False,
            self.max_iterations,
            last_model,
            trace,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    async def run_async(
        self,
        task: str,
        verifier: Callable[[str], VerificationResult],
        *,
        system_prompt: str = "",
    ) -> HarnessResult:
        return await asyncio.to_thread(
            self.run,
            task,
            verifier,
            system_prompt=system_prompt,
        )

    def invoke_tool(self, name: str, *, approved: bool = False, **kwargs: Any) -> Any:
        spec = self.tools.get(name)
        decision = self.guardrails.check_tool(spec, approved=approved)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        result = spec.function(**kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def run_sandboxed(
        self,
        command: str,
        *,
        approved: bool = False,
        timeout: float | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> SandboxResult:
        decision = self.guardrails.check_text(command)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if not approved:
            # Treat unrestricted shell as dangerous unless approved.
            raise PermissionError("sandboxed shell requires approval")
        return self.sandbox.run(command, cwd=cwd, timeout=timeout)
