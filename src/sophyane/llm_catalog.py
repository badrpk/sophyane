"""Top LLM providers + public models catalog for Sophyane browser/agent UI.

Cloud API providers deliver top agentic performance. Local open-source
(ollama / local_gguf) is always available as a free fallback when the user
has no API credits or prefers offline.
"""

from __future__ import annotations

from typing import Any

from sophyane.config import get_secret, load_config, load_secrets, save_config, save_secret
from sophyane.providers.fallback import DEFAULT_FALLBACK_ORDER, load_llm_config
from sophyane.version import __version__

# Top-tier providers users can pick for agent harness performance.
# Rank is display order (1 = highest priority marketing position).
TOP_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openai",
        "name": "OpenAI",
        "rank": 1,
        "tier": "cloud",
        "env": "OPENAI_API_KEY",
        "requires_api_key": True,
        "docs": "https://platform.openai.com/api-keys",
        "models": [
            {"id": "gpt-4o", "label": "GPT-4o"},
            {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
            {"id": "o3-mini", "label": "o3-mini (reasoning)"},
            {"id": "o4-mini", "label": "o4-mini"},
            {"id": "gpt-5-mini", "label": "GPT-5 mini"},
        ],
        "default_model": "gpt-4o-mini",
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "rank": 2,
        "tier": "cloud",
        "env": "ANTHROPIC_API_KEY",
        "requires_api_key": True,
        "docs": "https://console.anthropic.com/",
        "models": [
            {"id": "claude-opus-4-20250514", "label": "Claude Opus 4"},
            {"id": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
            {"id": "claude-3-5-haiku-latest", "label": "Claude 3.5 Haiku"},
            {"id": "claude-3-7-sonnet-latest", "label": "Claude 3.7 Sonnet"},
        ],
        "default_model": "claude-sonnet-4-20250514",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "rank": 3,
        "tier": "cloud",
        "env": "GEMINI_API_KEY",
        "requires_api_key": True,
        "docs": "https://aistudio.google.com/apikey",
        "models": [
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
        ],
        "default_model": "gemini-2.5-flash",
    },
    {
        "id": "xai",
        "name": "xAI Grok",
        "rank": 4,
        "tier": "cloud",
        "env": "XAI_API_KEY",
        "requires_api_key": True,
        "docs": "https://console.x.ai/",
        "models": [
            {"id": "grok-4", "label": "Grok 4"},
            {"id": "grok-3", "label": "Grok 3"},
            {"id": "grok-3-mini", "label": "Grok 3 mini"},
            {"id": "grok-2", "label": "Grok 2"},
        ],
        "default_model": "grok-4",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "rank": 5,
        "tier": "cloud",
        "env": "DEEPSEEK_API_KEY",
        "requires_api_key": True,
        "docs": "https://platform.deepseek.com/",
        "models": [
            {"id": "deepseek-chat", "label": "DeepSeek Chat (V3)"},
            {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner (R1)"},
        ],
        "default_model": "deepseek-chat",
    },
    {
        "id": "groq",
        "name": "Groq",
        "rank": 6,
        "tier": "cloud",
        "env": "GROQ_API_KEY",
        "requires_api_key": True,
        "docs": "https://console.groq.com/keys",
        "models": [
            {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B"},
            {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant"},
            {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "label": "Llama 4 Scout"},
            {"id": "qwen/qwen3-32b", "label": "Qwen3 32B"},
            {"id": "moonshotai/kimi-k2-instruct", "label": "Kimi K2"},
        ],
        "default_model": "llama-3.3-70b-versatile",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "rank": 7,
        "tier": "cloud",
        "env": "OPENROUTER_API_KEY",
        "requires_api_key": True,
        "docs": "https://openrouter.ai/keys",
        "note": "Gateway to many public models (Mistral, Llama, Qwen, etc.)",
        "models": [
            {"id": "openai/gpt-4o-mini", "label": "OpenAI GPT-4o mini"},
            {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4"},
            {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
            {"id": "x-ai/grok-3-mini", "label": "Grok 3 mini"},
            {"id": "deepseek/deepseek-chat", "label": "DeepSeek Chat"},
            {"id": "mistralai/mistral-large", "label": "Mistral Large"},
            {"id": "meta-llama/llama-3.3-70b-instruct", "label": "Llama 3.3 70B"},
            {"id": "qwen/qwen-2.5-72b-instruct", "label": "Qwen 2.5 72B"},
        ],
        "default_model": "openai/gpt-4o-mini",
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "rank": 8,
        "tier": "cloud",
        "env": "MISTRAL_API_KEY",
        "requires_api_key": True,
        "docs": "https://console.mistral.ai/",
        "note": "Uses OpenAI-compatible API via openrouter plugin when mistral plugin absent; prefer OpenRouter mistral models or set OPENROUTER.",
        "plugin": "openrouter",  # route through openrouter if no native plugin
        "models": [
            {"id": "mistralai/mistral-large", "label": "Mistral Large (via OpenRouter)"},
            {"id": "mistralai/mistral-medium", "label": "Mistral Medium"},
            {"id": "mistralai/codestral-latest", "label": "Codestral"},
            {"id": "mistralai/pixtral-large-latest", "label": "Pixtral Large"},
        ],
        "default_model": "mistralai/mistral-large",
    },
    {
        "id": "ollama",
        "name": "Ollama (local free)",
        "rank": 9,
        "tier": "local_free",
        "env": "",
        "requires_api_key": False,
        "docs": "https://ollama.com/",
        "note": "Free on your machine. Install models with `ollama pull …`.",
        "models": [
            {"id": "llama3.2", "label": "Llama 3.2"},
            {"id": "llama3.1", "label": "Llama 3.1"},
            {"id": "qwen2.5", "label": "Qwen 2.5"},
            {"id": "mistral", "label": "Mistral"},
            {"id": "deepseek-r1", "label": "DeepSeek R1"},
            {"id": "codellama", "label": "Code Llama"},
        ],
        "default_model": "llama3.2",
    },
    {
        "id": "local_gguf",
        "name": "Local GGUF (free fallback)",
        "rank": 10,
        "tier": "local_free",
        "env": "",
        "requires_api_key": False,
        "docs": "https://github.com/ggerganov/llama.cpp",
        "note": "Always-on free fallback when cloud keys are missing or unpaid. Limited vs frontier APIs.",
        "models": [
            {"id": "qwen2.5-0.5b", "label": "Qwen2.5 0.5B (tiny)"},
            {"id": "qwen2.5-1.5b", "label": "Qwen2.5 1.5B"},
            {"id": "qwen2.5-3b", "label": "Qwen2.5 3B"},
            {"id": "llama-3.2-1b", "label": "Llama 3.2 1B"},
            {"id": "local-gguf", "label": "Configured GGUF path"},
        ],
        "default_model": "qwen2.5-0.5b",
    },
]


def _mask_key(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "••••" + raw[-2:]
    return raw[:4] + "…" + raw[-4:]


def _key_configured(provider_id: str, env: str) -> bool:
    if not env:
        return True  # local free
    return bool(get_secret(provider_id, env))


def resolve_plugin_id(catalog_id: str) -> str:
    """Map catalog id → installed provider plugin id."""
    for p in TOP_PROVIDERS:
        if p["id"] == catalog_id:
            return str(p.get("plugin") or catalog_id)
    return catalog_id


def catalog_status() -> dict[str, Any]:
    """Full catalog + which keys/models are active on this host."""
    cfg = load_config()
    llm = load_llm_config()
    active_provider = str(cfg.get("provider") or llm.get("active_provider") or "gemini")
    active_model = str(cfg.get("model") or "")
    providers_cfg = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}

    out_providers = []
    for p in TOP_PROVIDERS:
        pid = p["id"]
        plugin = resolve_plugin_id(pid)
        pcfg = providers_cfg.get(plugin) or providers_cfg.get(pid) or {}
        configured_model = ""
        if isinstance(pcfg, dict):
            configured_model = str(pcfg.get("model") or "")
        has_key = _key_configured(plugin if plugin != "openrouter" or pid == "openrouter" else pid, p["env"])
        # Mistral maps to openrouter — check openrouter key if mistral selected
        if pid == "mistral":
            has_key = _key_configured("openrouter", "OPENROUTER_API_KEY") or _key_configured(
                "mistral", "MISTRAL_API_KEY"
            )
        secret_raw = ""
        if p["requires_api_key"]:
            secret_raw = get_secret(plugin if pid != "mistral" else "openrouter", p["env"] or "OPENROUTER_API_KEY")
            if pid == "mistral" and not secret_raw:
                secret_raw = get_secret("openrouter", "OPENROUTER_API_KEY")
        out_providers.append(
            {
                **{k: v for k, v in p.items() if k != "plugin"},
                "plugin_id": plugin,
                "has_api_key": bool(has_key) if p["requires_api_key"] else True,
                "api_key_preview": _mask_key(secret_raw) if p["requires_api_key"] else "",
                "configured_model": configured_model or p["default_model"],
                "selected": active_provider in {pid, plugin},
                "enabled": True if not isinstance(pcfg, dict) else pcfg.get("enabled", True) is not False,
            }
        )

    # Fallback chain description
    order = list(llm.get("fallback_order") or DEFAULT_FALLBACK_ORDER)
    return {
        "ok": True,
        "version": __version__,
        "active": {
            "provider": active_provider,
            "model": active_model
            or next(
                (x["configured_model"] for x in out_providers if x["selected"]),
                "local-gguf",
            ),
            "tier": next(
                (x["tier"] for x in out_providers if x["selected"]),
                "local_free",
            ),
        },
        "fallback_order": order,
        "note": (
            "Cloud API keys unlock top agentic performance. "
            "Local GGUF/Ollama remain free fallbacks when keys are missing or unpaid."
        ),
        "providers": out_providers,
    }


def apply_llm_selection(
    *,
    provider: str,
    model: str = "",
    api_key: str = "",
    set_fallback: bool = True,
) -> dict[str, Any]:
    """Persist provider + model (+ optional API key) for chat/agent harness."""
    provider = (provider or "").strip().lower()
    model = (model or "").strip()
    api_key = (api_key or "").strip()

    entry = next((p for p in TOP_PROVIDERS if p["id"] == provider), None)
    if entry is None:
        valid = [p["id"] for p in TOP_PROVIDERS]
        return {"ok": False, "error": f"unknown provider; choose one of {valid}"}

    plugin = resolve_plugin_id(provider)
    if not model:
        model = str(entry.get("default_model") or "")

    # Validate model is in catalog list (allow custom if user pastes openrouter id)
    known = {m["id"] for m in entry.get("models") or []}
    if known and model and model not in known and provider not in {"openrouter", "mistral", "ollama"}:
        # still allow but warn
        pass

    if entry.get("requires_api_key") and api_key:
        # Store under plugin id for fallback.py get_secret
        save_key_id = plugin
        if provider == "mistral":
            # Prefer openrouter for mistral models
            save_key_id = "openrouter"
        save_secret(save_key_id, api_key)
        if provider == "gemini":
            # also common alias
            pass
    elif entry.get("requires_api_key"):
        # Ensure key exists if selecting cloud
        env = str(entry.get("env") or "")
        existing = get_secret(plugin if provider != "mistral" else "openrouter", env or "OPENROUTER_API_KEY")
        if not existing and provider != "mistral":
            existing = get_secret(provider, env)
        if not existing:
            return {
                "ok": False,
                "error": (
                    f"API key required for {entry['name']}. "
                    f"Paste a key (env {entry.get('env')}) or pick Ollama / Local GGUF for free use."
                ),
                "docs": entry.get("docs"),
            }

    # Update config.json primary
    cfg = load_config()
    cfg["provider"] = plugin if provider != "mistral" else "openrouter"
    cfg["model"] = model
    save_config(cfg)

    # Update llm.json
    from sophyane.providers.fallback import LLM_CONFIG_FILE
    from sophyane.config import save_json

    llm = load_llm_config()
    llm["active_provider"] = cfg["provider"]
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}
    pcfg = dict(providers.get(cfg["provider"]) or {})
    pcfg["enabled"] = True
    pcfg["model"] = model
    if entry.get("env"):
        pcfg["api_key_env"] = [entry["env"]]
    providers[cfg["provider"]] = pcfg
    llm["providers"] = providers

    if set_fallback:
        # Selected cloud first, other clouds, free local last
        order: list[str] = []
        def add(n: str) -> None:
            n = n.strip().lower()
            if n and n not in order:
                order.append(n)

        add(cfg["provider"])
        for pid in DEFAULT_FALLBACK_ORDER:
            add(pid)
        add("ollama")
        add("local_gguf")
        llm["fallback_order"] = order

    save_json(LLM_CONFIG_FILE, llm)

    return {
        "ok": True,
        "message": f"Active model set to {cfg['provider']} / {model}. Local free models remain as fallback.",
        "active": {"provider": cfg["provider"], "model": model},
        "status": catalog_status(),
    }


def clear_provider_key(provider: str) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    plugin = resolve_plugin_id(provider)
    secrets = load_secrets()
    removed = False
    for key in {provider, plugin}:
        if key in secrets:
            del secrets[key]
            removed = True
    if removed:
        from sophyane.config import save_json, SECRETS_FILE

        save_json(SECRETS_FILE, secrets, private=True)
    return {"ok": True, "removed": removed, "status": catalog_status()}
