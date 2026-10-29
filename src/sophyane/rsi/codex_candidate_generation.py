"""Bounded, proposal-only Codex candidate generation for RSI experiments."""

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import time

from sophyane.providers.codex_cli import CodexCliProvider


@dataclass(frozen=True)
class CandidateGenerationResult:
    provider: str
    files: dict[str, str]
    elapsed_seconds: float


class CodexCandidateGenerator:
    """Ask Codex for a patch without applying or authorizing that patch."""

    def __init__(self, *, provider_factory=CodexCliProvider, timeout=300):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("candidate generation timeout must be positive")
        self.provider_factory = provider_factory
        self.timeout = timeout

    def generate(self, *, workspace, request, allowed_paths):
        root = Path(workspace).resolve()
        started = time.monotonic()
        provider = self.provider_factory(workspace=root, timeout=self.timeout)
        response = provider.generate(
            str(request),
            "Return only JSON of the form {\"files\": {\"relative/path\": \"complete replacement\"}}. "
            "Propose edits only. Do not execute commands, edit files, or make authority decisions.",
        )
        elapsed = time.monotonic() - started
        try:
            payload = json.loads(response) if isinstance(response, str) else response
        except json.JSONDecodeError as error:
            raise ValueError("Codex candidate response was not JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"files"} or not isinstance(payload["files"], dict):
            raise ValueError("Codex candidate response schema is invalid")
        permitted = {str(path) for path in allowed_paths}
        files = {}
        for name, contents in payload["files"].items():
            if not isinstance(name, str) or not isinstance(contents, str):
                raise ValueError("Codex candidate files must be string mappings")
            parsed = PurePosixPath(name)
            if parsed.is_absolute() or ".." in parsed.parts or name not in permitted:
                raise ValueError(f"Codex candidate path is outside the experiment policy: {name}")
            files[name] = contents
        if not files:
            raise ValueError("Codex candidate contained no files")
        return CandidateGenerationResult("codex_cli", files, elapsed)
