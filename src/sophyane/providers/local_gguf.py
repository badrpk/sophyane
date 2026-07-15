"""Local GGUF provider via llama-server (OpenAI-compatible) or llama-cli."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from sophyane.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json

DEFAULT_ENDPOINT = os.environ.get(
    "SOPHYANE_LLAMA_SERVER",
    "http://127.0.0.1:8766",
).rstrip("/")


class LocalGgufProvider(Provider):
    """Talk to a local llama.cpp server or fall back to one-shot llama-cli."""

    metadata = ProviderMetadata(
        provider_id="local_gguf",
        display_name="Local GGUF (Hugging Face / llama.cpp)",
        default_model="local-gguf",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(
        self,
        api_key: str = "",
        model: str = "local-gguf",
        timeout: int = 300,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        endpoint: str = "",
        gguf_path: str = "",
        cli_path: str = "",
    ) -> None:
        super().__init__(api_key, model, timeout, temperature, max_tokens)
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.gguf_path = gguf_path or os.environ.get("SOPHYANE_GGUF_PATH", "")
        self.cli_path = cli_path or os.environ.get("SOPHYANE_LLAMA_CLI", "")

    def generate(self, prompt: str, system_prompt: str) -> str:
        # Keep prompts tiny on constrained devices (Crostini / 2–3GB RAM).
        system_prompt = (system_prompt or "")[:800]
        prompt = (prompt or "")[:4000]

        # Prefer OpenAI-compatible server. Only fall back to llama-cli for
        # short prompts — long CLI invocations thrash low-RAM machines.
        try:
            return self._generate_via_server(prompt, system_prompt)
        except Exception as server_error:  # noqa: BLE001
            combined_len = len(prompt) + len(system_prompt)
            if self.cli_path and self.gguf_path and combined_len <= 2500:
                try:
                    return self._generate_via_cli(prompt, system_prompt)
                except Exception as cli_error:  # noqa: BLE001
                    raise ProviderError(
                        f"local_gguf server failed ({server_error}); "
                        f"cli failed ({cli_error})"
                    ) from cli_error
            raise ProviderError(
                f"local_gguf server unavailable: {server_error}. "
                "Run `sophyane /local` to bootstrap a Hugging Face GGUF model, "
                "or free RAM and ensure llama-server is listening on :8766."
            ) from server_error

    def _generate_via_server(self, prompt: str, system_prompt: str) -> str:
        response = post_json(
            f"{self.endpoint}/v1/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": False,
            },
            headers={"Authorization": "Bearer local"},
            timeout=self.timeout,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                f"Unexpected llama-server response: {json.dumps(response)[:1000]}"
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("llama-server returned no text")
        return content.strip()

    def _generate_via_cli(self, prompt: str, system_prompt: str) -> str:
        full = f"{system_prompt.strip()}\n\nUser: {prompt}\nAssistant:"
        cmd = [
            self.cli_path,
            "-m",
            self.gguf_path,
            "-p",
            full,
            "-n",
            str(max(32, min(self.max_tokens, 512))),
            "--temp",
            str(self.temperature),
            "-no-cnv",
        ]
        # Newer llama-cli uses -no-cnv / --simple-io flags inconsistently.
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            # Retry with alternate flag set for older builds.
            cmd = [
                self.cli_path,
                "-m",
                self.gguf_path,
                "-p",
                full,
                "-n",
                str(max(32, min(self.max_tokens, 512))),
                "--temp",
                str(self.temperature),
            ]
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        text = (completed.stdout or "").strip()
        if completed.returncode != 0 and not text:
            raise ProviderError(
                f"llama-cli failed ({completed.returncode}): "
                f"{(completed.stderr or '')[:500]}"
            )
        # Strip echoed prompt if present.
        if "Assistant:" in text:
            text = text.split("Assistant:")[-1].strip()
        text = re.sub(r"^User:.*$", "", text, flags=re.M).strip()
        if not text:
            raise ProviderError("llama-cli returned empty output")
        return text


def load_gguf_runtime_state() -> dict:
    path = Path.home() / ".local" / "state" / "sophyane" / "gguf_runtime.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
