from __future__ import annotations

from pathlib import Path

from sophyane.memory import MemoryStore
from sophyane.providers.base import ProviderCapabilities
from sophyane.v16_doer import CodingDoerRuntime


def _backend(prompt: str, system: str) -> str:
    raise AssertionError("backend should not be called by context tests")


def _runtime(
    tmp_path: Path,
    capabilities: ProviderCapabilities,
) -> CodingDoerRuntime:
    return CodingDoerRuntime(
        backend=_backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        capabilities=capabilities,
    )


def test_provider_managed_context_preserves_complete_ranked_file(
    tmp_path: Path,
) -> None:
    marker = "PROVIDER_MANAGED_TAIL_MARKER"

    (tmp_path / "feature.py").write_text(
        "class ImportantFeature:\n"
        + ("    value = 1\n" * 3000)
        + f"# {marker}\n",
        encoding="utf-8",
    )

    runtime = _runtime(
        tmp_path,
        ProviderCapabilities(
            provider_managed_context=True,
            provider_managed_output=True,
        ),
    )

    context = runtime._context("ImportantFeature")

    assert "Direct repository file: feature.py" in context
    assert marker in context
    assert "Repository summary" in context
    assert "Repository search hits" in context


def test_unknown_capacity_does_not_invent_repository_ceiling(
    tmp_path: Path,
) -> None:
    marker = "UNKNOWN_CAPACITY_TAIL_MARKER"

    (tmp_path / "module.py").write_text(
        "class UnknownCapacityFeature:\n"
        + ("    item = 1\n" * 2500)
        + f"# {marker}\n",
        encoding="utf-8",
    )

    runtime = _runtime(
        tmp_path,
        ProviderCapabilities(),
    )

    context = runtime._context("UnknownCapacityFeature")

    assert marker in context


def test_bounded_provider_preserves_compact_repository_intelligence(
    tmp_path: Path,
) -> None:
    marker = "OVERSIZED_FILE_TAIL_SHOULD_NOT_SURVIVE"

    (tmp_path / "large_feature.py").write_text(
        "class LocalFeature:\n"
        + ("    value = 'large payload'\n" * 4000)
        + f"# {marker}\n",
        encoding="utf-8",
    )

    runtime = _runtime(
        tmp_path,
        ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        ),
    )

    context = runtime._context("LocalFeature")

    assert "Repository summary" in context
    assert "Repository search hits" in context
    assert "LocalFeature" in context
    assert marker not in context


def test_capability_resolver_is_evaluated_per_context_build(
    tmp_path: Path,
) -> None:
    marker = "DYNAMIC_PROVIDER_TAIL_MARKER"

    (tmp_path / "dynamic.py").write_text(
        "class DynamicFeature:\n"
        + ("    value = 1\n" * 2500)
        + f"# {marker}\n",
        encoding="utf-8",
    )

    state = {"managed": True}

    def capabilities() -> ProviderCapabilities:
        if state["managed"]:
            return ProviderCapabilities(
                provider_managed_context=True,
            )
        return ProviderCapabilities(
            context_window_tokens=1024,
            max_output_tokens=256,
        )

    runtime = CodingDoerRuntime(
        backend=_backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        capabilities=capabilities,
    )

    assert marker in runtime._context("DynamicFeature")

    state["managed"] = False

    bounded = runtime._context("DynamicFeature")

    assert marker not in bounded
    assert "Repository summary" in bounded


def test_invalid_capability_resolver_falls_back_without_fake_limit(
    tmp_path: Path,
) -> None:
    marker = "INVALID_RESOLVER_TAIL_MARKER"

    (tmp_path / "fallback.py").write_text(
        "class ResolverFeature:\n"
        + ("    value = 1\n" * 2000)
        + f"# {marker}\n",
        encoding="utf-8",
    )

    runtime = CodingDoerRuntime(
        backend=_backend,
        memory=MemoryStore(tmp_path / "memory.db"),
        workspace=tmp_path,
        capabilities=lambda: {"context_window_tokens": 10},
    )

    context = runtime._context("ResolverFeature")

    assert marker in context
