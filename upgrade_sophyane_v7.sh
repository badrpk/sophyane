#!/usr/bin/env bash
set -Eeuo pipefail

BASE="$HOME/.local/share/sophyane-v7"
BIN="$HOME/.local/bin"
APP="$BASE/sophyane_v7.py"
CFG_DIR="$HOME/.config/sophyane"
STATE_DIR="$HOME/.local/state/sophyane"
BACKUP="$BIN/sophyane-6.1-backup"
CURRENT="$BIN/sophyane"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BASE" "$BIN" "$CFG_DIR" "$STATE_DIR/checkpoints" "$STATE_DIR/logs"

if [ -e "$CURRENT" ] && [ ! -e "$BACKUP" ]; then
  cp -a "$CURRENT" "$BACKUP"
fi
if [ -e "$CURRENT" ]; then
  cp -a "$CURRENT" "$STATE_DIR/sophyane.launcher.$STAMP.bak"
fi

cat > "$APP" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import queue
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

VERSION = "7.0.0"
HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "sophyane"
STATE_DIR = HOME / ".local" / "state" / "sophyane"
CHECKPOINT_DIR = STATE_DIR / "checkpoints"
LOG_DIR = STATE_DIR / "logs"
CONFIG_FILE = CONFIG_DIR / "llm.json"
PROJECT_FILE = STATE_DIR / "project.json"
METRICS_DB = STATE_DIR / "metrics.sqlite3"
LEGACY = HOME / ".local" / "bin" / "sophyane-6.1-backup"

