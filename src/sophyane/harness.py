"""Verified agent harness primitives for Sophyane v13."""
from __future__ import annotations

import asyncio
import inspect
import re
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

    def register(self, name: str, function: Callable[..., Any], *, description: str = "", dangerous: bool = False) -> ToolSpec:
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

    def register(self, name: str, backend: ModelBackend, *, priority: int = 100) -> None:
        if not name or not callable(backend):
            raise ValueError("model requires a non-empty name and callable backend")
        self._models[name] = ModelSpec(name, backend, priority)

    def ordered(self) -> list[ModelSpec]:
        return sorted(self._models.values(), key=lambda item: (item.priority, item.name))

    def generate(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        errors: list[str] = []
        for spec in self.ordered():
            try:
                return spec.name, spec.backend(prompt, system_prompt)
            except Exception as error:
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
        while self.items and sum(len(role) + len(content) for role, content in self.items) > self.max_chars:
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
        r"\bmkfs\b",
        r"\bdd\s+if=.*\s+of=/dev/",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bchmod\s+-R\s+777\s+/",
    )

    def check_text(self, text: str) -> GuardrailDecision:
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, text, flags=re.I):
                return GuardrailDecision(False, f"blocked dangerous pattern: {pattern}")
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


class AgentHarness:
    def __init__(self, models: ModelRegistry, tools: ToolRegistry | None = None, context: ContextManager | None = None, guardrails: Guardrails | None = None, max_iterations: int = 4) -> None:
        self.models = models
        self.tools = tools or ToolRegistry()
        self.context = context or ContextManager()
        self.guardrails = guardrails or Guardrails()
        self.max_iterations = max(1, max_iterations)

    def run(self, task: str, verifier: Callable[[str], VerificationResult], *, system_prompt: str = "") -> HarnessResult:
        decision = self.guardrails.check_text(task)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        trace: list[dict[str, Any]] = []
        prompt = task
        last_model = ""
        output = ""
        for iteration in range(1, self.max_iterations + 1):
            self.context.add("user", prompt)
            assembled = self.context.render()
            last_model, output = self.models.generate(assembled, system_prompt)
            trace.append({"step": "model", "iteration": iteration, "model": last_model})
            verification = verifier(output)
            trace.append({"step": "verify", "iteration": iteration, "passed": verification.passed, "feedback": verification.feedback})
            self.context.add("assistant", output)
            if verification.passed:
                return HarnessResult(output, True, iteration, last_model, trace)
            prompt = f"Repair the previous answer. Verification feedback: {verification.feedback}"
        return HarnessResult(output, False, self.max_iterations, last_model, trace)

    async def run_async(self, task: str, verifier: Callable[[str], VerificationResult], *, system_prompt: str = "") -> HarnessResult:
        return await asyncio.to_thread(self.run, task, verifier, system_prompt=system_prompt)

    def invoke_tool(self, name: str, *, approved: bool = False, **kwargs: Any) -> Any:
        spec = self.tools.get(name)
        decision = self.guardrails.check_tool(spec, approved=approved)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        result = spec.function(**kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
