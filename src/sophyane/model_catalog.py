"""Curated model choices shown by the Sophyane setup wizard.

Provider APIs still accept a custom model ID. This catalogue provides a clean,
useful default list instead of forcing users to know provider-specific names.
"""

from __future__ import annotations

from typing import TypedDict


class ModelChoice(TypedDict):
    provider: str
    model: str
    label: str
    note: str


FRONTIER_MODELS: tuple[ModelChoice, ...] = (
    {"provider": "gemini", "model": "gemini-3.5-flash", "label": "Google Gemini 3.5 Flash", "note": "fast agentic frontier"},
    {"provider": "gemini", "model": "gemini-3.1-pro", "label": "Google Gemini 3.1 Pro", "note": "deep reasoning"},
    {"provider": "openai", "model": "gpt-5.6-sol", "label": "OpenAI GPT-5.6 Sol", "note": "maximum capability"},
    {"provider": "openai", "model": "gpt-5.6-terra", "label": "OpenAI GPT-5.6 Terra", "note": "balanced frontier"},
    {"provider": "anthropic", "model": "claude-opus-4-8", "label": "Anthropic Claude Opus 4.8", "note": "coding and agents"},
    {"provider": "anthropic", "model": "claude-sonnet-4-6", "label": "Anthropic Claude Sonnet 4.6", "note": "fast professional work"},
    {"provider": "xai", "model": "grok-4.5", "label": "xAI Grok 4.5", "note": "reasoning and tools"},
    {"provider": "deepseek", "model": "deepseek-reasoner", "label": "DeepSeek Reasoner", "note": "reasoning model"},
    {"provider": "deepseek", "model": "deepseek-chat", "label": "DeepSeek Chat", "note": "general and coding"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B via Groq", "note": "very fast hosted inference"},
)


LOCAL_MODELS: tuple[ModelChoice, ...] = (
    {"provider": "ollama", "model": "gemma3:4b", "label": "Gemma 3 4B", "note": "recommended small multimodal"},
    {"provider": "ollama", "model": "qwen2.5:3b", "label": "Qwen 2.5 3B", "note": "multilingual and light"},
    {"provider": "ollama", "model": "llama3.2:3b", "label": "Llama 3.2 3B", "note": "general small model"},
    {"provider": "ollama", "model": "deepseek-r1:1.5b", "label": "DeepSeek R1 1.5B", "note": "small reasoning"},
    {"provider": "ollama", "model": "qwen2.5-coder:3b", "label": "Qwen 2.5 Coder 3B", "note": "coding on constrained devices"},
    {"provider": "ollama", "model": "phi4-mini", "label": "Phi-4 Mini", "note": "compact reasoning"},
    {"provider": "ollama", "model": "smollm2:1.7b", "label": "SmolLM2 1.7B", "note": "very low memory"},
    {"provider": "ollama", "model": "mistral:7b", "label": "Mistral 7B", "note": "strong general local"},
    {"provider": "ollama", "model": "llama3.1:8b", "label": "Llama 3.1 8B", "note": "stronger local generalist"},
    {"provider": "ollama", "model": "deepseek-r1:8b", "label": "DeepSeek R1 8B", "note": "stronger local reasoning"},
)
