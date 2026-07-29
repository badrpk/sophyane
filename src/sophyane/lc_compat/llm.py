"""Multi-provider LLM interface (wraps existing Sophyane providers when present)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

class LLMProvider(Protocol):
    def generate(self, prompt: str, system_prompt: str = "") -> str: ...

@dataclass
class LLMResult:
    text: str
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

def estimate_tokens(text: str) -> int:
    # cheap heuristic ~4 chars/token
    return max(1, len(text) // 4)

@dataclass
class MultiProviderLLM:
    """Tries providers in order; records token estimates for observability."""
    chain: list[tuple[str, Any]] = field(default_factory=list)

    def generate(self, prompt: str, system_prompt: str = "") -> LLMResult:
        import time
        errors: list[str] = []
        for name, provider in self.chain:
            t0 = time.perf_counter()
            try:
                text = provider.generate(prompt, system_prompt)
                ms = (time.perf_counter() - t0) * 1000
                return LLMResult(
                    text=text,
                    provider=name,
                    model=str(getattr(provider, "model", "") or ""),
                    prompt_tokens=estimate_tokens(system_prompt + prompt),
                    completion_tokens=estimate_tokens(text),
                    latency_ms=ms,
                )
            except Exception as e:
                errors.append(f"{name}: {e}")
        raise RuntimeError("All providers failed: " + "; ".join(errors))

def from_sophyane_config() -> MultiProviderLLM:
    """Best-effort load from installed Sophyane provider chain."""
    chain: list[tuple[str, Any]] = []
    try:
        from sophyane.providers.gemini import GeminiProvider  # type: ignore
        # caller must inject keys; this is structural only
    except Exception:
        pass
    return MultiProviderLLM(chain=chain)
