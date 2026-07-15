"""Hardware-fit local LLM policy: recommend → user approval → download.

- Profiles RAM/disk/CPU and picks open GGUF size that fits.
- Larger machines get larger/stronger local models offered automatically.
- Never downloads without explicit user approval (except already-installed).
- Users who prefer frontier APIs only can disable local models.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from sophyane.config import CONFIG_DIR, load_config, load_json, save_config, save_json
from sophyane.local_runtime import (
    GGUF_DIR,
    GGUF_STATE_FILE,
    HF_GGUF_CATALOG,
    HfGgufSpec,
    choose_hf_gguf,
    download_hf_gguf,
    list_hf_gguf_for_hardware,
    llama_server_reachable,
    persist_gguf_state,
    persist_local_provider,
    profile_hardware,
    start_llama_server,
    install_llama_cpp,
)
from sophyane.llm_catalog import apply_llm_selection
from sophyane.version import __version__

PREFS_FILE = CONFIG_DIR / "hardware_fit.json"
DOWNLOAD_STATE = Path.home() / ".local" / "state" / "sophyane" / "hardware_fit_download.json"

_download_lock = threading.Lock()
_download_thread: threading.Thread | None = None


def _default_prefs() -> dict[str, Any]:
    return {
        "prefer_api_only": False,
        "local_enabled": True,
        "auto_offer_upgrade": True,
        "last_offer_key": "",
        "last_offer_at": 0,
        "approved_keys": [],
        "declined_keys": [],
    }


def load_prefs() -> dict[str, Any]:
    data = load_json(PREFS_FILE)
    prefs = _default_prefs()
    if isinstance(data, dict):
        prefs.update(data)
    return prefs


def save_prefs(prefs: dict[str, Any]) -> None:
    save_json(PREFS_FILE, prefs)


def _write_download_state(payload: dict[str, Any]) -> None:
    DOWNLOAD_STATE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_STATE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def download_status() -> dict[str, Any]:
    if not DOWNLOAD_STATE.exists():
        return {"active": False, "status": "idle"}
    try:
        data = json.loads(DOWNLOAD_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"active": False, "status": "idle"}
    except Exception:  # noqa: BLE001
        return {"active": False, "status": "idle"}


def _spec_by_key(key: str) -> HfGgufSpec | None:
    for specs in HF_GGUF_CATALOG.values():
        for spec in specs:
            if spec.key == key:
                return spec
    return None


def current_local_model() -> dict[str, Any]:
    state = load_json(GGUF_STATE_FILE) if GGUF_STATE_FILE.exists() else {}
    cfg = load_config()
    installed = []
    if GGUF_DIR.exists():
        for path in sorted(GGUF_DIR.glob("*.gguf")):
            if path.stat().st_size > 1024 * 1024:
                installed.append(
                    {
                        "filename": path.name,
                        "path": str(path),
                        "size_mb": path.stat().st_size // (1024 * 1024),
                    }
                )
    return {
        "active_provider": cfg.get("provider"),
        "active_model": cfg.get("model"),
        "gguf_state": state,
        "installed_ggufs": installed,
        "llama_server_up": llama_server_reachable(1.5),
    }


def hardware_fit_status() -> dict[str, Any]:
    profile = profile_hardware()
    prefs = load_prefs()
    models = list_hf_gguf_for_hardware(profile)
    recommended = next((m for m in models if m.get("recommended")), models[0] if models else None)
    current = current_local_model()
    upgrade_offer = None
    if (
        prefs.get("local_enabled")
        and not prefs.get("prefer_api_only")
        and prefs.get("auto_offer_upgrade")
        and recommended
        and not recommended.get("installed")
        and recommended.get("fits_ram")
        and recommended.get("fits_disk")
        and recommended.get("key") not in (prefs.get("declined_keys") or [])
    ):
        upgrade_offer = {
            "key": recommended["key"],
            "notes": recommended["notes"],
            "size_mb": recommended["size_mb"],
            "min_ram_mb": recommended["min_ram_mb"],
            "message": (
                f"Your hardware tier is **{profile.tier}** "
                f"({profile.ram_mb}MB RAM, {profile.disk_free_mb}MB free disk). "
                f"Sophyane can download a stronger local model "
                f"`{recommended['key']}` (~{recommended['size_mb']}MB) after you approve. "
                "No download starts without your OK."
            ),
        }

    return {
        "ok": True,
        "version": __version__,
        "hardware": {
            "arch": profile.arch,
            "cpus": profile.cpus,
            "ram_mb": profile.ram_mb,
            "disk_free_mb": profile.disk_free_mb,
            "os_name": profile.os_name,
            "virtualization": profile.virtualization,
            "tier": profile.tier,
            "tier_meaning": {
                "nano": "very constrained — tiny models only",
                "micro": "light machine — sub-1B models",
                "small": "1–3B class fits",
                "standard": "3B+ class fits",
                "pro": "strong desktop — 7–8B class offered",
            }.get(profile.tier, profile.tier),
        },
        "prefs": {
            "prefer_api_only": bool(prefs.get("prefer_api_only")),
            "local_enabled": bool(prefs.get("local_enabled")),
            "auto_offer_upgrade": bool(prefs.get("auto_offer_upgrade")),
        },
        "recommended": recommended,
        "upgrade_offer": upgrade_offer,
        "models": models,
        "current": current,
        "download": download_status(),
        "policy": (
            "Hardware-fit local LLMs scale with your machine. "
            "Larger RAM/disk → stronger GGUF offered. "
            "Downloads require explicit approval. "
            "Choose API-only if you only want frontier cloud models."
        ),
    }


def cfg_model_guess() -> str:
    cfg = load_config()
    return str(cfg.get("model") or "")


def set_mode(*, prefer_api_only: bool | None = None, local_enabled: bool | None = None) -> dict[str, Any]:
    prefs = load_prefs()
    if prefer_api_only is not None:
        prefs["prefer_api_only"] = bool(prefer_api_only)
        if prefer_api_only:
            prefs["local_enabled"] = False
    if local_enabled is not None:
        prefs["local_enabled"] = bool(local_enabled)
        if local_enabled:
            prefs["prefer_api_only"] = False
    save_prefs(prefs)

    # When enabling API-only, keep config on a cloud provider if one has a key
    if prefs.get("prefer_api_only"):
        cfg = load_config()
        # Don't force switch if already on cloud; if on local, try xai/openai/gemini via catalog
        if str(cfg.get("provider") or "") in {"local_gguf", "ollama", ""}:
            from sophyane.config import get_secret

            for pid, env in (
                ("openai", "OPENAI_API_KEY"),
                ("anthropic", "ANTHROPIC_API_KEY"),
                ("gemini", "GEMINI_API_KEY"),
                ("xai", "XAI_API_KEY"),
            ):
                if get_secret(pid, env):
                    apply_llm_selection(provider=pid, model="")
                    break
    elif prefs.get("local_enabled"):
        # Ensure local is in fallback; activate if no cloud preferred
        pass

    return {"ok": True, "prefs": prefs, "status": hardware_fit_status()}


def decline_offer(model_key: str) -> dict[str, Any]:
    prefs = load_prefs()
    declined = list(prefs.get("declined_keys") or [])
    if model_key and model_key not in declined:
        declined.append(model_key)
    prefs["declined_keys"] = declined
    prefs["last_offer_key"] = model_key
    prefs["last_offer_at"] = time.time()
    save_prefs(prefs)
    return {"ok": True, "message": f"Declined auto-offer for {model_key}. You can still install later.", "status": hardware_fit_status()}


def approve_and_install(model_key: str, *, background: bool = True) -> dict[str, Any]:
    """User approved download of a hardware-fit GGUF. Never called without consent."""
    prefs = load_prefs()
    if prefs.get("prefer_api_only"):
        return {
            "ok": False,
            "error": "API-only mode is on. Turn on local models first, or pick a cloud provider under Models.",
        }
    if not prefs.get("local_enabled", True):
        return {"ok": False, "error": "Local models are disabled in preferences."}

    spec = _spec_by_key(model_key) if model_key else choose_hf_gguf()
    if model_key and spec is None:
        return {"ok": False, "error": f"unknown model key: {model_key}"}
    assert spec is not None

    profile = profile_hardware()
    if profile.ram_mb < spec.min_ram_mb:
        return {
            "ok": False,
            "error": (
                f"Not enough RAM for {spec.key}: need ~{spec.min_ram_mb}MB, "
                f"have {profile.ram_mb}MB. Pick a smaller model."
            ),
        }
    if profile.disk_free_mb < spec.size_mb + 150:
        return {
            "ok": False,
            "error": (
                f"Not enough free disk for {spec.key}: need ~{spec.size_mb + 150}MB free, "
                f"have {profile.disk_free_mb}MB."
            ),
        }

    approved = list(prefs.get("approved_keys") or [])
    if spec.key not in approved:
        approved.append(spec.key)
    prefs["approved_keys"] = approved
    prefs["local_enabled"] = True
    prefs["prefer_api_only"] = False
    save_prefs(prefs)

    st = download_status()
    if st.get("active") and st.get("status") == "running":
        return {"ok": True, "message": "A download is already running.", "download": st}

    def _run() -> None:
        log: list[str] = []

        def progress(msg: str) -> None:
            log.append(msg)
            _write_download_state(
                {
                    "active": True,
                    "status": "running",
                    "model_key": spec.key,
                    "message": msg,
                    "log": log[-40:],
                    "started_at": started,
                    "updated_at": time.time(),
                }
            )

        started = time.time()
        progress(f"User approved download of {spec.key} (~{spec.size_mb}MB)")
        try:
            with _download_lock:
                gguf_path = download_hf_gguf(spec, progress=progress)
                progress("Installing/checking llama.cpp runtime…")
                binaries = install_llama_cpp(progress)
                try:
                    start_llama_server(gguf_path, progress=progress, binaries=binaries)
                    progress("llama-server ready")
                except Exception as error:  # noqa: BLE001
                    progress(f"llama-server start deferred: {error}")
                persist_gguf_state(
                    model_key=spec.key,
                    gguf_path=gguf_path,
                    server=binaries.get("server", ""),
                    cli=binaries.get("cli", ""),
                )
                persist_local_provider(spec.key, provider="local_gguf")
                apply_llm_selection(provider="local_gguf", model=spec.key)
            _write_download_state(
                {
                    "active": False,
                    "status": "done",
                    "model_key": spec.key,
                    "message": f"Installed and activated {spec.key}",
                    "log": log[-40:],
                    "started_at": started,
                    "updated_at": time.time(),
                    "ok": True,
                }
            )
        except Exception as error:  # noqa: BLE001
            _write_download_state(
                {
                    "active": False,
                    "status": "error",
                    "model_key": spec.key,
                    "message": str(error),
                    "log": log[-40:],
                    "started_at": started,
                    "updated_at": time.time(),
                    "ok": False,
                }
            )

    global _download_thread
    if background:
        _download_thread = threading.Thread(target=_run, daemon=True, name="sophyane-gguf-download")
        _download_thread.start()
        return {
            "ok": True,
            "message": (
                f"Approved. Downloading `{spec.key}` (~{spec.size_mb}MB) in the background. "
                "Watch status under Local / hardware-fit."
            ),
            "model_key": spec.key,
            "download": download_status(),
        }

    _run()
    return {"ok": True, "download": download_status(), "status": hardware_fit_status()}
