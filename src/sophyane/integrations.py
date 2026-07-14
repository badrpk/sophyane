"""Compatibility probes and lightweight adapters for agent ecosystem tools."""

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
    tier: str = "base"


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
    IntegrationSpec("aws_bedrock", "langchain-aws", "langchain_aws", "model", "AWS_ACCESS_KEY_ID", "extended"),
    IntegrationSpec("cohere", "langchain-cohere", "langchain_cohere", "model", "COHERE_API_KEY", "extended"),
    IntegrationSpec("mistral", "langchain-mistralai", "langchain_mistralai", "model", "MISTRAL_API_KEY", "extended"),
    IntegrationSpec("groq", "langchain-groq", "langchain_groq", "model", "GROQ_API_KEY", "extended"),
    IntegrationSpec("ollama", "langchain-ollama", "langchain_ollama", "model", "OLLAMA_BASE_URL", "extended"),
    IntegrationSpec("huggingface", "langchain-huggingface", "langchain_huggingface", "model", "HUGGINGFACEHUB_API_TOKEN", "extended"),
    IntegrationSpec("pinecone", "langchain-pinecone", "langchain_pinecone", "vector_store", "PINECONE_API_KEY", "extended"),
    IntegrationSpec("qdrant", "langchain-qdrant", "langchain_qdrant", "vector_store", "QDRANT_URL", "extended"),
    IntegrationSpec("weaviate", "langchain-weaviate", "langchain_weaviate", "vector_store", "WEAVIATE_URL", "extended"),
    IntegrationSpec("chroma", "langchain-chroma", "langchain_chroma", "vector_store", "CHROMA_HOST", "extended"),
    IntegrationSpec("elasticsearch", "langchain-elasticsearch", "langchain_elasticsearch", "vector_store", "ELASTICSEARCH_URL", "extended"),
    IntegrationSpec("mongodb", "langchain-mongodb", "langchain_mongodb", "vector_store", "MONGODB_URI", "extended"),
    IntegrationSpec("sqlite_checkpoint", "langgraph-checkpoint-sqlite", "langgraph.checkpoint.sqlite", "persistence", tier="extended"),
    IntegrationSpec("opentelemetry", "opentelemetry-api", "opentelemetry", "observability", "OTEL_EXPORTER_OTLP_ENDPOINT", "extended"),
    IntegrationSpec("celery", "celery", "celery", "task_queue", "CELERY_BROKER_URL", "extended"),
    IntegrationSpec("kafka", "confluent-kafka", "confluent_kafka", "event_stream", "KAFKA_BOOTSTRAP_SERVERS", "extended"),
    IntegrationSpec("sqlalchemy", "SQLAlchemy", "sqlalchemy", "database", "SQLALCHEMY_URL", "extended"),
    IntegrationSpec("streamlit", "streamlit", "streamlit", "serving", tier="extended"),
    IntegrationSpec("gradio", "gradio", "gradio", "serving", tier="extended"),
    IntegrationSpec("llamaindex", "llama-index-core", "llama_index.core", "framework", tier="extended"),
)


def probe_integrations(tier: str | None = None) -> list[dict[str, Any]]:
    """Return import and installed-version evidence for supported targets."""
    rows: list[dict[str, Any]] = []
    for spec in INTEGRATIONS:
        if tier is not None and spec.tier != tier:
            continue
        try:
            module = importlib.import_module(spec.module)
            version = importlib.metadata.version(spec.package)
            rows.append(
                {
                    "key": spec.key,
                    "package": spec.package,
                    "module": spec.module,
                    "category": spec.category,
                    "tier": spec.tier,
                    "installed": True,
                    "version": version,
                    "module_name": module.__name__,
                    "live_environment": spec.live_environment,
                }
            )
        except Exception as error:
            rows.append(
                {
                    "key": spec.key,
                    "package": spec.package,
                    "module": spec.module,
                    "category": spec.category,
                    "tier": spec.tier,
                    "installed": False,
                    "error": f"{type(error).__name__}: {error}",
                    "live_environment": spec.live_environment,
                }
            )
    return rows


class InvokeAdapter:
    """Expose invoke-compatible objects as Sophyane worker backends."""

    def __init__(self, target: Any, *, system_prompt: str = "") -> None:
        if not callable(target) and not hasattr(target, "invoke"):
            raise TypeError("target must be callable or provide invoke()")
        self.target = target
        self.system_prompt = system_prompt

    def generate(self, prompt: str, system_prompt: str) -> str:
        combined_system = system_prompt or self.system_prompt
        payload: Any = prompt
        if combined_system:
            payload = [("system", combined_system), ("human", prompt)]
        result = self.target.invoke(payload) if hasattr(self.target, "invoke") else self.target(payload)
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)


class AsyncInvokeAdapter:
    """Expose async ainvoke-compatible objects through an async backend method."""

    def __init__(self, target: Any) -> None:
        if not hasattr(target, "ainvoke"):
            raise TypeError("target must provide ainvoke()")
        self.target = target

    async def generate(self, prompt: str, system_prompt: str) -> str:
        payload: Any = prompt if not system_prompt else [("system", system_prompt), ("human", prompt)]
        result = await self.target.ainvoke(payload)
        content = getattr(result, "content", result)
        return content if isinstance(content, str) else str(content)


def callable_tool(function: Callable[..., Any]) -> Callable[..., Any]:
    """Validate and return a plain callable for Sophyane worker code."""
    if not callable(function):
        raise TypeError("tool must be callable")
    return function