for directory in (CONFIG_DIR, STATE_DIR, CHECKPOINT_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: dict[str, Any] = {
    "active_provider": "gemini",
    "fallback_order": ["gemini", "anthropic", "xai", "openai"],
    "request": {
        "timeout_seconds": 75,
        "max_retries": 2,
        "backoff_base_seconds": 1.0,
        "temperature": 0.25,
        "max_output_tokens": 4096
    },
    "routing": {
        "mode": "automatic",
        "parallel_consensus": False,
        "prefer_low_latency": True,
        "task_rules": {
            "coding": ["anthropic", "openai", "gemini", "xai"],
            "reasoning": ["openai", "anthropic", "gemini", "xai"],
            "fast": ["gemini", "xai", "openai", "anthropic"],
            "general": ["gemini", "anthropic", "xai", "openai"]
        }
    },
    "providers": {
        "gemini": {
            "enabled": True,
            "api_key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "model": "gemini-2.5-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta"
        },
        "anthropic": {
            "enabled": True,
            "api_key_env": ["ANTHROPIC_API_KEY"],
            "model": "claude-sonnet-4-5",
            "base_url": "https://api.anthropic.com/v1"
        },
        "xai": {
            "enabled": True,
            "api_key_env": ["XAI_API_KEY"],
            "model": "grok-4",
            "base_url": "https://api.x.ai/v1"
        },
        "openai": {
            "enabled": True,
            "api_key_env": ["OPENAI_API_KEY"],
            "model": "gpt-5-mini",
            "base_url": "https://api.openai.com/v1"
        }
    }
}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        atomic_write(CONFIG_FILE, json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        broken = CONFIG_FILE.with_suffix(f".broken.{int(time.time())}.json")
        shutil.copy2(CONFIG_FILE, broken)
        print(f"⚠ Invalid config backed up to {broken}: {exc}", file=sys.stderr)
        loaded = {}
    merged = deep_merge(DEFAULT_CONFIG, loaded)
    atomic_write(CONFIG_FILE, json.dumps(merged, indent=2) + "\n")
    return merged


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, handler: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def publish_event(self, sender: str, event_type: str, payload: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        self._queue.put({
            "id": event_id,
            "sender": sender,
            "type": event_type,
            "payload": payload,
            "timestamp": time.time()
        })
        return event_id

    def drain(self) -> int:
        count = 0
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            for handler in list(self._subscribers.get(event["type"], [])):
                try:
                    handler(event)
                except Exception:
                    traceback.print_exc()
            count += 1
        return count


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    attempts: int
    fallback_used: bool
    request_id: str


class MetricsStore:
    def __init__(self, path: Path = METRICS_DB) -> None:
        self.path = path
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    error TEXT
                )
            """)

    def record(self, request_id: str, provider: str, model: str,
               success: bool, latency_ms: float, error: str = "") -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request_id, time.time(), provider, model, int(success), latency_ms, error[:1000])
            )

    def summary(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("""
                SELECT provider,
                       COUNT(*) AS calls,
                       ROUND(100.0 * AVG(success), 1) AS success_pct,
                       ROUND(AVG(latency_ms), 1) AS avg_latency_ms
                FROM calls GROUP BY provider ORDER BY provider
            """).fetchall()
        return [
            {"provider": r[0], "calls": r[1], "success_pct": r[2], "avg_latency_ms": r[3]}
            for r in rows
        ]


class HTTPError(RuntimeError):
    pass


def http_json(method: str, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise HTTPError(f"HTTP {exc.code}: {raw[:1500]}") from exc
    except urllib.error.URLError as exc:
        raise HTTPError(f"Network error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPError(f"Invalid JSON response from {url}") from exc


class ProviderAdapter:
    name = "base"

    def __init__(self, config: dict[str, Any], request_config: dict[str, Any]) -> None:
        self.config = config
        self.request_config = request_config
        self.model = str(config["model"])
        self.base_url = str(config["base_url"]).rstrip("/")

    def api_key(self) -> str:
        for variable in self.config.get("api_key_env", []):
            value = os.getenv(variable, "").strip()
            if value:
                return value
        raise RuntimeError(f"No API key found for {self.name}; set one of {self.config.get('api_key_env', [])}")

    def generate(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError

    @staticmethod
    def system_and_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        system_parts: list[str] = []
        normal: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
            else:
                normal.append({"role": role, "content": content})
        return "\n\n".join(system_parts), normal


class GeminiAdapter(ProviderAdapter):
    name = "gemini"

    def generate(self, messages: list[dict[str, str]]) -> str:
        key = self.api_key()
        system, normal = self.system_and_messages(messages)
        contents = []
        for msg in normal:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.request_config["temperature"],
                "maxOutputTokens": self.request_config["max_output_tokens"]
            }
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = http_json(
            "POST",
            f"{self.base_url}/models/{self.model}:generateContent?key={key}",
            {"Content-Type": "application/json"}, payload,
            int(self.request_config["timeout_seconds"])
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates: {data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if not text:
            raise RuntimeError(f"Gemini returned empty content: {data}")
        return text


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def generate(self, messages: list[dict[str, str]]) -> str:
        system, normal = self.system_and_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.request_config["max_output_tokens"],
            "temperature": self.request_config["temperature"],
            "messages": normal
        }
        if system:
            payload["system"] = system
        data = http_json(
            "POST", f"{self.base_url}/messages",
            {
                "Content-Type": "application/json",
                "x-api-key": self.api_key(),
                "anthropic-version": "2023-06-01"
            }, payload, int(self.request_config["timeout_seconds"])
        )
        text = "".join(
            str(block.get("text", "")) for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError(f"Anthropic returned empty content: {data}")
        return text


class OpenAICompatibleAdapter(ProviderAdapter):
    authorization = "Bearer"

    def generate(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.request_config["temperature"],
            "max_tokens": self.request_config["max_output_tokens"]
        }
        data = http_json(
            "POST", f"{self.base_url}/chat/completions",
            {
                "Content-Type": "application/json",
                "Authorization": f"{self.authorization} {self.api_key()}"
            }, payload, int(self.request_config["timeout_seconds"])
        )
        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise RuntimeError(f"{self.name} returned unexpected content: {data}") from exc
        if not text:
            raise RuntimeError(f"{self.name} returned empty content")
        return text


class XAIAdapter(OpenAICompatibleAdapter):
    name = "xai"


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def generate(self, messages: list[dict[str, str]]) -> str:
        input_items = []
        for msg in messages:
            input_items.append({
                "role": msg.get("role", "user"),
                "content": [{"type": "input_text", "text": str(msg.get("content", ""))}]
            })
        payload = {
            "model": self.model,
            "input": input_items,
            "temperature": self.request_config["temperature"],
            "max_output_tokens": self.request_config["max_output_tokens"]
        }
        data = http_json(
            "POST", f"{self.base_url}/responses",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key()}"
            }, payload, int(self.request_config["timeout_seconds"])
        )
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"].strip()
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    chunks.append(str(content.get("text", "")))
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError(f"OpenAI returned empty content: {data}")
        return text


ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "gemini": GeminiAdapter,
    "anthropic": AnthropicAdapter,
    "claude": AnthropicAdapter,
    "xai": XAIAdapter,
    "grok": XAIAdapter,
    "openai": OpenAIAdapter
}


class LLMClient:
    def __init__(self, config: dict[str, Any], bus: EventBus, metrics: MetricsStore) -> None:
        self.config = config
        self.bus = bus
        self.metrics = metrics
        self.active_provider = self._canonical(config.get("active_provider", "gemini"))

    @staticmethod
    def _canonical(provider: str) -> str:
        return {"claude": "anthropic", "grok": "xai"}.get(provider.lower(), provider.lower())

    def switch(self, provider: str) -> None:
        provider = self._canonical(provider)
        if provider not in self.config["providers"]:
            raise ValueError(f"Unknown provider '{provider}'. Available: {', '.join(self.config['providers'])}")
        if not self.config["providers"][provider].get("enabled", True):
            raise ValueError(f"Provider '{provider}' is disabled")
        self.active_provider = provider
        self.config["active_provider"] = provider
        atomic_write(CONFIG_FILE, json.dumps(self.config, indent=2) + "\n")

    def available(self) -> list[str]:
        available = []
        for name, provider in self.config["providers"].items():
            if not provider.get("enabled", True):
                continue
            if any(os.getenv(var, "").strip() for var in provider.get("api_key_env", [])):
                available.append(name)
        return available

    @staticmethod
    def classify(prompt: str) -> str:
        lower = prompt.lower()
        if any(token in lower for token in ("code", "python", "bash", "debug", "compile", "function", "class ")):
            return "coding"
        if any(token in lower for token in ("prove", "reason", "analyze", "logic", "calculate", "derive")):
            return "reasoning"
        if len(prompt) < 180:
            return "fast"
        return "general"

    def provider_order(self, prompt: str, requested: str | None = None) -> list[str]:
        requested = self._canonical(requested) if requested else None
        routing = self.config.get("routing", {})
        if requested:
            head = [requested]
        elif routing.get("mode") == "automatic":
            task = self.classify(prompt)
            head = [self._canonical(x) for x in routing.get("task_rules", {}).get(task, [])]
            if self.active_provider not in head:
                head.insert(0, self.active_provider)
        else:
            head = [self.active_provider]
        tail = [self._canonical(x) for x in self.config.get("fallback_order", [])]
        result: list[str] = []
        for name in head + tail:
            if name in self.config["providers"] and name not in result:
                if self.config["providers"][name].get("enabled", True):
                    result.append(name)
        return result

    def _adapter(self, provider: str) -> ProviderAdapter:
        provider = self._canonical(provider)
        adapter_cls = ADAPTERS[provider]
        return adapter_cls(self.config["providers"][provider], self.config["request"])

    def generate(self, prompt: str, *, provider: str | None = None,
                 system: str = "You are Sophyane, an execution-oriented AI engineering assistant.") -> LLMResult:
        request_id = str(uuid.uuid4())
        order = self.provider_order(prompt, provider)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        self.bus.publish_event("cli", "LLM_REQUEST", {
            "request_id": request_id, "provider_order": order, "prompt_chars": len(prompt)
        })
        errors: list[str] = []
        retries = max(1, int(self.config["request"].get("max_retries", 2)))
        base = float(self.config["request"].get("backoff_base_seconds", 1.0))
        attempts = 0
        for index, name in enumerate(order):
            provider_cfg = self.config["providers"][name]
            if not any(os.getenv(v, "").strip() for v in provider_cfg.get("api_key_env", [])):
                errors.append(f"{name}: missing API key")
                continue
            adapter = self._adapter(name)
            for retry in range(retries):
                attempts += 1
                started = time.perf_counter()
                try:
                    text = adapter.generate(messages)
                    latency = (time.perf_counter() - started) * 1000
                    self.metrics.record(request_id + f"-{attempts}", name, adapter.model, True, latency)
                    result = LLMResult(text, name, adapter.model, latency, attempts, index > 0, request_id)
                    self.bus.publish_event("llm_client", "LLM_RESPONSE", asdict(result))
                    self.bus.drain()
                    return result
                except Exception as exc:
                    latency = (time.perf_counter() - started) * 1000
                    message = f"{name}/{adapter.model}: {exc}"
                    errors.append(message)
                    self.metrics.record(request_id + f"-{attempts}", name, adapter.model, False, latency, str(exc))
                    if retry + 1 < retries:
                        time.sleep(base * (2 ** retry) + random.uniform(0, 0.25))
        self.bus.publish_event("llm_client", "LLM_RESPONSE", {
            "request_id": request_id, "success": False, "errors": errors
        })
        self.bus.drain()
        raise RuntimeError("All LLM providers failed:\n- " + "\n- ".join(errors))


class ProjectManager:
    def __init__(self, path: Path = PROJECT_FILE) -> None:
        self.path = path
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        default = {
            "active_task": "Interactive Sophyane session",
            "paused_tasks": [],
            "completed": [],
            "queued": [],
            "updated_at": time.time()
        }
        if not self.path.exists():
            atomic_write(self.path, json.dumps(default, indent=2) + "\n")
            return default
        try:
            return deep_merge(default, json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            return default

    def save(self) -> None:
        self.state["updated_at"] = time.time()
        atomic_write(self.path, json.dumps(self.state, indent=2) + "\n")

    def checkpoint(self, note: str = "manual checkpoint") -> Path:
        payload = dict(self.state)
        payload["note"] = note
        payload["created_at"] = time.time()
        path = CHECKPOINT_DIR / f"checkpoint-{time.strftime('%Y%m%d-%H%M%S')}.json"
        atomic_write(path, json.dumps(payload, indent=2) + "\n")
        return path

    def progress(self) -> str:
        completed = self.state.get("completed", [])
        queued = self.state.get("queued", [])
        paused = self.state.get("paused_tasks", [])
        total = max(1, len(completed) + len(queued) + len(paused) + 1)
        pct = int(100 * len(completed) / total)
        return (
            f"Project progress: {pct}%\n"
            f"Active: {self.state.get('active_task')}\n"
            f"Completed: {len(completed)} | Queued: {len(queued)} | Paused: {len(paused)}"
        )


class Verifier:
    @staticmethod
    def verify_python_text(text: str) -> tuple[bool, str]:
        blocks = re.findall(r"```(?:python|py)\s*(.*?)```", text, flags=re.S | re.I)
        if not blocks:
            return True, "No Python code block detected."
        failures = []
        for index, block in enumerate(blocks, 1):
            try:
                ast.parse(block)
            except SyntaxError as exc:
                failures.append(f"block {index}: {exc}")
        return (not failures, "Python syntax valid." if not failures else "; ".join(failures))

    @staticmethod
    def self_test() -> tuple[bool, list[str]]:
        checks: list[str] = []
        try:
            json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            checks.append("config JSON: PASS")
        except Exception as exc:
            checks.append(f"config JSON: FAIL ({exc})")
        try:
            ast.parse(Path(__file__).read_text(encoding="utf-8"))
            checks.append("runtime syntax: PASS")
        except Exception as exc:
            checks.append(f"runtime syntax: FAIL ({exc})")
        try:
            with sqlite3.connect(METRICS_DB) as db:
                db.execute("SELECT 1")
            checks.append("metrics database: PASS")
        except Exception as exc:
            checks.append(f"metrics database: FAIL ({exc})")
        return all("PASS" in check for check in checks), checks


class Sophyane:
    def __init__(self) -> None:
        self.config = load_config()
        self.bus = EventBus()
        self.metrics = MetricsStore()
        self.llm = LLMClient(self.config, self.bus, self.metrics)
        self.projects = ProjectManager()
        self.last_result: LLMResult | None = None
        self.bus.subscribe("LLM_REQUEST", self._log_event)
        self.bus.subscribe("LLM_RESPONSE", self._log_event)

    @staticmethod
    def _log_event(event: dict[str, Any]) -> None:
        log = LOG_DIR / "events.jsonl"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def banner(self) -> None:
        provider = self.llm.active_provider
        model = self.config["providers"][provider]["model"]
        print(f"\n🧠 Sophyane {VERSION}")
        print(f"Provider: {provider}")
        print(f"Model: {model}")
        print("Commands: status, progress, /llm status, /llm switch <provider>, /checkpoint, /verify, /legacy, /exit")

    def status(self) -> None:
        active = self.llm.active_provider
        print(f"Sophyane: {VERSION}")
        print(f"Current LLM: {active} / {self.config['providers'][active]['model']}")
        print(f"Routing mode: {self.config['routing']['mode']}")
        print(f"Available providers with keys: {', '.join(self.llm.available()) or 'none'}")
        print(f"Config: {CONFIG_FILE}")
        print(f"State: {STATE_DIR}")
        for row in self.metrics.summary():
            print(f"- {row['provider']}: calls={row['calls']}, success={row['success_pct']}%, avg={row['avg_latency_ms']}ms")

    def command(self, line: str) -> bool:
        stripped = line.strip()
        if stripped in {"/exit", "exit", "quit"}:
            return False
        if stripped in {"status", "/status"}:
            self.status(); return True
        if stripped in {"progress", "/progress"}:
            print(self.projects.progress()); return True
        if stripped.startswith("/llm switch "):
            provider = stripped.split(maxsplit=2)[2]
            self.llm.switch(provider)
            canonical = self.llm.active_provider
            print(f"✓ Switched to {canonical} / {self.config['providers'][canonical]['model']}")
            return True
        if stripped in {"/llm", "/llm status"}:
            self.status(); return True
        if stripped.startswith("/checkpoint"):
            note = stripped[len("/checkpoint"):].strip() or "manual checkpoint"
            print(f"✓ Checkpoint: {self.projects.checkpoint(note)}")
            return True
        if stripped == "/verify":
            ok, checks = Verifier.self_test()
            print("\n".join(checks))
            print("Overall:", "PASS" if ok else "FAIL")
            return True
        if stripped == "/legacy":
            if LEGACY.exists():
                os.execv(str(LEGACY), [str(LEGACY)])
            print(f"Legacy launcher not found: {LEGACY}")
            return True
        if stripped == "/config":
            print(CONFIG_FILE.read_text(encoding="utf-8")); return True
        return self.ask(stripped)

    def ask(self, prompt: str) -> bool:
        if not prompt:
            return True
        self.projects.state["active_task"] = prompt[:200]
        self.projects.save()
        try:
            result = self.llm.generate(prompt)
            self.last_result = result
            print(result.text)
            ok, message = Verifier.verify_python_text(result.text)
            if not ok:
                print(f"\n⚠ Verification: {message}")
            footer = f"\n[{result.provider}/{result.model} • {result.latency_ms:.0f} ms"
            if result.fallback_used:
                footer += " • fallback"
            footer += "]"
            print(footer)
        except Exception as exc:
            print(f"❌ {exc}", file=sys.stderr)
        return True

    def interactive(self) -> int:
        self.banner()
        while True:
            try:
                line = input("\nsophyane> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not self.command(line):
                return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sophyane multi-LLM orchestration runtime")
    parser.add_argument("prompt", nargs="*", help="Prompt to execute")
    parser.add_argument("--provider", choices=["gemini", "anthropic", "claude", "xai", "grok", "openai"])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    app = Sophyane()
    if args.self_test:
        ok, checks = Verifier.self_test()
        print("\n".join(checks))
        return 0 if ok else 1
    if args.status:
        app.status(); return 0
    if args.provider:
        app.llm.switch(args.provider)
    if args.prompt:
        app.ask(" ".join(args.prompt)); return 0
    return app.interactive()


if __name__ == "__main__":
    raise SystemExit(main())
PY

chmod +x "$APP"

cat > "$BIN/sophyane-v7" <<EOF
#!/usr/bin/env bash
exec python3 "$APP" "\$@"
EOF
chmod +x "$BIN/sophyane-v7"

python3 -m py_compile "$APP"
"$BIN/sophyane-v7" --self-test

cat > "$CURRENT" <<'EOF'
#!/usr/bin/env bash
set -e
exec "$HOME/.local/bin/sophyane-v7" "$@"
EOF
chmod +x "$CURRENT"

for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  touch "$rc"
  grep -Fq 'export PATH="$HOME/.local/bin:$PATH"' "$rc" || \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
done

cat <<EOF

✅ Sophyane v7 orchestration layer installed.

Main command:       sophyane
Direct v7 command:  sophyane-v7
Original backup:    sophyane-6.1-backup
Configuration:      $CFG_DIR/llm.json
State/checkpoints:  $STATE_DIR

Set API keys as needed:
  export GEMINI_API_KEY='...'
  export ANTHROPIC_API_KEY='...'
  export XAI_API_KEY='...'
  export OPENAI_API_KEY='...'

Then run:
  source ~/.bashrc
  sophyane

Useful commands inside Sophyane:
  status
  progress
  /llm status
  /llm switch claude
  /llm switch grok
  /llm switch openai
  /checkpoint before-change
  /verify
  /legacy
EOF
