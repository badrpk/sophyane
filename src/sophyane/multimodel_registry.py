"""Explicit model discovery for the authorized Sophyane Race Mode."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
from pathlib import Path
from typing import Any

from sophyane.intelligence_authority import ACTIVE_INTELLIGENCE_PROVIDERS


ANDROID_LLAMA_CLI = (
    Path.home()
    / ".local/share/sophyane/models/llama.cpp/source/build/bin/llama-cli"
)
DEFAULT_LOCAL_SLOTS = (
    {
        "id": "local_gguf:qwen",
        "name": "Qwen2.5-1.5B",
        "model": "qwen2.5-1.5b-instruct-q4_k_m",
        "path": str(
            Path.home()
            / ".local/share/sophyane/models/gguf/qwen2.5-1.5b-instruct-q4_k_m.gguf"
        ),
    },
    {
        "id": "local_gguf:tinyllama",
        "name": "TinyLlama Chat",
        "model": "tinyllama-chat.q4_k_m",
        "path": str(Path.home() / "models/tinyllama-chat.q4_k_m.gguf"),
    },
)
MAX_RACE_MODELS = 13  # Codex + ten NIFDU sites + two local slots.


def preferred_llama_cli(*, explicit: str | Path = "") -> Path:
    """Choose the working Android build before any legacy runtime launcher."""
    override = str(
        explicit
        or os.environ.get("SOPHYANE_MULTIMODEL_LLAMA_CLI")
        or ""
    ).strip()
    if override:
        return Path(override).expanduser()
    if ANDROID_LLAMA_CLI.is_file() and os.access(ANDROID_LLAMA_CLI, os.X_OK):
        return ANDROID_LLAMA_CLI
    return Path(
        os.environ.get("SOPHYANE_LLAMA_CLI")
        or Path.home() / ".local/share/sophyane/models/llama.cpp/runtime/llama-cli"
    ).expanduser()


def llama_cli_environment(
    cli_path: str | Path,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a subprocess environment with the CLI's shared libraries found."""
    result = dict(os.environ if environ is None else environ)
    directory = str(Path(cli_path).expanduser().resolve().parent)
    current = [part for part in result.get("LD_LIBRARY_PATH", "").split(os.pathsep) if part]
    if directory not in current:
        current.insert(0, directory)
    result["LD_LIBRARY_PATH"] = os.pathsep.join(current)
    return result


def valid_gguf_file(path: str | Path) -> bool:
    """Reject absent, truncated, or structurally empty GGUF files."""
    candidate = Path(path).expanduser()
    try:
        if candidate.stat().st_size < 1_000_000:
            return False
        with candidate.open("rb") as source:
            header = source.read(24)
        if len(header) != 24 or header[:4] != b"GGUF":
            return False
        version, tensor_count, metadata_count = struct.unpack("<IQQ", header[4:24])
        return version in {2, 3} and tensor_count > 0 and metadata_count > 0
    except (OSError, struct.error, ValueError):
        return False


