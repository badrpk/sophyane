"""Optional native Neuron index for bounded episodic-memory assistance.

Neuron is advisory here.  Sophyane/Xerus owns durable episodes and
verification authority; this module only produces ranking and activation
metadata.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


_MAX_KEY = 256
_MAX_NAMESPACE = 128
_MAX_TEXT = 4000
_DEFAULT_MAX_RECALL = 5
_DEFAULT_MAX_OUTPUT = 8192
_DEFAULT_TIMEOUT = 0.25
_BOOKKEEPING_TERMS = {
    "accepted", "authoritative", "created_at", "false", "status",
    "trace_id", "true", "trusted", "unverified", "verification",
    "verified", "verification_state",
}


@dataclass(frozen=True)
class NeuronStatus:
    backend: str
    available: bool
    error: str = ""
    executable: str = ""


@dataclass(frozen=True)
class NeuronScore:
    episode_key: str
    namespace: str
    score: float
    novelty: float
    activation: float
    authoritative: bool
    backend: str


@dataclass(frozen=True)
class NeuronRecall:
    episode_key: str
    namespace: str
    score: float
    authoritative: bool
    content: str
    backend: str


def _bounded_text(value: object, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _bounded_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _episode_projection(episode: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "episode_key": _bounded_text(
            episode.get("episode_key") or episode.get("trace_id"),
            _MAX_KEY,
        ),
        "namespace": _bounded_text(episode.get("namespace", "default"), _MAX_NAMESPACE),
        "objective": _bounded_text(episode.get("objective"), _MAX_TEXT),
        "result": _bounded_text(episode.get("result"), _MAX_TEXT),
        "capability_class": _bounded_text(episode.get("capability_class"), 128),
        "status": _bounded_text(episode.get("status"), 64),
        "created_at": float(episode.get("created_at", 0.0) or 0.0),
        "trusted": bool(episode.get("trusted", False)),
        "authoritative": bool(episode.get("authoritative", False)),
    }


def _semantic_tokens(*values: object) -> set[str]:
    tokens = set()
    for value in values:
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", str(value or "").casefold()):
            if token not in _BOOKKEEPING_TERMS:
                tokens.add(token)
    return tokens


class NeuronEpisodicIndex:
    """Use an explicitly configured Neuron process, with a safe fallback."""

    def __init__(
        self,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
        max_output_bytes: int = _DEFAULT_MAX_OUTPUT,
        max_recall: int = _DEFAULT_MAX_RECALL,
        max_records: int = 256,
    ) -> None:
        self.timeout_seconds = max(0.001, float(timeout_seconds))
        self.max_output_bytes = max(256, int(max_output_bytes))
        self.max_recall = max(1, int(max_recall))
        self.max_records = max(1, int(max_records))
        self._episodes: dict[tuple[str, str], dict[str, Any]] = {}
        self._status = self._discover()
        self._native_process: subprocess.Popen[str] | None = None
        self._native_lock = threading.Lock()

    @staticmethod
    def _discover() -> NeuronStatus:
        configured = os.environ.get("SOPHYANE_NEURON_BIN", "").strip()
        if not configured:
            return NeuronStatus("fallback", True)
        path = Path(configured).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            return NeuronStatus(
                "fallback",
                True,
                "configured Neuron executable is not a runnable regular file",
                str(path),
            )
        return NeuronStatus("native", True, "", str(path.resolve()))

    def status(self) -> NeuronStatus:
        return self._status

    def health(self) -> dict[str, Any]:
        """Return bounded runtime health without changing memory authority."""
        native = self._native("status", {}) if self._native_configured() else None
        process = self._native_process
        return {
            "backend": self._status.backend,
            "available": self._status.available,
            "error": self._status.error,
            "executable": self._status.executable,
            "process_live": bool(process is not None and process.poll() is None),
            "records": int(native.get("records", 0)) if isinstance(native, dict) else len(self._episodes),
        }

    def _stop_native(self) -> None:
        process = self._native_process
        self._native_process = None
        if process is None:
            return
        try:
            process.kill()
            process.wait(timeout=0.2)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def close(self) -> None:
        with self._native_lock:
            self._stop_native()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _native_failure(self, message: str) -> None:
        self._stop_native()
        self._status = NeuronStatus(
            "fallback", True, message[:500], self._status.executable
        )

    def _native_configured(self) -> bool:
        return bool(
            self._status.executable
            and Path(self._status.executable).is_file()
            and os.access(self._status.executable, os.X_OK)
        )

    def _ensure_native_process(self, command: list[str]) -> subprocess.Popen[str]:
        if self._native_process is None or self._native_process.poll() is not None:
            self._native_process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
            )
        return self._native_process

    def _native(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self._native_configured():
            return None
        command = [self._status.executable, "--episodic-json"]
        request = json.dumps(
            {"operation": operation, **dict(payload)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._native_lock:
            try:
                process = self._ensure_native_process(command)
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(request + "\n")
                process.stdin.flush()
                ready, _, _ = select.select(
                    [process.stdout], [], [], self.timeout_seconds
                )
                if not ready:
                    self._native_failure("native Neuron timeout")
                    return None
                output = process.stdout.readline() or ""
            except (OSError, ValueError, BrokenPipeError) as error:
                self._native_failure(f"native Neuron invocation failed: {error}")
                return None

        if not output:
            process = self._native_process
            if process is not None:
                try:
                    process.wait(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    pass
            if process is not None and process.poll() not in (None, 0):
                self._native_failure(f"native Neuron exit code {process.returncode}")
            else:
                self._native_failure("native Neuron returned no output")
            return None
        if len(output.encode("utf-8", errors="replace")) > self.max_output_bytes:
            self._native_failure("native Neuron output limit exceeded")
            return None
        process = self._native_process
        if process is not None and process.poll() not in (None, 0):
            self._native_failure(f"native Neuron exit code {process.returncode}")
            return None
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as error:
            self._native_failure(f"native Neuron JSON error: {error.msg}")
            return None
        if not isinstance(parsed, dict):
            self._native_failure("native Neuron JSON result is not an object")
            return None
        self._status = NeuronStatus("native", True, "", self._status.executable)
        return parsed

    def _native_batch(self, requests: list[tuple[str, Mapping[str, Any]]]) -> list[dict[str, Any]] | None:
        if not self._native_configured() or not requests:
            return None
        command = [self._status.executable, "--episodic-json"]
        encoded = [
            json.dumps(
                {"operation": operation, **dict(payload)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
            for operation, payload in requests
        ]
        with self._native_lock:
            try:
                process = self._ensure_native_process(command)
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write("".join(encoded))
                process.stdin.flush()
                outputs = []
                pending = b""
                while len(outputs) < len(requests):
                    ready, _, _ = select.select(
                        [process.stdout], [], [], self.timeout_seconds
                    )
                    if not ready:
                        self._native_failure("native Neuron batch timeout")
                        return None
                    chunk = os.read(process.stdout.fileno(), self.max_output_bytes + 1)
                    pending += chunk
                    if len(pending) > (self.max_output_bytes + 1) * len(requests):
                        self._native_failure("native Neuron batch output invalid")
                        return None
                    while b"\n" in pending and len(outputs) < len(requests):
                        raw, pending = pending.split(b"\n", 1)
                        if not raw or len(raw) > self.max_output_bytes:
                            self._native_failure("native Neuron batch output invalid")
                            return None
                        parsed = json.loads(raw.decode("utf-8"))
                        if not isinstance(parsed, dict):
                            self._native_failure("native Neuron batch result is not an object")
                            return None
                        outputs.append(parsed)
                self._status = NeuronStatus("native", True, "", self._status.executable)
                return outputs
            except (OSError, ValueError, BrokenPipeError, json.JSONDecodeError) as error:
                self._native_failure(f"native Neuron batch failed: {error}")
                return None

    def index_episodes(self, episodes: list[Mapping[str, Any]]) -> tuple[NeuronScore, ...]:
        """Index bounded episodes in one native IPC batch when available."""
        projections = [_episode_projection(episode) for episode in episodes]
        native = self._native_batch([
            ("index", {"episode": projection}) for projection in projections
        ])
        if native is None:
            return tuple(self.index_episode(episode) for episode in episodes)
        scores = []
        for projection, response in zip(projections, native):
            score = _bounded_float(response.get("score"))
            scores.append(NeuronScore(
                projection["episode_key"], projection["namespace"], score,
                _bounded_float(response.get("novelty"), score),
                _bounded_float(response.get("activation"), score),
                bool(projection["authoritative"]), "native",
            ))
        return tuple(scores)

    def index_episode(self, episode: Mapping[str, Any]) -> NeuronScore:
        projection = _episode_projection(episode)
        key = projection["episode_key"]
        namespace = projection["namespace"]
        native = self._native("index", {"episode": projection})
        if native is not None:
            score = _bounded_float(native.get("score"), 0.0)
            novelty = _bounded_float(native.get("novelty"), score)
            activation = _bounded_float(native.get("activation"), score)
            backend = "native"
        else:
            tokens = _semantic_tokens(
                projection["objective"],
                projection["result"],
                projection["capability_class"],
            )
            prior_tokens = [
                record["tokens"]
                for record in self._episodes.values()
                if record["namespace"] == namespace
            ]
            if tokens and not prior_tokens:
                novelty = 1.0
            elif tokens:
                novelty = 1.0 - max(
                    (
                        len(tokens & previous) / len(tokens | previous)
                        if tokens | previous
                        else 0.0
                    )
                    for previous in prior_tokens
                )
            else:
                novelty = 0.0
            activation = min(1.0, len(tokens) / 8.0)
            score = min(
                1.0,
                0.55 * novelty
                + 0.3 * activation
                + (0.15 if projection["trusted"] and projection["authoritative"] else 0.0),
            )
            backend = "fallback"
        record = {
            **projection,
            "score": score,
            "novelty": novelty,
            "activation": activation,
            "backend": backend,
            "indexed_at": time.time(),
            "tokens": _semantic_tokens(
                projection["objective"],
                projection["result"],
                projection["capability_class"],
            ),
        }
        self._episodes[(namespace, key)] = record
        while len(self._episodes) > self.max_records:
            victim = min(
                self._episodes.items(),
                key=lambda item: (
                    item[1]["score"],
                    item[1]["created_at"],
                    item[1]["episode_key"],
                ),
            )[0]
            del self._episodes[victim]
        return NeuronScore(
            key,
            namespace,
            score,
            novelty,
            activation,
            bool(projection["authoritative"]),
            backend,
        )

    def recall(
        self,
        query: str,
        *,
        namespace: str,
        limit: int = _DEFAULT_MAX_RECALL,
    ) -> tuple[NeuronRecall, ...]:
        clean_namespace = _bounded_text(namespace, _MAX_NAMESPACE)
        clean_query = _bounded_text(query, _MAX_TEXT).casefold()
        words = {word for word in clean_query.split() if len(word) > 2}
        native = self._native(
            "recall",
            {
                "query": clean_query,
                "namespace": clean_namespace,
                "limit": min(self.max_recall, max(0, int(limit))),
            },
        )
        if native is not None and isinstance(native.get("records"), list):
            native_records = []
            for item in native["records"][: self.max_recall]:
                if not isinstance(item, Mapping):
                    continue
                if _bounded_text(item.get("namespace"), _MAX_NAMESPACE) != clean_namespace:
                    continue
                native_records.append(
                    NeuronRecall(
                        _bounded_text(item.get("episode_key"), _MAX_KEY),
                        clean_namespace,
                        _bounded_float(item.get("score")),
                        bool(item.get("authoritative", False)),
                        _bounded_text(item.get("content"), _MAX_TEXT),
                        "native",
                    )
                )
            return tuple(native_records[: max(0, min(self.max_recall, int(limit)))])
        candidates = []
        for record in self._episodes.values():
            if record["namespace"] != clean_namespace:
                continue
            content = f'{record["objective"]} {record["result"]}'.strip()
            overlap = sum(word in content.casefold() for word in words)
            candidates.append((overlap, record["score"], -record["created_at"], record["episode_key"], record, content))
        candidates.sort(key=lambda item: item[:4], reverse=True)
        bounded_limit = max(0, min(self.max_recall, int(limit)))
        return tuple(
            NeuronRecall(
                record["episode_key"],
                record["namespace"],
                _bounded_float(record["score"]),
                bool(record["authoritative"]),
                content[:_MAX_TEXT],
                record["backend"],
            )
            for _, _, _, _, record, content in candidates[:bounded_limit]
        )

    def forget(self, episode_key: str, *, namespace: str) -> bool:
        clean_key = _bounded_text(episode_key, _MAX_KEY)
        clean_namespace = _bounded_text(namespace, _MAX_NAMESPACE)
        self._native(
            "forget",
            {"episode_key": clean_key, "namespace": clean_namespace},
        )
        return self._episodes.pop(
            (clean_namespace, clean_key),
            None,
        ) is not None


__all__ = [
    "NeuronEpisodicIndex",
    "NeuronRecall",
    "NeuronScore",
    "NeuronStatus",
]
