"""Local GGUF provider via persistent llama-server or bounded llama-cli."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from sophyane.providers.base import Provider, ProviderError, ProviderMetadata
from sophyane.providers.http import post_json
from sophyane.runtime_cancel import cancelled, register, unregister

DEFAULT_ENDPOINT = os.environ.get("SOPHYANE_LLAMA_SERVER", "http://127.0.0.1:8766").rstrip("/")


class LocalGgufProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="local_gguf",
        display_name="Local GGUF (Hugging Face / llama.cpp)",
        default_model="local-gguf",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(self, api_key: str = "", model: str = "local-gguf", timeout: int = 300,
                 temperature: float = 0.3, max_tokens: int = 1024, endpoint: str = "",
                 gguf_path: str = "", cli_path: str = "") -> None:
        super().__init__(api_key, model, timeout, temperature, max_tokens)
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.gguf_path = gguf_path or os.environ.get("SOPHYANE_GGUF_PATH", "")
        self.cli_path = cli_path or os.environ.get("SOPHYANE_LLAMA_CLI", "")

    def generate(self, prompt: str, system_prompt: str) -> str:
        if cancelled():
            raise ProviderError("local generation cancelled")
        system_prompt = (system_prompt or "")[:800]
        prompt = (prompt or "")[:4000]
        try:
            return self._generate_via_server(prompt, system_prompt)
        except Exception as first_server_error:  # noqa: BLE001
            if cancelled():
                raise ProviderError("local generation cancelled") from first_server_error

            detail = ""
            try:
                from sophyane.local_server import (
                    ensure_server_background,
                    failure_detail,
                    wait_until_ready,
                )
                started, startup_message = ensure_server_background()
                if started and wait_until_ready(timeout=8.0):
                    return self._generate_via_server(prompt, system_prompt)
                detail = failure_detail() or startup_message
            except Exception as startup_error:  # noqa: BLE001
                detail = f"server startup check failed: {startup_error}"

            if cancelled():
                raise ProviderError("local generation cancelled") from first_server_error

            combined_len = len(prompt) + len(system_prompt)
            if self.cli_path and self.gguf_path and combined_len <= 5000:
                try:
                    return self._generate_via_cli(prompt, system_prompt)
                except Exception as cli_error:  # noqa: BLE001
                    raise ProviderError(
                        "local_gguf unavailable. "
                        f"Server: {detail or first_server_error}. "
                        f"CLI fallback: {cli_error}"
                    ) from cli_error
            raise ProviderError(
                "local_gguf server unavailable. "
                f"{detail or first_server_error}"
            ) from first_server_error

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
                "max_tokens": min(self.max_tokens, 384),
                "stream": False,
            },
            headers={"Authorization": "Bearer local"},
            timeout=min(self.timeout, 50),
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

    @staticmethod
    def _clean_cli_output(text: str) -> str:
        text = (text or "").replace("\r", "\n")
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
        if fenced:
            return fenced[-1].strip()
        starts = [match.start() for match in re.finditer(r"\{", text)]
        for start in reversed(starts):
            candidate = text[start:text.rfind("}") + 1].strip()
            if candidate:
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass
        if "Assistant:" in text:
            text = text.split("Assistant:")[-1]
        text = re.sub(r"^User:.*$", "", text, flags=re.M)
        text = re.sub(r"^>\s*$", "", text, flags=re.M)
        return text.strip()

    def _run_cli(self, cmd: list[str], deadline: int) -> tuple[int, str, str]:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, **kwargs)
        register(process)
        try:
            stdout, stderr = process.communicate(timeout=deadline)
            return process.returncode or 0, stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                stdout, stderr = process.communicate(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            cleaned = self._clean_cli_output(stdout or "")
            if cleaned:
                return 0, cleaned, stderr or ""
            if cancelled():
                raise ProviderError("llama-cli cancelled")
            raise ProviderError(f"llama-cli produced no complete answer within {deadline}s")
        finally:
            unregister(process)

    def _generate_via_cli(self, prompt: str, system_prompt: str) -> str:
        full = f"{system_prompt.strip()}\n\nUser: {prompt}\nAssistant:"
        tokens = str(max(32, min(self.max_tokens, 192)))
        deadline = max(12, min(int(self.timeout), 32))
        variants = [
            [self.cli_path, "-m", self.gguf_path, "-p", full, "-n", tokens,
             "--temp", str(self.temperature), "--single-turn", "--simple-io",
             "--no-display-prompt"],
            [self.cli_path, "-m", self.gguf_path, "-p", full, "-n", tokens,
             "--temp", str(self.temperature), "-no-cnv"],
        ]
        errors: list[str] = []
        for cmd in variants:
            if cancelled():
                raise ProviderError("llama-cli cancelled")
            code, stdout, stderr = self._run_cli(cmd, deadline)
            text = self._clean_cli_output(stdout)
            if code == 0 and text:
                return text
            errors.append(f"exit={code}: {stderr[:180]}")
        raise ProviderError("llama-cli failed: " + " | ".join(errors))


def load_gguf_runtime_state() -> dict:
    path = Path.home() / ".local" / "state" / "sophyane" / "gguf_runtime.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