def _nifdu_bridge_profiles(bridge_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    path = Path(bridge_path).expanduser() if bridge_path else (
        Path.home() / "nifdu/tools/nifdu_browser_bridge.py"
    )
    if not path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("_sophyane_nifdu_profiles", path)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return {}
    profiles = getattr(module, "PROFILES", None)
    ask = getattr(module, "ask", None)
    if not isinstance(profiles, dict) or not callable(ask):
        return {}
    return {
        str(site): value
        for site, value in profiles.items()
        if isinstance(site, str) and site and isinstance(value, dict)
    }


def discover_nifdu_models(
    *, bridge_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Discover only site routes exported by the installed NIFDU bridge."""
    profiles = _nifdu_bridge_profiles(bridge_path)
    return [
        {
            "id": f"nifdu_browser:{site}",
            "provider_id": "nifdu_browser",
            "site": site,
            "model": f"nifdu-site:{site}",
            "display_name": f"NIFDU Browser ({profile.get('label') or site})",
            # `available` means the supported site route and bridge exist.
            # Authentication/readiness is checked by the provider on use.
            "available": True,
            "availability": "registered",
        }
        for site, profile in sorted(profiles.items())
    ]


def _configured_local_slots(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw: Any = (config or {}).get("local_model_slots")
    if raw is None:
        env_slots = os.environ.get("SOPHYANE_LOCAL_MODEL_SLOTS", "").strip()
        if env_slots:
            try:
                raw = json.loads(env_slots)
            except json.JSONDecodeError as error:
                raise ValueError("SOPHYANE_LOCAL_MODEL_SLOTS must be valid JSON") from error
    if raw is None:
        raw = list(DEFAULT_LOCAL_SLOTS)
    if not isinstance(raw, (list, tuple)):
        raise ValueError("local_model_slots must be a list")
    if len(raw) > 2:
        raise ValueError("local_model_slots supports at most two configured slots")
    result = []
    for item in raw:
        if isinstance(item, str):
            path = Path(item).expanduser()
            item = {"id": f"local_gguf:{path.stem}", "name": path.stem, "model": path.stem, "path": str(path)}
        if not isinstance(item, dict):
            raise ValueError("each local model slot must be a path or object")
        model_id = str(item.get("id") or "").strip()
        path_value = str(item.get("path") or "").strip()
        if not model_id.startswith("local_gguf:") or not path_value:
            raise ValueError("local model slots require a local_gguf:<name> id and path")
        result.append({**item, "id": model_id, "path": str(Path(path_value).expanduser())})
    if len({item["id"] for item in result}) != len(result):
        raise ValueError("local model slot IDs must be unique")
    return result


def discover_local_models(
    config: dict[str, Any] | None = None,
    *,
    cli_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return configured, structurally valid local GGUF slots only."""
    cli = preferred_llama_cli(explicit=cli_path or "")
    cli_available = cli.is_file() and os.access(cli, os.X_OK)
    result = []
    for item in _configured_local_slots(config):
        path = Path(item["path"])
        if not valid_gguf_file(path):
            continue
        result.append(
            {
                "id": item["id"],
                "provider_id": "local_gguf",
                "model": str(item.get("model") or path.stem),
                "display_name": str(item.get("name") or path.stem),
                "gguf_path": str(path),
                "cli_path": str(cli),
                "available": cli_available,
                "availability": "ready" if cli_available else "llama_cli_missing",
                "reasoning": str(item.get("reasoning") or "off"),
                "max_tokens": max(32, min(512, int(item.get("max_tokens") or 192))),
                "timeout": max(3, min(300, int(item.get("timeout") or 60))),
            }
        )
    return result


def discover_models(
    config: dict[str, Any] | None = None,
    *,
    nifdu_bridge_path: str | Path | None = None,
    cli_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return redaction-safe identities for all installed route types."""
    configured_codex = os.environ.get("SOPHYANE_CODEX_CLI", "").strip()
    codex = shutil.which("codex")
    if configured_codex:
        configured_path = Path(configured_codex).expanduser()
        if configured_path.is_file() and os.access(configured_path, os.X_OK):
            codex = str(configured_path)
        else:
            codex = shutil.which(configured_codex)
    rows = [
        {
            "id": "codex_cli",
            "provider_id": "codex_cli",
            "model": os.environ.get("SOPHYANE_CODEX_MODEL", "codex-default"),
            "display_name": "Codex CLI",
            "available": bool(codex),
            "availability": "ready" if codex else "executable_missing",
        }
    ]
    rows.extend(discover_nifdu_models(bridge_path=nifdu_bridge_path))
    rows.extend(discover_local_models(config, cli_path=cli_path))
    return rows


def build_race_model_routes(
    config: dict[str, Any],
    *,
    catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Validate an explicit route list and map models to race worker IDs."""
    selected = config.get("race_models")
    if not isinstance(selected, (list, tuple)) or not selected:
        raise ValueError("race_models must explicitly select one or more model IDs")
    if len(selected) > MAX_RACE_MODELS:
        raise ValueError(f"race_models supports at most {MAX_RACE_MODELS} registered routes")
    rows = catalog if catalog is not None else discover_models(config)
    indexed = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    if len(indexed) != len(rows):
        raise ValueError("model catalog contains duplicate or invalid IDs")
    routes = []
    seen = set()
    for raw_id in selected:
        model_id = str(raw_id or "").strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        row = indexed.get(model_id)
        if row is None:
            raise ValueError(f"unknown model ID: {model_id}")
        provider_id = str(row.get("provider_id") or "")
        if provider_id not in ACTIVE_INTELLIGENCE_PROVIDERS:
            raise ValueError(f"unauthorized provider route: {provider_id}")
        if provider_id == "local_gguf":
            worker_id = "local:" + model_id.split(":", 1)[1]
        elif provider_id == "nifdu_browser":
            worker_id = "browser:" + str(row.get("site") or model_id.split(":", 1)[1])
        else:
            worker_id = "harness:codex_cli"
        if not row.get("available"):
            row = {**row, "unavailable_reason": str(row.get("availability") or "provider unavailable")}
        routes.append({**row, "worker_id": worker_id})
    return routes


def verify_math_answer(prompt: str, actual: str) -> bool:
    """Independently verify the one fixed arithmetic acceptance task."""
    expected_prompt = "Calculate 3 * 3 - 3. Reply with only the number."
    if str(prompt).strip() != expected_prompt:
        return False
    return str(actual or "").strip() == "6"

