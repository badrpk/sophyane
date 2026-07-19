"""Curated cloud-company and local-model catalogue for Sophyane setup."""

from __future__ import annotations

from typing import TypedDict


class ModelChoice(TypedDict):
    provider: str
    model: str
    label: str
    note: str
    min_ram_gb: int


class CompanyChoice(TypedDict):
    name: str
    provider: str
    credential_provider: str
    note: str
    models: tuple[ModelChoice, ...]


def _m(provider: str, model: str, label: str, note: str, ram: int = 0) -> ModelChoice:
    return {
        "provider": provider,
        "model": model,
        "label": label,
        "note": note,
        "min_ram_gb": ram,
    }


CLOUD_COMPANIES: tuple[CompanyChoice, ...] = (
    {
        "name": "Google",
        "provider": "gemini",
        "credential_provider": "gemini",
        "note": "Gemini API",
        "models": (
            _m("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", "fast and balanced"),
            _m("gemini", "gemini-2.5-pro", "Gemini 2.5 Pro", "deeper reasoning"),
            _m("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash", "compatible fallback"),
        ),
    },
    {
        "name": "OpenAI",
        "provider": "openai",
        "credential_provider": "openai",
        "note": "OpenAI API",
        "models": (
            _m("openai", "gpt-4.1", "GPT-4.1", "general and coding"),
            _m("openai", "gpt-4.1-mini", "GPT-4.1 Mini", "fast and economical"),
            _m("openai", "o3", "o3", "reasoning"),
        ),
    },
    {
        "name": "Anthropic",
        "provider": "anthropic",
        "credential_provider": "anthropic",
        "note": "Claude API",
        "models": (
            _m("anthropic", "claude-sonnet-4-20250514", "Claude Sonnet 4", "coding and professional work"),
            _m("anthropic", "claude-opus-4-20250514", "Claude Opus 4", "highest capability"),
            _m("anthropic", "claude-3-5-haiku-latest", "Claude Haiku", "fast and economical"),
        ),
    },
    {
        "name": "xAI",
        "provider": "xai",
        "credential_provider": "xai",
        "note": "Grok API",
        "models": (
            _m("xai", "grok-3", "Grok 3", "general frontier"),
            _m("xai", "grok-3-mini", "Grok 3 Mini", "fast reasoning"),
        ),
    },
    {
        "name": "DeepSeek",
        "provider": "deepseek",
        "credential_provider": "deepseek",
        "note": "DeepSeek API",
        "models": (
            _m("deepseek", "deepseek-chat", "DeepSeek Chat", "general and coding"),
            _m("deepseek", "deepseek-reasoner", "DeepSeek Reasoner", "reasoning"),
        ),
    },
    {
        "name": "Groq",
        "provider": "groq",
        "credential_provider": "groq",
        "note": "Groq hosted inference",
        "models": (
            _m("groq", "llama-3.3-70b-versatile", "Llama 3.3 70B", "fast hosted general model"),
            _m("groq", "qwen-qwq-32b", "Qwen QwQ 32B", "hosted reasoning"),
        ),
    },
    {
        "name": "OpenRouter",
        "provider": "openrouter",
        "credential_provider": "openrouter",
        "note": "many model vendors through one key",
        "models": (
            _m("openrouter", "openrouter/auto", "OpenRouter Auto", "automatically routes requests"),
            _m("openrouter", "meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "open model via OpenRouter"),
        ),
    },
    {
        "name": "Mistral AI",
        "provider": "openrouter",
        "credential_provider": "openrouter",
        "note": "Mistral models via OpenRouter",
        "models": (
            _m("openrouter", "mistralai/mistral-large", "Mistral Large", "general frontier"),
            _m("openrouter", "mistralai/codestral", "Codestral", "coding"),
        ),
    },
    {
        "name": "Cohere",
        "provider": "openrouter",
        "credential_provider": "openrouter",
        "note": "Command models via OpenRouter",
        "models": (
            _m("openrouter", "cohere/command-r-plus", "Command R+", "retrieval and enterprise work"),
            _m("openrouter", "cohere/command-r", "Command R", "balanced enterprise model"),
        ),
    },
    {
        "name": "Together AI",
        "provider": "openrouter",
        "credential_provider": "openrouter",
        "note": "open models through OpenRouter-compatible routing",
        "models": (
            _m("openrouter", "deepseek/deepseek-r1", "DeepSeek R1", "hosted open reasoning"),
            _m("openrouter", "qwen/qwen-2.5-coder-32b-instruct", "Qwen Coder 32B", "hosted coding"),
        ),
    },
)


LOCAL_MODELS: tuple[ModelChoice, ...] = (
    _m("ollama", "smollm2:1.7b", "SmolLM2 1.7B", "very low memory", 3),
    _m("ollama", "deepseek-r1:1.5b", "DeepSeek R1 1.5B", "small reasoning", 3),
    _m("ollama", "qwen2.5:3b", "Qwen 2.5 3B", "multilingual and light", 5),
    _m("ollama", "llama3.2:3b", "Llama 3.2 3B", "general small model", 5),
    _m("ollama", "qwen2.5-coder:3b", "Qwen 2.5 Coder 3B", "coding on constrained devices", 5),
    _m("ollama", "gemma3:4b", "Gemma 3 4B", "small multimodal", 7),
    _m("ollama", "phi4-mini", "Phi-4 Mini", "compact reasoning", 7),
    _m("ollama", "mistral:7b", "Mistral 7B", "strong general local", 10),
    _m("ollama", "llama3.1:8b", "Llama 3.1 8B", "strong local generalist", 12),
    _m("ollama", "deepseek-r1:8b", "DeepSeek R1 8B", "strong local reasoning", 12),
)

# Backward compatibility for code importing the previous flat list.
FRONTIER_MODELS: tuple[ModelChoice, ...] = tuple(
    model for company in CLOUD_COMPANIES for model in company["models"][:1]
)
