from __future__ import annotations

import ast
from pathlib import Path

from sophyane.lc_compat.llm import MultiProviderLLM, from_sophyane_config


def _source() -> str:
    return (
        Path(__file__).parents[1]
        / "src"
        / "sophyane"
        / "lc_compat"
        / "llm.py"
    ).read_text(encoding="utf-8")


def test_lc_compat_does_not_import_unused_gemini_provider() -> None:
    tree = ast.parse(_source())

    imports = [
        node.lineno
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "sophyane.providers.gemini"
            and any(
                alias.name == "GeminiProvider"
                for alias in node.names
            )
        )
    ]

    assert imports == []


def test_from_sophyane_config_explicitly_returns_empty_chain() -> None:
    result = from_sophyane_config()

    assert isinstance(result, MultiProviderLLM)
    assert result.chain == []


def test_multi_provider_generate_behavior_remains_available() -> None:
    class Provider:
        model = "test-model"

        def generate(
            self,
            prompt: str,
            system_prompt: str = "",
        ) -> str:
            return f"{system_prompt}:{prompt}"

    llm = MultiProviderLLM(
        chain=[
            ("test", Provider()),
        ]
    )

    result = llm.generate(
        "hello",
        "system",
    )

    assert result.text == "system:hello"
    assert result.provider == "test"
    assert result.model == "test-model"
