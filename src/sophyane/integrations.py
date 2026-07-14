"""Compatibility probes and lightweight adapters for common agent ecosystem tools."""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class IntegrationSpec:
    key: str
    package: str
    module: str
    category: str
    live_environment: str | None = None


INTEGRATIONS: tuple[IntegrationSpec, ...] = (
    IntegrationSpec("langchain_core", "langchain-core", "langchain_core", "framework"),
    IntegrationSpec("langsmith", "langsmith", "langsmith", "observability", "LANGSMITH_API_KEY"),
    IntegrationSpec("openai", "langchain-openai", "langchain_openai", "model", "OPENAI_API_KEY"),
    IntegrationSpec("anthropic", "langchain-anthropic", "langchain_anthropic", "model", "ANTHROPIC_API_KEY"),
    IntegrationSpec("google_genai", "langchain-google-genai", "langchain_google_genai", "model", "GOOGLE_API_KEY"),
    IntegrationSpec("tavily", "langchain-tavily", "langchain_tavily", "tool", "TAVILY_API_KEY"),
    IntegrationSpec("mcp", "langchain-mcp-adapters", "langchain_mcp_adapters", "protocol"),
    IntegrationSpec("postgres", "langgraph-checkpoint-postgres", "langgraph.checkpoint.postgres", "persistence", "POSTGRES_URI"),
    IntegrationSpec("redis", "langgraph-checkpoint-redis", "langgraph.checkpoint.redis", "persistence", "REDIS_URL"),
    IntegrationSpec("fastapi", "fastapi", "fastapi", "serving"),
)


def probe_integrations() -> list[dict[str, Any]]:
    """Return import and installed-version evidence for every supported target."""
    rows: list[dict[str, Any]] = []
    for spec in INTEGRATIONS:
        try:
            module = importlib.import_module(spec.module)
            version = importlib.metadata.version(spec.package)
            rows.append(
                {
                    "key": spec.key,
                    "package": spec.package,
                    "module": spec.module,
                    "category": spec.category,
                    "installed": True,
                    "version": version,
                    "module_name": module.__name__,
                    "live_environment": spec.live_environment,
                }
            )
        except Exception as error:  # report rather than hide optional failures
            rows.append(
                {
                    "key": spec.key,
                    "package": spec.package,
                    "module": spec.module,
                    "category": spec.category,
                    "installed": False,
                    "error": f"{type(error).__name__}: {error}",
                    "live_environment": spec.live_environment,
                }
            )
    return rows


class InvokeAdapter:
    """Expose LangChain-style Runnable objects as Sophyane worker backends."""

    def __init__(self, target: Any, *, system_prompt: str = "") -> None:
        if not callable(target) and not hasattr(target, "invoke"):
            raise TypeError("target must be callable or provide invoke()")
        self.target = target
        self.system_prompt = system_prompt

    def generate(self, prompt: str, system_prompt: str) -> str:
        combined_system = system_prompt or self.system_prompt
        payload: Any = prompt
        if combined_system:
            payload = [
                ("system", combined_system),
                ("human", prompt),
            ]
        if hasattr(self.target, "invoke"):
            result = self.target.invoke(payload)
        else:
            result = self.target(payload)
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)


def callable_tool(function: Callable[..., Any]) -> Callable[..., Any]:
    """Validate and return a plain callable for use by Sophyane worker code."""
    if not callable(function):
        raise TypeError("tool must be callable")
    return function
